"""Built-in Package, License & Compliance Self-Audit Engine.

Checks the pack/plugin ITSELF before or alongside pipeline runs:
1. Python AST syntax & import sanity across all core/*.py and orchestrator.py files.
2. Package structure & manifest contract consistency:
   - Universal Pack: AGENT_START_HERE.md + PIPELINE_MANIFEST.json + SKILL.md + orchestrator.py
   - DSH Plugin: package.json (`dsh.bundle.patch`, `icon` <= 256 KiB, `engines.dsh`) + cordis.patch.yml + lib/index.js + skills/*/SKILL.md
3. Bundled binary core health (`ww-extract.exe self-test`: Zlib-ng, Detex, ACL CUE4Parse-Natives.dll, SkiaSharp).
4. Bundled Blender addon integrity (`io_scene_ueformat` + its GPL-3.0 `LICENSE` file).
5. Compliance & legal boundaries:
   - Verifies NO proprietary `oodle-data-shared.dll` is bundled in `bin/`
   - Verifies NO unlicensed `ww_blender_reconstruct` addon is bundled in `bundled_addons/`
   - Verifies `THIRD_PARTY_LICENSES.md` and `NOTICE.md` exist
   - Verifies ZERO remote key endpoints (`wuwa-keys` / `yarik0chka` / `fetch_remote_wuwa_keys`) or leaked internal codenames
   - Verifies ZERO hardcoded private AES keys, game assets, or personal dev-machine paths!
6. Offline synthetic self-checks (AST patcher on Blender 4.x/5.x fixtures, AES validator, multiform Chinese matcher).
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .addon_sandbox import patch_python_source_compat, scan_python_source_compat
from .aes_resolver import validate_aes_key_bundle
from .blender_runner import detect_host_blender_ui_language
from .config_rules import (
    classify_texture_suffix,
    resolve_character_query_tokens,
    resolve_character_query_variants,
)
from .env_detector import detect_ww_extract

LEAKED_DEV_PATH_PATTERNS = [
    re.compile(
        r"[A-Za-z]:[/\\]{1,2}Users[/\\]{1,2}(?!<|your|user\b|example|runneradmin|administrator|public|default)[A-Za-z0-9._-]{3,}[/\\]{1,2}",
        re.IGNORECASE,
    ),
    re.compile(r"/Users/(?!<|your|user\b|example)[A-Za-z0-9._-]{3,}/"),
    re.compile(r"[A-Za-z]:[/\\]{1,2}Apps[/\\]{1,2}dotnet", re.IGNORECASE),
]

HARDCODED_AES_HEX_RE = re.compile(r"0x[0-9a-fA-F]{64}")
LEAKED_SECRET_TOKEN_RE = re.compile(
    r"(?:\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{24,}|AIza[0-9A-Za-z\-_]{30,}|xox[baprs]-[0-9A-Za-z\-]{10,}|vd_source=[0-9a-fA-F]{16,})\b|-----BEGIN [A-Z ]*PRIVATE KEY-----)"
)
BANNED_COMPLIANCE_TOKENS_RE = re.compile(
    r"(?:yarik0chka|wuwa-keys|fetch_remote_wuwa_keys|ww_blender_reconstruct|第九位魔神|太刀女|aimisigd|xinyuehushen)",
    re.IGNORECASE,
)
UNEXPECTED_CTRL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]")


def run_package_self_audit(project_root: Path, *, check_binary: bool = True) -> Dict[str, Any]:
    """Audit the current pack or DSH plugin directory for internal defects, contract drift, or compliance leaks."""
    project_root = project_root.resolve()
    checks: List[Dict[str, Any]] = []
    failures: List[str] = []
    warnings: List[str] = []

    def _record(name: str, ok: bool, detail: Any, severity: str = "error") -> None:
        checks.append({"check": name, "ok": ok, "severity": severity, "detail": detail})
        if not ok:
            if severity == "error":
                failures.append(f"[{name}] {detail}")
            else:
                warnings.append(f"[{name}] {detail}")

    is_dsh_plugin = (project_root / "package.json").is_file() and (project_root / "cordis.patch.yml").is_file()
    is_agent_pack = (project_root / "AGENT_START_HERE.md").is_file() and (project_root / "PIPELINE_MANIFEST.json").is_file()
    flavor = "dsh_plugin" if is_dsh_plugin else ("agent_pack" if is_agent_pack else "core_workspace")

    # 1. Python AST syntax check across core/ and orchestrator.py
    py_files: List[Path] = []
    for sub in ("core", "ww-auto-core"):
        d = project_root / sub
        if d.is_dir():
            py_files.extend(sorted(d.rglob("*.py")))
    if (project_root / "orchestrator.py").is_file():
        py_files.append(project_root / "orchestrator.py")

    syntax_errors: List[str] = []
    for pf in py_files:
        if "__pycache__" in pf.parts:
            continue
        try:
            ast.parse(pf.read_text(encoding="utf-8-sig"), filename=str(pf))
        except SyntaxError as exc:
            syntax_errors.append(f"{pf.relative_to(project_root)}:{exc.lineno}: {exc.msg}")
    _record(
        "python_ast_syntax",
        len(syntax_errors) == 0 and len(py_files) > 0,
        f"Checked {len(py_files)} Python files; errors={syntax_errors}" if syntax_errors else f"All {len(py_files)} Python files valid AST",
    )

    # 2. Flavor-specific manifest & contract checks
    if is_agent_pack:
        try:
            manifest = json.loads((project_root / "PIPELINE_MANIFEST.json").read_text(encoding="utf-8"))
            stages = manifest.get("stages", [])
            has_s0 = any(s.get("id") == 0 for s in stages)
            has_hard_game_gate = bool(manifest.get("safety_policies", {}).get("never_auto_download_game"))
            ue_not_required = manifest.get("safety_policies", {}).get("unreal_engine_required") is False
            no_remote_keys = manifest.get("safety_policies", {}).get("no_remote_aes_fetch") is True
            ok = has_s0 and has_hard_game_gate and ue_not_required and no_remote_keys and len(stages) >= 5
            _record(
                "agent_pack_manifest_contract",
                ok,
                f"stages={len(stages)}, has_s0={has_s0}, never_download_game={has_hard_game_gate}, ue_required=False:{ue_not_required}, no_remote_aes={no_remote_keys}",
            )
        except Exception as exc:
            _record("agent_pack_manifest_contract", False, f"Invalid PIPELINE_MANIFEST.json: {exc}")

        sop_text = (project_root / "AGENT_START_HERE.md").read_text(encoding="utf-8", errors="replace")
        sop_ok = ("--step 0" in sop_text or "Stage 0" in sop_text) and ("--self-audit" in sop_text) and ("consent" in sop_text.lower() or "同意" in sop_text)
        _record("agent_sop_completeness", sop_ok, "AGENT_START_HERE.md contains Stage 0, self-audit, and consent rules")

        pack_skill_md = project_root / "SKILL.md"
        if pack_skill_md.is_file():
            stxt = pack_skill_md.read_text(encoding="utf-8", errors="replace")
            has_zh_desc = bool(re.search(r"description:.*[\u4e00-\u9fff]", stxt))
            fm_ok = stxt.startswith("---") and "name: ww-auto-model-extractor" in stxt and "description:" in stxt and has_zh_desc
            _record("agent_pack_skill_frontmatter", fm_ok, f"Root SKILL.md valid frontmatter with Chinese description (zh_desc={has_zh_desc})")
        else:
            _record("agent_pack_skill_frontmatter", False, f"Missing dual-use root {pack_skill_md}")

        broken_links: List[str] = []
        missing_disclaimer: List[str] = []
        md_targets = [
            project_root / "README.md",
            project_root / "SKILL.md",
            project_root / "AGENT_START_HERE.md",
        ]
        if (project_root / "docs").is_dir():
            md_targets.extend(sorted((project_root / "docs").glob("*.md")))
        for md_f in md_targets:
            if not md_f.is_file():
                continue
            mtxt = md_f.read_text(encoding="utf-8", errors="replace")
            rel_md = md_f.relative_to(project_root).as_posix()
            for lm in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", mtxt):
                href = lm.group(1).strip()
                if href.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                target_p = (md_f.parent / href.split("#")[0]).resolve()
                if not (target_p.is_file() or target_p.is_dir()):
                    broken_links.append(f"{rel_md} -> {href}")
            if md_f.name in ("README.md", "SKILL.md", "AGENT_START_HERE.md", "USER_GUIDE_AND_NOTICES.md", "REFERENCES.md"):
                if not all(kw in mtxt for kw in ("免责", "非官方", "测试服", "商业", "交易", "Kuro Games")):
                    missing_disclaimer.append(rel_md)
        _record(
            "agent_pack_docs_links_and_compliance",
            len(broken_links) == 0 and len(missing_disclaimer) == 0,
            f"broken_links={broken_links}, missing_disclaimer={missing_disclaimer}",
        )

    if is_dsh_plugin:
        try:
            pkg = json.loads((project_root / "package.json").read_text(encoding="utf-8"))
            dsh_obj = pkg.get("dsh", {})
            patch_rel = dsh_obj.get("bundle", {}).get("patch")
            icon_rel = pkg.get("icon")
            icon_path = (project_root / icon_rel) if icon_rel else None
            icon_ok = bool(icon_path and icon_path.is_file() and icon_path.stat().st_size <= 256 * 1024)
            patch_ok = bool(patch_rel and (project_root / patch_rel).is_file())
            main_rel = pkg.get("main")
            main_ok = bool(main_rel and (project_root / main_rel).is_file())
            engines_dsh = pkg.get("engines", {}).get("dsh", "")
            engines_future_ok = bool(engines_dsh and engines_dsh.startswith(">=") and "<0.4.0" not in engines_dsh)
            desc_zh_ok = bool(re.search(r"[\u4e00-\u9fff]", str(pkg.get("description", ""))))
            _record(
                "dsh_package_json_spec",
                bool(patch_ok and icon_ok and main_ok and engines_future_ok and desc_zh_ok),
                f"patch_ok={patch_ok}, icon_ok={icon_ok} ({icon_path.stat().st_size if icon_path and icon_path.is_file() else 0}B <= 256KiB), main_ok={main_ok}, engines.dsh={engines_dsh} (future_ok={engines_future_ok}), desc_zh={desc_zh_ok}",
            )
        except Exception as exc:
            _record("dsh_package_json_spec", False, f"Invalid package.json: {exc}")

        loc_dir = project_root / "locale"
        en_loc = loc_dir / "en.json"
        zh_loc = loc_dir / "zh.json"
        stale_zhcn = loc_dir / "zh-CN.json"
        loc_issues: List[str] = []
        if not en_loc.is_file():
            loc_issues.append("missing locale/en.json (required by DSH readPluginMeta)")
        if not zh_loc.is_file():
            loc_issues.append("missing locale/zh.json (DSH uses 'zh', not 'zh-CN')")
        if stale_zhcn.is_file():
            loc_issues.append("stale locale/zh-CN.json present (remove to avoid confusion)")
        for lf, need_zh in ((en_loc, False), (zh_loc, True)):
            if lf.is_file():
                try:
                    lobj = json.loads(lf.read_text(encoding="utf-8"))
                    m = lobj.get("meta", {})
                    if not m.get("title") or not m.get("description"):
                        loc_issues.append(f"{lf.name}: missing meta.title or meta.description")
                    if need_zh and not (
                        re.search(r"[\u4e00-\u9fff]", str(m.get("title", "")))
                        and re.search(r"[\u4e00-\u9fff]", str(m.get("description", "")))
                    ):
                        loc_issues.append(f"{lf.name}: meta.title and meta.description must be Chinese")
                except Exception as exc:
                    loc_issues.append(f"{lf.name}: invalid JSON ({exc})")
        _record("dsh_locale_zh_en_spec", len(loc_issues) == 0, f"issues={loc_issues}" if loc_issues else "locale/en.json + locale/zh.json valid for DSH")

        dsh_readme = project_root / "README.md"
        readme_issues: List[str] = []
        if not dsh_readme.is_file():
            readme_issues.append("missing README.md")
        else:
            rtxt = dsh_readme.read_text(encoding="utf-8", errors="replace")
            rel_md_links = re.findall(r"\[[^\]]+\]\(((?!https?://|#|mailto:)[^)]+\.md(?:#[^)]*)?)\)", rtxt, flags=re.IGNORECASE)
            if rel_md_links:
                readme_issues.append(f"unclickable relative .md links in DSH UI README: {rel_md_links}")
            for req_kw in ("免责", "非官方", "测试服", "商业", "交易", "Kuro Games", "ww_action_sync.py", "D1–D4"):
                if req_kw not in rtxt:
                    readme_issues.append(f"README.md missing required section/keyword: {req_kw}")
        _record("dsh_readme_inline_and_compliance", len(readme_issues) == 0, f"issues={readme_issues}" if readme_issues else "DSH README self-contained with zero dead relative links & full disclaimer")

        skill_md = project_root / "skills" / "ww-auto-model-extractor" / "SKILL.md"
        if skill_md.is_file():
            stxt = skill_md.read_text(encoding="utf-8")
            has_zh_desc = bool(re.search(r"description:.*[\u4e00-\u9fff]", stxt))
            fm_ok = stxt.startswith("---") and "name: ww-auto-model-extractor" in stxt and "description:" in stxt and has_zh_desc
            _record("dsh_skill_frontmatter", fm_ok, f"SKILL.md has valid YAML frontmatter with Chinese description (zh_desc={has_zh_desc})")
        else:
            _record("dsh_skill_frontmatter", False, f"Missing {skill_md}")

        node_exe = shutil.which("node")
        idx_js = project_root / "lib" / "index.js"
        if idx_js.is_file():
            idx_src = idx_js.read_text(encoding="utf-8", errors="replace")
            has_bad_optional_inject = bool(re.search(r"export\s+const\s+inject\s*=\s*\{", idx_src))
            has_async_apply = bool(re.search(r"export\s+async\s+function\s+apply\b", idx_src))
            has_tools_inject = bool(re.search(r'export\s+const\s+inject\s*=\s*\[[^\]]*"tools"', idx_src))
            cordis4_ok = (not has_bad_optional_inject) and (not has_async_apply) and has_tools_inject
            _record(
                "dsh_cordis4_plugin_contract",
                cordis4_ok,
                f"array_inject_tools={has_tools_inject}, bad_object_inject={has_bad_optional_inject}, async_apply={has_async_apply}",
            )
        if node_exe and idx_js.is_file():
            nres = subprocess.run([node_exe, "--check", str(idx_js)], capture_output=True, text=True, timeout=15)
            _record("dsh_js_syntax", nres.returncode == 0, nres.stderr.strip() or "lib/index.js ESM syntax valid")

    # 3. Bundled ww-extract binary core health (open-source Zlib-ng + Detex + ACL + SkiaSharp)
    if check_binary:
        ext_info = detect_ww_extract(project_root)
        st = ext_info.get("self_test", {})
        nat = st.get("native", {})
        _record(
            "bundled_ww_extract_health",
            bool(ext_info.get("core_decoders_ok")),
            f"exe={ext_info.get('executable')}, core_decoders_ok={ext_info.get('core_decoders_ok')}, zlib={nat.get('zlib', {}).get('ok')}, detex={nat.get('detex', {}).get('ok')}, acl={nat.get('acl', {}).get('ok')}, host_oodle_ready={ext_info.get('oodle_ok')}",
        )

    # 4. Bundled Blender addons & third-party license file checks
    uef_init = project_root / "bundled_addons" / "io_scene_ueformat" / "__init__.py"
    uef_gpl = project_root / "bundled_addons" / "io_scene_ueformat" / "LICENSE"
    tp_lic = project_root / "THIRD_PARTY_LICENSES.md"
    notice_md = project_root / "NOTICE.md"
    bundled_oodle = project_root / "bin" / "ww-extract" / "native" / "oodle-data-shared.dll"
    bundled_ww_rec = project_root / "bundled_addons" / "ww_blender_reconstruct"
    if is_agent_pack or is_dsh_plugin:
        _record(
            "bundled_addon_ueformat_and_gpl",
            uef_init.is_file() and uef_gpl.is_file() and uef_gpl.stat().st_size > 10000,
            f"UEFormat present={uef_init.is_file()}, GPL-3.0 LICENSE present={uef_gpl.is_file()}",
        )
        _record(
            "compliance_third_party_and_binary_boundaries",
            tp_lic.is_file()
            and notice_md.is_file()
            and (not bundled_oodle.exists())
            and (not bundled_ww_rec.exists()),
            (
                f"THIRD_PARTY_LICENSES.md={tp_lic.is_file()}, NOTICE.md={notice_md.is_file()}, "
                f"no_bundled_oodle={not bundled_oodle.exists()}, no_unlicensed_ww_reconstruct={not bundled_ww_rec.exists()}"
            ),
        )

    # 5. Security, Privacy & Compliance Leak Scan across all shipped files
    leaked_paths: List[str] = []
    leaked_keys: List[str] = []
    banned_tokens: List[str] = []
    scan_exts = {".py", ".js", ".mjs", ".json", ".yml", ".yaml", ".md"}
    shipped_roots = [
        project_root / "core",
        project_root / "ww-auto-core",
        project_root / "lib",
        project_root / "locale",
        project_root / "skills",
        project_root / "docs",
        project_root / ".github",
        project_root / "bundled_addons",
        project_root / "tests",
    ]
    shipped_files: List[Path] = []
    for root_f in (
        "orchestrator.py",
        "package.json",
        "cordis.patch.yml",
        "AGENT_START_HERE.md",
        "SKILL.md",
        "PIPELINE_MANIFEST.json",
        "tools.schema.json",
        "README.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "CONTRIBUTING.md",
        "NOTICE.md",
        "THIRD_PARTY_LICENSES.md",
        "LICENSE",
    ):
        cand = project_root / root_f
        if cand.is_file():
            shipped_files.append(cand)
    for sr in shipped_roots:
        if sr.is_dir():
            for f in sr.rglob("*"):
                if f.is_file() and f.suffix.lower() in scan_exts and "__pycache__" not in f.parts:
                    shipped_files.append(f)

    for f in shipped_files:
        if f.name == "self_audit.py":
            continue
        rel_str = str(f.relative_to(project_root)).replace("\\", "/")
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if f.name != "test_pipeline_suite.py":
            for pat in LEAKED_DEV_PATH_PATTERNS:
                if pat.search(txt):
                    leaked_paths.append(f"{rel_str} matched {pat.pattern}")
            if HARDCODED_AES_HEX_RE.search(txt) or LEAKED_SECRET_TOKEN_RE.search(txt):
                leaked_keys.append(rel_str)
            m_ban = BANNED_COMPLIANCE_TOKENS_RE.search(txt)
            if m_ban:
                banned_tokens.append(f"{rel_str} ({m_ban.group(0)})")
            m_ctrl = UNEXPECTED_CTRL_CHAR_RE.search(txt)
            if m_ctrl:
                banned_tokens.append(f"{rel_str} (unexpected_ctrl_char={m_ctrl.group(0)!r})")

    _record(
        "no_hardcoded_dev_paths",
        len(leaked_paths) == 0,
        f"Leaked dev paths: {leaked_paths}" if leaked_paths else "Zero hardcoded personal/developer machine paths in shipped source",
    )
    _record(
        "no_bundled_aes_keys",
        len(leaked_keys) == 0,
        f"Hardcoded AES keys or secret tokens found in: {leaked_keys}" if leaked_keys else "Zero hardcoded AES keys or API tokens bundled",
    )
    _record(
        "no_remote_key_urls_or_unreleased_codenames",
        len(banned_tokens) == 0,
        f"Banned compliance tokens found in: {banned_tokens}" if banned_tokens else "Zero remote key endpoints or unreleased internal codenames in shipped files",
    )

    # 6. Offline functional self-checks
    sample_broken_36 = (
        "def build(nodes, mesh, action):\n"
        "    mix = nodes.new('ShaderNodeMixRGB')\n"
        "    bsdf = nodes.new('ShaderNodeBsdfPrincipled')\n"
        "    bsdf.inputs['Specular'].default_value = 0.5\n"
        "    mesh.use_auto_smooth = True\n"
        "    return list(action.fcurves)\n"
    )
    detected = scan_python_source_compat(sample_broken_36, "synthetic.py", (5, 2, 0))
    patched_src, applied = patch_python_source_compat(sample_broken_36, (5, 2, 0))
    remaining = scan_python_source_compat(patched_src, "synthetic.py", (5, 2, 0))
    ast_patcher_ok = len(detected) >= 4 and len(applied) >= 4 and len(remaining) == 0
    _record(
        "self_check_ast_patcher",
        ast_patcher_ok,
        f"detected={len(detected)}, applied={len(applied)}, remaining_after_patch={len(remaining)}",
    )

    v_lili = resolve_character_query_variants("莉莉")
    v_unlisted = resolve_character_query_variants("星月")
    tokens_ok = (
        "jinxi" in resolve_character_query_tokens("今汐")
        and "kmola" in resolve_character_query_tokens("珂莱塔")
        and "莉莉" in v_lili["chinese"]
        and "lili" in v_lili["english_lower"]
        and "Lili" in v_lili["english_capitalized"]
        and "星月" in v_unlisted["chinese"]
        and "xingyue" in v_unlisted["english_lower"]
        and "Xingyue" in v_unlisted["english_capitalized"]
        and "XingYue" in v_unlisted["english_capitalized"]
    )
    sfx_ok = classify_texture_suffix("T_R2T1JinxiMd10011Down_ID.png")[0] == "_id" and classify_texture_suffix("T_Foo_N.png")[0] == "_n"
    aes_val_ok = validate_aes_key_bundle({"mainKey": "0x" + "A" * 64, "dynamicKeys": []})["valid"] and not validate_aes_key_bundle({"mainKey": "bad"})["valid"]
    ui_lang_ok = (
        detect_host_blender_ui_language("zh-CN")["blender_languages"] == ["zh_HANS", "zh_CN"]
        and detect_host_blender_ui_language("en-US")["blender_languages"] == ["en_US"]
    )
    _record(
        "self_check_core_logic",
        bool(tokens_ok and sfx_ok and aes_val_ok and ui_lang_ok),
        f"multiform_match_ok={tokens_ok}, suffix_ok={sfx_ok}, aes_validator_ok={aes_val_ok}, ui_lang_ok={ui_lang_ok}",
    )

    return {
        "status": "PASS" if not failures else "FAIL",
        "flavor": flavor,
        "project_root": str(project_root),
        "total_checks": len(checks),
        "failed_count": len(failures),
        "warning_count": len(warnings),
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }
