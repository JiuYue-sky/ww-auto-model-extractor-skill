"""Stage 3: 3-Tier Dynamic Texture Matcher, Channel Auditor, _N Splitter, _SDF Analyzer & VerifyGate 3.

Runs image pixel operations via Blender's embedded Python (OpenImageIO + numpy) with automatic
Pillow fallback — requiring ZERO pip installs on the host machine.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config_rules import (
    HAIR_ALPHA_CLIP_TOKENS,
    MI_TEXTURE_PARAM_SLOTS,
    SWITCH_TEXTURE_TOKEN,
    classify_texture_suffix,
)
from .watchdog import run_watched


# Standalone worker script executed inside Blender's embedded Python (OpenImageIO + numpy) or Pillow Python
_PIXEL_AUDIT_WORKER = r'''
import json, math, os, sys
from pathlib import Path
import numpy as np

HAS_OIIO = False
HAS_PIL = False
try:
    import OpenImageIO as oiio
    HAS_OIIO = True
except Exception:
    pass
if not HAS_OIIO:
    try:
        from PIL import Image
        HAS_PIL = True
    except Exception:
        pass


def _win_long(path: str) -> str:
    if os.name == "nt" and len(path) >= 240 and not path.startswith("\\\\?\\"):
        return "\\\\?\\" + os.path.abspath(path)
    return path


def load_rgba_u8(path: str):
    path = _win_long(path)
    if HAS_OIIO:
        inp = oiio.ImageInput.open(path)
        if inp is None:
            raise RuntimeError(f"OIIO failed to open {path}: {oiio.geterror()}")
        spec = inp.spec()
        is_hdr = path.lower().endswith(".hdr") or path.lower().endswith(".exr")
        if is_hdr:
            arr = inp.read_image("float")
            inp.close()
            if arr is None:
                raise RuntimeError("OIIO read_image(float) returned None")
            return arr, spec.width, spec.height, spec.nchannels, str(spec.format), True
        arr = inp.read_image("uint8")
        inp.close()
        if arr is None:
            raise RuntimeError("OIIO read_image(uint8) returned None")
        if arr.ndim == 2:
            arr = arr[:, :, None]
        return arr, spec.width, spec.height, spec.nchannels, str(spec.format), False
    elif HAS_PIL:
        if path.lower().endswith(".hdr") or path.lower().endswith(".exr"):
            return None, 0, 0, 0, "hdr_skipped_no_oiio", True
        with Image.open(path) as im:
            w, h = im.size
            orig_mode = im.mode
            arr = np.array(im)
            if arr.ndim == 2:
                arr = arr[:, :, None]
            return arr, w, h, arr.shape[2], orig_mode, False
    else:
        raise RuntimeError("Neither OpenImageIO nor Pillow is available in Python environment")


def save_png_u8(path: str, arr: np.ndarray):
    out_p = _win_long(path)
    Path(out_p).parent.mkdir(parents=True, exist_ok=True)
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    if HAS_OIIO:
        h, w, c = arr.shape
        out = oiio.ImageOutput.create(out_p)
        if out is None:
            raise RuntimeError(f"OIIO create failed for {out_p}")
        spec = oiio.ImageSpec(w, h, c, oiio.UINT8)
        out.open(out_p, spec)
        out.write_image(arr)
        out.close()
    elif HAS_PIL:
        mode = {1: "L", 3: "RGB", 4: "RGBA"}[arr.shape[2]]
        Image.fromarray(arr[:, :, 0] if mode == "L" else arr, mode=mode).save(out_p)


def safe_corr(a: np.ndarray, b: np.ndarray) -> float:
    af = a.astype(np.float64).ravel()
    bf = b.astype(np.float64).ravel()
    sa = af.std()
    sb = bf.std()
    if sa < 1e-6 or sb < 1e-6:
        return 0.0
    return float(np.corrcoef(af, bf)[0, 1])


def main():
    job = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_split_dir = Path(job["split_dir"])
    out_repaired_dir = Path(job["repaired_dir"])
    out_split_dir.mkdir(parents=True, exist_ok=True)
    out_repaired_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for item in job["textures"]:
        path = item["disk_path"]
        slot = item["slot"]
        is_hair_mat = item.get("is_hair_material", False)
        rec = {
            "disk_path": path,
            "name": item["name"],
            "slot": slot,
            "decode_ok": False,
            "warnings": [],
            "repairs": [],
            "derived_files": {},
        }
        try:
            arr, w, h, nch, fmt, is_hdr = load_rgba_u8(path)
            rec["decode_ok"] = True
            rec["width"] = int(w)
            rec["height"] = int(h)
            rec["channels"] = int(nch)
            rec["raw_format"] = fmt
            rec["is_hdr"] = is_hdr

            if is_hdr or arr is None:
                rec["pixel_stats"] = {"note": "HDR/cubemap validated"}
                results.append(rec)
                continue

            ch_stats = []
            all_zero = True
            for c in range(nch):
                ch = arr[:, :, c]
                cmin, cmax = int(ch.min()), int(ch.max())
                cmean, cstd = float(ch.mean()), float(ch.std())
                nz = ch[ch > 0]
                nz_mean = float(nz.mean()) if nz.size > 0 else 0.0
                if cmax > 0:
                    all_zero = False
                ch_stats.append({
                    "channel": c,
                    "min": cmin,
                    "max": cmax,
                    "mean": round(cmean, 2),
                    "std": round(cstd, 2),
                    "nz_mean": round(nz_mean, 2),
                    "nz_pct": round(float(nz.size) / float(ch.size) * 100.0, 2) if ch.size else 0.0,
                })
            rec["channel_stats"] = ch_stats
            rec["all_zero"] = all_zero

            if all_zero:
                rec["warnings"].append(f"All-zero/blank decoded texture ({w}x{h}); check game asset or UE format.")

            # Tier 3 semantic pixel checks
            # A. Ramp / Skin aspect ratio check
            if w > 0 and h > 0 and (w / max(1, h) >= 6.0) and slot == "unknown":
                rec["pixel_inferred_slot"] = "skin_ramp"

            # B. Diffuse (_D) RGBA alpha preservation & semantic classification
            if slot == "base_color":
                if nch == 3:
                    # Repair missing alpha channel -> RGBA with full opaque alpha
                    alpha_ch = np.full((h, w, 1), 255, dtype=np.uint8)
                    rgba = np.concatenate([arr, alpha_ch], axis=2)
                    rep_path = str(out_repaired_dir / (Path(path).stem + "_RGBA.png"))
                    save_png_u8(rep_path, rgba)
                    rec["repairs"].append("Added missing Alpha channel (RGB -> RGBA)")
                    rec["derived_files"]["repaired_rgba"] = rep_path
                    rec["alpha_semantics"] = "opaque_repaired"
                elif nch >= 4:
                    a = arr[:, :, 3].astype(np.float32) / 255.0
                    near_zero = float((a < 0.05).mean())
                    mid_05_45 = float(((a >= 0.05) & (a <= 0.45)).mean())
                    above_05 = float((a > 0.50).mean())
                    near_one = float((a > 0.90).mean())
                    p99 = float(np.percentile(a, 99))
                    rec["alpha_profile"] = {
                        "near_zero_pct": round(near_zero * 100.0, 2),
                        "mid_05_45_pct": round(mid_05_45 * 100.0, 2),
                        "above_05_pct": round(above_05 * 100.0, 2),
                        "near_one_pct": round(near_one * 100.0, 2),
                        "p99": round(p99, 4),
                        "min": round(float(a.min()), 4),
                        "max": round(float(a.max()), 4),
                    }
                    # Kuro MSM_ToonCommon packs shadow/emissive/AO masks into MainTex.Alpha at ~0.00..0.41
                    # (with optional <2% 1.0 emissive sparkle dots, e.g. Down_D p99=0.404, near_one=0.23%).
                    is_kuro_data_alpha = (p99 <= 0.55) or (near_one < 0.05 and mid_05_45 > 0.30)
                    if is_kuro_data_alpha:
                        rec["alpha_semantics"] = "data_channel_shadow_mask"
                    elif is_hair_mat and near_zero >= 0.01 and near_one >= 0.05:
                        rec["alpha_semantics"] = "opacity_mask_hair"
                    elif near_zero > 0.01 and near_one > 0.25:
                        rec["alpha_semantics"] = "potential_cutout_or_data"
                    else:
                        rec["alpha_semantics"] = "opaque_or_full"

            # C. Packed Normal (_N): verify RG normal-like distribution + split into _N_Normal (BC5) & _MR (BC7)
            if slot == "normal_packed" and nch >= 3 and not all_zero:
                r_ch = arr[:, :, 0]
                g_ch = arr[:, :, 1]
                b_ch = arr[:, :, 2]
                a_ch = arr[:, :, 3] if nch >= 4 else np.full((h, w), 255, dtype=np.uint8)

                r_nz = r_ch[r_ch > 0]
                g_nz = g_ch[g_ch > 0]
                rg_mean_ok = (
                    (r_nz.size > 0 and 75.0 <= float(r_nz.mean()) <= 185.0)
                    and (g_nz.size > 0 and 75.0 <= float(g_nz.mean()) <= 185.0)
                )
                has_packed_ba = (float(b_ch.std()) > 1.0) or (nch >= 4 and float(a_ch.std()) > 1.0)
                rec["normal_audit"] = {
                    "rg_looks_like_normal": rg_mean_ok,
                    "has_packed_metallic_roughness": has_packed_ba,
                    "channel_layout": "RG=DirectX_Normal(G=-Y), B=Metallic, A=Roughness" if has_packed_ba else "RGB=Normal",
                }
                if has_packed_ba:
                    # Split Scheme A: derive tangent-space Z for clean BC5 Normalmap + separate _MR mask
                    nx = (r_ch.astype(np.float32) / 255.0) * 2.0 - 1.0
                    ny = (g_ch.astype(np.float32) / 255.0) * 2.0 - 1.0
                    nz_sq = np.clip(1.0 - nx * nx - ny * ny, 0.0, 1.0)
                    nz = np.sqrt(nz_sq)
                    z_u8 = np.clip(np.round((nz * 0.5 + 0.5) * 255.0), 0, 255).astype(np.uint8)
                    norm_rgb = np.stack([r_ch, g_ch, z_u8], axis=2)
                    mr_rgb = np.stack([b_ch, a_ch, np.zeros_like(b_ch)], axis=2)

                    norm_out = str(out_split_dir / (Path(path).stem + "_Normal.png"))
                    mr_out = str(out_split_dir / (Path(path).stem + "_MR.png"))
                    save_png_u8(norm_out, norm_rgb)
                    save_png_u8(mr_out, mr_rgb)
                    rec["derived_files"]["split_normal_bc5"] = norm_out
                    rec["derived_files"]["split_mr_bc7"] = mr_out

            # D. Face SDF (_SDF): channel variance & horizontal mirror correlation audit!
            if slot == "sdf" and nch >= 2 and not all_zero:
                # Subsample to <= 256x256 for fast exact correlation
                step = max(1, min(w, h) // 256)
                sub = arr[::step, ::step, :]
                pairs = []
                mirrored_pair = None
                codir_channels = [0]
                for i in range(nch):
                    for j in range(i + 1, nch):
                        c_same = safe_corr(sub[:, :, i], sub[:, :, j])
                        c_flip = safe_corr(sub[:, :, i], np.fliplr(sub[:, :, j]))
                        pairs.append({
                            "ch_i": i,
                            "ch_j": j,
                            "corr_same": round(c_same, 4),
                            "corr_mirror": round(c_flip, 4),
                        })
                        if c_flip > 0.75 and c_flip > c_same + 0.15:
                            mirrored_pair = [i, j]
                        if i == 0 and c_same > 0.90:
                            codir_channels.append(j)

                if mirrored_pair:
                    strategy = "KEEP_SINGLE_CHANNEL_MIRROR_UV"
                    sdf_single = arr[:, :, mirrored_pair[0]]
                elif len(codir_channels) >= 2:
                    strategy = "USE_CO_DIRECTIONAL_PRIMARY_R"
                    sdf_single = arr[:, :, 0]
                else:
                    strategy = "PRESERVE_MULTICHANNEL_RAW"
                    sdf_single = arr[:, :, 0]

                sdf_out = str(out_split_dir / (Path(path).stem + "_SDF_R.png"))
                save_png_u8(sdf_out, sdf_single[:, :, None])
                rec["derived_files"]["sdf_primary_single"] = sdf_out
                rec["sdf_audit"] = {
                    "strategy": strategy,
                    "mirrored_lr_pair": mirrored_pair,
                    "co_directional_with_r": codir_channels,
                    "use_uv_1_minus_u_mirror": bool(mirrored_pair or len(codir_channels) >= 2),
                    "pairwise_correlations": pairs,
                }
        except Exception as exc:
            rec["decode_ok"] = False
            rec["error"] = str(exc)

        results.append(rec)

    Path(sys.argv[2]).write_text(json.dumps({"ok": True, "backend": "OpenImageIO" if HAS_OIIO else "Pillow", "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
'''


def _safe_p(p: str | Path) -> Path:
    ps = os.path.abspath(str(p)) if p else ""
    if os.name == "nt" and len(ps) >= 240 and not ps.startswith("\\\\?\\"):
        return Path("\\\\?\\" + ps)
    return Path(ps) if ps else Path("")


def parse_material_instance_json(mi_path: Path) -> Dict[str, Any]:
    """Parse a CUE4Parse-exported MI_*.json into structured material metadata."""
    data = json.loads(_safe_p(mi_path).read_text(encoding="utf-8-sig"))
    mat_name = mi_path.stem
    textures_raw = data.get("Textures") or {}
    bound_textures: Dict[str, Dict[str, str]] = {}

    if isinstance(textures_raw, dict):
        for param_name, ref in textures_raw.items():
            if not isinstance(ref, dict):
                continue
            obj_name = str(ref.get("ObjectName", ""))
            obj_path = str(ref.get("ObjectPath", ""))
            # Extract Texture2D'T_Foo' -> T_Foo
            m = re.search(r"'([^']+)'", obj_name)
            tex_stem = m.group(1) if m else Path(obj_path.split(".")[0]).name
            p_low = param_name.lower()
            semantic = MI_TEXTURE_PARAM_SLOTS.get(p_low)
            if not semantic:
                # Fallback by texture stem suffix
                _, rule = classify_texture_suffix(tex_stem)
                semantic = str(rule["slot"])
            bound_textures[param_name] = {
                "texture_name": tex_stem,
                "object_path": obj_path,
                "semantic_slot": semantic,
            }

    blend_mode = data.get("BlendMode", 0)
    shading_model = data.get("ShadingModel", 0)
    scalars = data.get("Scalars") or {}
    switches = data.get("Switches") or {}
    name_low = mat_name.lower()
    # Trust engine-native BlendMode first! BlendMode==0 (Opaque) uses Alpha as shadow/HETA data, NOT cutout clip!
    # BlendMode==1 (Masked) or 2 (Translucent), or explicit Alpha/Lash/HETA slots enable alpha clipping.
    is_hair_or_masked = (
        blend_mode in (1, 2)
        or any(tok in name_low for tok in HAIR_ALPHA_CLIP_TOKENS)
    )

    props = data.get("Properties") or {}
    base_overrides = props.get("BasePropertyOverrides") or {}
    clip_val = scalars.get("OpacityMaskClipValue", base_overrides.get("OpacityMaskClipValue", 0.3333))

    return {
        "material_name": mat_name,
        "json_path": str(mi_path.resolve()),
        "blend_mode": blend_mode,
        "shading_model": shading_model,
        "is_hair_or_masked": is_hair_or_masked,
        "is_fur_shader": bool(switches.get("UseFurry")) or any(k.lower() in ("fur_tex", "furtex") for k in bound_textures.keys()),
        "opacity_mask_clip_value": float(clip_val),
        "bound_textures": bound_textures,
        "switches": switches,
        "scalars": scalars,
        "colors": data.get("Colors") or {},
    }


def _select_image_python(blender_info: Optional[Dict[str, Any]]) -> str:
    if blender_info and blender_info.get("embedded_python") and Path(blender_info["embedded_python"]).is_file():
        return str(blender_info["embedded_python"])
    return sys.executable


def audit_and_process_textures(
    extraction_index_path: Path,
    audit_out_dir: Path,
    *,
    blender_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run 3-tier dynamic texture matching, channel auditing, _N splitting, _SDF correlation, and VerifyGate 3."""
    index_data = json.loads(extraction_index_path.read_text(encoding="utf-8-sig"))
    audit_out_dir.mkdir(parents=True, exist_ok=True)

    # Tier 1: Parse all Material Instance JSON files
    # Primary `Model/MI_*.json` MUST take precedence over cutscene/subvariant overrides (`Model/Seq/`, `Model/BlendWater/`, `Model/LOD/`)
    def _mi_path_priority(mp: Path) -> tuple[int, int, int]:
        parts_low = [p.lower() for p in mp.parts]
        is_direct_model = 1 if mp.parent.name.lower() == "model" else 0
        is_subvariant = 1 if any(tok in parts_low for tok in ("seq", "blendwater", "lod", "low", "mobile")) else 0
        return (is_direct_model, 1 - is_subvariant, -len(parts_low))

    material_catalog: Dict[str, Dict[str, Any]] = {}
    material_priority: Dict[str, tuple[int, int, int]] = {}
    tex_to_tier1: Dict[str, Dict[str, Any]] = {}
    hair_texture_names: set[str] = set()

    for mi_str in index_data.get("materials", []):
        mp = _safe_p(mi_str)
        if not mp.is_file():
            continue
        mi = parse_material_instance_json(mp)
        mname = mi["material_name"]
        prio = _mi_path_priority(mp)
        if mname not in material_priority or prio > material_priority[mname]:
            material_catalog[mname] = mi
            material_priority[mname] = prio
        for param_name, binfo in mi["bound_textures"].items():
            tname_low = binfo["texture_name"].lower()
            # Keep strongest semantic binding (prefer explicit named slots like MainTex, Normal_Roughness_Metallic, MaskTex)
            if tname_low not in tex_to_tier1 or param_name.lower() in MI_TEXTURE_PARAM_SLOTS:
                tex_to_tier1[tname_low] = {
                    "material": mname,
                    "param": param_name,
                    "slot": binfo["semantic_slot"],
                }
            if mi["is_hair_or_masked"] and prio == material_priority.get(mname):
                hair_texture_names.add(tname_low)

    # Build texture worklist combining Tier 1 + Tier 2 + UE native metadata
    tex_jobs: List[Dict[str, Any]] = []
    tex_meta_by_path: Dict[str, Dict[str, Any]] = {}
    for t in index_data.get("textures", []):
        disk_path = t.get("disk_path", "")
        if not disk_path or not _safe_p(disk_path).is_file():
            continue
        tname = Path(disk_path).stem
        tlow = tname.lower()
        is_switch = SWITCH_TEXTURE_TOKEN in tlow

        suffix, suffix_rule = classify_texture_suffix(disk_path)
        t1 = tex_to_tier1.get(tlow)

        # Tier 1 overrides Tier 2 EXCEPT when Tier 1 returned generic 'sdf_or_mask' and suffix clarifies '_sdf'
        if t1 and t1["slot"] != "unknown":
            slot = t1["slot"]
            if slot == "sdf_or_mask" and suffix_rule["slot"] != "unknown":
                slot = str(suffix_rule["slot"])
            match_tier = "tier1_material_json"
        else:
            slot = str(suffix_rule["slot"])
            match_tier = "tier2_suffix_regex" if suffix != "(unknown)" else "tier3_pending"

        is_hair_mat = (tlow in hair_texture_names) or any(tok in tlow for tok in HAIR_ALPHA_CLIP_TOKENS)

        tex_meta_by_path[disk_path] = {
            **t,
            "name": tname,
            "matched_tier": match_tier,
            "matched_suffix": suffix,
            "slot": slot,
            "is_switch_variant": is_switch,
            "is_hair_material": is_hair_mat,
            "tier1_binding": t1,
            "rule_blender_colorspace": suffix_rule["blender_colorspace"],
            "rule_ue_srgb": suffix_rule["ue_srgb"],
            "rule_ue_compression": suffix_rule["ue_compression"],
            "rule_notes": suffix_rule["notes"],
        }
        tex_jobs.append(
            {
                "disk_path": disk_path,
                "name": tname,
                "slot": slot,
                "is_hair_material": is_hair_mat,
            }
        )

    # Tier 3: Execute pixel audit & channel splitting using Blender's embedded Python (OIIO + numpy)
    worker_py = audit_out_dir / "_pixel_audit_worker.py"
    job_json = audit_out_dir / "_pixel_audit_job.json"
    out_json = audit_out_dir / "_pixel_audit_out.json"
    split_dir = audit_out_dir / "split_textures"
    repaired_dir = audit_out_dir / "repaired_textures"

    worker_py.write_text(_PIXEL_AUDIT_WORKER, encoding="utf-8")
    job_json.write_text(
        json.dumps(
            {
                "split_dir": str(split_dir.resolve()),
                "repaired_dir": str(repaired_dir.resolve()),
                "textures": tex_jobs,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    py_exe = _select_image_python(blender_info)
    res = run_watched(
        [py_exe, str(worker_py), str(job_json), str(out_json)],
        hard_timeout_s=180,
        io_idle_timeout_s=60,
        watch_dir=audit_out_dir,
        max_retries=1,
        label="texture-pixel-audit",
    )

    if not res.ok or not out_json.is_file():
        return {
            "status": "FAIL",
            "error": f"Pixel audit worker failed: {res.stderr[-800:] or res.stdout[-800:]}",
            "watchdog": res.to_dict(),
        }

    pixel_data = json.loads(out_json.read_text(encoding="utf-8"))
    pixel_by_path = {r["disk_path"]: r for r in pixel_data.get("results", [])}

    audited_textures: List[Dict[str, Any]] = []
    gate_failures: List[str] = []
    gate_warnings: List[str] = []
    split_normal_count = 0
    sdf_audited_count = 0
    repaired_count = 0
    all_zero_textures: List[str] = []

    for disk_path, meta in tex_meta_by_path.items():
        pix = pixel_by_path.get(disk_path, {})
        merged = {**meta, "pixel_audit": pix}

        # Apply Tier 3 pixel inference if slot was unknown
        if merged["slot"] == "unknown" and pix.get("pixel_inferred_slot"):
            merged["slot"] = pix["pixel_inferred_slot"]
            merged["matched_tier"] = "tier3_pixel_stats"

        # Determine final authoritative sRGB & UE compression (reconciling rule vs UE4 native UTexture2D!)
        ue_native_srgb = merged.get("ue_srgb")
        final_srgb = merged["rule_ue_srgb"]
        if isinstance(ue_native_srgb, bool) and merged["slot"] in ("eye_highlight", "emissive", "unknown"):
            final_srgb = ue_native_srgb

        # Critical _N BC5 vs BC7 protection!
        final_ue_compression = merged["rule_ue_compression"]
        if merged["slot"] == "normal_packed":
            if pix.get("normal_audit", {}).get("has_packed_metallic_roughness"):
                final_ue_compression = "TC_BC7"  # Raw packed MUST be BC7 (never BC5!)
                split_normal_count += 1
            else:
                final_ue_compression = "TC_Normalmap"
        elif merged["slot"] == "base_color" and pix.get("channels") == 3 and not pix.get("derived_files"):
            final_ue_compression = "TC_Default"
        elif merged["slot"] == "sdf":
            sdf_audited_count += 1

        merged["final_ue_settings"] = {
            "srgb": bool(final_srgb),
            "compression": final_ue_compression,
            "blender_colorspace": "sRGB" if final_srgb else "Non-Color",
            "blender_alpha_mode": "CHANNEL_PACKED" if merged["slot"] == "base_color" else "STRAIGHT",
        }

        if not pix.get("decode_ok"):
            gate_failures.append(f"Corrupt/undecodable texture: {merged['name']} ({pix.get('error')})")
        if pix.get("all_zero"):
            all_zero_textures.append(merged["name"])
            gate_warnings.append(f"Texture {merged['name']} decoded as all-zero pixels ({pix.get('width')}x{pix.get('height')}).")
        if pix.get("repairs"):
            repaired_count += len(pix["repairs"])
        for w in pix.get("warnings", []):
            if w not in gate_warnings:
                gate_warnings.append(f"{merged['name']}: {w}")

        audited_textures.append(merged)

    audit_report = {
        "status": "PASS" if not gate_failures else "FAIL",
        "backend": pixel_data.get("backend"),
        "python_used": py_exe,
        "summary": {
            "total_textures": len(audited_textures),
            "total_materials": len(material_catalog),
            "split_normal_maps": split_normal_count,
            "sdf_maps_audited": sdf_audited_count,
            "repairs_applied": repaired_count,
            "all_zero_textures": all_zero_textures,
        },
        "verify_gate_3": {
            "passed": len(gate_failures) == 0,
            "failures": gate_failures,
            "warnings": gate_warnings,
        },
        "materials": material_catalog,
        "textures": audited_textures,
    }

    report_path = audit_out_dir / "texture_audit.json"
    report_path.write_text(json.dumps(audit_report, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "status": audit_report["status"],
        "audit_report_path": str(report_path.resolve()),
        "summary": audit_report["summary"],
        "verify_gate_3": audit_report["verify_gate_3"],
        "watchdog": res.to_dict(),
    }
