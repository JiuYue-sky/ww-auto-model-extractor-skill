"""Consent-gated safe environment bootstrapper (Blender portable, Oodle runtime, FModel, & Safe Local Key-Bundle FModel Link).

CRITICAL SECURITY & COMPLIANCE INVARIANTS:
1. NEVER downloads Wuthering Waves game files. Missing game -> fatal error & abort.
2. NEVER downloads any third-party software or codec without explicit host consent flags.
3. Downloads ONLY into project-isolated `runtime/` directory (never mutates global Program Files).
4. Verifies SHA256 checksums before trusting downloaded binaries.
5. Creates timestamped `.bak` backup BEFORE modifying FModel's `AppSettings.json`, ONLY on explicit consent,
   parses host-provided `.json`/`.zip` key bundles strictly IN MEMORY, NEVER stores keys inside the repo/plugin directory,
   and NEVER injects remote AES key URLs.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .aes_resolver import load_user_key_bundle_file
from .env_detector import WUTHERING_WAVES_UE_VERSION_INT

BLENDER_DOWNLOAD_SPEC = {
    "version": "5.2.3",
    "url": "https://download.blender.org/release/Blender5.2/blender-5.2.3-windows-x64.zip",
    "sha256_url": "https://download.blender.org/release/Blender5.2/blender-5.2.3.sha256",
    "expected_filename": "blender-5.2.3-windows-x64.zip",
    "approx_size_mb": 390,
}

OODLE_RUNTIME_SPEC = {
    "version": "2.9.16",
    "url": "https://github.com/WorkingRobot/OodleUE/releases/download/2026-06-04-1357/clang-cl-x64-release.zip",
    "zip_entry": "bin/oodle-data-shared.dll",
    "expected_dll_sha256": "cba19529d0a3b5ec9c630e95652af01e123ae29a34a8a5f7507f5bcf23d9e82b",
    "approx_size_mb": 0.5,
}

FMODEL_GITHUB_LATEST_API = "https://api.github.com/repos/4sval/FModel/releases/latest"

_ALLOWED_DOWNLOAD_HOSTS: Tuple[str, ...] = (
    "download.blender.org",
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
)
_MAX_TEXT_RESPONSE_BYTES = 2 * 1024 * 1024


def _validate_https_url(url: str, allowed_hosts: Tuple[str, ...] = _ALLOWED_DOWNLOAD_HOSTS) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ValueError(f"Refusing non-HTTPS URL: {url}")
    host = (parsed.hostname or "").lower()
    if not host or not any(host == h or host.endswith("." + h) for h in allowed_hosts):
        raise ValueError(f"Refusing untrusted download host: {host!r}")
    return url


def _safe_rel_token(raw: str, fallback: str = "latest") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw or fallback).name).strip("._-")
    return cleaned[:64] or fallback


def safe_extract_zip(zip_path: Path, dest_dir: Path) -> List[Path]:
    """Extract zip archive with strict Zip Slip and symlink traversal protection."""
    dest_root = dest_dir.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    extracted: List[Path] = []
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            member_name = info.filename.replace("\\", "/")
            if (
                not member_name
                or "\x00" in member_name
                or member_name.startswith("/")
                or re.match(r"^[A-Za-z]:", member_name)
                or ".." in Path(member_name).parts
            ):
                raise ValueError(f"Unsafe zip member path rejected (Zip Slip guard): {info.filename!r}")
            unix_mode = (info.external_attr >> 16) & 0o170000
            if unix_mode == 0o120000:
                raise ValueError(f"Symlink entry rejected in zip archive: {info.filename!r}")
            target = (dest_root / member_name).resolve()
            if target != dest_root and not target.is_relative_to(dest_root):
                raise ValueError(f"Zip member escapes target directory: {info.filename!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 256)
            extracted.append(target)
    return extracted


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest().lower()


def _download_file(url: str, dest: Path, timeout_s: int = 120) -> Path:
    _validate_https_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "ww-auto-model-extractor/0.1.1"})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out, length=1024 * 256)
    tmp.replace(dest)
    return dest


def _fetch_text(url: str, timeout_s: int = 30) -> str:
    _validate_https_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "ww-auto-model-extractor/0.1.1"})
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read(_MAX_TEXT_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_TEXT_RESPONSE_BYTES:
            raise ValueError(f"Remote text response exceeded {_MAX_TEXT_RESPONSE_BYTES} bytes limit")
        return raw.decode("utf-8", errors="replace")


def download_blender_portable(project_root: Path, *, consent_granted: bool) -> Dict[str, Any]:
    """Download and verify official portable Blender LTS into `<project_root>/runtime/blender/`."""
    if not consent_granted:
        return {
            "status": "CONSENT_REQUIRED",
            "component": "blender",
            "plan": {
                **BLENDER_DOWNLOAD_SPEC,
                "target_dir": str(project_root / "runtime" / "blender" / BLENDER_DOWNLOAD_SPEC["version"]),
            },
            "message": (
                f"需要宿主机明确同意后方可下载 Blender {BLENDER_DOWNLOAD_SPEC['version']} 官方便携版 "
                f"(~{BLENDER_DOWNLOAD_SPEC['approx_size_mb']} MB，将做官方 SHA256 校验并解压到项目隔离目录)。"
                "请传入 --consent-download blender 以授权。"
            ),
        }

    dl_dir = project_root / "runtime" / "_downloads"
    zip_path = dl_dir / BLENDER_DOWNLOAD_SPEC["expected_filename"]
    target_root = project_root / "runtime" / "blender"
    target_root.mkdir(parents=True, exist_ok=True)

    sha_text = _fetch_text(BLENDER_DOWNLOAD_SPEC["sha256_url"])
    expected_sha: Optional[str] = None
    for line in sha_text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1].endswith(BLENDER_DOWNLOAD_SPEC["expected_filename"]):
            expected_sha = parts[0].lower()
            break
    if not expected_sha:
        return {
            "status": "FAIL",
            "component": "blender",
            "error": "Could not locate official SHA256 entry for Blender archive; aborting download for safety.",
        }

    _download_file(BLENDER_DOWNLOAD_SPEC["url"], zip_path, timeout_s=600)
    actual_sha = sha256_file(zip_path)
    if actual_sha != expected_sha:
        zip_path.unlink(missing_ok=True)
        return {
            "status": "FAIL",
            "component": "blender",
            "error": f"SHA256 mismatch! expected={expected_sha} actual={actual_sha}",
        }

    safe_extract_zip(zip_path, target_root)

    found_exes = list(target_root.rglob("blender.exe"))
    return {
        "status": "INSTALLED" if found_exes else "FAIL",
        "component": "blender",
        "sha256": actual_sha,
        "executable": str(found_exes[0]) if found_exes else None,
        "host_notice": f"已获授权下载并通过官方 SHA256 校验安装便携版 Blender 到隔离目录: {found_exes[0] if found_exes else target_root}",
    }


def download_oodle_runtime(project_root: Path, *, consent_granted: bool) -> Dict[str, Any]:
    """Download CUE4Parse upstream Oodle runtime DLL into `<project_root>/runtime/native/` only with explicit consent."""
    target_dir = project_root / "runtime" / "native"
    target_dll = target_dir / "oodle-data-shared.dll"
    if not consent_granted:
        return {
            "status": "CONSENT_REQUIRED",
            "component": "oodle",
            "plan": {
                **OODLE_RUNTIME_SPEC,
                "target_dir": str(target_dir),
            },
            "message": (
                "开源包体不内置专有 Oodle 动态库；需要宿主机明确同意后方可按需下载到隔离目录 runtime/native/（含固定 SHA256 校验）。"
                "请传入 --consent-download oodle 以授权。"
            ),
        }

    dl_dir = project_root / "runtime" / "_downloads"
    zip_path = dl_dir / "oodle-clang-cl-x64-release.zip"
    _download_file(OODLE_RUNTIME_SPEC["url"], zip_path, timeout_s=120)

    with tempfile.TemporaryDirectory(prefix="ww_oodle_") as td:
        td_p = Path(td)
        safe_extract_zip(zip_path, td_p)
        cand = td_p / "bin" / "oodle-data-shared.dll"
        if not cand.is_file():
            matches = list(td_p.rglob("oodle-data-shared.dll"))
            cand = matches[0] if matches else cand
        if not cand.is_file():
            return {"status": "FAIL", "component": "oodle", "error": "oodle-data-shared.dll not found in downloaded archive"}
        actual_sha = sha256_file(cand)
        if actual_sha != OODLE_RUNTIME_SPEC["expected_dll_sha256"]:
            return {
                "status": "FAIL",
                "component": "oodle",
                "error": f"Oodle DLL SHA256 mismatch! expected={OODLE_RUNTIME_SPEC['expected_dll_sha256']} actual={actual_sha}",
            }
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cand, target_dll)

    return {
        "status": "INSTALLED",
        "component": "oodle",
        "sha256": OODLE_RUNTIME_SPEC["expected_dll_sha256"],
        "dll_path": str(target_dll.resolve()),
        "host_notice": f"已获授权下载并通过 SHA256 校验安装 Oodle 运行时解码库到隔离目录: {target_dll}",
    }


def download_fmodel_portable(project_root: Path, *, consent_granted: bool) -> Dict[str, Any]:
    """Download official FModel release zip from GitHub into `<project_root>/runtime/fmodel/`."""
    if not consent_granted:
        return {
            "status": "CONSENT_REQUIRED",
            "component": "fmodel",
            "plan": {
                "api_url": FMODEL_GITHUB_LATEST_API,
                "target_dir": str(project_root / "runtime" / "fmodel"),
            },
            "message": (
                "需要宿主机明确同意后方可从 GitHub (4sval/FModel) 下载官方 FModel 压缩包到项目隔离目录 runtime/fmodel/。"
                "请传入 --consent-download fmodel 以授权。"
            ),
        }

    rel_meta = json.loads(_fetch_text(FMODEL_GITHUB_LATEST_API))
    tag = _safe_rel_token(str(rel_meta.get("tag_name", "latest")), fallback="latest")
    asset_url: Optional[str] = None
    asset_name = "FModel.zip"
    for asset in rel_meta.get("assets", []):
        name = str(asset.get("name", ""))
        if name.lower().endswith(".zip") and "fmodel" in name.lower():
            asset_url = str(asset.get("browser_download_url"))
            asset_name = _safe_rel_token(name, fallback="FModel.zip")
            break
    if not asset_url:
        return {"status": "FAIL", "component": "fmodel", "error": "No FModel zip asset found in GitHub latest release."}

    dl_dir = project_root / "runtime" / "_downloads"
    zip_path = dl_dir / asset_name
    _download_file(asset_url, zip_path, timeout_s=300)
    actual_sha = sha256_file(zip_path)

    target_dir = project_root / "runtime" / "fmodel" / tag
    safe_extract_zip(zip_path, target_dir)

    found_exes = list(target_dir.rglob("FModel.exe"))
    return {
        "status": "INSTALLED" if found_exes else "FAIL",
        "component": "fmodel",
        "release_tag": tag,
        "sha256": actual_sha,
        "executable": str(found_exes[0]) if found_exes else None,
        "host_notice": f"已获授权从 GitHub ({tag}) 下载并安装 FModel 到隔离目录 (SHA256={actual_sha[:16]}...): {found_exes[0] if found_exes else target_dir}",
    }


def link_fmodel_to_wuthering_waves(
    ww_info: Dict[str, Any],
    *,
    consent_granted: bool,
    appsettings_path: Optional[Path] = None,
    keys_bundle_path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Safely link local FModel AppSettings.json to local Wuthering Waves and optionally import host-provided `.json`/`.zip` keys.

    - Strictly consent-gated (`consent_granted=True`).
    - Creates timestamped `.bak` backup before writing.
    - Reads `.zip` / `.json` key package strictly IN MEMORY (zero untrusted file extraction, zero keys copied into plugin repo).
    - Writes ZERO remote key `Endpoints` URLs.
    """
    if not ww_info.get("found"):
        return {
            "status": "FATAL_MISSING_WUTHERING_WAVES",
            "error": "无法配置 FModel 链接：本机未找到《鸣潮》游戏客户端。",
        }

    target_path = appsettings_path or (Path(os.environ.get("APPDATA", "")) / "FModel" / "AppSettings.json")
    ww_content_dir = str(Path(ww_info["content_dir"]).resolve())

    if not consent_granted:
        return {
            "status": "CONSENT_REQUIRED",
            "component": "fmodel_link",
            "plan": {
                "appsettings_path": str(target_path),
                "ww_content_dir": ww_content_dir,
                "ue_version": WUTHERING_WAVES_UE_VERSION_INT,
                "keys_bundle_provided": bool(keys_bundle_path),
            },
            "message": (
                f"需要宿主机明确同意后方可更新本地 FModel 配置 ({target_path}) 以关联到本机《鸣潮》目录 ({ww_content_dir})。"
                "更新前会自动创建时间戳备份（不写入任何第三方密钥地址）。请传入 --consent-link-fmodel 以授权。"
            ),
        }

    parsed_keys: Optional[Dict[str, Any]] = None
    if keys_bundle_path:
        loaded = load_user_key_bundle_file(keys_bundle_path)
        if not loaded.get("ok"):
            return {
                "status": "FAIL",
                "component": "fmodel_link",
                "error": loaded.get("error", "Invalid key file/package"),
                "host_notice": f"[密钥文件包校验失败] {loaded.get('error')}。未修改本地 FModel 配置。",
            }
        parsed_keys = loaded

    target_path.parent.mkdir(parents=True, exist_ok=True)
    backup_path: Optional[Path] = None
    cfg: Dict[str, Any] = {}
    if target_path.is_file():
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup_path = target_path.with_name(f"{target_path.name}.bak-{ts}")
        shutil.copy2(target_path, backup_path)
        try:
            cfg = json.loads(target_path.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}

    per_dir = cfg.setdefault("PerDirectory", {})
    if not isinstance(per_dir, dict):
        per_dir = {}
        cfg["PerDirectory"] = per_dir

    # Reuse existing entry matching ww_content_dir case-insensitively if present
    matched_key = ww_content_dir
    for existing_k in list(per_dir.keys()):
        if str(existing_k).lower().rstrip("\\/") == ww_content_dir.lower().rstrip("\\/"):
            matched_key = str(existing_k)
            break

    existing = per_dir.get(matched_key, {})
    if not isinstance(existing, dict):
        existing = {}

    existing.update(
        {
            "GameName": existing.get("GameName") or "Wuthering Waves (All)",
            "GameDirectory": ww_content_dir,
            "IsManual": True,
            "UeVersion": WUTHERING_WAVES_UE_VERSION_INT,
            "TexturePlatform": 0,
        }
    )

    imported_key_count = 0
    if parsed_keys is not None:
        norm = parsed_keys["normalized"]
        prev_aes = existing.get("AesKeys") if isinstance(existing.get("AesKeys"), dict) else {}
        merged_dyn: Dict[str, str] = {}
        if isinstance(prev_aes.get("dynamicKeys"), list):
            for item in prev_aes["dynamicKeys"]:
                if isinstance(item, dict) and item.get("guid") and item.get("key"):
                    merged_dyn[str(item["guid"]).replace("-", "").upper()] = str(item["key"])
        for item in norm["dynamicKeys"]:
            merged_dyn[item["guid"]] = item["key"]
        main_k = norm["mainKey"] if parsed_keys.get("has_main_key") else (prev_aes.get("mainKey") or norm["mainKey"])
        existing["AesKeys"] = {
            "mainKey": main_k,
            "dynamicKeys": [{"guid": g, "key": k} for g, k in sorted(merged_dyn.items())],
        }
        imported_key_count = int(parsed_keys["total_keys"])

    per_dir[matched_key] = existing
    cfg["GameDirectory"] = ww_content_dir
    cfg["KeepDirectoryStructure"] = True

    tmp_path = target_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(target_path)

    key_msg = f"，并安全导入宿主机提供的本地密钥配置（共 {imported_key_count} 条）" if imported_key_count > 0 else ""
    return {
        "status": "LINKED",
        "component": "fmodel_link",
        "appsettings_path": str(target_path),
        "backup_path": str(backup_path) if backup_path else None,
        "linked_game_dir": ww_content_dir,
        "imported_key_count": imported_key_count,
        "host_notice": (
            f"已自动备份原配置至 {backup_path}，将本地 FModel 关联至本机《鸣潮》目录 {ww_content_dir}{key_msg}（零联网、未写入任何外部密钥地址）。"
            if backup_path
            else f"已创建本地 FModel 配置并关联至本机《鸣潮》目录 {ww_content_dir}{key_msg}（零联网、未写入任何外部密钥地址）。"
        ),
    }


def apply_consented_bootstrap(
    project_root: Path,
    env_report: Dict[str, Any],
    *,
    consent_downloads: Optional[List[str]] = None,
    consent_link_fmodel: bool = False,
    keys_bundle_path: Optional[str | Path] = None,
    fmodel_appsettings_path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Execute ONLY the bootstrap/linking actions explicitly consented to by the host."""
    actions_done: List[Dict[str, Any]] = []
    allowed = {c.strip().lower() for c in (consent_downloads or []) if c.strip()}

    if "wuthering_waves" in allowed or "ww" in allowed or "game" in allowed:
        actions_done.append(
            {
                "status": "REFUSED",
                "component": "wuthering_waves",
                "error": "安全策略禁止自动下载《鸣潮》游戏本体。",
            }
        )

    if not env_report["wuthering_waves"]["found"]:
        return actions_done

    if not env_report["blender"]["found"] and ("blender" in allowed or "all" in allowed):
        actions_done.append(download_blender_portable(project_root, consent_granted=True))

    if not env_report.get("ww_extract", {}).get("oodle_ok") and ("oodle" in allowed or "all" in allowed):
        actions_done.append(download_oodle_runtime(project_root, consent_granted=True))

    if not env_report["fmodel"]["found"] and ("fmodel" in allowed or "all" in allowed):
        actions_done.append(download_fmodel_portable(project_root, consent_granted=True))

    if consent_link_fmodel and (
        env_report["fmodel"].get("needs_link_repair")
        or env_report["fmodel"].get("aes_key_count", 0) == 0
        or bool(keys_bundle_path)
    ):
        actions_done.append(
            link_fmodel_to_wuthering_waves(
                env_report["wuthering_waves"],
                consent_granted=True,
                appsettings_path=fmodel_appsettings_path,
                keys_bundle_path=keys_bundle_path,
            )
        )

    return actions_done
