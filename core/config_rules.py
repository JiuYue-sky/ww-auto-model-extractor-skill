"""Dynamic matching rules, corrected UE/Blender texture channel specs, and multi-form character folder matching."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .pinyin_index import has_cjk, text_to_pinyin_variants

_COMPACT_SEP_RE = re.compile(r"[\s_\-·•・/\\()（）\[\]【】:,：，.。]+")

# Officially released playable character aliases ONLY (no unreleased / datamined / internal prototype entries).
# Note:
#   1. `ww-extract` discovers playable character folders dynamically from the host's live official pak VFS.
#   2. Any Pinyin-named playable character folder (including future officially released characters not listed here)
#      is matched automatically via `pinyin_index` across Chinese, lowercase English/Pinyin, and Capitalized/PascalCase variants.
#   3. Entries below map officially released characters whose internal folder differs from Pinyin or English localization.
CHARACTER_ALIASES: Dict[str, List[str]] = {
    "aimisi": ["爱弥斯", "愛彌斯", "aemeath", "aimisi", "Aimisi"],
    "anke": ["安可", "encore", "anke", "Anke"],
    "aogusita": ["奥古斯塔", "奧古斯塔", "augusta", "aogusita", "Aogusita"],
    "baer": ["莫特斐", "mortefi", "baer", "Baer", "motefei"],
    "bailian": ["白芷", "baizhi", "bailian", "BaiLian"],
    "bulante": ["布兰特", "布蘭特", "brant", "bulante", "Bulante"],
    "buling": ["卜灵", "卜靈", "buling", "Buling"],
    "changli": ["长离", "長離", "changli", "ChangLi"],
    "chun": ["椿", "camellya", "chun", "Chun"],
    "daniya": ["达妮娅", "達妮婭", "达尼亚", "denia", "daniya", "Daniya"],
    "dengdeng": ["灯灯", "燈燈", "lumi", "dengdeng", "Dengdeng"],
    "feibi": ["菲比", "phoebe", "feibi", "Feibi"],
    "fuludelisi": ["芙露德莉斯", "芙露德莉絲", "fleurdelys", "fuludelisi", "Fuludelisi", "大卡提"],
    "fuluoluo": ["弗洛洛", "phrolova", "fuluoluo", "Fuluoluo"],
    "jiabeilina": ["嘉贝莉娜", "嘉貝莉娜", "galbrena", "calbrena", "jiabeilina", "Jiabeilina"],
    "jianxin": ["鉴心", "鑒心", "jianxin", "Jianxin"],
    "jinxi": ["今汐", "jinhsi", "jinxi", "Jinxi", "令尹"],
    "jiyan": ["忌炎", "jiyan", "Jiyan"],
    "jueyuan": ["维里奈", "維里奈", "verina", "jueyuan", "Jueyuan", "weilina"],
    "kakaluo": ["卡卡罗", "卡卡羅", "calcharo", "kakaluo", "Kakaluo"],
    "kanteleila": ["坎特蕾拉", "cantarella", "kanteleila", "Kanteleila"],
    "katixiya": ["卡提希娅", "卡提希婭", "cartethyia", "katixiya", "Katixiya", "卡提"],
    "kmola": ["珂莱塔", "珂萊塔", "carlotta", "kamola", "kmola", "Kmola", "kelaita"],
    "lili": ["莉莉", "黎丽", "丽丽", "黎麗", "麗麗", "lily", "lili", "Lili"],
    "lingyang": ["凌阳", "凌陽", "lingyang", "Lingyang"],
    "linnai": ["琳奈", "linnai", "LinNai", "linnaea"],
    "luhesi": ["陆赫斯", "陆·赫斯", "陸赫斯", "陸·赫斯", "卢赫斯", "luuk", "luhesi", "Luhesi"],
    "luokeke": ["洛可可", "roccia", "rococo", "luokeke", "Luokeke"],
    "luosela": ["洛瑟菈", "洛瑟拉", "罗塞拉", "羅塞拉", "lucilla", "luosela", "Luosela"],
    "lupa": ["露帕", "lupa", "Lupa"],
    "maxiaofang": ["炽霞", "熾霞", "chixia", "maxiaofang", "Maxiaofang"],
    "micai": ["丹瑾", "danjin", "micai", "Micai"],
    "mone": ["莫宁", "莫寧", "mornye", "mone", "Mone"],
    "nanzhu": ["漂泊者男", "男漂", "男漂泊者", "男主", "rovermale", "nanzhu", "Nanzhu", "playermale", "malerover"],
    "nvzhu": ["漂泊者女", "女漂", "女漂泊者", "女主", "roverfemale", "nvzhu", "Nvzhu", "playerfemale", "femalerover"],
    "qianxia": ["千咲", "chisa", "qianxia", "Qianxia", "qianxiao"],
    "qiushui": ["秋水", "aalto", "qiushui", "Qiushui"],
    "qiuyuan": ["仇远", "仇遠", "qiuyuan", "Qiuyuan"],
    "sanhua": ["散华", "散華", "sanhua", "Sanhua"],
    "shouanren": ["守岸人", "shorekeeper", "shouanren", "Shouanren"],
    "taidaonv": ["绯雪", "緋雪", "hiyuki", "feixue", "taidaonv", "TaiDaoNv"],
    "taohua": ["桃祈", "taoqi", "taohua", "Taohua"],
    "xiakong": ["夏空", "ciaccona", "xiakong", "Xiakong"],
    "xiangliyao": ["相里要", "xiangliyao", "Xiangliyao"],
    "xigelika": ["西格莉卡", "希格莉卡", "西格丽卡", "sigrika", "xigelika", "Xigelika"],
    "yangyang": ["秧秧", "yangyang", "Yangyang"],
    "yinlin": ["吟霖", "yinlin", "YinLin"],
    "youhu": ["釉瑚", "釉胡", "youhu", "Youhu"],
    "younuo": ["尤诺", "尤諾", "iuno", "younuo", "Younuo"],
    "yuanwu": ["渊武", "淵武", "yuanwu", "Yuanwu"],
    "zanni": ["赞妮", "贊妮", "zani", "zanni", "Zanni"],
    "zhezhi": ["折枝", "zhezhi", "Zhezhi"],
}

MI_TEXTURE_PARAM_SLOTS: Dict[str, str] = {
    "maintex": "base_color",
    "pm_diffuse": "base_color",
    "basecolor": "base_color",
    "basetexture": "base_color",
    "diffuse": "base_color",
    "albedo": "base_color",
    "pm_normals": "normal_packed",
    "normal_roughness_metallic": "normal_packed",
    "normalmap": "normal_packed",
    "normaltex": "normal_packed",
    "normal": "normal_packed",
    "masktex": "sdf_or_mask",
    "sdftex": "sdf",
    "facesdf": "sdf",
    "typemask": "id_mask",
    "idmap": "id_mask",
    "rgid": "id_mask",
    "ramp": "skin_ramp",
    "skinramp": "skin_ramp",
    "ramptex": "skin_ramp",
    "ftm": "ftm_mask",
    "hairmask": "hair_mask",
    "hm": "hair_mask",
    "hn": "hair_flow",
    "het": "het_mask",
    "fur_tex": "fur_mask",
    "furtex": "fur_mask",
    "emissivetex": "emissive",
    "emission": "emissive",
    "eyehighlight": "eye_highlight",
    "matcap": "matcap",
    "pbrcubemap": "cubemap",
    "cubemap": "cubemap",
}

TEXTURE_SUFFIX_RULES: Dict[str, Dict[str, object]] = {
    "_basecolor": {
        "slot": "base_color",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "ue_compression_no_alpha": "TC_Default",
        "notes": "Base color; preserve Alpha (hair opacity mask or cloth shadow data)",
    },
    "_diffuse": {
        "slot": "base_color",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "ue_compression_no_alpha": "TC_Default",
        "notes": "Base diffuse texture",
    },
    "_albedo": {
        "slot": "base_color",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "ue_compression_no_alpha": "TC_Default",
        "notes": "Albedo diffuse texture",
    },
    "_color": {
        "slot": "base_color",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "ue_compression_no_alpha": "TC_Default",
        "notes": "Color map",
    },
    "_matcap": {
        "slot": "matcap",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "notes": "View-space matcap reflection map",
    },
    "_normal": {
        "slot": "normal_packed",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "ue_compression_split_normal": "TC_Normalmap",
        "ue_compression_split_mr": "TC_BC7",
        "notes": "DirectX Normal (G=-Y); in WW often RGBA packed (R/G=Normal, B=Metallic, A=Roughness)",
    },
    "_cube": {
        "slot": "cubemap",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_HDR",
        "notes": "HDR environment cubemap",
    },
    "_skin": {
        "slot": "skin_ramp",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_EditorIcon",
        "notes": "Shadow ramp LUT (UserInterface2D/uncompressed to prevent banding)",
    },
    "_ramp": {
        "slot": "skin_ramp",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_EditorIcon",
        "notes": "Shadow ramp LUT",
    },
    "_rgid": {
        "slot": "id_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "Material region ID mask",
    },
    "_heta": {
        "slot": "het_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "Hair/outline/edge transparency mask",
    },
    "_sdf": {
        "slot": "sdf",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_VectorDisplacementmap",
        "notes": "Face SDF shadow threshold map (check channel correlation/mirroring before combining!)",
    },
    "_ftm": {
        "slot": "ftm_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "4-channel linear mask (Opacity/Metallic/Roughness/Detail)",
    },
    "_het": {
        "slot": "het_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "Edge/outline mask",
    },
    "_prm": {
        "slot": "pbr_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "PBR packed mask",
    },
    "_ilm": {
        "slot": "lightmap",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "ILM toon lightmap",
    },
    "_hm": {
        "slot": "hair_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "Hair highlight / shadow offset mask",
    },
    "_hn": {
        "slot": "hair_flow",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "Hair anisotropic normal / flow map",
    },
    "_hr": {
        "slot": "hair_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "Hair highlight range mask",
    },
    "_id": {
        "slot": "id_mask",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_Grayscale",
        "notes": "Material zone ID mask",
    },
    "_eg": {
        "slot": "eye_highlight",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "notes": "Eye highlight / glow map",
    },
    "_em": {
        "slot": "emissive",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "notes": "Eye / emissive mask",
    },
    "_ld": {
        "slot": "hair_light_detail",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "notes": "Hair light detail map",
    },
    "_d": {
        "slot": "base_color",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "ue_compression_no_alpha": "TC_Default",
        "notes": "Base color (preserve Alpha; hair=opacity mask, cloth=shadow data)",
    },
    "_n": {
        "slot": "normal_packed",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_BC7",
        "ue_compression_split_normal": "TC_Normalmap",
        "ue_compression_split_mr": "TC_BC7",
        "notes": "DirectX Normal (G=-Y) + packed B=Metallic, A=Roughness; NEVER use TC_Normalmap on unsplit RGBA!",
    },
    "_m": {
        "slot": "metallic",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_Grayscale",
        "notes": "Metallic mask",
    },
    "_r": {
        "slot": "roughness",
        "blender_colorspace": "Non-Color",
        "ue_srgb": False,
        "ue_compression": "TC_Grayscale",
        "notes": "Roughness mask",
    },
    "_e": {
        "slot": "emissive",
        "blender_colorspace": "sRGB",
        "ue_srgb": True,
        "ue_compression": "TC_BC7",
        "notes": "Emissive texture",
    },
}

TEXTURE_SUFFIX_ORDER: List[str] = sorted(TEXTURE_SUFFIX_RULES.keys(), key=len, reverse=True)
HAIR_ALPHA_CLIP_TOKENS: Tuple[str, ...] = ("alpha", "lash", "eyelash", "heta", "trans")
SWITCH_TEXTURE_TOKEN = "_switch"
ALPHA_CLIP_THRESHOLD = 0.333


def normalize_character_key(text: str) -> str:
    """Strip whitespace and common punctuation/separators and lowercase ASCII."""
    return _COMPACT_SEP_RE.sub("", (text or "").strip()).lower()


def _capitalize_ascii_variants(token: str) -> List[str]:
    """Generate first-letter capitalized and title/underscore capitalized forms for an ASCII token."""
    raw = (token or "").strip()
    if not raw or not raw.isascii():
        return []
    out: List[str] = []

    def _add(val: str) -> None:
        if val and val not in out:
            out.append(val)

    if any(c.isupper() for c in raw) and any(c.islower() for c in raw):
        _add(raw[0].upper() + raw[1:])

    parts = [p for p in re.split(r"[\s_\-]+", raw) if p]
    if len(parts) >= 2:
        _add("_".join(p[0].upper() + p[1:].lower() if not p.isupper() else p for p in parts))
        _add("".join(p[0].upper() + p[1:].lower() if not p.isupper() else p for p in parts))

    low = raw.lower()
    if low:
        _add(low[0].upper() + low[1:])
    return out


def resolve_character_query_variants(user_query: str) -> Dict[str, Any]:
    """Expand a Chinese/English/Pinyin/ModelId query into explicit multi-channel folder matching variants."""
    raw = (user_query or "").strip()
    if not raw:
        return {
            "raw": "",
            "has_cjk": False,
            "chinese": [],
            "english_lower": [],
            "english_capitalized": [],
            "pinyin_syllables": [],
            "matched_alias_canonical": [],
            "all_tokens": [],
        }

    compact_raw = normalize_character_key(raw)
    query_has_cjk = has_cjk(raw)

    chinese: List[str] = []
    english_lower: List[str] = []
    english_capitalized: List[str] = []
    matched_canonicals: List[str] = []

    def _add_unique(bucket: List[str], val: str) -> None:
        if val and val not in bucket:
            bucket.append(val)

    def _add_english(token: str) -> None:
        t = (token or "").strip()
        if not t or not t.isascii():
            return
        _add_unique(english_lower, t.lower())
        compact_t = normalize_character_key(t)
        if compact_t and compact_t != t.lower():
            _add_unique(english_lower, compact_t)
        for cap in _capitalize_ascii_variants(t):
            _add_unique(english_capitalized, cap)

    if query_has_cjk:
        _add_unique(chinese, raw)
        stripped_zh = _COMPACT_SEP_RE.sub("", raw)
        if stripped_zh and stripped_zh != raw:
            _add_unique(chinese, stripped_zh)
    else:
        _add_english(raw)

    py_info = text_to_pinyin_variants(raw) if query_has_cjk else {"lower": [], "capitalized": [], "syllables": []}

    exact_matches: List[Tuple[str, List[str]]] = []
    for canonical, aliases in CHARACTER_ALIASES.items():
        norm_canon = normalize_character_key(canonical)
        norm_aliases = [normalize_character_key(a) for a in aliases]
        if compact_raw == norm_canon or compact_raw in norm_aliases or any(raw == a for a in aliases):
            exact_matches.append((canonical, aliases))

    if not exact_matches and py_info["lower"]:
        py_low_set = set(py_info["lower"][:8])
        for canonical, aliases in CHARACTER_ALIASES.items():
            norm_canon = normalize_character_key(canonical)
            if norm_canon in py_low_set:
                exact_matches.append((canonical, aliases))

    if not exact_matches and len(compact_raw) >= 2:
        sub_candidates: List[Tuple[int, str, List[str]]] = []
        for canonical, aliases in CHARACTER_ALIASES.items():
            best_len = 0
            for a in aliases:
                na = normalize_character_key(a)
                if len(na) >= 2 and (compact_raw in na or na in compact_raw):
                    best_len = max(best_len, min(len(compact_raw), len(na)))
            if best_len > 0:
                sub_candidates.append((best_len, canonical, aliases))
        sub_candidates.sort(key=lambda x: (-x[0], x[1]))
        if sub_candidates:
            top_len = sub_candidates[0][0]
            exact_matches = [(c, al) for bl, c, al in sub_candidates if bl == top_len]

    for canonical, aliases in exact_matches:
        _add_unique(matched_canonicals, canonical)
        _add_english(canonical)
        for a in aliases:
            if a.isascii():
                _add_english(a)
            elif has_cjk(a):
                _add_unique(chinese, a)

    for lw in py_info["lower"]:
        _add_unique(english_lower, lw)
    for cp in py_info["capitalized"]:
        _add_unique(english_capitalized, cp)

    all_tokens: List[str] = []
    for bucket in (matched_canonicals, english_lower, english_capitalized, chinese):
        for tok in bucket:
            if tok and tok not in all_tokens:
                all_tokens.append(tok)
    if raw not in all_tokens:
        all_tokens.append(raw)

    return {
        "raw": raw,
        "has_cjk": query_has_cjk,
        "chinese": chinese,
        "english_lower": english_lower,
        "english_capitalized": english_capitalized,
        "pinyin_syllables": py_info["syllables"],
        "matched_alias_canonical": matched_canonicals,
        "all_tokens": all_tokens,
    }


def resolve_character_query_tokens(user_query: str) -> List[str]:
    """Expand a Chinese/English/Pinyin character query into ordered VFS search tokens."""
    return resolve_character_query_variants(user_query)["all_tokens"]


def classify_texture_suffix(filename: str) -> Tuple[str, Dict[str, object]]:
    """Classify a texture filename using longest-suffix match."""
    import os

    stem = os.path.splitext(os.path.basename(filename))[0].lower()
    if "matcap" in stem or "premake" in stem:
        return ("_matcap", TEXTURE_SUFFIX_RULES["_matcap"])
    for sfx in TEXTURE_SUFFIX_ORDER:
        if stem.endswith(sfx):
            return (sfx, TEXTURE_SUFFIX_RULES[sfx])
    return (
        "(unknown)",
        {
            "slot": "unknown",
            "blender_colorspace": "Non-Color",
            "ue_srgb": False,
            "ue_compression": "TC_BC7",
            "notes": "Unrecognized suffix; preserved for manual/downstream inspection",
        },
    )
