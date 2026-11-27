"""Stage 1a Gate & Safe Local Key-Bundle Loader (BYOK — Zero Bundled Keys & Zero Remote Key Fetching).

Compliance & Usability Invariants:
1. NEVER bundles keys and NEVER fetches keys from any remote URL.
2. When local keys already exist on the host (in FModel AppSettings.json, FModel directory, work_dir,
   or a host-provided local `.json` / `.zip` / `.txt` / folder path), directly validates and uses them
   without interrogating file provenance or reading unrelated documentation files (e.g. README.md).
3. `.zip` archives are inspected strictly IN MEMORY (`zipfile.ZipFile` read stream) — NEVER extracts
   `.exe`, `.bat`, `.cmd`, `.ps1`, `.dll`, symlinks, or arbitrary files to disk.
4. Clearly distinguishes:
   - Missing local keys (`CONSENT_REQUIRED` / `HOST_KEYS_REQUIRED`): neutral reminder that this plugin
     does not provide or search for keys; user may temporarily disable the plugin and open a new session
     or locate keys manually, OR pass an existing local path directly.
   - Invalid/unusable/expired local keys (`FAIL` / `HOST_KEYS_INVALID`): explicit user-facing notice
     "密钥本身存在问题，请使用正确可用的密钥".
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from .watchdog import run_watched

HEX_KEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")
RAW_64_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")
INLINE_0X_KEY_RE = re.compile(r"\b0x[0-9a-fA-F]{64}\b")
INLINE_GUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}\b")
GUID_HEX_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
ZERO_AES_KEY = "0x" + ("0" * 64)

_MAX_KEY_JSON_BYTES = 2 * 1024 * 1024
_MAX_KEY_TXT_BYTES = 256 * 1024
_MAX_KEY_ZIP_BYTES = 16 * 1024 * 1024

INVALID_KEY_NOTICE_ZH = "密钥本身存在问题，请使用正确可用的密钥。"


def _normalize_hex_key(raw: Any, *, allow_zero: bool = False) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    s = raw.strip().strip('"').strip("'")
    norm: Optional[str] = None
    if HEX_KEY_RE.match(s):
        norm = "0x" + s[2:].upper()
    elif RAW_64_HEX_RE.match(s):
        norm = "0x" + s.upper()
    if norm is None:
        return None
    if not allow_zero and norm == ZERO_AES_KEY:
        return None
    return norm


def _normalize_guid(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    s = raw.strip().strip("{}")
    if not GUID_HEX_RE.match(s):
        return None
    return s.replace("-", "").upper()


def validate_aes_key_bundle(payload: Any) -> Dict[str, Any]:
    """Validate and normalize `{mainKey, dynamicKeys:[{guid,key}]}` (or FModel AppSettings / key map / list)."""
    candidates: List[Dict[str, Any]] = []
    norm_main: Optional[str] = None
    dyn_map: Dict[str, str] = {}

    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str):
                mk = _normalize_hex_key(item)
                if mk and not norm_main:
                    norm_main = mk
            elif isinstance(item, dict):
                g = _normalize_guid(item.get("guid") or item.get("Guid"))
                k = _normalize_hex_key(item.get("key") or item.get("Key"))
                if g and k:
                    dyn_map[g] = k
                elif k and not norm_main:
                    norm_main = k
    elif isinstance(payload, dict):
        candidates.append(payload)
        for ak_name in ("AesKeys", "aesKeys", "aes", "keys"):
            sub = payload.get(ak_name)
            if isinstance(sub, dict):
                candidates.append(sub)
            elif isinstance(sub, list):
                for item in sub:
                    if isinstance(item, dict):
                        g = _normalize_guid(item.get("guid") or item.get("Guid"))
                        k = _normalize_hex_key(item.get("key") or item.get("Key"))
                        if g and k:
                            dyn_map[g] = k
                        elif k and not norm_main:
                            norm_main = k
                    elif isinstance(item, str):
                        mk = _normalize_hex_key(item)
                        if mk and not norm_main:
                            norm_main = mk
        per_dir = payload.get("PerDirectory")
        if isinstance(per_dir, dict):
            # Prefer Wuthering Waves entries first if present
            ordered_vals = sorted(
                per_dir.items(),
                key=lambda kv: 0
                if (
                    isinstance(kv[1], dict)
                    and (
                        kv[1].get("UeVersion") == 68812811
                        or str(kv[1].get("UeVersion", "")).upper() == "GAME_WUTHERINGWAVES"
                        or "wuthering" in str(kv[0]).lower()
                        or "wuthering" in str(kv[1].get("GameName", "")).lower()
                    )
                )
                else 1,
            )
            for _, v in ordered_vals:
                if isinstance(v, dict):
                    ak = v.get("AesKeys") or v.get("aesKeys")
                    if isinstance(ak, dict):
                        candidates.append(ak)
    else:
        return {"valid": False, "error": "Payload is not a valid JSON object or array"}

    for obj in candidates:
        mk = _normalize_hex_key(obj.get("mainKey") or obj.get("MainKey") or obj.get("main_key") or obj.get("key") or obj.get("Key"))
        if mk and not norm_main:
            norm_main = mk
        dlist = obj.get("dynamicKeys") if isinstance(obj.get("dynamicKeys"), list) else obj.get("DynamicKeys")
        if isinstance(dlist, list):
            for item in dlist:
                if not isinstance(item, dict):
                    continue
                g = _normalize_guid(item.get("guid") or item.get("Guid"))
                k = _normalize_hex_key(item.get("key") or item.get("Key"))
                if g and k:
                    dyn_map[g] = k
        # Support flat maps like {"<guid>": "0x..."} or {"main": "0x..."}
        for k_name, v_val in obj.items():
            if not isinstance(v_val, str):
                continue
            hk = _normalize_hex_key(v_val)
            if not hk:
                continue
            gn = _normalize_guid(k_name)
            if gn:
                dyn_map[gn] = hk
            elif not norm_main:
                norm_main = hk

    if not norm_main and not dyn_map:
        return {"valid": False, "error": "No valid non-zero 256-bit hex AES keys (mainKey / dynamicKeys) found"}

    normalized_bundle = {
        "mainKey": norm_main or ZERO_AES_KEY,
        "dynamicKeys": [{"guid": g, "key": k} for g, k in sorted(dyn_map.items())],
    }
    return {
        "valid": True,
        "has_main_key": norm_main is not None,
        "dynamic_key_count": len(dyn_map),
        "total_keys": (1 if norm_main else 0) + len(dyn_map),
        "normalized": normalized_bundle,
    }


def _parse_plain_text_keys(text: str) -> Dict[str, Any]:
    """Parse a raw `.txt` / `.key` file containing JSON or `0x...` 64-hex key(s) (optionally paired with GUIDs)."""
    stripped = (text or "").strip()
    if not stripped:
        return {"valid": False, "error": "Key text file is empty"}
    if stripped.startswith(("{", "[")):
        try:
            return validate_aes_key_bundle(json.loads(stripped))
        except Exception:
            pass

    norm_main: Optional[str] = None
    dyn_map: Dict[str, str] = {}
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        keys_in_line = [_normalize_hex_key(m.group(0)) for m in INLINE_0X_KEY_RE.finditer(line)]
        keys_in_line = [k for k in keys_in_line if k]
        if not keys_in_line:
            single = _normalize_hex_key(line)
            if single:
                keys_in_line = [single]
        if not keys_in_line:
            continue
        guids_in_line = [_normalize_guid(m.group(0)) for m in INLINE_GUID_RE.finditer(line)]
        guids_in_line = [g for g in guids_in_line if g]
        if guids_in_line:
            dyn_map[guids_in_line[0]] = keys_in_line[0]
        elif not norm_main:
            norm_main = keys_in_line[0]

    if not norm_main and not dyn_map:
        return {"valid": False, "error": "No valid 256-bit hex AES key found in text file"}
    return {
        "valid": True,
        "has_main_key": norm_main is not None,
        "dynamic_key_count": len(dyn_map),
        "total_keys": (1 if norm_main else 0) + len(dyn_map),
        "normalized": {
            "mainKey": norm_main or ZERO_AES_KEY,
            "dynamicKeys": [{"guid": g, "key": k} for g, k in sorted(dyn_map.items())],
        },
    }


def _load_key_directory(dir_path: Path) -> Dict[str, Any]:
    """Scan ONLY candidate key files inside a host-provided local folder (max depth 2); NEVER reads README/markdown."""
    candidates: List[Path] = []
    queue: List[tuple[Path, int]] = [(dir_path, 0)]
    while queue:
        cur, depth = queue.pop(0)
        try:
            for entry in cur.iterdir():
                if entry.is_file():
                    sfx = entry.suffix.lower()
                    if sfx in (".json", ".zip", ".txt", ".key"):
                        candidates.append(entry)
                elif entry.is_dir() and depth < 2 and entry.name not in (".git", "__pycache__", "node_modules"):
                    queue.append((entry, depth + 1))
        except OSError:
            continue

    if not candidates:
        return {
            "ok": False,
            "code": "HOST_KEYS_INVALID",
            "error": f"No .json / .zip / .txt / .key file found inside directory: {dir_path}",
        }

    def _priority(p: Path) -> tuple[int, int, str]:
        nm = p.name.lower()
        if nm == "keys.json":
            rank = 0
        elif "key" in nm and p.suffix.lower() == ".json":
            rank = 1
        elif nm == "appsettings.json":
            rank = 2
        elif p.suffix.lower() == ".json":
            rank = 3
        elif p.suffix.lower() == ".zip":
            rank = 4
        elif "key" in nm and p.suffix.lower() in (".txt", ".key"):
            rank = 5
        else:
            rank = 6
        return (rank, len(p.parts), nm)

    candidates.sort(key=_priority)
    last_err = "No valid AES key file found in directory"
    for cand in candidates[:25]:
        res = load_user_key_bundle_file(cand)
        if res.get("ok"):
            res["loaded_from_directory"] = str(dir_path.resolve())
            return res
        last_err = f"{cand.name}: {res.get('error')}"
    return {"ok": False, "code": "HOST_KEYS_INVALID", "error": last_err}


def load_user_key_bundle_file(bundle_path: str | Path) -> Dict[str, Any]:
    """Safely parse a host-provided local `.json`, `.zip` (in-memory), `.txt`/`.key`, or directory path."""
    raw_str = str(bundle_path or "").strip().strip('"').strip("'")
    if not raw_str or "\x00" in raw_str:
        return {"ok": False, "code": "HOST_KEYS_INVALID", "error": "Empty or invalid key path"}
    p = Path(raw_str)
    if p.is_dir():
        return _load_key_directory(p)
    if not p.is_file():
        return {"ok": False, "code": "HOST_KEYS_INVALID", "error": f"Key file/package does not exist: {p}"}

    st_size = p.stat().st_size
    sfx = p.suffix.lower()

    if sfx == ".zip":
        if st_size > _MAX_KEY_ZIP_BYTES:
            return {"ok": False, "code": "HOST_KEYS_INVALID", "error": f"Zip archive exceeds {_MAX_KEY_ZIP_BYTES} bytes safety limit"}
        try:
            with zipfile.ZipFile(p, "r") as zf:
                cand_infos = [
                    info
                    for info in zf.infolist()
                    if (not info.is_dir())
                    and Path(info.filename).suffix.lower() in (".json", ".txt", ".key")
                    and "\x00" not in info.filename
                    and ((info.external_attr >> 16) & 0o170000) != 0o120000
                ]
                if not cand_infos:
                    return {
                        "ok": False,
                        "code": "HOST_KEYS_INVALID",
                        "error": "No .json/.txt key file found inside the .zip package (executable/non-key members are ignored)",
                    }
                cand_infos.sort(
                    key=lambda i: (
                        0 if Path(i.filename).name.lower() == "keys.json"
                        else (1 if i.filename.lower().endswith(".json") else 2),
                        len(i.filename),
                    )
                )
                last_err = "No valid AES key inside archive"
                for info in cand_infos:
                    limit = _MAX_KEY_JSON_BYTES if info.filename.lower().endswith(".json") else _MAX_KEY_TXT_BYTES
                    if info.file_size > limit:
                        last_err = f"{info.filename} exceeds {limit} bytes limit"
                        continue
                    with zf.open(info, "r") as fp:
                        raw_bytes = fp.read(limit + 1)
                    if len(raw_bytes) > limit:
                        continue
                    decoded = io.BytesIO(raw_bytes).read().decode("utf-8-sig", errors="replace")
                    if info.filename.lower().endswith(".json"):
                        try:
                            val = validate_aes_key_bundle(json.loads(decoded))
                        except Exception as exc:
                            last_err = f"{info.filename}: invalid JSON ({exc})"
                            continue
                    else:
                        val = _parse_plain_text_keys(decoded)
                    if val["valid"]:
                        return {
                            "ok": True,
                            "source_type": "zip_in_memory",
                            "source_path": str(p.resolve()),
                            "zip_member": info.filename,
                            **val,
                        }
                    last_err = f"{info.filename}: {val.get('error')}"
                return {"ok": False, "code": "HOST_KEYS_INVALID", "error": last_err}
        except zipfile.BadZipFile:
            return {"ok": False, "code": "HOST_KEYS_INVALID", "error": f"Corrupt or invalid .zip file: {p}"}
        except Exception as exc:
            return {"ok": False, "code": "HOST_KEYS_INVALID", "error": f"Failed reading .zip key package: {exc}"}

    if sfx in (".txt", ".key"):
        if st_size > _MAX_KEY_TXT_BYTES:
            return {"ok": False, "code": "HOST_KEYS_INVALID", "error": f"Key text file exceeds {_MAX_KEY_TXT_BYTES} bytes safety limit"}
        val = _parse_plain_text_keys(p.read_text(encoding="utf-8-sig", errors="replace"))
        if not val["valid"]:
            return {"ok": False, "code": "HOST_KEYS_INVALID", "error": val.get("error", "Invalid key text file")}
        return {
            "ok": True,
            "source_type": "text_file",
            "source_path": str(p.resolve()),
            **val,
        }

    if st_size > _MAX_KEY_JSON_BYTES:
        return {"ok": False, "code": "HOST_KEYS_INVALID", "error": f"Key JSON file exceeds {_MAX_KEY_JSON_BYTES} bytes safety limit"}
    raw_text = p.read_text(encoding="utf-8-sig", errors="replace")
    try:
        parsed = json.loads(raw_text)
        val = validate_aes_key_bundle(parsed)
    except Exception as exc:
        # Fallback if a plain key was saved with no extension or non-JSON text
        val = _parse_plain_text_keys(raw_text)
        if not val["valid"]:
            return {"ok": False, "code": "HOST_KEYS_INVALID", "error": f"Invalid JSON in {p.name}: {exc}"}
        return {
            "ok": True,
            "source_type": "text_file",
            "source_path": str(p.resolve()),
            **val,
        }

    if not val["valid"]:
        return {"ok": False, "code": "HOST_KEYS_INVALID", "error": val.get("error", "Invalid key JSON structure")}
    return {
        "ok": True,
        "source_type": "json_file",
        "source_path": str(p.resolve()),
        **val,
    }


def _build_ww_extract_env() -> Dict[str, str]:
    return os.environ.copy()


def _key_files_fingerprint(key_files: List[str]) -> List[Dict[str, Any]]:
    fp: List[Dict[str, Any]] = []
    for kf in key_files:
        p = Path(kf)
        if p.is_file():
            st = p.stat()
            fp.append({"path": str(p.resolve()), "size": st.st_size, "mtime_ns": st.st_mtime_ns})
    return fp


def _write_character_catalog_cache(
    work_dir: Path,
    ww: Dict[str, Any],
    aes: Dict[str, Any],
    characters: Optional[List[Dict[str, Any]]],
) -> None:
    if not isinstance(characters, list) or not characters:
        return
    cache_file = work_dir / "character_catalog_cache.json"
    payload = {
        "fingerprint": {
            "game_root": str(ww.get("game_root", "")),
            "client_version": str(ww.get("client_version", "")),
            "pak_total": int(ww.get("pak_counts", {}).get("total", 0)),
            "mounted_paks": int(aes.get("mounted_paks", 0)),
        },
        "count": len(characters),
        "characters": characters,
    }
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _probe_paks(
    ww_extract_exe: str,
    native_dir: Optional[str],
    game_dir: str,
    keys_paths: List[str],
    include_saved: bool = True,
    with_characters: bool = True,
) -> Dict[str, Any]:
    cmd = [
        ww_extract_exe,
        "probe-paks",
        "--game-dir",
        game_dir,
        "--include-saved",
        "true" if include_saved else "false",
        "--with-characters",
        "true" if with_characters else "false",
    ]
    if native_dir:
        cmd.extend(["--native-dir", native_dir])
    valid_keys = [k for k in keys_paths if k and Path(k).is_file()]
    if valid_keys:
        cmd.extend(["--keys", ",".join(valid_keys)])

    res = run_watched(
        cmd,
        env=_build_ww_extract_env(),
        hard_timeout_s=120,
        io_idle_timeout_s=60,
        max_retries=2,
        label="ww-extract-probe-paks",
    )
    if not res.ok:
        return {"ok": False, "error": res.stderr[-800:] or res.stdout[-800:], "watchdog": res.to_dict()}
    try:
        data = json.loads(res.stdout)
        data["watchdog"] = res.to_dict()
        return data
    except Exception as exc:
        return {"ok": False, "error": f"Failed to parse probe-paks JSON: {exc}", "raw": res.stdout[:600]}


def resolve_and_verify_aes_keys(
    env_report: Dict[str, Any],
    work_dir: Path,
    *,
    extra_keys_file: Optional[str | Path] = None,
    ignore_fmodel_keys: bool = False,
) -> Dict[str, Any]:
    """Mount paks using existing local FModel / local key files or host-provided path; never fetches remote keys."""
    ww = env_report["wuthering_waves"]
    ww_ext = env_report["ww_extract"]
    fmodel = env_report.get("fmodel") or {}

    if not ww.get("found"):
        return {"status": "FAIL", "error": "Wuthering Waves not found"}
    if not ww_ext.get("ok"):
        return {"status": "FAIL", "error": "ww-extract is not operational"}

    client_ver = ww.get("client_version", "unknown")
    game_dir = ww["game_root"]
    exe = ww_ext["executable"]
    native_dir = ww_ext.get("native_dir")

    local_key_files: List[str] = []
    temp_normalized_json: Optional[Path] = None
    has_loaded_keys = False

    if not ignore_fmodel_keys:
        if fmodel.get("appsettings_path") and Path(fmodel["appsettings_path"]).is_file():
            local_key_files.append(str(Path(fmodel["appsettings_path"]).resolve()))
            if int(fmodel.get("aes_key_count", 0)) > 0 or int(fmodel.get("any_ww_aes_key_count", 0)) > 0:
                has_loaded_keys = True
        for lkf in fmodel.get("detected_local_key_files") or []:
            lp = Path(lkf)
            if lp.is_file():
                local_key_files.append(str(lp.resolve()))
                has_loaded_keys = True
        wd_keys = work_dir / "keys.json"
        if wd_keys.is_file():
            loaded_wd = load_user_key_bundle_file(wd_keys)
            if loaded_wd.get("ok"):
                local_key_files.append(str(wd_keys.resolve()))
                has_loaded_keys = True

    if extra_keys_file:
        loaded = load_user_key_bundle_file(extra_keys_file)
        if not loaded.get("ok"):
            return {
                "status": "FAIL",
                "code": "HOST_KEYS_INVALID",
                "client_version": client_ver,
                "key_files": local_key_files,
                "error": loaded.get("error", "Invalid --keys-file"),
                "host_notice": f"{INVALID_KEY_NOTICE_ZH}（校验详情：{loaded.get('error')}）",
            }
        has_loaded_keys = True
        if loaded["source_type"] in ("zip_in_memory", "text_file"):
            temp_normalized_json = work_dir / "_transient_session_keys.json"
            temp_normalized_json.parent.mkdir(parents=True, exist_ok=True)
            temp_normalized_json.write_text(json.dumps(loaded["normalized"], indent=2), encoding="utf-8")
            local_key_files.append(str(temp_normalized_json.resolve()))
        else:
            local_key_files.append(loaded["source_path"])

    local_key_files = list(dict.fromkeys(local_key_files))

    probe_cache_file = work_dir / "aes_probe_cache.json"
    cur_fp = {
        "game_root": str(game_dir),
        "client_version": str(client_ver),
        "pak_total": int(ww.get("pak_counts", {}).get("total", 0)),
        "ignore_fmodel_keys": bool(ignore_fmodel_keys),
        "keys_fp": _key_files_fingerprint(local_key_files) if temp_normalized_json is None else ["transient_bundle"],
    }
    if temp_normalized_json is None and probe_cache_file.is_file():
        try:
            cached = json.loads(probe_cache_file.read_text(encoding="utf-8"))
            if (
                cached.get("fingerprint") == cur_fp
                and cached.get("aes", {}).get("status") == "FULL"
                and (work_dir / "character_catalog_cache.json").is_file()
            ):
                return {
                    "status": "PASS",
                    "client_version": client_ver,
                    "key_files": local_key_files,
                    "aes": cached["aes"],
                    "remote_refreshed": False,
                    "cached_probe": True,
                    "host_notice": "",
                }
        except Exception:
            pass

    probe1 = _probe_paks(exe, native_dir, game_dir, local_key_files, include_saved=True, with_characters=True)
    if not probe1.get("ok"):
        if temp_normalized_json and temp_normalized_json.is_file():
            temp_normalized_json.unlink(missing_ok=True)
        return {
            "status": "FAIL",
            "stage": "initial_probe",
            "error": probe1.get("error", "probe-paks failed"),
            "probe": probe1,
        }

    aes1 = probe1.get("aes", {})
    _write_character_catalog_cache(work_dir, ww, aes1, probe1.get("characters"))
    if aes1.get("status") == "FULL":
        if temp_normalized_json is None:
            probe_cache_file.parent.mkdir(parents=True, exist_ok=True)
            probe_cache_file.write_text(
                json.dumps({"fingerprint": cur_fp, "aes": aes1}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return {
            "status": "PASS",
            "client_version": client_ver,
            "key_files": local_key_files,
            "aes": aes1,
            "remote_refreshed": False,
            "cached_probe": False,
            "host_notice": "",
        }

    mounted = int(aes1.get("mounted_paks", 0))
    total = int(aes1.get("total_paks", 0))
    missing = aes1.get("missing_guids", [])
    discovered_chars = probe1.get("characters") or []

    if mounted == 0 or (len(discovered_chars) == 0 and len(missing) > 0):
        if temp_normalized_json and temp_normalized_json.is_file():
            temp_normalized_json.unlink(missing_ok=True)
        if has_loaded_keys:
            return {
                "status": "FAIL",
                "code": "HOST_KEYS_INVALID",
                "client_version": client_ver,
                "key_files": local_key_files,
                "aes": aes1,
                "remote_refreshed": False,
                "error": f"Provided/local AES keys failed to mount client {client_ver} paks ({mounted}/{total} mounted, 0 characters).",
                "host_notice": (
                    f"{INVALID_KEY_NOTICE_ZH}"
                    f"（本机已加载本地密钥配置，但无法挂载当前《鸣潮》{client_ver} 资源包：仅挂载 {mounted}/{total} 个基础包，"
                    f"缺失 {len(missing)} 个加密包配置、检出角色 0 个，密钥可能无效或已随版本更新过期。）"
                ),
            }
        notice = (
            f"[需要宿主机提供本地密钥配置] 检测到本机 FModel 尚未配置《鸣潮》({client_ver}) 密钥"
            f"（当前仅挂载 {mounted}/{total} 个未加密基础包，缺失 {len(missing)} 个包配置），工作已暂停。"
            "本插件不提供也不代为联网搜索密钥；如尚未准备，可先临时关闭本插件并另开新会话执行，或手动寻找并准备好本地密钥文件。"
            "如本机已有现成密钥文件/压缩包/目录（支持 `.json`、`.zip`、`.txt` 或所在目录），直接传入 `--keys-file \"<本地路径>\" --consent-link-fmodel` 即可自动备份关联并使用。"
        )
        return {
            "status": "CONSENT_REQUIRED",
            "code": "HOST_KEYS_REQUIRED",
            "client_version": client_ver,
            "key_files": local_key_files,
            "aes": aes1,
            "remote_refreshed": False,
            "error": f"No local AES keys found ({mounted}/{total} paks mounted). Paused waiting for host-supplied local key path.",
            "host_notice": notice,
        }

    partial_notice = (
        f"[本地密钥覆盖不完整提示] 本机当前密钥已挂载 {mounted}/{total} 个 pak"
        f"（客户端版本 {client_ver}，缺失 {len(missing)} 个增量包 GUID）。"
        "若目标已实装角色位于新版本增量包而未检出，请更换适配当前版本的可用密钥并通过 `--keys-file \"<本地路径>\" --consent-link-fmodel` 更新本地 FModel 关联。"
    )
    return {
        "status": "WARN_PARTIAL",
        "client_version": client_ver,
        "key_files": local_key_files,
        "aes": aes1,
        "remote_refreshed": False,
        "host_notice": partial_notice,
    }
