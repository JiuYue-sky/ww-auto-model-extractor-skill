"""Unified 5-Stage State Machine Orchestrator for `ww-auto-core` (Open-Source Compliant Edition).

Stages:
  self-audit : Package & plugin self-diagnosis (verifies code, licenses, compliance boundaries, and native decoders)
  Stage 0    : Environment detection (Hard Gate: official WW client MUST exist locally; UE NOT required!),
               consent-gated bootstrap (Blender / Oodle runtime / FModel / FModel-WW link),
               Blender addon AST compat scan + isolated sandbox hot-patch + headless smoke test.
  [Pause]    : Returns explicit character-name prompt contract when run interactively/stepwise.
  Stage 1    : Local AES mount verification (zero bundled keys, zero remote key fetching; pauses if missing/expired so host
               can supply a local .json/.zip key package to link FModel) -> character & animation parsing + VerifyGate 1.
  Stage 2    : Texture 3-Tier Audit (MI JSON -> regex -> pixel stats via Blender Python OIIO/numpy, _N split,
               _SDF correlation/mirroring) + VerifyGate 3.
  Stage 3    : Sandboxed Blender headless assembly (.uemodel + Stylized Toon Shader + .ueanim + RibbonAnim merge +
               v10 Shape Key curves + studio lighting + multi-frame motion delta verification + preview renders +
               rest-pose FBX round-trip verification) + VerifyGate 2.
  Stage 4    : Standardized Handoff Packager (`handoff_manifest.json` + `DELIVERY_REPORT.md` + optional
               `ue_handoff_reference.py`) + VerifyGate 4.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .addon_sandbox import prepare_and_verify_blender_sandbox
from .aes_resolver import resolve_and_verify_aes_keys
from .asset_extractor import extract_character_assets, list_available_characters
from .blender_runner import run_blender_assembly
from .delivery_packager import build_handoff_and_delivery_report
from .env_bootstrap import apply_consented_bootstrap
from .env_detector import detect_full_environment
from .self_audit import run_package_self_audit
from .texture_auditor import audit_and_process_textures
from .version import CORE_VERSION

_WIN_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _safe_slug(text: str) -> str:
    raw = (text or "character").replace("\x00", "").strip()
    s = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "_", raw).strip("._-")
    s = s[:64].strip("._-")
    if not s:
        s = "character"
    if s.upper() in _WIN_RESERVED_DEVICE_NAMES:
        s = f"char_{s}"
    return s


class PipelineOrchestrator:
    def __init__(self, project_root: Path, work_dir: Optional[Path] = None) -> None:
        self.project_root = project_root.resolve()
        self.work_dir = (work_dir or (self.project_root / "output")).resolve()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.work_dir / "pipeline_state.json"

    def _load_state(self) -> Dict[str, Any]:
        if self.state_path.is_file():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"core_version": CORE_VERSION}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

    def run_self_audit(self) -> Dict[str, Any]:
        return run_package_self_audit(self.project_root, check_binary=True)

    def run_stage_0_preflight(
        self,
        *,
        game_dir: Optional[str] = None,
        blender_path: Optional[str] = None,
        fmodel_dir: Optional[str] = None,
        fmodel_appsettings_path: Optional[Path] = None,
        extra_keys_file: Optional[str] = None,
        consent_downloads: Optional[List[str]] = None,
        consent_link_fmodel: bool = False,
        include_self_audit: bool = True,
    ) -> Dict[str, Any]:
        """Stage 0: Package Self-Audit + Environment Detection + Safe Key/FModel Link Gate + Blender Sandbox Gate."""
        state = self._load_state()
        host_notices: List[str] = []

        self_audit_res = self.run_self_audit() if include_self_audit else None
        if self_audit_res and self_audit_res["status"] != "PASS":
            return {
                "stage": 0,
                "status": "FAIL",
                "code": "PACKAGE_SELF_AUDIT_FAILED",
                "self_audit": self_audit_res,
                "error": f"包体/插件自检发现内部问题: {self_audit_res['failures']}",
            }

        env = detect_full_environment(
            self.project_root,
            game_dir=game_dir,
            blender_path=blender_path,
            fmodel_dir=fmodel_dir,
            fmodel_appsettings_path=fmodel_appsettings_path,
            extra_keys_file=extra_keys_file,
        )

        if not env["wuthering_waves"]["found"]:
            return {
                "stage": 0,
                "status": "FAIL",
                "code": "FATAL_MISSING_WUTHERING_WAVES",
                "auto_download_allowed": False,
                "env": env,
                "error": env["wuthering_waves"]["message"],
                "host_notice": env["wuthering_waves"]["message"],
            }

        bootstrap_actions: List[Dict[str, Any]] = []
        if consent_downloads or consent_link_fmodel:
            bootstrap_actions = apply_consented_bootstrap(
                self.project_root,
                env,
                consent_downloads=consent_downloads,
                consent_link_fmodel=consent_link_fmodel,
                keys_bundle_path=extra_keys_file,
                fmodel_appsettings_path=fmodel_appsettings_path,
            )
            failed_boot = [a for a in bootstrap_actions if a.get("status") == "FAIL"]
            if failed_boot:
                return {
                    "stage": 0,
                    "status": "FAIL",
                    "code": "BOOTSTRAP_OR_KEY_LINK_FAILED",
                    "bootstrap_actions": bootstrap_actions,
                    "host_notice": "\n".join(a.get("host_notice") or a.get("error", "") for a in failed_boot),
                    "error": failed_boot[0].get("error", "Bootstrap/link action failed"),
                }
            for act in bootstrap_actions:
                if act.get("host_notice"):
                    host_notices.append(act["host_notice"])
            effective_blender = None if any(a.get("component") == "blender" and a.get("status") == "INSTALLED" for a in bootstrap_actions) else blender_path
            effective_fmodel = None if any(a.get("component") == "fmodel" and a.get("status") == "INSTALLED" for a in bootstrap_actions) else fmodel_dir
            env = detect_full_environment(
                self.project_root,
                game_dir=game_dir,
                blender_path=effective_blender,
                fmodel_dir=effective_fmodel,
                fmodel_appsettings_path=fmodel_appsettings_path,
                extra_keys_file=extra_keys_file,
            )

        missing_required = [c for c in env.get("consent_actions", []) if c.get("required")]
        if missing_required:
            return {
                "stage": 0,
                "status": "CONSENT_REQUIRED",
                "code": "HOST_CONSENT_REQUIRED",
                "env": env,
                "bootstrap_actions": bootstrap_actions,
                "consent_actions": env["consent_actions"],
                "host_notice": (
                    "检测到尚未满足的前置环境或本地密钥关联项，工作已暂停："
                    + " ; ".join(f"{c['action_id']} ({c['flag']}): {c['reason']}" for c in missing_required)
                ),
            }

        if not env["ww_extract"]["ok"]:
            return {
                "stage": 0,
                "status": "FAIL",
                "code": "EXTRACTOR_UNAVAILABLE",
                "env": env,
                "error": f"底层解析组件不可用: {env['ww_extract'].get('error') or env['ww_extract'].get('self_test')}",
            }

        sandbox_root = self.work_dir / "sandbox_blender"
        sandbox = prepare_and_verify_blender_sandbox(env["blender"], env["addons"], sandbox_root)
        if sandbox.get("host_notice"):
            host_notices.append(sandbox["host_notice"])

        optional_consents = [c for c in env.get("consent_actions", []) if not c.get("required")]
        if optional_consents:
            host_notices.append(
                "[可选环境提示] " + " ; ".join(f"{c['reason']}（如需自动处理请附加 `{c['flag']}`）" for c in optional_consents)
            )

        if sandbox["status"] == "FAIL":
            return {
                "stage": 0,
                "status": "FAIL",
                "code": "BLENDER_SANDBOX_FAILED",
                "env": env,
                "sandbox": sandbox,
                "host_notice": "\n".join(host_notices),
                "error": "Blender 隔离沙盒冒烟测试失败，无法启用 UEFormat 或构建基础材质。",
            }

        final_status = "PATCHED" if (sandbox["status"] == "PATCHED" or bool(bootstrap_actions)) else "PASS"
        state["stage_0"] = {
            "status": final_status,
            "env": env,
            "sandbox": sandbox,
            "self_audit": self_audit_res,
            "bootstrap_actions": bootstrap_actions,
        }
        self._save_state(state)

        return {
            "stage": 0,
            "status": final_status,
            "env": env,
            "sandbox": sandbox,
            "self_audit": self_audit_res,
            "bootstrap_actions": bootstrap_actions,
            "optional_consent_actions": optional_consents,
            "host_notice": "\n".join(host_notices),
            "next_prompt_for_user": "宿主机环境、本地 FModel 关联校验与 Blender 隔离沙盒冒烟测试已全部通过。请输入需要在 Blender 中进行风格化动作展示的《鸣潮》正式服已实装自机角色名称（支持中文、英文名、拼音或 ModelId）：",
        }

    def run_list_characters(
        self,
        *,
        query: Optional[str] = None,
        extra_keys_file: Optional[str] = None,
        ignore_fmodel_keys: bool = False,
    ) -> Dict[str, Any]:
        state = self._load_state()
        s0 = state.get("stage_0")
        if not s0 or s0.get("status") not in ("PASS", "PATCHED"):
            return {"status": "FAIL", "error": "Must run Stage 0 preflight first."}
        aes = resolve_and_verify_aes_keys(
            s0["env"],
            self.work_dir,
            extra_keys_file=extra_keys_file,
            ignore_fmodel_keys=ignore_fmodel_keys,
        )
        if aes["status"] == "CONSENT_REQUIRED":
            return {"status": "CONSENT_REQUIRED", "code": aes.get("code", "HOST_KEYS_REQUIRED"), "aes": aes, "host_notice": aes.get("host_notice", "")}
        if aes["status"] == "FAIL":
            return {"status": "FAIL", "aes": aes, "host_notice": aes.get("host_notice", "")}
        try:
            listing = list_available_characters(s0["env"], aes["key_files"], query=query, work_dir=self.work_dir)
        finally:
            (self.work_dir / "_transient_session_keys.json").unlink(missing_ok=True)
        return {
            "status": "PASS" if listing.get("ok") else "FAIL",
            "aes_status": aes["status"],
            "host_notice": aes.get("host_notice", ""),
            **listing,
        }

    def run_stage_1_extract(
        self,
        character_query: str,
        *,
        model_path: Optional[str] = None,
        extra_keys_file: Optional[str] = None,
        export_anims: bool = True,
        max_anims: int = 6,
        anim_names: Optional[List[str]] = None,
        ignore_fmodel_keys: bool = False,
    ) -> Dict[str, Any]:
        """Stage 1: Local AES Verification Gate + Character & Animation Parsing + VerifyGate 1."""
        state = self._load_state()
        s0 = state.get("stage_0")
        if not s0 or s0.get("status") not in ("PASS", "PATCHED"):
            return {"stage": 1, "status": "FAIL", "error": "Stage 0 Preflight has not passed. Run --step 0 first."}

        aes = resolve_and_verify_aes_keys(
            s0["env"],
            self.work_dir,
            extra_keys_file=extra_keys_file,
            ignore_fmodel_keys=ignore_fmodel_keys,
        )
        if aes["status"] == "CONSENT_REQUIRED":
            return {
                "stage": 1,
                "status": "CONSENT_REQUIRED",
                "code": aes.get("code", "HOST_KEYS_REQUIRED"),
                "aes": aes,
                "host_notice": aes.get("host_notice", ""),
                "error": aes.get("error", "Paused waiting for host-provided local key file/package"),
            }
        if aes["status"] == "FAIL":
            return {
                "stage": 1,
                "status": "FAIL",
                "code": "AES_RESOLUTION_FAILED",
                "aes": aes,
                "host_notice": aes.get("host_notice", ""),
                "error": aes.get("error", "Local AES key verification failed"),
            }

        slug = _safe_slug(character_query)
        runs_root = (self.work_dir / "runs").resolve()
        char_work_dir = (runs_root / slug).resolve()
        if char_work_dir == runs_root or not char_work_dir.is_relative_to(runs_root):
            return {"stage": 1, "status": "FAIL", "error": f"Invalid character output slug rejected: {slug!r}"}
        raw_out_dir = char_work_dir / "raw_extracted"

        try:
            ext = extract_character_assets(
                s0["env"],
                aes["key_files"],
                character_query,
                raw_out_dir,
                model_path_override=model_path,
                export_anims=export_anims,
                max_anims=max_anims,
                anim_names=anim_names,
                work_dir=self.work_dir,
            )
        finally:
            (self.work_dir / "_transient_session_keys.json").unlink(missing_ok=True)
        final_status = ext["status"]

        result = {
            "stage": 1,
            "status": final_status,
            "character_query": character_query,
            "run_dir": str(char_work_dir.resolve()),
            "aes": aes,
            "extraction": ext,
            "host_notice": aes.get("host_notice", ""),
        }
        state["active_run_dir"] = str(char_work_dir.resolve())
        state["stage_1"] = result
        self._save_state(state)
        return result

    def run_stage_2_texture_audit(self) -> Dict[str, Any]:
        """Stage 2 (Texture Audit & Channel Repair): 3-tier matching, _N split, _SDF correlation + VerifyGate 3."""
        state = self._load_state()
        s0 = state.get("stage_0")
        s1 = state.get("stage_1")
        if not s1 or s1.get("status") not in ("PASS", "PATCHED"):
            return {"stage": 2, "status": "FAIL", "error": "Stage 1 has not passed."}

        run_dir = Path(s1["run_dir"])
        ext_idx = Path(s1["extraction"]["extraction_index"])
        audit_dir = run_dir / "texture_audit"
        res = audit_and_process_textures(ext_idx, audit_dir, blender_info=s0["env"]["blender"])

        out = {"stage": 2, **res}
        state["stage_2_textures"] = out
        self._save_state(state)
        return out

    def run_stage_3_blender_showcase(self) -> Dict[str, Any]:
        """Stage 3 (Blender Assembly & Stylized Motion Showcase): .uemodel + Toon Shader + .ueanim + Ribbon + Shape Keys + Previews + FBX Roundtrip."""
        state = self._load_state()
        s0 = state.get("stage_0")
        s1 = state.get("stage_1")
        s2 = state.get("stage_2_textures")
        if not s2 or s2.get("status") not in ("PASS", "PATCHED"):
            return {"stage": 3, "status": "FAIL", "error": "Stage 2 texture audit has not passed."}

        run_dir = Path(s1["run_dir"])
        deliverable_dir = run_dir / "deliverable"
        res = run_blender_assembly(
            s0["env"],
            s0["sandbox"],
            Path(s1["extraction"]["extraction_index"]),
            Path(s2["audit_report_path"]),
            deliverable_dir,
        )
        out = {"stage": 3, **res}
        state["stage_3_blender"] = out
        self._save_state(state)
        return out

    def run_stage_4_package_delivery(self) -> Dict[str, Any]:
        """Stage 4: Standardized Handoff Manifest + Delivery & Motion Verification Report + VerifyGate 4."""
        state = self._load_state()
        s0 = state.get("stage_0")
        s1 = state.get("stage_1")
        s2 = state.get("stage_2_textures")
        s3 = state.get("stage_3_blender")
        if not s3 or s3.get("status") not in ("PASS", "PATCHED"):
            return {"stage": 4, "status": "FAIL", "error": "Stage 3 Blender assembly has not passed."}

        run_dir = Path(s1["run_dir"])
        deliverable_dir = run_dir / "deliverable"
        res = build_handoff_and_delivery_report(
            s0["env"],
            s0["sandbox"],
            s1["aes"],
            s1["extraction"],
            s2,
            s3,
            deliverable_dir,
        )
        out = {"stage": 4, **res}
        state["stage_4_delivery"] = out
        self._save_state(state)
        return out

    def run_auto(
        self,
        character_query: str,
        *,
        game_dir: Optional[str] = None,
        blender_path: Optional[str] = None,
        fmodel_dir: Optional[str] = None,
        model_path: Optional[str] = None,
        extra_keys_file: Optional[str] = None,
        consent_downloads: Optional[List[str]] = None,
        consent_link_fmodel: bool = False,
        export_anims: bool = True,
        max_anims: int = 6,
        anim_names: Optional[List[str]] = None,
        ignore_fmodel_keys: bool = False,
    ) -> Dict[str, Any]:
        """Run full end-to-end pipeline Stage 0 -> 1 -> 2 -> 3 -> 4 with strict VerifyGate halting."""
        notices: List[str] = []

        r0 = self.run_stage_0_preflight(
            game_dir=game_dir,
            blender_path=blender_path,
            fmodel_dir=fmodel_dir,
            extra_keys_file=extra_keys_file,
            consent_downloads=consent_downloads,
            consent_link_fmodel=consent_link_fmodel,
        )
        if r0.get("host_notice"):
            notices.append(r0["host_notice"])
        if r0["status"] not in ("PASS", "PATCHED"):
            return {"status": r0["status"], "failed_stage": 0, "stage_0": r0, "host_notice": "\n".join(notices)}

        r1 = self.run_stage_1_extract(
            character_query,
            model_path=model_path,
            extra_keys_file=extra_keys_file,
            export_anims=export_anims,
            max_anims=max_anims,
            anim_names=anim_names,
            ignore_fmodel_keys=ignore_fmodel_keys,
        )
        if r1.get("host_notice"):
            notices.append(r1["host_notice"])
        if r1["status"] not in ("PASS", "PATCHED"):
            return {"status": r1["status"], "failed_stage": 1, "stage_0": r0, "stage_1": r1, "host_notice": "\n".join(notices)}

        r2 = self.run_stage_2_texture_audit()
        if r2["status"] not in ("PASS", "PATCHED"):
            return {"status": "FAIL", "failed_stage": 2, "stage_0": r0, "stage_1": r1, "stage_2": r2, "host_notice": "\n".join(notices)}

        r3 = self.run_stage_3_blender_showcase()
        if r3["status"] not in ("PASS", "PATCHED"):
            return {"status": "FAIL", "failed_stage": 3, "stage_0": r0, "stage_1": r1, "stage_2": r2, "stage_3": r3, "host_notice": "\n".join(notices)}

        r4 = self.run_stage_4_package_delivery()
        overall = "PASS"
        if r4["status"] != "PASS":
            overall = "FAIL"
        elif any(r.get("status") == "PATCHED" for r in (r0, r1)):
            overall = "PATCHED"

        return {
            "status": overall,
            "character": r1["extraction"].get("character"),
            "host_notice": "\n".join(n for n in notices if n),
            "deliverables": {
                "showcase_blend": r4.get("showcase_blend_path"),
                "handoff_fbx": r4.get("handoff_fbx_path"),
                "handoff_manifest": r4.get("handoff_manifest_path"),
                "delivery_report": r4.get("delivery_report_md"),
                "preview_renders": r4.get("preview_renders", []),
            },
            "stages": {
                "stage_0": {"status": r0["status"], "blender": r0["env"]["blender"]["version"]},
                "stage_1": {"status": r1["status"], "summary": r1["extraction"].get("summary")},
                "stage_2": {"status": r2["status"], "summary": r2.get("summary")},
                "stage_3": {
                    "status": r3["status"],
                    "motion_verification": r3.get("motion_verification"),
                    "fbx_roundtrip_verify": r3.get("fbx_roundtrip_verify"),
                    "animations_imported": r3.get("animations", {}).get("imported_count"),
                },
                "stage_4": {"status": r4["status"], "verify_gate_4": r4.get("verify_gate_4")},
            },
        }
