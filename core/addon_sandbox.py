"""Stage 0 Gate: Blender 3.6/4.x/5.x Addon AST Compatibility Scanner, Sandbox Patcher & Headless Smoke Test.

Key engineering guarantees:
- NEVER modifies host global Blender addon/extension directories.
- Isolates Blender via BLENDER_USER_SCRIPTS + BLENDER_USER_EXTENSIONS + BLENDER_USER_CONFIG.
- Scans UEFormat addon Python AST for cross-version breaking APIs across Blender 3.6, 4.0, 4.1, 4.2+, 4.4+, and 5.x.
- Produces structured `host_notice` BEFORE/WHEN applying sandbox compatibility patches.
- Runs real headless Blender smoke test verifying UEFormat enables cleanly and can construct a dummy toon material.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .watchdog import run_watched


@dataclass
class CompatIssue:
    file: str
    line: int
    rule_id: str
    min_broken_version: Tuple[int, int, int]
    description: str
    patch_strategy: str
    auto_patchable: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "rule_id": self.rule_id,
            "min_broken_version": ".".join(map(str, self.min_broken_version)),
            "description": self.description,
            "patch_strategy": self.patch_strategy,
            "auto_patchable": self.auto_patchable,
        }


def scan_python_source_compat(
    source_code: str,
    rel_file: str,
    blender_version: Tuple[int, int, int],
) -> List[CompatIssue]:
    """Static AST + pattern compatibility scan of a Blender addon Python source file."""
    issues: List[CompatIssue] = []
    try:
        tree = ast.parse(source_code, filename=rel_file)
    except SyntaxError as exc:
        issues.append(
            CompatIssue(
                file=rel_file,
                line=exc.lineno or 1,
                rule_id="SYNTAX_ERROR",
                min_broken_version=(3, 0, 0),
                description=f"Python syntax error: {exc.msg}",
                patch_strategy="Manual review required",
                auto_patchable=False,
            )
        )
        return issues

    lines = source_code.splitlines()

    def _has_guard(lineno: int, keywords: Tuple[str, ...]) -> bool:
        lo = max(0, lineno - 4)
        hi = min(len(lines), lineno + 2)
        window = "\n".join(lines[lo:hi])
        return any(kw in window for kw in keywords)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            lineno = getattr(node, "lineno", 1)
            if val == "ShaderNodeMixRGB" and blender_version >= (4, 0, 0):
                if not _has_guard(lineno, ("'ShaderNodeMix'", '"ShaderNodeMix"', "app.version", "try:")):
                    issues.append(
                        CompatIssue(
                            file=rel_file,
                            line=lineno,
                            rule_id="B40_MIXRGB_REMOVED",
                            min_broken_version=(4, 0, 0),
                            description="ShaderNodeMixRGB removed in Blender 4.0+; must use ShaderNodeMix (data_type='RGBA').",
                            patch_strategy="Replace ShaderNodeMixRGB with compat helper creating ShaderNodeMix(data_type='RGBA')",
                        )
                    )

        if isinstance(node, ast.Subscript) and blender_version >= (4, 0, 0):
            if isinstance(node.value, ast.Attribute) and node.value.attr == "inputs":
                key_val = None
                if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                    key_val = node.slice.value
                if key_val in ("Specular", "Subsurface", "Transmission"):
                    lineno = getattr(node, "lineno", 1)
                    if not _has_guard(lineno, ("Specular IOR Level", "Subsurface Weight", "Transmission Weight", "if ", "get(")):
                        rename_map = {
                            "Specular": "Specular IOR Level",
                            "Subsurface": "Subsurface Weight",
                            "Transmission": "Transmission Weight",
                        }
                        issues.append(
                            CompatIssue(
                                file=rel_file,
                                line=lineno,
                                rule_id=f"B40_BSDF_SOCKET_{key_val.upper()}",
                                min_broken_version=(4, 0, 0),
                                description=f"Principled BSDF input '{key_val}' renamed to '{rename_map[key_val]}' in Blender 4.0+.",
                                patch_strategy=f"Rewrite inputs['{key_val}'] -> inputs['{rename_map[key_val]}']",
                            )
                        )

        if isinstance(node, ast.Attribute) and node.attr == "use_auto_smooth" and blender_version >= (4, 1, 0):
            lineno = getattr(node, "lineno", 1)
            if not _has_guard(lineno, ("hasattr", "getattr", "try:", "app.version")):
                issues.append(
                    CompatIssue(
                        file=rel_file,
                        line=lineno,
                        rule_id="B41_USE_AUTO_SMOOTH_REMOVED",
                        min_broken_version=(4, 1, 0),
                        description="Mesh.use_auto_smooth removed in Blender 4.1+.",
                        patch_strategy="Guard attribute access with hasattr(..., 'use_auto_smooth')",
                    )
                )

        if isinstance(node, ast.Attribute) and node.attr == "fcurves" and blender_version >= (5, 0, 0):
            lineno = getattr(node, "lineno", 1)
            owner_src = ""
            if isinstance(node.value, ast.Name):
                owner_src = node.value.id.lower()
            if owner_src not in ("bag", "channelbag", "cb") and not _has_guard(
                lineno, ("getattr(", "channelbags", "action_fcurves", "hasattr", "app.version")
            ):
                issues.append(
                    CompatIssue(
                        file=rel_file,
                        line=lineno,
                        rule_id="B50_ACTION_FCURVES_REMOVED",
                        min_broken_version=(5, 0, 0),
                        description="Action.fcurves removed in Blender 5.0+ (replaced by action.layers[].strips[].channelbags[].fcurves).",
                        patch_strategy="Inject slotted-action channelbag helper for action.fcurves access",
                    )
                )

    return issues


def scan_addon_directory(addon_dir: Path, blender_version: Tuple[int, int, int]) -> List[CompatIssue]:
    """Scan all Python files inside an addon directory for Blender version compatibility issues."""
    all_issues: List[CompatIssue] = []
    for py_file in sorted(addon_dir.rglob("*.py")):
        if "__pycache__" in py_file.parts or ".bak" in py_file.name:
            continue
        rel = str(py_file.relative_to(addon_dir)).replace("\\", "/")
        try:
            src = py_file.read_text(encoding="utf-8-sig")
        except Exception:
            src = py_file.read_text(encoding="utf-8", errors="replace")
        all_issues.extend(scan_python_source_compat(src, rel, blender_version))
    return all_issues


def _insert_after_future_imports(source_code: str, helper_block: str) -> str:
    """Insert top-level helper AFTER module docstring and any `from __future__ import ...` lines."""
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return helper_block + "\n" + source_code

    insert_after_line = 0
    for idx, stmt in enumerate(tree.body):
        if idx == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            insert_after_line = max(insert_after_line, getattr(stmt, "end_lineno", stmt.lineno))
            continue
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
            insert_after_line = max(insert_after_line, getattr(stmt, "end_lineno", stmt.lineno))
            continue
        break

    lines = source_code.splitlines(keepends=True)
    if insert_after_line <= 0:
        return helper_block + "\n" + source_code
    return "".join(lines[:insert_after_line]) + "\n" + helper_block + "\n" + "".join(lines[insert_after_line:])


def patch_python_source_compat(source_code: str, blender_version: Tuple[int, int, int]) -> Tuple[str, List[str]]:
    """Apply deterministic compatibility patches to addon Python source code (inside sandbox ONLY)."""
    patched = source_code
    applied: List[str] = []

    if blender_version >= (4, 0, 0):
        for old_key, new_key in [
            ("Specular", "Specular IOR Level"),
            ("Subsurface", "Subsurface Weight"),
            ("Transmission", "Transmission Weight"),
        ]:
            pattern = rf"(\.inputs\[\s*['\"]){old_key}(['\"]\s*\])"
            new_src, cnt = re.subn(pattern, rf"\g<1>{new_key}\g<2>", patched)
            if cnt > 0:
                patched = new_src
                applied.append(f"BSDF inputs['{old_key}'] -> '{new_key}' ({cnt}x)")

        if "ShaderNodeMixRGB" in patched and "_ww_compat_new_mix_rgb" not in patched:
            helper = (
                "# [ww-auto-sandbox] Blender 4.x+ MixRGB compatibility shim\n"
                "def _ww_compat_new_mix_rgb(nodes):\n"
                "    n = nodes.new('ShaderNodeMix')\n"
                "    n.data_type = 'RGBA'\n"
                "    return n\n"
            )
            new_src, cnt = re.subn(
                r"([A-Za-z_][A-Za-z0-9_\.]*)\.new\(\s*['\"]ShaderNodeMixRGB['\"]\s*\)",
                r"_ww_compat_new_mix_rgb(\1)",
                patched,
            )
            if cnt > 0:
                patched = _insert_after_future_imports(new_src, helper)
                applied.append(f"ShaderNodeMixRGB -> ShaderNodeMix(RGBA) ({cnt}x)")

    if blender_version >= (4, 1, 0):
        new_src, cnt = re.subn(
            r"^([ \t]*)([A-Za-z_][A-Za-z0-9_\.]*)\.use_auto_smooth\s*=\s*(.+)$",
            r"\1setattr(\2, 'use_auto_smooth', \3) if hasattr(\2, 'use_auto_smooth') else None",
            patched,
            flags=re.MULTILINE,
        )
        if cnt > 0:
            patched = new_src
            applied.append(f"Guarded .use_auto_smooth assignment ({cnt}x)")

    if blender_version >= (5, 0, 0):
        if re.search(r"\baction\.fcurves\b", patched) and "_ww_compat_action_fcurves" not in patched and "def action_fcurves(" not in patched:
            helper = (
                "# [ww-auto-sandbox] Blender 5.x slotted Action.fcurves compatibility shim\n"
                "def _ww_compat_action_fcurves(act):\n"
                "    if act is None: return []\n"
                "    leg = getattr(act, 'fcurves', None)\n"
                "    if leg is not None: return leg\n"
                "    out = []\n"
                "    for layer in getattr(act, 'layers', ()):\n"
                "        for strip in getattr(layer, 'strips', ()):\n"
                "            for cb in getattr(strip, 'channelbags', ()):\n"
                "                out.extend(getattr(cb, 'fcurves', ()))\n"
                "    return out\n"
            )
            new_src, cnt = re.subn(r"\baction\.fcurves\b", "_ww_compat_action_fcurves(action)", patched)
            if cnt > 0:
                patched = _insert_after_future_imports(new_src, helper)
                applied.append(f"action.fcurves -> slotted-action helper ({cnt}x)")

    if applied:
        ast.parse(patched)

    return patched, applied


def build_sandbox_env(sandbox_root: Path) -> Dict[str, str]:
    """Return environment dict isolating Blender scripts, extensions, and config to sandbox_root."""
    env = os.environ.copy()
    scripts_dir = sandbox_root / "scripts"
    ext_dir = sandbox_root / "extensions"
    cfg_dir = sandbox_root / "config"
    (scripts_dir / "addons").mkdir(parents=True, exist_ok=True)
    (ext_dir / "user_default").mkdir(parents=True, exist_ok=True)
    cfg_dir.mkdir(parents=True, exist_ok=True)

    env["BLENDER_USER_SCRIPTS"] = str(scripts_dir.resolve())
    env["BLENDER_USER_EXTENSIONS"] = str(ext_dir.resolve())
    env["BLENDER_USER_CONFIG"] = str(cfg_dir.resolve())
    return env


def _copy_addon_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)

    def _ignore(_dir: str, names: List[str]) -> List[str]:
        return [n for n in names if n == "__pycache__" or ".bak" in n or n.endswith(".pyc")]

    shutil.copytree(src, dst, ignore=_ignore)


def prepare_and_verify_blender_sandbox(
    blender_info: Dict[str, Any],
    addons_info: Dict[str, Any],
    sandbox_root: Path,
) -> Dict[str, Any]:
    """Prepare isolated Blender sandbox, scan & patch UEFormat if needed, and run headless smoke test."""
    if not blender_info.get("found"):
        return {
            "status": "FAIL",
            "error": "Blender not available for sandbox preparation",
        }

    blender_exe = blender_info["executable"]
    ver_tup = tuple(blender_info.get("version_tuple") or (4, 2, 0))
    uses_ext = ver_tup >= (4, 2, 0)

    sandbox_root.mkdir(parents=True, exist_ok=True)
    env = build_sandbox_env(sandbox_root)
    ext_user_default = sandbox_root / "extensions" / "user_default"
    legacy_addons = sandbox_root / "scripts" / "addons"

    addon_reports: Dict[str, Any] = {}
    host_notices: List[str] = []
    any_patched = False

    uef_meta = addons_info.get("ueformat", {})
    uef_module_name = ""
    if uef_meta.get("found") and uef_meta.get("selected_path"):
        src_uef = Path(uef_meta["selected_path"])
        is_ext_pkg = (src_uef / "blender_manifest.toml").is_file() and uses_ext
        dst_uef = (ext_user_default / "io_scene_ueformat") if is_ext_pkg else (legacy_addons / "io_scene_ueformat")
        uef_module_name = "bl_ext.user_default.io_scene_ueformat" if is_ext_pkg else "io_scene_ueformat"
        _copy_addon_clean(src_uef, dst_uef)
        issues = scan_addon_directory(dst_uef, ver_tup)
        patches_applied: List[str] = []
        if issues:
            for py_file in sorted(dst_uef.rglob("*.py")):
                orig = py_file.read_text(encoding="utf-8", errors="replace")
                new_src, p_list = patch_python_source_compat(orig, ver_tup)
                if p_list:
                    py_file.write_text(new_src, encoding="utf-8")
                    patches_applied.extend([f"{py_file.name}: {x}" for x in p_list])
            if patches_applied:
                any_patched = True
                host_notices.append(
                    f"[插件沙盒热修补] Blender {blender_info['version']} 检测到 UEFormat 存在 {len(issues)} 处跨版本 API 差异，"
                    f"已在隔离沙盒 ({dst_uef}) 写入补丁（未修改宿主机原始安装目录）: {'; '.join(patches_applied)}"
                )
        addon_reports["ueformat"] = {
            "source": uef_meta["selected_source"],
            "sandbox_path": str(dst_uef),
            "module_name": uef_module_name,
            "issues_found": [i.to_dict() for i in issues],
            "patches_applied": patches_applied,
        }
    else:
        return {
            "status": "FAIL",
            "error": "UEFormat addon not found in host or bundled_addons/",
        }

    smoke_script = sandbox_root / "_smoke_test.py"
    smoke_script.write_text(
        f"""import json, sys, traceback
import bpy, addon_utils

result = {{
    "blender_version": list(bpy.app.version),
    "ueformat_enabled": False,
    "has_import_uemodel": False,
    "has_import_ueanim": False,
    "dummy_material_ok": False,
    "errors": [],
}}

try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if hasattr(bpy.utils, "refresh_script_paths"):
        bpy.utils.refresh_script_paths()
    try:
        bpy.ops.extensions.repo_sync_all()
    except Exception:
        pass

    uef_mod = {uef_module_name!r}
    for cand in (uef_mod, "bl_ext.user_default.io_scene_ueformat", "io_scene_ueformat"):
        if not cand:
            continue
        try:
            mod = addon_utils.enable(cand, default_set=True, persistent=False)
            if mod is not None and "import_uemodel" in dir(bpy.ops.uf):
                result["ueformat_enabled"] = True
                result["ueformat_resolved_module"] = cand
                break
        except Exception as exc:
            result["errors"].append(f"ueformat({{cand}}): {{exc}}")

    uf_ops = dir(bpy.ops.uf)
    result["has_import_uemodel"] = "import_uemodel" in uf_ops
    result["has_import_ueanim"] = "import_ueanim" in uf_ops

    mat = bpy.data.materials.new(name="_WW_SmokeTest_Mat")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    if bpy.app.version >= (4, 0, 0):
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    else:
        mix = nt.nodes.new("ShaderNodeMixRGB")
        nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    result["dummy_material_ok"] = True
except Exception as exc:
    result["errors"].append(traceback.format_exc())

print("WW_SMOKE_JSON:" + json.dumps(result, ensure_ascii=False))
""",
        encoding="utf-8",
    )

    res = run_watched(
        [str(blender_exe), "--background", "--factory-startup", "--python", str(smoke_script)],
        env=env,
        hard_timeout_s=60,
        io_idle_timeout_s=45,
        max_retries=1,
        label="blender-sandbox-smoke",
    )

    smoke_data: Dict[str, Any] = {}
    for line in res.stdout.splitlines():
        if line.startswith("WW_SMOKE_JSON:"):
            try:
                smoke_data = json.loads(line[len("WW_SMOKE_JSON:") :])
            except Exception:
                pass

    smoke_ok = bool(
        res.ok
        and smoke_data.get("ueformat_enabled")
        and smoke_data.get("has_import_uemodel")
        and smoke_data.get("has_import_ueanim")
        and smoke_data.get("dummy_material_ok")
    )

    status = "PASS" if (smoke_ok and not any_patched) else ("PATCHED" if smoke_ok else "FAIL")
    return {
        "status": status,
        "sandbox_root": str(sandbox_root.resolve()),
        "blender_version": blender_info["version"],
        "addons": addon_reports,
        "smoke_test": smoke_data,
        "watchdog": res.to_dict(),
        "host_notice": "\n".join(host_notices) if host_notices else "",
        "stderr_tail": res.stderr[-800:] if not smoke_ok else "",
    }
