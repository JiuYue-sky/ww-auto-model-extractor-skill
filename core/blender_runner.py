"""Stage 2 Runner: Launches sandboxed Blender headless assembly, animation & FBX round-trip verification (VerifyGate 2)."""

from __future__ import annotations

import ctypes
import json
import locale
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from .addon_sandbox import build_sandbox_env
from .watchdog import run_watched


def _map_locale_to_blender_languages(raw_locale: str) -> List[str]:
    """Map an OS/BCP-47/POSIX/Blender locale identifier into ordered Blender language candidates.

    Includes both Blender 4.x/5.x codes (zh_HANS / zh_HANT) and Blender 3.6 legacy fallbacks (zh_CN / zh_TW).
    """
    raw = (raw_locale or "").strip()
    if not raw:
        return ["en_US"]
    norm = raw.split(".", 1)[0].split("@", 1)[0].strip().replace("-", "_").lower()

    # Direct Blender language identifiers or explicit overrides
    if norm in ("zh_hans", "zh_cn", "zh_sg", "zh") or "chinese (simplified)" in norm or norm.startswith("zh_hans"):
        return ["zh_HANS", "zh_CN"]
    if norm in ("zh_hant", "zh_tw", "zh_hk", "zh_mo") or "chinese (traditional)" in norm or norm.startswith("zh_hant"):
        return ["zh_HANT", "zh_TW"]
    if norm.startswith("ja") or "japanese" in norm:
        return ["ja_JP"]
    if norm.startswith("ko") or "korean" in norm:
        return ["ko_KR"]
    if norm.startswith("ru") or "russian" in norm:
        return ["ru_RU"]
    if norm.startswith("de") or "german" in norm:
        return ["de_DE"]
    if norm.startswith("fr") or "french" in norm:
        return ["fr_FR"]
    if norm.startswith("es") or "spanish" in norm:
        return ["es"]
    if norm.startswith("it") or "italian" in norm:
        return ["it_IT"]
    if norm in ("pt_br", "pt_brazil"):
        return ["pt_BR", "pt_PT"]
    if norm.startswith("pt") or "portuguese" in norm:
        return ["pt_PT", "pt_BR"]
    if norm.startswith("en") or norm in ("c", "posix") or "english" in norm:
        return ["en_US"]
    return [raw, "en_US"]


def detect_host_blender_ui_language(override_locale: Optional[str] = None) -> Dict[str, Any]:
    """Read-only detection of host OS/UI language for localizing .blend WorkSpace tabs (never mutates host config)."""
    if override_locale is not None:
        return {
            "source": "override",
            "raw_locale": override_locale,
            "blender_languages": _map_locale_to_blender_languages(override_locale),
        }

    env_override = (os.environ.get("WW_BLENDER_UI_LANGUAGE") or "").strip()
    if env_override:
        return {
            "source": "env:WW_BLENDER_UI_LANGUAGE",
            "raw_locale": env_override,
            "blender_languages": _map_locale_to_blender_languages(env_override),
        }

    raw_loc = ""
    source = "default"
    if os.name == "nt":
        try:
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, len(buf)) > 0 and buf.value:
                raw_loc = buf.value
                source = "win32:GetUserDefaultLocaleName"
        except Exception:
            pass
        if not raw_loc:
            try:
                lcid = int(ctypes.windll.kernel32.GetUserDefaultUILanguage())
                if lcid in (0x0804, 0x1004):
                    raw_loc = "zh-CN"
                    source = "win32:GetUserDefaultUILanguage"
                elif lcid in (0x0404, 0x0C04, 0x1404):
                    raw_loc = "zh-TW"
                    source = "win32:GetUserDefaultUILanguage"
            except Exception:
                pass
    else:
        for k in ("LC_ALL", "LC_MESSAGES", "LANG"):
            v = (os.environ.get(k) or "").strip()
            if v:
                raw_loc = v
                source = f"env:{k}"
                break

    if not raw_loc:
        try:
            loc_tuple = locale.getlocale()
            if loc_tuple and loc_tuple[0]:
                raw_loc = str(loc_tuple[0])
                source = "python:locale.getlocale"
        except Exception:
            pass

    return {
        "source": source,
        "raw_locale": raw_loc or "en_US",
        "blender_languages": _map_locale_to_blender_languages(raw_loc or "en_US"),
    }


def _safe_exists(path_str: str) -> bool:
    if not path_str:
        return False
    ps = os.path.abspath(path_str)
    if os.name == "nt" and len(ps) >= 240 and not ps.startswith("\\\\?\\"):
        ps = "\\\\?\\" + ps
    return os.path.isfile(ps)


def run_blender_assembly(
    env_report: Dict[str, Any],
    sandbox_report: Dict[str, Any],
    extraction_index_path: Path,
    texture_audit_path: Path,
    deliverable_dir: Path,
) -> Dict[str, Any]:
    """Execute `blender_assemble.py` inside the isolated sandbox and assert VerifyGate 2."""
    blender_exe = env_report["blender"]["executable"]
    sandbox_root = Path(sandbox_report["sandbox_root"])
    env = build_sandbox_env(sandbox_root)

    idx = json.loads(extraction_index_path.read_text(encoding="utf-8-sig"))
    char_info = idx.get("character", {})
    model_id = char_info.get("model_id") or "Character"
    raw_meshes = idx.get("meshes", [])
    primary_meshes = [m for m in raw_meshes if m.get("is_primary", True)]
    if not primary_meshes and raw_meshes:
        primary_meshes = [raw_meshes[0]]
    variant_meshes = [m for m in raw_meshes if m not in primary_meshes]

    uemodel_paths = [m["uemodel_path"] for m in primary_meshes if _safe_exists(m.get("uemodel_path", ""))]
    variant_uemodel_paths = [m["uemodel_path"] for m in variant_meshes if _safe_exists(m.get("uemodel_path", ""))]
    anims = idx["verified_animations"] if "verified_animations" in idx else (idx.get("animations") or [])

    deliverable_dir.mkdir(parents=True, exist_ok=True)
    work_meta_dir = deliverable_dir / "_work"
    work_meta_dir.mkdir(parents=True, exist_ok=True)

    blend_out = deliverable_dir / "blender_showcase" / f"{model_id}_showcase.blend"
    preview_dir = deliverable_dir / "blender_showcase" / "previews"
    handoff_dir = deliverable_dir / "ue_handoff"

    uef_mod = (
        sandbox_report.get("smoke_test", {}).get("ueformat_resolved_module")
        or sandbox_report.get("addons", {}).get("ueformat", {}).get("module_name")
        or "bl_ext.user_default.io_scene_ueformat"
    )

    ui_lang_info = detect_host_blender_ui_language()

    job_payload = {
        "model_id": model_id,
        "ueformat_module": uef_mod,
        "uemodel_paths": uemodel_paths,
        "variant_uemodel_paths": variant_uemodel_paths,
        "texture_audit_path": str(texture_audit_path.resolve()),
        "animations": anims,
        "blend_out_path": str(blend_out.resolve()),
        "preview_dir": str(preview_dir.resolve()),
        "handoff_dir": str(handoff_dir.resolve()),
        "host_ui_locale": ui_lang_info["raw_locale"],
        "ui_language_candidates": ui_lang_info["blender_languages"],
    }
    job_path = work_meta_dir / "blender_job.json"
    result_path = work_meta_dir / "blender_result.json"
    job_path.write_text(json.dumps(job_payload, indent=2, ensure_ascii=False), encoding="utf-8")

    assemble_script = Path(__file__).resolve().parent / "blender_assemble.py"
    cmd = [
        str(blender_exe),
        "--background",
        "--factory-startup",
        "--python",
        str(assemble_script),
        "--",
        str(job_path.resolve()),
        str(result_path.resolve()),
    ]

    res = run_watched(
        cmd,
        env=env,
        hard_timeout_s=360,
        io_idle_timeout_s=90,
        watch_dir=deliverable_dir,
        max_retries=2,
        label="blender-assemble",
    )

    if not res.ok or not result_path.is_file():
        return {
            "status": "FAIL",
            "error": f"Blender assembly failed (rc={res.returncode}): {res.stderr[-1000:] or res.stdout[-1000:]}",
            "watchdog": res.to_dict(),
        }

    data = json.loads(result_path.read_text(encoding="utf-8"))

    # === VerifyGate 2: Deterministic geometry, skeleton, morph, animation & render assertions ===
    gate_failures: List[str] = []
    gate_warnings: List[str] = list(data.get("warnings", []))

    if not data.get("ok"):
        gate_failures.append(f"Blender script reported error: {data.get('errors')}")

    geo = data.get("geometry", {})
    rt = data.get("fbx_roundtrip_verify", {})
    anim_summary = data.get("animations", {})
    motion = data.get("motion_verification", {})
    renders = data.get("renders", [])

    if int(geo.get("total_vertices", 0)) < 100:
        gate_failures.append(f"Geometry vertex count too low: {geo.get('total_vertices')}")
    if int(geo.get("bone_count", 0)) < 10:
        gate_failures.append(f"Skeleton bone count too low: {geo.get('bone_count')}")

    # Check FBX roundtrip integrity
    if not Path(data.get("handoff_fbx_path", "")).is_file() or int(rt.get("fbx_bytes", 0)) < 1024:
        gate_failures.append("Handoff FBX missing or empty.")
    if rt.get("has_double_root_armature"):
        gate_failures.append(f"Double-root trap detected in exported FBX! Roots={rt.get('root_bones')}")
    if int(geo.get("shape_key_count", 0)) > 0 and float(rt.get("morph_retention_ratio", 0.0)) < 0.95:
        gate_failures.append(
            f"Morph target loss in FBX export! Original={geo.get('shape_key_count')} vs Roundtrip={rt.get('shape_key_count')}"
        )
    if int(geo.get("physics_bone_count", 0)) > 0 and int(rt.get("physics_bone_count", 0)) < int(geo.get("physics_bone_count", 0)):
        gate_failures.append(
            f"Physics Bone* chain loss in FBX! Original={geo.get('physics_bone_count')} vs Roundtrip={rt.get('physics_bone_count')}"
        )

    # Check Blender Showcase .blend + Real In-Game Motion + Non-Blank Renders!
    if not Path(data.get("showcase_blend_path", "")).is_file():
        gate_failures.append("Showcase .blend file was not saved.")
    if anims and int(anim_summary.get("imported_count", 0)) == 0:
        gate_failures.append("Extracted animations were provided, but 0 animations imported into Blender.")
    if anims and not motion.get("animated"):
        gate_failures.append(
            f"Motion verification failed: character appears static across sampled frames ({motion})."
        )
    cg_audit = anim_summary.get("channel_group_audit") or {}
    if int(cg_audit.get("total_fcurves", 0)) > 0 and not cg_audit.get("all_curves_grouped", False):
        gate_failures.append(
            f"Action channel groups incomplete (ISS-008): {cg_audit.get('grouped_fcurves')}/{cg_audit.get('total_fcurves')} curves grouped."
        )
    blank_renders = [r["shot"] for r in renders if not r.get("non_blank_ok")]
    if not renders:
        gate_failures.append("No preview renders were produced.")
    elif blank_renders:
        gate_failures.append(f"Blank or solid-color preview renders detected: {blank_renders}")

    unmatched_mats = data.get("materials", {}).get("unmatched_slots", [])
    if unmatched_mats:
        gate_warnings.append(f"Material slots without matched _D base color: {unmatched_mats}")

    data["verify_gate_2"] = {
        "passed": len(gate_failures) == 0,
        "failures": gate_failures,
        "warnings": gate_warnings,
    }
    result_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "PASS" if not gate_failures else "FAIL",
        "result_path": str(result_path.resolve()),
        "showcase_blend_path": data.get("showcase_blend_path"),
        "handoff_fbx_path": data.get("handoff_fbx_path"),
        "geometry": geo,
        "fbx_roundtrip_verify": rt,
        "animations": anim_summary,
        "motion_verification": motion,
        "renders": renders,
        "workspace_localization": data.get("workspace_localization"),
        "verify_gate_2": data["verify_gate_2"],
        "watchdog": res.to_dict(),
    }
