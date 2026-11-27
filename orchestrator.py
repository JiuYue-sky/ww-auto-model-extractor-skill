#!/usr/bin/env python3
"""[Unofficial] Single-entry CLI orchestrator for Wuthering Waves Stylized Blender Showcase & UE Handoff.

Supports both stepwise Agent-driven execution (--self-audit, --step 0..4, --list-characters)
and full automated execution (--auto --character <name>).
Outputs deterministic JSON to stdout so any AI Agent or DeepSeekHarness plugin can parse it reliably.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
if (ROOT_DIR / "core").is_dir():
    sys.path.insert(0, str(ROOT_DIR))
    from core.pipeline import PipelineOrchestrator  # type: ignore
    from core.version import CORE_VERSION  # type: ignore
else:
    sys.path.insert(0, str(ROOT_DIR))
    import importlib.util

    pkg_dir = ROOT_DIR / "ww-auto-core"
    spec = importlib.util.spec_from_file_location("core", str(pkg_dir / "__init__.py"), submodule_search_locations=[str(pkg_dir)])
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core"] = mod
    spec.loader.exec_module(mod)
    from core.pipeline import PipelineOrchestrator  # type: ignore
    from core.version import CORE_VERSION  # type: ignore


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orchestrator.py",
        description="[Unofficial] Wuthering Waves Stylized Character Blender Showcase & UE Handoff Orchestrator",
    )
    p.add_argument("--version", action="store_true", help="Print version JSON and exit")
    p.add_argument("--self-audit", action="store_true", help="Run package/plugin internal compliance & health self-audit")
    p.add_argument("--step", type=int, choices=[0, 1, 2, 3, 4], help="Execute a specific pipeline stage (0..4)")
    p.add_argument("--auto", action="store_true", help="Execute full pipeline Stages 0..4 end-to-end")
    p.add_argument("--list-characters", action="store_true", help="List released playable characters discovered in local WW client")

    p.add_argument("--character", type=str, default="", help="Character name (Chinese / English / Pinyin / ModelId)")
    p.add_argument("--model-path", type=str, default="", help="Optional exact VFS model .uasset path override")
    p.add_argument("--query", type=str, default="", help="Optional filter for --list-characters")
    p.add_argument("--work-dir", type=str, default="", help="Workspace output directory (default: <pack>/output)")
    p.add_argument("--game-dir", type=str, default="", help="Optional override for local official Wuthering Waves install path")
    p.add_argument("--blender", type=str, default="", help="Optional override for Blender executable path")
    p.add_argument("--fmodel-dir", type=str, default="", help="Optional override for FModel directory")
    p.add_argument(
        "--keys-file",
        type=str,
        default="",
        help="Host-provided local key path (.json, .zip, .txt/.key, or folder containing keys.json; directly validated and linked to local FModel)",
    )

    p.add_argument("--no-anims", action="store_true", help="Skip animation assembly (default includes in-game animations)")
    p.add_argument("--max-anims", type=int, default=6, help="Max animations per character (default: 6)")
    p.add_argument("--anim-names", type=str, default="", help="Comma-separated specific animation names")
    p.add_argument(
        "--ignore-fmodel-keys",
        action="store_true",
        help="Ignore host FModel AppSettings.json AES keys and strictly use --keys-file / local keys.json",
    )

    p.add_argument(
        "--consent-download",
        type=str,
        default="",
        help="Explicit host consent to download missing components into isolated runtime/ (comma-separated: blender,oodle,fmodel; NEVER downloads game!)",
    )
    p.add_argument(
        "--consent-link-fmodel",
        action="store_true",
        help="Explicit host consent to backup AppSettings.json and link FModel directory to local Wuthering Waves",
    )
    return p


def _emit(payload: dict) -> int:
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    status = str(payload.get("status", "")).upper()
    if status in ("PASS", "PATCHED", "OK"):
        return 0
    if status == "CONSENT_REQUIRED":
        return 2
    return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()

    for field_name in (
        "character",
        "model_path",
        "query",
        "work_dir",
        "game_dir",
        "blender",
        "fmodel_dir",
        "keys_file",
        "anim_names",
        "consent_download",
    ):
        val = getattr(args, field_name, "")
        if isinstance(val, str) and "\x00" in val:
            return _emit({"status": "FAIL", "error": f"Invalid NUL byte rejected in --{field_name.replace('_', '-')}"})

    args.max_anims = max(1, min(64, int(args.max_anims)))

    if args.version:
        return _emit({"status": "PASS", "core_version": CORE_VERSION, "project_root": str(ROOT_DIR)})

    work_dir = Path(args.work_dir) if args.work_dir else None
    orch = PipelineOrchestrator(ROOT_DIR, work_dir=work_dir)

    consent_downloads = [x.strip() for x in args.consent_download.split(",") if x.strip()]
    anim_names = [x.strip() for x in args.anim_names.split(",") if x.strip()] or None

    if args.self_audit:
        return _emit(orch.run_self_audit())

    if args.list_characters:
        return _emit(
            orch.run_list_characters(
                query=args.query or None,
                extra_keys_file=args.keys_file or None,
                ignore_fmodel_keys=args.ignore_fmodel_keys,
            )
        )

    if args.auto:
        if not args.character and not args.model_path:
            return _emit({"status": "FAIL", "error": "--auto requires --character <name> or --model-path <vfs>"})
        return _emit(
            orch.run_auto(
                args.character or Path(args.model_path).stem,
                game_dir=args.game_dir or None,
                blender_path=args.blender or None,
                fmodel_dir=args.fmodel_dir or None,
                model_path=args.model_path or None,
                extra_keys_file=args.keys_file or None,
                consent_downloads=consent_downloads or None,
                consent_link_fmodel=args.consent_link_fmodel,
                export_anims=not args.no_anims,
                max_anims=args.max_anims,
                anim_names=anim_names,
                ignore_fmodel_keys=args.ignore_fmodel_keys,
            )
        )

    if args.step is None:
        return _emit({"status": "FAIL", "error": "Specify --self-audit, --step 0..4, --list-characters, or --auto"})

    if args.step == 0:
        return _emit(
            orch.run_stage_0_preflight(
                game_dir=args.game_dir or None,
                blender_path=args.blender or None,
                fmodel_dir=args.fmodel_dir or None,
                extra_keys_file=args.keys_file or None,
                consent_downloads=consent_downloads or None,
                consent_link_fmodel=args.consent_link_fmodel,
            )
        )
    if args.step == 1:
        if not args.character and not args.model_path:
            return _emit({"status": "FAIL", "stage": 1, "error": "Stage 1 requires --character <name> or --model-path <vfs>"})
        return _emit(
            orch.run_stage_1_extract(
                args.character or Path(args.model_path).stem,
                model_path=args.model_path or None,
                extra_keys_file=args.keys_file or None,
                export_anims=not args.no_anims,
                max_anims=args.max_anims,
                anim_names=anim_names,
                ignore_fmodel_keys=args.ignore_fmodel_keys,
            )
        )
    if args.step == 2:
        return _emit(orch.run_stage_2_texture_audit())
    if args.step == 3:
        return _emit(orch.run_stage_3_blender_showcase())
    if args.step == 4:
        return _emit(orch.run_stage_4_package_delivery())

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
