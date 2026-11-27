"""Stage 1b: Dynamic Character Discovery, Full Asset & Animation Extraction, and VerifyGate 1."""

from __future__ import annotations

import gzip
import json
import os
import re
import struct
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .config_rules import (
    normalize_character_key,
    resolve_character_query_tokens,
    resolve_character_query_variants,
)
from .watchdog import run_watched

_ROLE_FOLDER_RE = re.compile(
    r"Character/Role/[^/]+/([^/]+)/",
    re.IGNORECASE,
)


def _extract_playable_folder_name(char_entry: Dict[str, Any]) -> str:
    """Resolve the playable character's naming folder from CharacterFolder or ModelPath/ModelDir."""
    folder = str(char_entry.get("CharacterFolder", "") or "").strip()
    if folder:
        return folder
    for key in ("ModelPath", "ModelDir"):
        raw_p = str(char_entry.get(key, "") or "").replace("\\", "/")
        m = _ROLE_FOLDER_RE.search(raw_p)
        if m:
            return m.group(1).strip()
    return ""


def _build_ww_extract_env() -> Dict[str, str]:
    return os.environ.copy()


def _try_load_catalog_cache(work_dir: Optional[Path], ww_info: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    if work_dir is None:
        return None
    cache_file = work_dir / "character_catalog_cache.json"
    if not cache_file.is_file():
        return None
    try:
        doc = json.loads(cache_file.read_text(encoding="utf-8"))
        fp = doc.get("fingerprint") or {}
        if (
            fp.get("game_root") == str(ww_info.get("game_root", ""))
            and fp.get("client_version") == str(ww_info.get("client_version", ""))
            and int(fp.get("pak_total", -1)) == int(ww_info.get("pak_counts", {}).get("total", 0))
            and isinstance(doc.get("characters"), list)
            and len(doc["characters"]) > 0
        ):
            return doc["characters"]
    except Exception:
        pass
    return None


def list_available_characters(
    env_report: Dict[str, Any],
    key_files: List[str],
    *,
    query: Optional[str] = None,
    work_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Query live mounted paks (or verified work_dir catalog cache) for all playable characters."""
    ww_info = env_report["wuthering_waves"]
    cached_chars = _try_load_catalog_cache(work_dir, ww_info)
    from_cache = cached_chars is not None

    if cached_chars is not None:
        chars = cached_chars
    else:
        exe = env_report["ww_extract"]["executable"]
        native_dir = env_report["ww_extract"].get("native_dir")
        game_dir = ww_info["game_root"]

        cmd = [exe, "list-characters", "--game-dir", game_dir, "--include-saved", "true"]
        if native_dir:
            cmd.extend(["--native-dir", native_dir])
        valid_keys = [k for k in key_files if k and Path(k).is_file()]
        if valid_keys:
            cmd.extend(["--keys", ",".join(valid_keys)])

        res = run_watched(cmd, env=_build_ww_extract_env(), hard_timeout_s=120, io_idle_timeout_s=60, max_retries=2, label="list-characters")
        if not res.ok:
            return {"ok": False, "error": res.stderr[-800:] or res.stdout[-800:]}
        data = json.loads(res.stdout)
        chars = data.get("characters", [])
        if work_dir is not None and chars:
            cache_file = work_dir / "character_catalog_cache.json"
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(
                json.dumps(
                    {
                        "fingerprint": {
                            "game_root": str(ww_info.get("game_root", "")),
                            "client_version": str(ww_info.get("client_version", "")),
                            "pak_total": int(ww_info.get("pak_counts", {}).get("total", 0)),
                            "mounted_paks": int(data.get("aes", {}).get("mounted_paks", 0)),
                        },
                        "count": len(chars),
                        "characters": chars,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    if query:
        variants = resolve_character_query_variants(query)
        tokens = variants["all_tokens"]
        matched, match_details = _match_characters_detailed(chars, variants)
        return {
            "ok": True,
            "from_cache": from_cache,
            "query": query,
            "search_tokens": tokens,
            "query_variants": {
                "chinese": variants["chinese"],
                "english_lower": variants["english_lower"],
                "english_capitalized": variants["english_capitalized"],
                "pinyin_syllables": variants["pinyin_syllables"],
                "matched_alias_canonical": variants["matched_alias_canonical"],
            },
            "match_details": match_details,
            "count": len(matched),
            "characters": matched,
            "total_in_game": len(chars),
            "available_character_folders": sorted(
                {f for f in (_extract_playable_folder_name(c) for c in chars) if f},
                key=str.lower,
            )
            if not matched
            else [],
        }

    return {"ok": True, "from_cache": from_cache, "count": len(chars), "characters": chars}


def _score_character_entry(
    c: Dict[str, Any],
    variants: Dict[str, Any],
) -> Tuple[int, str, str]:
    """Score one playable character entry directly against its naming folder & ModelId.

    Explicitly evaluates:
      1. Chinese tokens against folder / ModelId (`chinese_folder_exact`, `chinese_folder_substr`)
      2. Capitalized / Title / PascalCase English tokens against exact folder casing (`english_capitalized_folder_exact`)
      3. Lowercase English / Pinyin tokens against exact lowercase & case-insensitive folder (`english_lower_folder_exact`, `english_lower_folder_ci`)
      4. Separator-normalized compact folder & ModelId matching (`folder_compact_exact`, `model_id_exact`)
    """
    folder_raw = _extract_playable_folder_name(c)
    folder_low = folder_raw.lower()
    folder_compact = normalize_character_key(folder_raw)
    model_id_raw = str(c.get("ModelId", "") or "").strip()
    model_id_low = model_id_raw.lower()
    model_id_compact = normalize_character_key(model_id_raw)

    zh_tokens: List[str] = variants.get("chinese", [])
    low_tokens: List[str] = variants.get("english_lower", [])
    cap_tokens: List[str] = variants.get("english_capitalized", [])
    all_tokens: List[str] = variants.get("all_tokens", [])

    mat_cnt = int(c.get("MaterialCount", 0))
    if mat_cnt == 0 and int(c.get("TextureCount", 0)) == 0:
        # Skip broken/empty variant entries like YangyangwumaoMd10011 unless exact ModelId requested
        if not any(t.lower() == model_id_low for t in all_tokens):
            return (0, "", "")

    best_score = 0
    best_channel = ""
    best_token = ""

    def _consider(score: int, channel: str, tok: str) -> None:
        nonlocal best_score, best_channel, best_token
        if score > best_score:
            best_score = score
            best_channel = channel
            best_token = tok

    # Channel A: Exact ModelId match (highest specificity for skin overrides like R2T1JinxiMd20011)
    for idx, tok in enumerate(all_tokens):
        t_low = tok.lower()
        t_comp = normalize_character_key(tok)
        weight = max(1, 20 - idx)
        if model_id_low and model_id_low == t_low:
            _consider(1200 + weight, "model_id_exact", tok)
        elif model_id_compact and t_comp and model_id_compact == t_comp:
            _consider(1180 + weight, "model_id_compact_exact", tok)

    # Channel B: Direct Chinese matching against playable character naming folder
    for idx, tok in enumerate(zh_tokens):
        weight = max(1, 20 - idx)
        t_comp = normalize_character_key(tok)
        if folder_raw and folder_raw == tok:
            _consider(1150 + weight, "chinese_folder_exact", tok)
        elif folder_compact and t_comp and folder_compact == t_comp:
            _consider(1120 + weight, "chinese_folder_compact_exact", tok)
        elif folder_raw and len(tok) >= 2 and tok in folder_raw:
            _consider(620 + weight, "chinese_folder_substr", tok)
        elif model_id_raw and len(tok) >= 2 and tok in model_id_raw:
            _consider(580 + weight, "chinese_model_id_substr", tok)

    # Channel C: Direct Capitalized / Title-Case / PascalCase English matching against exact folder casing
    # (e.g. "莉莉" -> "Lili" == "Lili", "琳奈" -> "LinNai" == "LinNai", "长离" -> "ChangLi" == "ChangLi")
    for idx, tok in enumerate(cap_tokens):
        weight = max(1, 30 - idx)
        if folder_raw and folder_raw == tok:
            _consider(1080 + weight, "english_capitalized_folder_exact", tok)
        elif folder_raw and len(tok) >= 4 and folder_raw.startswith(tok):
            _consider(660 + weight, "english_capitalized_folder_prefix", tok)

    # Channel D: Direct Lowercase English / Pinyin matching against exact lowercase & case-insensitive folder
    # (e.g. "莉莉" -> "lili" == "lili" or folder.lower() == "lili", "弗洛洛礼服" -> "fuluoluolifu" == compact("Fuluoluo_Lifu"))
    for idx, tok in enumerate(low_tokens):
        weight = max(1, 30 - idx)
        t_low = tok.lower()
        t_comp = normalize_character_key(tok)
        if folder_raw and folder_raw == t_low:
            _consider(1070 + weight, "english_lower_folder_exact", tok)
        elif folder_low and folder_low == t_low:
            _consider(1030 + weight, "english_lower_folder_ci", tok)
        elif folder_compact and t_comp and folder_compact == t_comp:
            _consider(1010 + weight, "english_compact_folder_exact", tok)
        elif folder_low and len(t_low) >= 4 and folder_low.startswith(t_low):
            _consider(640 + weight, "english_lower_folder_prefix", tok)
        elif folder_compact and len(t_comp) >= 4 and folder_compact.startswith(t_comp):
            _consider(630 + weight, "english_compact_folder_prefix", tok)
        elif model_id_low and len(t_low) >= 4 and t_low in model_id_low:
            _consider(520 + weight, "model_id_substr", tok)
        elif folder_low and len(t_low) >= 4 and t_low in folder_low:
            _consider(460 + weight, "english_lower_folder_substr", tok)

    if best_score > 0 and "md10011" in model_id_low:
        # Prefer default skin Md10011 slightly over alt skins unless explicitly specified
        best_score += 25

    return (best_score, best_channel, best_token)


def _match_characters_detailed(
    chars: List[Dict[str, Any]],
    query_or_tokens: Union[str, Dict[str, Any], List[str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Rank playable character entries directly against their naming folders and return (matches, match_details)."""
    if isinstance(query_or_tokens, dict):
        variants = query_or_tokens
    elif isinstance(query_or_tokens, str):
        variants = resolve_character_query_variants(query_or_tokens)
    else:
        # Backward-compatible plain token list support
        tok_list = [str(t).strip() for t in query_or_tokens if str(t).strip()]
        zh_t: List[str] = []
        low_t: List[str] = []
        cap_t: List[str] = []
        for t in tok_list:
            if not t.isascii():
                if t not in zh_t:
                    zh_t.append(t)
            else:
                if t.lower() not in low_t:
                    low_t.append(t.lower())
                if any(ch.isupper() for ch in t) and t not in cap_t:
                    cap_t.append(t)
                cap_first = t.lower()[0].upper() + t.lower()[1:]
                if cap_first not in cap_t:
                    cap_t.append(cap_first)
        variants = {
            "chinese": zh_t,
            "english_lower": low_t,
            "english_capitalized": cap_t,
            "all_tokens": tok_list,
        }

    scored: List[Tuple[int, str, str, Dict[str, Any]]] = []
    for c in chars:
        score, channel, tok = _score_character_entry(c, variants)
        if score > 0:
            scored.append((score, channel, tok, c))

    scored.sort(key=lambda x: (-x[0], str(x[3].get("ModelId", ""))))

    # If we have exact folder/ModelId matches (>= 1000), drop weak unrelated inner-substring noise (< 600)
    if scored and scored[0][0] >= 1000:
        scored = [item for item in scored if item[0] >= 600]

    matched_chars = [item[3] for item in scored]
    details = [
        {
            "model_id": item[3].get("ModelId", ""),
            "character_folder": _extract_playable_folder_name(item[3]),
            "body_type": item[3].get("BodyType", ""),
            "match_channel": item[1],
            "matched_token": item[2],
            "score": item[0],
        }
        for item in scored
    ]
    return matched_chars, details


def _match_characters(
    chars: List[Dict[str, Any]],
    tokens: Union[str, Dict[str, Any], List[str]],
) -> List[Dict[str, Any]]:
    """Rank character entries against resolved multi-form query variants or token list."""
    matched, _ = _match_characters_detailed(chars, tokens)
    return matched


def _safe_path(p: Path | str) -> Path:
    """Apply Windows \\?\\ extended-length prefix when path >= 240 chars to prevent MAX_PATH errors."""
    ps = str(Path(p).resolve()) if p else ""
    if os.name == "nt" and len(ps) >= 240 and not ps.startswith("\\\\?\\"):
        return Path("\\\\?\\" + ps)
    return Path(ps) if ps else Path("")


_CONTROL_CURVE_PREFIXES = (
    "ik_",
    "foot_ik_",
    "l_up",
    "l_p",
    "l_f",
    "l_b",
    "r_up",
    "r_p",
    "r_f",
    "r_b",
    "rootx",
    "rooty",
    "rootz",
    "weight_",
    "footstate",
    "layering_",
    "landingtime",
    "mor_",
    "morpher_",
    "kawaii_",
)
_AERIAL_LOOP_TOKENS = ("jump_loop", "fall_loop", "glide_loop", "hover_loop", "air_loop", "fly_loop")


def _is_control_curve_name(cname: str) -> bool:
    cl = (cname or "").strip().lower()
    if not cl:
        return True
    return any(cl.startswith(p) for p in _CONTROL_CURVE_PREFIXES)


def _value_span(vals: List[Tuple[float, ...]]) -> float:
    if len(vals) <= 1:
        return 0.0
    v0 = vals[0]
    m = 0.0
    for v in vals[1:]:
        d = max(abs(a - b) for a, b in zip(v0, v))
        if d > m:
            m = d
    return m


def inspect_ueanim_binary(path: Path) -> Dict[str, Any]:
    """Full binary parser for UEFormat `.ueanim` to verify bone tracks, motion spans, and curves (VerifyGate 1 + D4)."""
    try:
        sp = _safe_path(path)
        data = sp.read_bytes()
        file_bytes = len(data)
        pos = 0

        def r(n: int) -> bytes:
            nonlocal pos
            if pos + n > len(data):
                raise EOFError("Truncated .ueanim")
            s = data[pos : pos + n]
            pos += n
            return s

        def ri() -> int:
            return struct.unpack("<i", r(4))[0]

        def rf() -> float:
            return struct.unpack("<f", r(4))[0]

        def rfs() -> str:
            ln = ri()
            if ln < 0 or ln > 4096:
                raise ValueError(f"Invalid FString length {ln}")
            return r(ln).rstrip(b"\x00").decode("utf-8", errors="replace")

        magic = r(8).decode("ascii", errors="replace")
        if magic != "UEFORMAT":
            return {"valid": False, "error": f"Bad magic: {magic!r}", "bytes": file_bytes}
        ident = rfs()
        if ident != "UEANIM":
            return {"valid": False, "error": f"Not UEANIM: {ident!r}", "bytes": file_bytes}
        ver = r(1)[0]
        obj_name = rfs()
        if ver >= 10:
            _obj_path = rfs()
        is_comp = bool(r(1)[0])
        comp_type = None
        if is_comp:
            comp_type = rfs()
            usize = ri()
            _csize = ri()
            comp_bytes = data[pos:]
            if comp_type == "GZIP":
                data = gzip.decompress(comp_bytes)
                pos = 0
            elif comp_type == "ZSTD":
                try:
                    import zstandard as zstd  # type: ignore

                    data = zstd.ZstdDecompressor().decompress(comp_bytes, max_output_size=usize)
                    pos = 0
                except Exception:
                    return {"valid": True, "version": ver, "name": obj_name, "compressed": comp_type, "bytes": file_bytes}
            else:
                return {"valid": True, "version": ver, "name": obj_name, "compressed": comp_type, "bytes": file_bytes}

        attr_cnt = ri()
        num_frames = 0
        fps = 30.0
        track_count = 0
        single_key_tracks = 0
        moving_tracks = 0
        non_root_moving_tracks = 0
        root_pos_span_cm = 0.0
        max_non_root_rot_span = 0.0
        curve_count = 0
        curve_names: List[str] = []

        for _ in range(attr_cnt):
            if pos >= len(data):
                break
            sname = rfs()
            bsz = ri()
            end = min(len(data), pos + bsz)
            if sname == "METADATA":
                num_frames = ri()
                fps = round(rf(), 2)
            elif sname == "TRACKS":
                track_count = ri()
                for _t in range(track_count):
                    bname = rfs()
                    pc = ri()
                    pvals: List[Tuple[float, ...]] = []
                    for _k in range(pc):
                        _fr = ri()
                        pvals.append((rf(), rf(), rf()))
                    rc = ri()
                    rvals: List[Tuple[float, ...]] = []
                    for _k in range(rc):
                        _fr = ri()
                        rvals.append((rf(), rf(), rf(), rf()))
                    sc = ri()
                    svals: List[Tuple[float, ...]] = []
                    for _k in range(sc):
                        _fr = ri()
                        svals.append((rf(), rf(), rf()))

                    max_k = max(pc, rc, sc)
                    if max_k <= 1:
                        single_key_tracks += 1
                    pspan = _value_span(pvals)
                    rspan = _value_span(rvals)
                    sspan = _value_span(svals)
                    is_moving = (pspan > 1e-2) or (rspan > 1e-3) or (sspan > 1e-3)
                    if is_moving:
                        moving_tracks += 1
                        if bname.lower() == "root":
                            root_pos_span_cm = max(root_pos_span_cm, pspan)
                        else:
                            non_root_moving_tracks += 1
                            max_non_root_rot_span = max(max_non_root_rot_span, rspan)
                    elif bname.lower() == "root":
                        root_pos_span_cm = max(root_pos_span_cm, pspan)
            elif sname == "CURVES":
                curve_count = ri()
                for _c in range(curve_count):
                    cname = rfs()
                    kc = ri()
                    pos += kc * 8
                    curve_names.append(cname)
            pos = end

        single_key_ratio = round(single_key_tracks / max(1, track_count), 4) if track_count > 0 else 0.0
        control_curve_count = sum(1 for c in curve_names if _is_control_curve_name(c))
        morph_curve_count = curve_count - control_curve_count
        control_curves_only = curve_count > 0 and morph_curve_count == 0

        return {
            "valid": track_count > 0 or curve_count > 0,
            "version": ver,
            "name": obj_name,
            "compressed": comp_type,
            "bytes": file_bytes,
            "num_frames": num_frames,
            "fps": fps,
            "track_count": track_count,
            "single_key_tracks": single_key_tracks,
            "single_key_ratio": single_key_ratio,
            "moving_tracks": moving_tracks,
            "non_root_moving_tracks": non_root_moving_tracks,
            "root_pos_span_cm": round(root_pos_span_cm, 2),
            "max_non_root_rot_span": round(max_non_root_rot_span, 4),
            "curve_count": curve_count,
            "control_curve_count": control_curve_count,
            "morph_curve_count": morph_curve_count,
            "control_curves_only": control_curves_only,
            "curve_sample": curve_names[:20],
            "error": "" if (track_count > 0 or curve_count > 0) else "Empty animation (0 bone tracks and 0 curves — check ACL CUE4Parse-Natives.dll and virtual paths!)",
        }
    except Exception as exc:
        return {"valid": False, "error": str(exc), "bytes": path.stat().st_size if path.exists() else 0}


def classify_animation_bake_status(
    bin_info: Dict[str, Any],
    category: str,
    anim_name: str,
    sibling_max_bytes: int = 0,
) -> Dict[str, Any]:
    """Universal playable-character classifier for Decision D3/D4 (unbaked curve-driven clips vs baked clips).

    - RibbonAnim clips are NEVER filtered here (they intentionally animate physics Bone* chains only).
    - Body animations (CommonAnim / BaseAnim) that lack baked skeletal poses (e.g. IK/root-motion-only
      fragments like Land_Roll_Attack01_2) are marked `needs_ue_bake=True` so Stage 1b excludes them from
      extraction & Blender showcase and records them for the downstream UE handoff plugin (Decision D4).
    - Baked aerial/hover loops (e.g. Jump_Loop) are PRESERVED (`needs_ue_bake=False`) and annotated
      with `is_aerial_loop=True` / `blender_showcase_acceptance=False` (Decision D3).
    """
    cat_low = (category or "").lower()
    name_low = (anim_name or "").lower()
    if cat_low == "ribbonanim" or name_low.startswith("rib_"):
        return {
            "needs_ue_bake": False,
            "is_aerial_loop": False,
            "blender_showcase_acceptance": True,
            "reasons": [],
        }

    track_count = int(bin_info.get("track_count", 0))
    single_ratio = float(bin_info.get("single_key_ratio", 0.0))
    moving = int(bin_info.get("moving_tracks", 0))
    non_root_moving = int(bin_info.get("non_root_moving_tracks", 0))
    file_bytes = int(bin_info.get("bytes", 0))
    ctrl_only = bool(bin_info.get("control_curves_only", False))
    root_span = float(bin_info.get("root_pos_span_cm", 0.0))

    reasons: List[str] = []
    if track_count >= 10:
        if single_ratio > 0.90 and non_root_moving <= 2:
            reasons.append(f"single_key_ratio={single_ratio * 100:.1f}%>90% (non_root_moving={non_root_moving})")
        if moving <= 2:
            reasons.append(f"tracks_moving={moving}<=2 (only Root/static pose)")
        if non_root_moving == 0 and (ctrl_only or root_span > 10.0):
            reasons.append(
                f"curve_or_root_only (non_root_moving=0, control_curves_only={ctrl_only}, root_pos_span_cm={root_span})"
            )
        if file_bytes > 0 and file_bytes < 50_000 and sibling_max_bytes >= 150_000 and non_root_moving <= 5:
            reasons.append(
                f"tiny_unbaked_stub ({file_bytes}B < 50KB vs sibling {sibling_max_bytes}B, non_root_moving={non_root_moving})"
            )

    needs_ue_bake = len(reasons) > 0
    is_aerial_loop = (not needs_ue_bake) and any(tok in name_low for tok in _AERIAL_LOOP_TOKENS)
    return {
        "needs_ue_bake": needs_ue_bake,
        "is_aerial_loop": is_aerial_loop,
        "blender_showcase_acceptance": not (needs_ue_bake or is_aerial_loop),
        "reasons": reasons,
    }


def extract_character_assets(
    env_report: Dict[str, Any],
    key_files: List[str],
    character_query: str,
    out_dir: Path,
    *,
    model_path_override: Optional[str] = None,
    export_anims: bool = True,
    max_anims: int = 6,
    anim_names: Optional[List[str]] = None,
    work_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extract character meshes, materials, textures, and animations + run deterministic VerifyGate 1."""
    exe = env_report["ww_extract"]["executable"]
    native_dir = env_report["ww_extract"].get("native_dir")
    game_dir = env_report["wuthering_waves"]["game_root"]

    selected_model_path = model_path_override
    matched_candidates: List[Dict[str, Any]] = []

    if not selected_model_path:
        listing = list_available_characters(env_report, key_files, query=character_query, work_dir=work_dir)
        if not listing.get("ok"):
            return {"status": "FAIL", "error": listing.get("error", "Failed to list characters")}
        matched_candidates = listing.get("characters", [])
        if not matched_candidates:
            return {
                "status": "FAIL",
                "error": f"未能在本机《鸣潮》资源中匹配到角色 '{character_query}'。可运行 --list-characters 查看本机全部 {listing.get('total_in_game', 0)} 个可用角色。",
                "search_tokens": listing.get("search_tokens", []),
                "query_variants": listing.get("query_variants", {}),
                "available_character_folders": listing.get("available_character_folders", []),
            }
        selected_model_path = matched_candidates[0]["ModelPath"]

    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe,
        "extract-character",
        "--game-dir",
        game_dir,
        "--model-path",
        selected_model_path,
        "--out-dir",
        str(out_dir.resolve()),
        "--include-saved",
        "true",
        "--export-anims",
        "true" if export_anims else "false",
        "--max-anims",
        str(max_anims),
        "--include-extra-textures",
        "true",
    ]
    if native_dir:
        cmd.extend(["--native-dir", native_dir])
    valid_keys = [k for k in key_files if k and Path(k).is_file()]
    if valid_keys:
        cmd.extend(["--keys", ",".join(valid_keys)])
    if anim_names:
        cmd.extend(["--anim-names", ",".join(anim_names)])

    res = run_watched(
        cmd,
        env=_build_ww_extract_env(),
        hard_timeout_s=300,
        io_idle_timeout_s=75,
        watch_dir=out_dir,
        max_retries=2,
        label="ww-extract-character",
    )

    index_path = out_dir / "extraction_index.json"
    if not res.ok or not index_path.is_file():
        return {
            "status": "FAIL",
            "error": f"Extraction failed (rc={res.returncode}): {res.stderr[-800:] or res.stdout[-800:]}",
            "watchdog": res.to_dict(),
        }

    index_data = json.loads(index_path.read_text(encoding="utf-8-sig"))

    # === VerifyGate 1: Deterministic asset completeness & binary integrity checks ===
    gate_failures: List[str] = []
    gate_warnings: List[str] = []

    meshes = index_data.get("meshes", [])
    if not meshes:
        gate_failures.append("No skeletal mesh exported.")
    else:
        for m in meshes:
            is_primary = bool(m.get("is_primary", True))
            mp = _safe_path(m.get("uemodel_path", ""))
            if not mp.is_file() or mp.stat().st_size < 1024:
                if is_primary:
                    gate_failures.append(f"Missing or corrupt primary .uemodel: {mp}")
                else:
                    gate_warnings.append(f"Variant .uemodel missing or small: {mp}")
            if int(m.get("bone_count", 0)) < 10:
                if is_primary:
                    gate_failures.append(f"Suspicious bone count ({m.get('bone_count')}) on primary mesh {m.get('name')}")
                else:
                    gate_warnings.append(f"Variant mesh {m.get('name')} has {m.get('bone_count')} bones.")
            if is_primary and int(m.get("morph_target_count", 0)) == 0:
                gate_warnings.append(f"Primary mesh {m.get('name')} has 0 morph targets (may be body-only or non-standard mesh).")

    materials = index_data.get("materials", [])
    if not materials:
        gate_failures.append("No material instance JSON (MI_*.json) exported.")

    textures = index_data.get("textures", [])
    missing_tex = [t["disk_path"] for t in textures if not _safe_path(t.get("disk_path", "")).is_file() or _safe_path(t.get("disk_path", "")).stat().st_size == 0]
    export_errors = index_data.get("export_errors", [])
    if not textures:
        gate_failures.append("No textures exported.")
    elif missing_tex:
        gate_failures.append(f"{len(missing_tex)} exported textures missing or 0-byte: {missing_tex[:5]}")
    if export_errors:
        skia_errs = [e for e in export_errors if "skiasharp" in str(e.get("error", "")).lower()]
        if skia_errs or (len(export_errors) > len(textures)):
            gate_failures.append(
                f"Mass export failure ({len(export_errors)} export_errors vs {len(textures)} textures): {export_errors[:3]}"
            )
        else:
            gate_warnings.append(f"{len(export_errors)} export_errors reported: {export_errors[:3]}")

    # Verify exported .ueanim binary tracks & curves + apply Decision D3/D4 unbaked-clip filter!
    raw_inspected: List[Dict[str, Any]] = []
    for anim in index_data.get("animations", []):
        ap = _safe_path(anim.get("ueanim_path", ""))
        if not ap.is_file():
            gate_warnings.append(f"Animation failed to export: {anim.get('name')} ({anim.get('category')})")
            continue
        bin_info = inspect_ueanim_binary(ap)
        anim_entry = {**anim, "binary_check": bin_info}
        raw_inspected.append(anim_entry)
        if not bin_info.get("valid"):
            gate_failures.append(f"Corrupt or empty animation {ap.name}: {bin_info.get('error')}")

    body_sizes = [
        int(a["binary_check"].get("bytes", 0))
        for a in raw_inspected
        if a.get("category") != "RibbonAnim" and a["binary_check"].get("valid")
    ]
    sibling_max_bytes = max(body_sizes) if body_sizes else 0

    verified_anims: List[Dict[str, Any]] = []
    filtered_unbaked_anims: List[Dict[str, Any]] = []
    filtered_body_names: set[str] = set()
    kept_body_names: set[str] = set()

    for entry in raw_inspected:
        bake_status = classify_animation_bake_status(
            entry["binary_check"],
            str(entry.get("category", "")),
            str(entry.get("name", "")),
            sibling_max_bytes=sibling_max_bytes,
        )
        entry["bake_status"] = bake_status
        if bake_status["needs_ue_bake"]:
            filtered_body_names.add(str(entry.get("name", "")).lower())
            ap = _safe_path(entry.get("ueanim_path", ""))
            try:
                if ap.is_file():
                    ap.unlink()
            except OSError:
                pass
            filtered_unbaked_anims.append(
                {
                    "name": entry.get("name"),
                    "category": entry.get("category"),
                    "vfs_path": entry.get("vfs_path"),
                    "decision": "D4_DEFERRED_TO_UE_BAKE",
                    "reasons": bake_status["reasons"],
                    "binary_check": entry["binary_check"],
                }
            )
            gate_warnings.append(
                f"[D4 Filtered Unbaked Anim -> Deferred to UE] {entry.get('name')} ({entry.get('category')}): "
                + "; ".join(bake_status["reasons"])
            )
        else:
            if entry.get("category") != "RibbonAnim":
                kept_body_names.add(str(entry.get("name", "")).lower())
            verified_anims.append(entry)

    # Also drop any orphaned RibbonAnim whose sole paired body animation was filtered by D4
    if filtered_body_names:
        pruned_verified: List[Dict[str, Any]] = []
        for entry in verified_anims:
            if entry.get("category") == "RibbonAnim":
                stem_low = str(entry.get("name", "")).lower()
                base_stem = stem_low[4:] if stem_low.startswith("rib_") else stem_low
                if base_stem in filtered_body_names and base_stem not in kept_body_names:
                    ap = _safe_path(entry.get("ueanim_path", ""))
                    try:
                        if ap.is_file():
                            ap.unlink()
                    except OSError:
                        pass
                    continue
            pruned_verified.append(entry)
        verified_anims = pruned_verified

    if export_anims and not verified_anims and not filtered_unbaked_anims:
        gate_failures.append("Animation export requested, but 0 valid .ueanim files were produced.")

    # Save enriched animation verification & D4 deferred list into extraction_index.json
    index_data["verified_animations"] = verified_anims
    index_data["filtered_unbaked_animations"] = filtered_unbaked_anims
    index_data["verify_gate_1"] = {
        "passed": len(gate_failures) == 0,
        "failures": gate_failures,
        "warnings": gate_warnings,
    }
    index_path.write_text(json.dumps(index_data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "status": "PASS" if not gate_failures else "FAIL",
        "character": index_data.get("character"),
        "alternative_skins": [
            {"model_id": c["ModelId"], "model_path": c["ModelPath"]}
            for c in matched_candidates[1:5]
        ],
        "out_dir": str(out_dir.resolve()),
        "extraction_index": str(index_path.resolve()),
        "summary": index_data.get("summary"),
        "verified_animations_count": len(verified_anims),
        "filtered_unbaked_animations_count": len(filtered_unbaked_anims),
        "filtered_unbaked_animations": filtered_unbaked_anims,
        "verify_gate_1": index_data["verify_gate_1"],
        "watchdog": res.to_dict(),
    }
