"""Stage 4: Standardized Handoff Packager (for downstream separate UE Import Plugin) & Delivery Report + VerifyGate 4.

Note: Unreal Engine is NOT required here. We emit a strictly versioned `handoff_manifest.json`
plus a self-contained Delivery & Motion Verification Report (`DELIVERY_REPORT.md` + `delivery_summary.json`)
and a reference `ue_handoff_reference.py` (optional reference script for the future UE handoff plugin).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from .version import (
    CONTACT_EMAIL,
    CORE_VERSION,
    HANDOFF_SCHEMA_VERSION,
    LEGAL_NOTICE,
    LEGAL_NOTICE_ZH,
    UPSTREAM_REFERENCES,
)


def _sha256_short(path: Path) -> str:
    if not path.is_file():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 512), b""):
            h.update(chunk)
    return h.hexdigest()


def _generate_ue_handoff_reference_script() -> str:
    """Generate an AST-valid optional UE4.27/UE5 Python reference importer reading `handoff_manifest.json`.

    Not executed by this project (UE is intentionally decoupled to a separate handoff plugin),
    provided as a machine-verified reference blueprint for the downstream UE handoff plugin.
    """
    return '''"""Optional Reference UE4.27 / UE5 Python Importer for `handoff_manifest.json`.

NOTE: This extraction workflow does NOT require Unreal Engine. A separate downstream
UE Handoff Plugin is intended to consume `handoff_manifest.json`. This reference script
can also be run manually inside Unreal Editor (Tools -> Execute Python Script) once
Python Editor Script Plugin & Editor Scripting Utilities are enabled.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

try:
    import unreal  # type: ignore
except ImportError:
    unreal = None


COMPRESSION_MAP = {
    "TC_Default": "TC_DEFAULT",
    "TC_Normalmap": "TC_NORMALMAP",
    "TC_Masks": "TC_MASKS",
    "TC_Grayscale": "TC_GRAYSCALE",
    "TC_BC7": "TC_BC7",
    "TC_VectorDisplacementmap": "TC_VECTOR_DISPLACEMENTMAP",
    "TC_EditorIcon": "TC_EDITOR_ICON",
    "TC_HDR": "TC_HDR",
}


def import_from_handoff_manifest(manifest_path: str, dest_content_path: str = "/Game/WW_Imported") -> dict:
    """Import FBX (preserving Normals/Tangents & Morph Targets) and configure textures per manifest."""
    if unreal is None:
        raise RuntimeError("This script must be executed inside Unreal Editor's Python environment.")

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    model_id = manifest["character"]["model_id"]
    target_root = f"{dest_content_path.rstrip('/')}/{model_id}"
    tex_root = f"{target_root}/Textures"
    tasks = []

    # 1. Skeletal Mesh FBX Import Task (Lock Import Normals & Tangents + Import Morph Targets!)
    fbx_file = manifest["handoff_assets"]["fbx_path"]
    if fbx_file and os.path.isfile(fbx_file):
        fbx_task = unreal.AssetImportTask()
        fbx_task.filename = fbx_file
        fbx_task.destination_path = target_root
        fbx_task.destination_name = model_id
        fbx_task.automated = True
        fbx_task.replace_existing = True
        fbx_task.save = True

        opts = unreal.FbxImportUI()
        opts.import_mesh = True
        opts.import_as_skeletal = True
        opts.import_materials = False
        opts.import_textures = False
        opts.import_animations = False
        opts.skeletal_mesh_import_data.import_morph_targets = True
        opts.skeletal_mesh_import_data.normal_import_method = unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS
        opts.skeletal_mesh_import_data.use_t0_as_ref_pose = True
        fbx_task.options = opts
        tasks.append(fbx_task)

    # 2. Texture Import Tasks (Scheme A split _N_Normal/_MR + primary textures)
    tex_records = []
    for trec in manifest.get("textures", []):
        if trec.get("is_switch_variant"):
            continue
        derived = trec.get("derived_files", {})
        if trec.get("slot") == "normal_packed" and derived.get("split_normal_bc5") and derived.get("split_mr_bc7"):
            tex_records.append((derived["split_normal_bc5"], False, "TC_Normalmap"))
            tex_records.append((derived["split_mr_bc7"], False, "TC_BC7"))
        else:
            src_path = derived.get("repaired_rgba") or trec.get("disk_path")
            if src_path and os.path.isfile(src_path):
                ue_cfg = trec.get("final_ue_settings", {})
                tex_records.append((src_path, bool(ue_cfg.get("srgb", False)), str(ue_cfg.get("compression", "TC_BC7"))))

    for src_path, _srgb, _comp in tex_records:
        tt = unreal.AssetImportTask()
        tt.filename = src_path
        tt.destination_path = tex_root
        tt.automated = True
        tt.replace_existing = True
        tt.save = False
        tasks.append(tt)

    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)

    # 3. Post-import Texture sRGB & Compression Configuration
    configured = 0
    for src_path, srgb, comp_name in tex_records:
        asset_name = Path(src_path).stem
        asset_path = f"{tex_root}/{asset_name}"
        tex_asset = unreal.EditorAssetLibrary.load_asset(asset_path)
        if tex_asset is None:
            continue
        tex_asset.set_editor_property("srgb", srgb)
        enum_attr = COMPRESSION_MAP.get(comp_name, "TC_BC7")
        if hasattr(unreal.TextureCompressionSettings, enum_attr):
            tex_asset.set_editor_property("compression_settings", getattr(unreal.TextureCompressionSettings, enum_attr))
        unreal.EditorAssetLibrary.save_loaded_asset(tex_asset)
        configured += 1

    return {"ok": True, "model_id": model_id, "target_root": target_root, "textures_configured": configured}


if __name__ == "__main__":
    default_manifest = str(Path(__file__).resolve().parent / "handoff_manifest.json")
    if os.path.isfile(default_manifest):
        print(import_from_handoff_manifest(default_manifest))
'''


def build_handoff_and_delivery_report(
    env_report: Dict[str, Any],
    sandbox_report: Dict[str, Any],
    aes_report: Dict[str, Any],
    extract_report: Dict[str, Any],
    texture_audit_result: Dict[str, Any],
    blender_result: Dict[str, Any],
    deliverable_dir: Path,
) -> Dict[str, Any]:
    """Assemble standardized handoff_manifest.json + Delivery Report + VerifyGate 4."""
    deliverable_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir = deliverable_dir / "ue_handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)

    ext_idx = json.loads(Path(extract_report["extraction_index"]).read_text(encoding="utf-8-sig"))
    tex_audit = json.loads(Path(texture_audit_result["audit_report_path"]).read_text(encoding="utf-8"))
    bl_data = json.loads(Path(blender_result["result_path"]).read_text(encoding="utf-8"))

    char_info = ext_idx.get("character", {})
    model_id = char_info.get("model_id", "Character")
    geo = bl_data.get("geometry", {})
    rt = bl_data.get("fbx_roundtrip_verify", {})
    anim_summary = bl_data.get("animations", {})
    motion = bl_data.get("motion_verification", {})
    renders = bl_data.get("renders", [])

    blend_path = Path(bl_data.get("showcase_blend_path", ""))
    fbx_path = Path(bl_data.get("handoff_fbx_path", ""))

    # Build clean texture list for downstream handoff plugin
    handoff_textures: List[Dict[str, Any]] = []
    for t in tex_audit.get("textures", []):
        pix = t.get("pixel_audit", {})
        handoff_textures.append(
            {
                "name": t["name"],
                "slot": t["slot"],
                "matched_tier": t["matched_tier"],
                "is_switch_variant": t.get("is_switch_variant", False),
                "is_hair_material": t.get("is_hair_material", False),
                "disk_path": t["disk_path"],
                "width": pix.get("width", t.get("size_x", 0)),
                "height": pix.get("height", t.get("size_y", 0)),
                "channels": pix.get("channels", 0),
                "all_zero": pix.get("all_zero", False),
                "ue_native_metadata": {
                    "srgb": t.get("ue_srgb"),
                    "pixel_format": t.get("ue_pixel_format"),
                    "compression": t.get("ue_compression"),
                },
                "final_ue_settings": t.get("final_ue_settings", {}),
                "alpha_semantics": pix.get("alpha_semantics"),
                "normal_audit": pix.get("normal_audit"),
                "sdf_audit": pix.get("sdf_audit"),
                "derived_files": pix.get("derived_files", {}),
            }
        )

    manifest = {
        "schema_version": HANDOFF_SCHEMA_VERSION,
        "core_version": CORE_VERSION,
        "contact_email": CONTACT_EMAIL,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "legal_notice": LEGAL_NOTICE,
        "legal_notice_zh": LEGAL_NOTICE_ZH,
        "compliance_restrictions": {
            "unofficial_non_affiliated": True,
            "personal_study_and_research_only": True,
            "no_commercial_use": True,
            "no_private_trading_or_resale": True,
            "no_public_asset_redistribution": True,
            "no_beta_or_unreleased_leaks": True,
            "no_process_injection_or_anticheat_bypass": True,
            "no_nsfw_or_defamatory_use": True,
        },
        "upstream_references": UPSTREAM_REFERENCES,
        "character": char_info,
        "host_context": {
            "ww_client_version": env_report["wuthering_waves"].get("client_version"),
            "blender_version": env_report["blender"].get("version"),
            "aes_coverage": f"{aes_report.get('aes', {}).get('mounted_paks', 0)}/{aes_report.get('aes', {}).get('total_paks', 0)}",
        },
        "blender_showcase": {
            "blend_path": str(blend_path.resolve()) if blend_path.is_file() else "",
            "blend_sha256": _sha256_short(blend_path),
            "textures_packed": bool(bl_data.get("textures_packed_in_blend")),
            "workspace_localization": bl_data.get("workspace_localization"),
            "active_action": anim_summary.get("active_showcase_action"),
            "ww_action_sync_embedded": bool(anim_summary.get("ww_action_sync_embedded")),
            "channel_group_audit": anim_summary.get("channel_group_audit"),
            "imported_animations": anim_summary.get("details", []),
            "motion_verification": motion,
            "preview_renders": renders,
        },
        "handoff_assets": {
            "note": "Standardized handoff bundle for downstream separate UE Import & Fix plugin (UE not required during extraction). Unbaked/curve-driven animations are excluded from extraction and listed in deferred_to_ue_animations (Decision D4).",
            "fbx_path": str(fbx_path.resolve()) if fbx_path.is_file() else "",
            "fbx_sha256": _sha256_short(fbx_path),
            "raw_extraction_dir": extract_report.get("out_dir"),
            "primary_uemodels": [m.get("uemodel_path") for m in ext_idx.get("meshes", []) if m.get("is_primary", True)],
            "variant_uemodels": [m.get("uemodel_path") for m in ext_idx.get("meshes", []) if not m.get("is_primary", True)],
            "raw_uemodels": [m.get("uemodel_path") for m in ext_idx.get("meshes", [])],
            "raw_ueanims": [
                {
                    "name": a.get("name"),
                    "category": a.get("category"),
                    "path": a.get("ueanim_path"),
                    "is_aerial_loop": bool((a.get("bake_status") or {}).get("is_aerial_loop", False)),
                    "blender_showcase_acceptance": bool((a.get("bake_status") or {}).get("blender_showcase_acceptance", True)),
                }
                for a in ext_idx.get("verified_animations", [])
            ],
            "deferred_to_ue_animations": ext_idx.get("filtered_unbaked_animations", []),
            "material_jsons": ext_idx.get("materials", []),
            "ue_import_requirements": {
                "normal_import_method": "Import Normals and Tangents",
                "import_morph_targets": True,
                "smooth_normal_uv_index": geo.get("uv_audit", {}).get("smooth_normal_uv_index", 1),
                "root_bones": rt.get("root_bones", []),
                "has_double_root_armature": rt.get("has_double_root_armature", False),
                "skeleton_hash": geo.get("skeleton_hash"),
                "physics_bone_count": rt.get("physics_bone_count", 0),
                "morph_target_count": rt.get("shape_key_count", 0),
            },
        },
        "materials": tex_audit.get("materials", {}),
        "textures": handoff_textures,
    }

    manifest_path = handoff_dir / "handoff_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write optional UE handoff reference script and syntax-check it via AST!
    ref_script_path = handoff_dir / "ue_handoff_reference.py"
    ref_code = _generate_ue_handoff_reference_script()
    ref_script_path.write_text(ref_code, encoding="utf-8")

    import ast

    ref_ast_ok = True
    ref_ast_err = ""
    try:
        ast.parse(ref_code, filename="ue_handoff_reference.py")
    except SyntaxError as exc:
        ref_ast_ok = False
        ref_ast_err = str(exc)

    # Render human-readable Markdown Delivery & Verification Report
    vp_info = bl_data.get("viewport_framing") or {}
    report_lines = [
        f"# [非官方]《鸣潮》（Wuthering Waves）角色风格化 Blender 动作展示与交接验收报告 — `{model_id}`",
        "",
        "> [!IMPORTANT]",
        "> **首次打开 `.blend` 弹出「自动运行 Python 脚本」安全提示说明（非恶意脚本，请放心）**：",
        "> 工程内嵌了完全开源、可在 Blender「脚本」标签页查看全文的 `ww_action_sync.py`（**零联网、零磁盘读写、不修改原始关键帧**），仅负责在切换动作时自动校准时间轴起止帧、联动同步/清零面部伴生表情 `*_ShapeKeys` 并提供右侧 `N` 键 `WW Showcase` 面板。点击 **「允许执行 / Allow Execution」** 即可激活；即使选择拒绝，模型与动画依然完整可用。",
        "",
        f"- **生成时间**：`{manifest['generated_at']}`",
        f"- **引擎核心版本**：`ww-auto-core v{CORE_VERSION}`（Handoff Schema `v{HANDOFF_SCHEMA_VERSION}`）",
        f"- **角色信息**：`{char_info.get('body_type')}` / `{char_info.get('character_folder')}` / `{model_id}`",
        f"- **宿主机客户端版本**：`{env_report['wuthering_waves'].get('client_version')}`（AES 挂载 `{manifest['host_context']['aes_coverage']}`）",
        f"- **Blender 版本**：`{env_report['blender'].get('version')}`（隔离沙盒执行，零宿主机污染）",
        "- **UE 引擎说明**：按项目规范，本工作流不要求宿主机安装 Unreal Engine；已输出标准化 `ue_handoff/handoff_manifest.json` 供后续独立 UE 交接插件消费。",
        "",
        "## 一、Blender 角色与游戏内动作展示验收",
        "",
        f"- **开箱即播工程文件**：`{blend_path}`（贴图内嵌打包：`{manifest['blender_showcase']['textures_packed']}`）",
        f"- **几何与骨架**：顶点数 `{geo.get('total_vertices')}` | 面数 `{geo.get('total_polygons')}` | 骨骼数 `{geo.get('bone_count')}` | 物理骨 (`Bone*`) `{geo.get('physics_bone_count')}` | 面部形态键 `{geo.get('shape_key_count')}`",
        f"- **骨架树哈希**：`{geo.get('skeleton_hash')}`（根骨骼：`{geo.get('root_bones')}`）",
        f"- **平滑法线 UV 索引**：`UV{geo.get('uv_audit', {}).get('smooth_normal_uv_index', 1)}`（共 `{geo.get('uv_audit', {}).get('uv_count')}` 层 UV）",
        f"- **默认展示动作**：`{anim_summary.get('active_showcase_action')}`（帧范围 `{anim_summary.get('frame_range')}`）",
        f"- **动画通道组审计 (ISS-008)**：`{(anim_summary.get('channel_group_audit') or {}).get('grouped_fcurves', 0)}/{(anim_summary.get('channel_group_audit') or {}).get('total_fcurves', 0)}` 曲线已归组（`{(anim_summary.get('channel_group_audit') or {}).get('total_groups', 0)}` 组，`all_curves_grouped={(anim_summary.get('channel_group_audit') or {}).get('all_curves_grouped')}`）",
        f"- **开箱近景视口构图与默认视图**：已按角色身高 `{vp_info.get('character_height_m', 'N/A')}m` 自动拉近 `布局`/`动画` 3D 视口（观察距 `{vp_info.get('view_distance_m', 'N/A')}m`、默认材质预览 `MATERIAL`、`动画` 底部默认 `动作编辑器` 并重置展示相机为全身正视）",
        f"- **自动时间轴校准与面部表情联动 (`ww_action_sync.py`)**：已内嵌（不修改原始关键帧数据；切换 `Armature` 身体主动作时自动校准底部时间轴起止帧范围，并自动同步/清零配套面部伴生表情 `*_ShapeKeys`；亦可在 3D 视图右侧按 `N` 打开 `WW Showcase` 面板一键切换动作与骨骼分组）。⚠️ 请勿将 `*_ShapeKeys` 手动挂到 `Armature` 上（它属于网格 `KEY` 形态键伴生表情轨，不是待蒸馏废动作）。",
        f"- **顶部工作区导航栏本地化**：`{(bl_data.get('workspace_localization') or {}).get('applied_language', 'en_US')}`（已本地化 `{(bl_data.get('workspace_localization') or {}).get('renamed_count', 0)}` 个工作区，默认激活 `{(bl_data.get('workspace_localization') or {}).get('active_workspace') or 'Layout'}`）",
        f"- **实测动作位移验证**：`animated={motion.get('animated')}` | 最大骨骼旋转角 `{motion.get('max_bone_rot_delta_deg')}°` | 最大骨骼位移 `{motion.get('max_bone_pos_delta_m')}m` | 最活跃骨骼 `{motion.get('most_active_bone')}`",
        "",
        "### 已导入动画清单",
        "",
        "| 动画名称 | 类别 | 帧范围 | F-Curves | 飘带/头发 Ribbon 合并曲线 | 面部形态键曲线 | 形态键关键帧 | 说明 |",
        "| :--- | :--- | :--- | ---: | ---: | ---: | ---: | :--- |",
    ]
    for a in anim_summary.get("details", []):
        note = "空中态循环（已烘焙保留，Blender 侧不作为展示验收项 · D3）" if a.get("is_aerial_loop") else "已烘焙可播"
        report_lines.append(
            f"| `{a['name']}` | `{a['category']}` | `{a['frame_start']}..{a['frame_end']}` | {a['fcurve_count']} | {a['ribbon_merged_fcurves']} | {a['shape_key_curves_matched']} | {a['shape_key_keyframes']} | {note} |"
        )

    deferred_anims = ext_idx.get("filtered_unbaked_animations", [])
    if deferred_anims:
        report_lines.extend(
            [
                "",
                "### 已过滤并移交下游 UE 插件烘焙的动作清单（决策 D4）",
                "",
                "| 动画名称 | 类别 | 过滤依据 |",
                "| :--- | :--- | :--- |",
            ]
        )
        for da in deferred_anims:
            report_lines.append(
                f"| `{da.get('name')}` | `{da.get('category')}` | {'; '.join(da.get('reasons') or [])} |"
            )

    report_lines.extend(
        [
            "",
            "### 多角度 / 动作帧预览图校验",
            "",
            "| 机位 | 帧号 | 大小 (Bytes) | 像素标准差 | 非黑屏/非纯色校验 | 文件路径 |",
            "| :--- | ---: | ---: | ---: | :---: | :--- |",
        ]
    )
    for r in renders:
        report_lines.append(
            f"| `{r['shot']}` | {r['frame']} | {r['bytes']} | {r['pixel_std']} | {'PASS' if r['non_blank_ok'] else 'FAIL'} | `{r['path']}` |"
        )

    report_lines.extend(
        [
            "",
            "## 二、下游 UE 交接包（Handoff）与 FBX 往返核验",
            "",
            f"- **交接清单**：`{manifest_path}`",
            f"- **标准化 Rest-Pose FBX**：`{fbx_path}`（`{rt.get('fbx_bytes', 0)}` bytes）",
            f"- **无双 Root 陷阱校验**：`has_double_root_armature={rt.get('has_double_root_armature')}`（根骨骼 `{rt.get('root_bones')}`）",
            f"- **形态键保留率**：`{rt.get('shape_key_count')}/{geo.get('shape_key_count')}`（`{round(float(rt.get('morph_retention_ratio', 0.0))*100, 1)}%`）",
            f"- **物理骨骼链保留**：`{rt.get('physics_bone_count')}/{geo.get('physics_bone_count')}`",
            "",
            "## 三、贴图三维审计与通道纠偏汇总",
            "",
            f"- 审计贴图总数：`{tex_audit['summary']['total_textures']}`（后端：`{tex_audit.get('backend')}`）",
            f"- `_N` 四通道拆分（`_N_Normal` BC5 + `_MR` BC7）：`{tex_audit['summary']['split_normal_maps']}` 组",
            f"- `_SDF` 通道相关性与镜像审计：`{tex_audit['summary']['sdf_maps_audited']}` 张",
            f"- 自动修补数量：`{tex_audit['summary']['repairs_applied']}`",
            f"- 全零/空白解码告警贴图：`{tex_audit['summary']['all_zero_textures']}`",
            "",
            "## 四、免责声明、联系方式与上游参考登记",
            "",
            f"- **问题反馈与版权响应联系邮箱**：`{CONTACT_EMAIL}`",
            "",
            f"> {LEGAL_NOTICE_ZH}",
            "",
            f"> {LEGAL_NOTICE}",
            "",
        ]
    )
    for ref in UPSTREAM_REFERENCES.values():
        report_lines.append(f"- {ref['title']}: {ref['url']}")

    report_md_path = deliverable_dir / "DELIVERY_REPORT.md"
    report_md_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    # === VerifyGate 4 ===
    gate4_failures: List[str] = []
    if not manifest_path.is_file():
        gate4_failures.append("handoff_manifest.json missing")
    if not report_md_path.is_file():
        gate4_failures.append("DELIVERY_REPORT.md missing")
    if not ref_ast_ok:
        gate4_failures.append(f"ue_handoff_reference.py AST syntax error: {ref_ast_err}")
    if not blend_path.is_file():
        gate4_failures.append("Showcase .blend missing")
    if not fbx_path.is_file():
        gate4_failures.append("Handoff .fbx missing")

    summary_out = {
        "status": "PASS" if not gate4_failures else "FAIL",
        "deliverable_dir": str(deliverable_dir.resolve()),
        "handoff_manifest_path": str(manifest_path.resolve()),
        "delivery_report_md": str(report_md_path.resolve()),
        "ue_handoff_reference_py": str(ref_script_path.resolve()),
        "showcase_blend_path": str(blend_path.resolve()) if blend_path.is_file() else "",
        "handoff_fbx_path": str(fbx_path.resolve()) if fbx_path.is_file() else "",
        "preview_renders": [r["path"] for r in renders],
        "verify_gate_4": {
            "passed": len(gate4_failures) == 0,
            "failures": gate4_failures,
            "ref_script_ast_ok": ref_ast_ok,
        },
    }
    (deliverable_dir / "delivery_summary.json").write_text(json.dumps(summary_out, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary_out
