"""Stage 1a Gate & Safe Local Key-Bundle Loader (BYOK — Zero Bundled Keys & Zero Remote Key Fetching).

Compliance & Security Invariants:
1. NEVER bundles keys and NEVER fetches keys from any remote URL.
2. Supports host-supplied local `.json` or `.zip` key packages (`load_user_key_bundle_file`):
   - `.zip` archives are inspected strictly IN MEMORY (`zipfile.ZipFile` read stream) — NEVER extracts
     `.exe`, `.bat`, `.cmd`, `.ps1`, `.dll`, symlinks, or arbitrary files to disk!
   - Strictly validates `0x` + 64-hex AES-256 keys and 32-hex GUIDs.
3. When local FModel is unlinked or lacks valid keys, pauses and reminds the host neutrally to provide
   their own local key file/package so the tool can link FModel locally (after timestamped `.bak` backup).
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
GUID_HEX_RE = re.compile(r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$")
_MAX_KEY_JSON_BYTES = 2 * 1024 * 1024
_MAX_KEY_ZIP_BYTES = 16 * 1024 * 1024


def _normalize_hex_key(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if HEX_KEY_RE.match(s):
        return "0x" + s[2:].upper()
    if RAW_64_HEX_RE.match(s):
        return "0x" + s.upper()
    return None


def _normalize_guid(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    s = raw.strip().strip("{}")
    if not GUID_HEX_RE.match(s):
        return None
    return s.replace("-", "").upper()


def validate_aes_key_bundle(payload: Any) -> Dict[str, Any]:
    """Validate and normalize `{mainKey, dynamicKeys:[{guid,key}]}` (or FModel PerDirectory/AesKeys) structure."""
    if not isinstance(payload, dict):
        return {"valid": False, "error": "Payload is not a JSON object"}

    candidates: List[Dict[str, Any]] = [payload]
    if isinstance(payload.get("AesKeys"), dict):
        candidates.append(payload["AesKeys"])
    if isinstance(payload.get("PerDirectory"), dict):
        for v in payload["PerDirectory"].values():
            if isinstance(v, dict) and isinstance(v.get("AesKeys"), dict):
                candidates.append(v["AesKeys"])

    norm_main: Optional[str] = None
    dyn_map: Dict[str, str] = {}

    for obj in candidates:
        mk = _normalize_hex_key(obj.get("mainKey") or obj.get("MainKey"))
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

    if not norm_main and not dyn_map:
        return {"valid": False, "error": "No valid 256-bit hex AES keys (mainKey / dynamicKeys) found in JSON"}

    normalized_bundle = {
        "mainKey": norm_main or ("0x" + "0" * 64),
        "dynamicKeys": [{"guid": g, "key": k} for g, k in sorted(dyn_map.items())],
    }
    return {
        "valid": True,
        "has_main_key": norm_main is not None,
        "dynamic_key_count": len(dyn_map),
        "total_keys": (1 if norm_main else 0) + len(dyn_map),
        "normalized": normalized_bundle,
    }


def load_user_key_bundle_file(bundle_path: str | Path) -> Dict[str, Any]:
    """Safely parse a host-provided `.json` or `.zip` key package IN MEMORY (never extracts binaries to disk)."""
    raw_str = str(bundle_path or "").strip()
    if not raw_str or "\x00" in raw_str:
        return {"ok": False, "error": "Empty or invalid key bundle path"}
    p = Path(raw_str)
    if not p.is_file():
        return {"ok": False, "error": f"Key file/package does not exist: {p}"}

    st_size = p.stat().st_size
    sfx = p.suffix.lower()

    if sfx == ".zip":
        if st_size > _MAX_KEY_ZIP_BYTES:
            return {"ok": False, "error": f"Zip archive exceeds {_MAX_KEY_ZIP_BYTES} bytes safety limit"}
        try:
            with zipfile.ZipFile(p, "r") as zf:
                json_infos = [
                    info
                    for info in zf.infolist()
                    if (not info.is_dir())
                    and info.filename.lower().endswith(".json")
                    and "\x00" not in info.filename
                    and ((info.external_attr >> 16) & 0o170000) != 0o120000
                ]
                if not json_infos:
                    return {
                        "ok": False,
                        "error": "No .json key file found inside the .zip package (executable/non-JSON members are ignored for safety)",
                    }
                # Prefer entries named keys.json first
                json_infos.sort(key=lambda i: (0 if Path(i.filename).name.lower() == "keys.json" else 1, len(i.filename)))
                last_err = "No valid AES key JSON inside archive"
                for info in json_infos:
                    if info.file_size > _MAX_KEY_JSON_BYTES:
                        last_err = f"{info.filename} exceeds {_MAX_KEY_JSON_BYTES} bytes limit"
                        continue
                    with zf.open(info, "r") as fp:
                        raw_bytes = fp.read(_MAX_KEY_JSON_BYTES + 1)
                    if len(raw_bytes) > _MAX_KEY_JSON_BYTES:
                        continue
                    try:
                        parsed = json.loads(io.BytesIO(raw_bytes).read().decode("utf-8-sig"))
                    except Exception as exc:
                        last_err = f"{info.filename}: invalid JSON ({exc})"
                        continue
                    val = validate_aes_key_bundle(parsed)
                    if val["valid"]:
                        return {
                            "ok": True,
                            "source_type": "zip_in_memory",
                            "source_path": str(p.resolve()),
                            "zip_member": info.filename,
                            **val,
                        }
                    last_err = f"{info.filename}: {val.get('error')}"
                return {"ok": False, "error": last_err}
        except zipfile.BadZipFile:
            return {"ok": False, "error": f"Corrupt or invalid .zip file: {p}"}
        except Exception as exc:
            return {"ok": False, "error": f"Failed reading .zip key package: {exc}"}

    if st_size > _MAX_KEY_JSON_BYTES:
        return {"ok": False, "error": f"Key JSON file exceeds {_MAX_KEY_JSON_BYTES} bytes safety limit"}
    try:
        parsed = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {"ok": False, "error": f"Invalid JSON in {p.name}: {exc}"}

    val = validate_aes_key_bundle(parsed)
    if not val["valid"]:
        return {"ok": False, "error": val.get("error", "Invalid key JSON structure")}
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
    """Mount paks strictly using local FModel config or host-supplied local `.json`/`.zip` key package; pause if missing."""
    ww = env_report["wuthering_waves"]
    ww_ext = env_report["ww_extract"]
    fmodel = env_report["fmodel"]

    if not ww.get("found"):
        return {"status": "FAIL", "error": "Wuthering Waves not found"}
    if not ww_ext.get("ok"):
        return {"status": "FAIL", "error": "ww-extract is not operational"}

    client_ver = ww.get("client_version", "unknown")
    game_dir = ww["game_root"]
    exe = ww_ext["executable"]
    native_dir = ww_ext.get("native_dir")

    local_key_files: List[str] = []
    temp_extracted_json: Optional[Path] = None

    if not ignore_fmodel_keys and fmodel.get("appsettings_path") and Path(fmodel["appsettings_path"]).is_file():
        local_key_files.append(str(Path(fmodel["appsettings_path"]).resolve()))

    if extra_keys_file:
        loaded = load_user_key_bundle_file(extra_keys_file)
        if not loaded.get("ok"):
            return {
                "status": "FAIL",
                "client_version": client_ver,
                "key_files": local_key_files,
                "error": loaded.get("error", "Invalid --keys-file"),
                "host_notice": f"[密钥文件校验未通过] {loaded.get('error')}。请确认提供的本地 .json 或 .zip 密钥文件包完整有效。",
            }
        if loaded["source_type"] == "zip_in_memory":
            # Write normalized JSON only to temporary runtime scratch inside work_dir and unlink immediately after probe/run
            temp_extracted_json = work_dir / "_transient_session_keys.json"
            temp_extracted_json.parent.mkdir(parents=True, exist_ok=True)
            temp_extracted_json.write_text(json.dumps(loaded["normalized"], indent=2), encoding="utf-8")
            local_key_files.append(str(temp_extracted_json.resolve()))
        else:
            local_key_files.append(loaded["source_path"])

    local_key_files = list(dict.fromkeys(local_key_files))

    probe_cache_file = work_dir / "aes_probe_cache.json"
    cur_fp = {
        "game_root": str(game_dir),
        "client_version": str(client_ver),
        "pak_total": int(ww.get("pak_counts", {}).get("total", 0)),
        "ignore_fmodel_keys": bool(ignore_fmodel_keys),
        "keys_fp": _key_files_fingerprint(local_key_files) if temp_extracted_json is None else ["transient_zip"],
    }
    if temp_extracted_json is None and probe_cache_file.is_file():
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
        if temp_extracted_json and temp_extracted_json.is_file():
            temp_extracted_json.unlink(missing_ok=True)
        return {
            "status": "FAIL",
            "stage": "initial_probe",
            "error": probe1.get("error", "probe-paks failed"),
            "probe": probe1,
        }

    aes1 = probe1.get("aes", {})
    _write_character_catalog_cache(work_dir, ww, aes1, probe1.get("characters"))
    if aes1.get("status") == "FULL":
        if temp_extracted_json is None:
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
        if temp_extracted_json and temp_extracted_json.is_file():
            temp_extracted_json.unlink(missing_ok=True)
        notice = (
            f"[需要宿主机提供本地密钥配置] 检测到本机 FModel 尚未关联《鸣潮》({client_ver}) 有效密钥或现有密钥已过期"
            f"（当前仅挂载 {mounted}/{total} 个未加密基础包，缺失 {len(missing)} 个包配置，可用角色 0 个），工作已暂停。"
            "本开源工具不内置亦不联网获取任何密钥；请提供你本地自备的密钥文件或压缩包路径（支持 `.json` 或含 `keys.json` 的 `.zip`），"
            "并通过 `--keys-file \"<本地路径>\" --consent-link-fmodel` 授权，程序将在自动备份原 `AppSettings.json` 后为你完成本地 FModel 关联。"
        )
        return {
            "status": "CONSENT_REQUIRED",
            "code": "HOST_KEYS_REQUIRED",
            "client_version": client_ver,
            "key_files": local_key_files,
            "aes": aes1,
            "remote_refreshed": False,
            "error": f"Local FModel AES keys missing or expired ({mounted}/{total} paks mounted). Paused waiting for host-supplied local key file/package.",
            "host_notice": notice,
        }

    partial_notice = (
        f"[本地密钥覆盖不完整提示] 宿主机当前本地密钥已挂载 {mounted}/{total} 个 pak"
        f"（客户端版本 {client_ver}，缺失 {len(missing)} 个增量包 GUID）。"
        "本开源工具不联网获取密钥；若目标已实装角色位于新版本增量包导致未能检出，"
        "请提供更新后的本地密钥文件包并通过 `--keys-file \"<本地路径>\" --consent-link-fmodel` 更新本地 FModel 关联。"
    )
    return {
        "status": "WARN_PARTIAL",
        "client_version": client_ver,
        "key_files": local_key_files,
        "aes": aes1,
        "remote_refreshed": False,
        "host_notice": partial_notice,
    }
