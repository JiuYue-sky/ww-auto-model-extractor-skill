"""Stage 0 Environment Detector: Wuthering Waves (Hard Gate), Blender, FModel & Link, ww-extract, Addons.

Note: Unreal Engine is explicitly NOT a required dependency (handled by a separate downstream handoff plugin).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import string
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .watchdog import run_watched

WUTHERING_WAVES_UE_VERSION_INT = 68812811  # EGame.GAME_WutheringWaves


def _read_registry_value(root_name: str, subkey: str, value_name: str) -> Optional[str]:
    if os.name != "nt":
        return None
    try:
        import winreg

        root_map = {
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKCU": winreg.HKEY_CURRENT_USER,
        }
        root = root_map.get(root_name)
        if root is None:
            return None
        with winreg.OpenKey(root, subkey) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return str(val) if val else None
    except OSError:
        return None


def _normalize_ww_game_root(candidate: Path) -> Optional[Path]:
    """Given any path inside or around Wuthering Waves, return the `Wuthering Waves Game` root (contains Client/Content/Paks)."""
    if not candidate or not candidate.exists():
        return None
    checks = [
        candidate,
        candidate / "Wuthering Waves Game",
        candidate.parent,
        candidate.parent.parent,
        candidate.parent.parent.parent,
    ]
    for c in checks:
        if (c / "Client" / "Content" / "Paks").is_dir():
            paks = list((c / "Client" / "Content" / "Paks").glob("*.pak"))
            if paks:
                return c.resolve()
    return None


def _read_fmodel_appsettings(appsettings_path: Optional[Path] = None) -> Tuple[Optional[Path], Optional[Dict[str, Any]]]:
    candidates: List[Path] = []
    if appsettings_path:
        candidates.append(appsettings_path)
    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "FModel" / "AppSettings.json")
    for p in candidates:
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    return (p, data)
            except Exception:
                return (p, None)
    return (None, None)


def _scan_uninstall_registry_by_name(name_tokens: Tuple[str, ...]) -> List[Tuple[str, Path]]:
    """Dynamically enumerate Windows Uninstall registry keys matching any token in DisplayName."""
    results: List[Tuple[str, Path]] = []
    if os.name != "nt":
        return results
    try:
        import winreg
    except ImportError:
        return results

    roots = [
        ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ("HKCU", winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    for root_label, root_key, base_subkey in roots:
        try:
            with winreg.OpenKey(root_key, base_subkey) as parent:
                sub_cnt = winreg.QueryInfoKey(parent)[0]
                for i in range(sub_cnt):
                    try:
                        sub_name = winreg.EnumKey(parent, i)
                        with winreg.OpenKey(parent, sub_name) as item:
                            try:
                                disp, _ = winreg.QueryValueEx(item, "DisplayName")
                            except OSError:
                                disp = sub_name
                            disp_low = str(disp or "").lower()
                            if not any(tok in disp_low for tok in name_tokens):
                                continue
                            for vname in ("InstallLocation", "InstallPath", "LauncherPath", "DisplayIcon"):
                                try:
                                    val, _ = winreg.QueryValueEx(item, vname)
                                except OSError:
                                    continue
                                if not val:
                                    continue
                                cleaned = str(val).strip().strip('"').split(",")[0].strip()
                                if cleaned:
                                    p = Path(cleaned)
                                    results.append((f"registry_uninstall:{root_label}", p.parent if p.suffix.lower() == ".exe" else p))
                    except OSError:
                        continue
        except OSError:
            continue
    return results


def _find_steam_library_roots() -> List[Path]:
    """Discover Steam library roots from registry + libraryfolders.vdf for cross-host Steam installs."""
    libs: List[Path] = []
    if os.name != "nt":
        return libs
    steam_roots: List[Path] = []
    for rr, sk, vn in [
        ("HKCU", r"Software\Valve\Steam", "SteamPath"),
        ("HKLM", r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        ("HKLM", r"SOFTWARE\Valve\Steam", "InstallPath"),
    ]:
        v = _read_registry_value(rr, sk, vn)
        if v:
            p = Path(v)
            if p.is_dir():
                steam_roots.append(p)
    for drive in string.ascii_uppercase:
        for rel in ("Program Files (x86)\\Steam", "Program Files\\Steam", "Steam", "SteamLibrary"):
            p = Path(f"{drive}:\\{rel}")
            if p.is_dir():
                steam_roots.append(p)

    seen: set[str] = set()
    for sr in steam_roots:
        k = str(sr).lower()
        if k not in seen:
            seen.add(k)
            libs.append(sr)
        vdf = sr / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                txt = vdf.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r'"path"\s+"([^"]+)"', txt):
                    lp = Path(m.group(1).replace("\\\\", "\\"))
                    lk = str(lp).lower()
                    if lp.is_dir() and lk not in seen:
                        seen.add(lk)
                        libs.append(lp)
            except Exception:
                pass
    return libs


def _bounded_find_files(root: Path, filename: str, max_depth: int = 2) -> List[Path]:
    """Fast depth-bounded file search (never stalls on huge Downloads/Desktop directories on foreign hosts)."""
    found: List[Path] = []
    if not root.is_dir():
        return found
    fn_low = filename.lower()
    queue: List[Tuple[Path, int]] = [(root, 0)]
    while queue:
        cur, depth = queue.pop(0)
        try:
            for entry in cur.iterdir():
                if entry.is_file() and entry.name.lower() == fn_low:
                    found.append(entry)
                elif entry.is_dir() and depth < max_depth:
                    queue.append((entry, depth + 1))
        except OSError:
            continue
    return sorted(found, reverse=True)


def detect_wuthering_waves(override_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    """Detect local Wuthering Waves installation across CN/Global/Steam/Epic/WeGame. NEVER downloads the game if missing."""
    candidates: List[Tuple[str, Path]] = []

    if override_dir:
        candidates.append(("cli_override", Path(override_dir)))
    else:
        for reg_root, subkey in [
            ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\KRInstall Wuthering Waves"),
            ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\KRInstall Wuthering Waves"),
            ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\KRInstall Wuthering Waves"),
            ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\KRInstall Wuthering Waves Global"),
        ]:
            for val_name in ("InstallPath", "LauncherPath", "InstallLocation"):
                v = _read_registry_value(reg_root, subkey, val_name)
                if v:
                    candidates.append((f"registry:{reg_root}", Path(v)))
        candidates.extend(_scan_uninstall_registry_by_name(("wuthering waves", "鸣潮")))

        _, fmodel_cfg = _read_fmodel_appsettings()
        if fmodel_cfg:
            gd = fmodel_cfg.get("GameDirectory")
            if isinstance(gd, str) and gd:
                candidates.append(("fmodel_appsettings", Path(gd)))
            per_dir = fmodel_cfg.get("PerDirectory")
            if isinstance(per_dir, dict):
                for k in per_dir.keys():
                    candidates.append(("fmodel_perdir", Path(k)))

        for slib in _find_steam_library_roots():
            for sname in ("Wuthering Waves", "Wuthering Waves Game"):
                sp = slib / "steamapps" / "common" / sname
                if sp.exists():
                    candidates.append(("steam_library", sp))

        if os.name == "nt":
            for drive in string.ascii_uppercase:
                root = Path(f"{drive}:\\")
                if not root.exists():
                    continue
                for rel in (
                    "鸣潮\\Wuthering Waves",
                    "鸣潮",
                    "Wuthering Waves",
                    "Games\\Wuthering Waves",
                    "Games\\鸣潮",
                    "Game\\Wuthering Waves",
                    "Program Files\\Wuthering Waves",
                    "Program Files\\Epic Games\\WutheringWavesj3oWh",
                    "Epic Games\\WutheringWavesj3oWh",
                    "WeGameApps\\rail_apps\\Wuthering Waves",
                ):
                    p = root / rel
                    if p.exists():
                        candidates.append((f"scan:{drive}:", p))

    found_root: Optional[Path] = None
    found_source = ""
    for src, cand in candidates:
        norm = _normalize_ww_game_root(cand)
        if norm is not None:
            found_root = norm
            found_source = src
            break

    if found_root is None:
        return {
            "found": False,
            "fatal": True,
            "code": "FATAL_MISSING_WUTHERING_WAVES",
            "auto_download_allowed": False,
            "message": (
                "未在本机检测到《鸣潮》游戏客户端（缺少 Client/Content/Paks/*.pak）。"
                "按安全规范本工具严禁自动下载游戏本体，任务已终止。请安装官方正式服《鸣潮》或通过 --game-dir 指定目录。"
            ),
            "checked_sources": [f"{s}:{p}" for s, p in candidates[:12]],
        }

    client_dir = found_root / "Client"
    paks_dir = client_dir / "Content" / "Paks"
    hd_dir = client_dir / "Content" / "HD"
    uhd_dir = client_dir / "Content" / "UHD"
    saved_res_dir = client_dir / "Saved" / "Resources"

    base_paks = list(paks_dir.glob("*.pak"))
    hd_paks = list(hd_dir.glob("*.pak")) if hd_dir.is_dir() else []
    uhd_paks = list(uhd_dir.glob("*.pak")) if uhd_dir.is_dir() else []
    saved_paks = list(saved_res_dir.rglob("*.pak")) if saved_res_dir.is_dir() else []

    launcher_ver = _read_registry_value(
        "HKLM",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\KRInstall Wuthering Waves",
        "DisplayVersion",
    )
    resource_versions: Dict[str, Any] = {}
    dl_cfg_path = found_root / "launcherDownloadConfig.json"
    if dl_cfg_path.is_file():
        try:
            dl_cfg = json.loads(dl_cfg_path.read_text(encoding="utf-8-sig"))
            resource_versions["base"] = dl_cfg.get("version")
            bundles = dl_cfg.get("bundles", {})
            if isinstance(bundles, dict):
                for bname, binfo in bundles.items():
                    if isinstance(binfo, dict) and binfo.get("version"):
                        resource_versions[bname.lower()] = binfo.get("version")
        except Exception:
            pass

    saved_ver_dirs: List[str] = []
    if saved_res_dir.is_dir():
        for d in sorted(saved_res_dir.iterdir()):
            if d.is_dir() and re.match(r"^\d+\.\d+", d.name):
                saved_ver_dirs.append(d.name)
    if saved_ver_dirs:
        resource_versions["saved_hotfix_dirs"] = saved_ver_dirs

    effective_client_ver = (
        (saved_ver_dirs[-1] if saved_ver_dirs else None)
        or resource_versions.get("uhd")
        or resource_versions.get("hd")
        or resource_versions.get("base")
        or launcher_ver
        or "unknown"
    )

    return {
        "found": True,
        "fatal": False,
        "source": found_source,
        "game_root": str(found_root),
        "client_dir": str(client_dir),
        "content_dir": str(client_dir / "Content"),
        "paks_dir": str(paks_dir),
        "launcher_version": launcher_ver,
        "client_version": effective_client_ver,
        "resource_versions": resource_versions,
        "pak_counts": {
            "base": len(base_paks),
            "hd": len(hd_paks),
            "uhd": len(uhd_paks),
            "saved_hotfix": len(saved_paks),
            "total": len(base_paks) + len(hd_paks) + len(uhd_paks) + len(saved_paks),
        },
    }


def _parse_blender_version(stdout: str) -> Tuple[Optional[str], Optional[Tuple[int, int, int]]]:
    m = re.search(r"Blender\s+(\d+)\.(\d+)\.(\d+)", stdout)
    if m:
        tup = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return (f"{tup[0]}.{tup[1]}.{tup[2]}", tup)
    m2 = re.search(r"Blender\s+(\d+)\.(\d+)", stdout)
    if m2:
        tup = (int(m2.group(1)), int(m2.group(2)), 0)
        return (f"{tup[0]}.{tup[1]}.0", tup)
    return (None, None)


def _find_blender_embedded_python(blender_exe: Path, ver_tuple: Optional[Tuple[int, int, int]]) -> Optional[Path]:
    base = blender_exe.parent
    if ver_tuple:
        mm = f"{ver_tuple[0]}.{ver_tuple[1]}"
        cand = base / mm / "python" / "bin" / ("python.exe" if os.name == "nt" else "python3")
        if cand.is_file():
            return cand
    for cand in base.glob("*/python/bin/python*"):
        if cand.is_file() and cand.name.lower() in ("python.exe", "python", "python3"):
            return cand
    return None


def detect_blender(
    override_path: Optional[str | Path] = None,
    project_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Locate Blender 3.6+ / 4.x / 5.x executable and inspect its embedded Python capabilities."""
    candidates: List[Tuple[str, Path]] = []

    if override_path:
        p = Path(override_path)
        if p.is_dir():
            p = p / ("blender.exe" if os.name == "nt" else "blender")
        candidates.append(("cli_override", p))
    else:
        if project_root:
            rt_dir = project_root / "runtime" / "blender"
            if rt_dir.is_dir():
                for exe in sorted(rt_dir.rglob("blender.exe" if os.name == "nt" else "blender"), reverse=True):
                    candidates.append(("project_runtime", exe))

        which_b = shutil.which("blender")
        if which_b:
            candidates.append(("PATH", Path(which_b)))

        if os.name == "nt":
            for reg_root, subkey in [
                ("HKCU", r"Software\Classes\Blender.Project\shell\open\command"),
                ("HKLM", r"Software\Classes\Blender.Project\shell\open\command"),
                ("HKCU", r"Software\Classes\blendfile\shell\open\command"),
                ("HKLM", r"Software\Classes\blendfile\shell\open\command"),
            ]:
                cmd = _read_registry_value(reg_root, subkey, "")
                if cmd:
                    m = re.search(r'"([^"]*blender(?:-launcher)?\.exe)"', cmd, re.IGNORECASE)
                    if m:
                        exe = Path(m.group(1))
                        if exe.name.lower() == "blender-launcher.exe" and (exe.parent / "blender.exe").is_file():
                            exe = exe.parent / "blender.exe"
                        candidates.append((f"registry:{reg_root}", exe))

            for src, base_dir in _scan_uninstall_registry_by_name(("blender",)):
                for exe in _bounded_find_files(base_dir, "blender.exe", max_depth=1):
                    candidates.append((src, exe))

            for slib in _find_steam_library_roots():
                sbl = slib / "steamapps" / "common" / "Blender" / "blender.exe"
                if sbl.is_file():
                    candidates.append(("steam_library", sbl))

            scan_roots: List[Path] = []
            local_app = os.environ.get("LOCALAPPDATA")
            if local_app:
                scan_roots.append(Path(local_app) / "Programs" / "Blender Foundation")
            for drive in string.ascii_uppercase:
                droot = Path(f"{drive}:\\")
                if not droot.exists():
                    continue
                for rel in ("Program Files\\Blender Foundation", "Blender Foundation", "Apps\\Blender", "Blender"):
                    sr = droot / rel
                    if sr.is_dir():
                        scan_roots.append(sr)
            for sr in scan_roots:
                for exe in _bounded_find_files(sr, "blender.exe", max_depth=2):
                    candidates.append((f"scan:{sr}", exe))

    seen: set[str] = set()
    for src, exe in candidates:
        if not exe.is_file():
            continue
        key = str(exe.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)

        res = run_watched([str(exe), "--version"], hard_timeout_s=20, io_idle_timeout_s=15, max_retries=1, label="blender-ver")
        ver_str, ver_tup = _parse_blender_version(res.stdout + "\n" + res.stderr)
        if not ver_str or not ver_tup:
            continue

        emb_py = _find_blender_embedded_python(exe, ver_tup)
        emb_libs: Dict[str, bool] = {}
        if emb_py:
            probe_code = (
                "import json; out={}; "
                "\nfor m in ('numpy','OpenImageIO','PIL','zstandard','requests'):\n"
                "  try: __import__(m); out[m]=True\n"
                "  except Exception: out[m]=False\n"
                "print(json.dumps(out))"
            )
            py_res = run_watched([str(emb_py), "-c", probe_code], hard_timeout_s=20, io_idle_timeout_s=15, max_retries=1, label="blender-py")
            if py_res.ok:
                try:
                    emb_libs = json.loads(py_res.stdout.strip().splitlines()[-1])
                except Exception:
                    emb_libs = {}

        return {
            "found": True,
            "source": src,
            "executable": str(exe.resolve()),
            "version": ver_str,
            "version_tuple": list(ver_tup),
            "major_minor": f"{ver_tup[0]}.{ver_tup[1]}",
            "uses_extensions_system": ver_tup >= (4, 2, 0),
            "uses_slotted_actions": ver_tup >= (4, 4, 0),
            "embedded_python": str(emb_py.resolve()) if emb_py else None,
            "embedded_libs": emb_libs,
        }

    return {
        "found": False,
        "executable": None,
        "version": None,
        "version_tuple": None,
        "consent_download_supported": True,
        "message": "未在本机检测到 Blender (3.6+ / 4.x / 5.x)。可在征得宿主机同意后自动下载官方便携版 Blender LTS 到隔离目录。",
    }


def detect_fmodel(
    ww_info: Optional[Dict[str, Any]] = None,
    override_dir: Optional[str | Path] = None,
    project_root: Optional[Path] = None,
    appsettings_override: Optional[Path] = None,
) -> Dict[str, Any]:
    """Detect FModel installation and verify its AppSettings.json link to local Wuthering Waves."""
    exe_candidates: List[Tuple[str, Path]] = []
    if override_dir:
        p = Path(override_dir)
        exe_candidates.append(("cli_override", p / "FModel.exe" if p.is_dir() else p))
    else:
        if project_root:
            rt_dir = project_root / "runtime" / "fmodel"
            if rt_dir.is_dir():
                for exe in _bounded_find_files(rt_dir, "FModel.exe", max_depth=3):
                    exe_candidates.append(("project_runtime", exe))
        if os.name == "nt":
            scan_roots: List[Path] = []
            for drive in string.ascii_uppercase:
                droot = Path(f"{drive}:\\")
                if not droot.exists():
                    continue
                for rel in ("Apps\\FModel", "FModel", "Program Files\\FModel", "Tools\\FModel"):
                    sr = droot / rel
                    if sr.is_dir():
                        scan_roots.append(sr)
            local_app = os.environ.get("LOCALAPPDATA")
            if local_app:
                scan_roots.append(Path(local_app) / "FModel")
            scan_roots.extend([Path.home() / "Desktop", Path.home() / "Downloads"])
            for sr in scan_roots:
                if sr.is_dir():
                    for exe in _bounded_find_files(sr, "FModel.exe", max_depth=2):
                        exe_candidates.append((f"scan:{sr}", exe))
                        break

    fmodel_exe: Optional[Path] = None
    fmodel_source = ""
    for src, exe in exe_candidates:
        if exe.is_file():
            fmodel_exe = exe.resolve()
            fmodel_source = src
            break

    appsettings_path, cfg = _read_fmodel_appsettings(appsettings_override)
    linked_to_ww = False
    aes_key_count = 0
    any_ww_aes_key_count = 0
    matched_per_dir_key: Optional[str] = None

    def _canon_dir_str(raw_p: Any) -> str:
        s = str(raw_p or "").strip()
        if not s:
            return ""
        try:
            p_obj = Path(s)
            if p_obj.exists():
                return str(p_obj.resolve()).lower().rstrip("\\/")
        except OSError:
            pass
        return s.lower().rstrip("\\/")

    def _paths_overlap_ww(cand_norm: str, roots: List[str]) -> bool:
        if not cand_norm:
            return False
        for r in roots:
            if not r:
                continue
            if (
                cand_norm == r
                or cand_norm.startswith(r + "\\")
                or cand_norm.startswith(r + "/")
                or r.startswith(cand_norm + "\\")
                or r.startswith(cand_norm + "/")
            ):
                return True
        return False

    def _count_valid_aes_keys(aes_obj: Any) -> int:
        from .aes_resolver import validate_aes_key_bundle

        if not isinstance(aes_obj, dict):
            return 0
        v = validate_aes_key_bundle(aes_obj)
        return int(v.get("total_keys", 0)) if v.get("valid") else 0

    ww_roots: List[str] = []
    if ww_info and ww_info.get("found"):
        for k in ("game_root", "client_dir", "content_dir", "paks_dir"):
            cn = _canon_dir_str(ww_info.get(k, ""))
            if cn and cn not in ww_roots:
                ww_roots.append(cn)

    if isinstance(cfg, dict):
        per_dir = cfg.get("PerDirectory")
        if isinstance(per_dir, dict):
            for dir_key, entry in per_dir.items():
                if not isinstance(entry, dict):
                    continue
                dk_norm = _canon_dir_str(dir_key)
                gd_norm = _canon_dir_str(entry.get("GameDirectory", ""))
                ue_ver = entry.get("UeVersion")
                gname = str(entry.get("GameName", "")).lower()
                is_ww_ver = (
                    ue_ver == WUTHERING_WAVES_UE_VERSION_INT
                    or str(ue_ver or "").upper() == "GAME_WUTHERINGWAVES"
                    or "wuthering" in gname
                    or "鸣潮" in gname
                )
                matches_local = bool(ww_roots and (_paths_overlap_ww(dk_norm, ww_roots) or _paths_overlap_ww(gd_norm, ww_roots)))
                cnt = _count_valid_aes_keys(entry.get("AesKeys") or entry.get("aesKeys"))
                if is_ww_ver or matches_local:
                    any_ww_aes_key_count = max(any_ww_aes_key_count, cnt)
                if (is_ww_ver or cnt > 0) and (matches_local or not ww_roots):
                    linked_to_ww = True
                    matched_per_dir_key = str(dir_key)
                    aes_key_count = max(aes_key_count, cnt)

    fmodel_data_dir: Optional[Path] = None
    if fmodel_exe:
        cand_data = fmodel_exe.parent / "Output" / ".data"
        if cand_data.is_dir():
            fmodel_data_dir = cand_data
    if fmodel_data_dir is None and appsettings_path and appsettings_path.is_file():
        cand_appdata = appsettings_path.parent / "Output" / ".data"
        if cand_appdata.is_dir():
            fmodel_data_dir = cand_appdata

    # Detect existing local key files in standard FModel locations (never scans random user folders or network)
    detected_local_key_files: List[str] = []
    if appsettings_override is None:
        from .aes_resolver import load_user_key_bundle_file

        local_cand_files: List[Path] = []
        if appsettings_path and appsettings_path.is_file():
            local_cand_files.extend([appsettings_path.parent / "keys.json", appsettings_path.parent / "Output" / ".data" / "keys.json"])
        if fmodel_exe:
            local_cand_files.extend([fmodel_exe.parent / "AppSettings.json", fmodel_exe.parent / "keys.json", fmodel_exe.parent / "Output" / ".data" / "keys.json"])
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            local_cand_files.extend([Path(local_app) / "FModel" / "AppSettings.json", Path(local_app) / "FModel" / "keys.json"])
        seen_lkf: set[str] = set()
        for cf in local_cand_files:
            if not cf.is_file():
                continue
            rs = str(cf.resolve())
            if rs.lower() in seen_lkf or (appsettings_path and rs.lower() == str(appsettings_path.resolve()).lower()):
                continue
            seen_lkf.add(rs.lower())
            if load_user_key_bundle_file(cf).get("ok"):
                detected_local_key_files.append(rs)

    effective_aes_count = max(aes_key_count, any_ww_aes_key_count)
    has_local_keys_ready = effective_aes_count > 0 or len(detected_local_key_files) > 0

    return {
        "found": fmodel_exe is not None,
        "source": fmodel_source,
        "executable": str(fmodel_exe) if fmodel_exe else None,
        "data_dir": str(fmodel_data_dir) if fmodel_data_dir else None,
        "appsettings_path": str(appsettings_path) if appsettings_path else None,
        "appsettings_valid": isinstance(cfg, dict),
        "linked_to_local_ww": linked_to_ww,
        "matched_per_dir_key": matched_per_dir_key,
        "aes_key_count": aes_key_count,
        "any_ww_aes_key_count": any_ww_aes_key_count,
        "detected_local_key_files": detected_local_key_files,
        "has_local_keys_ready": has_local_keys_ready,
        "needs_link_repair": bool(ww_info and ww_info.get("found") and not linked_to_ww),
        "consent_download_supported": True,
    }


def _find_host_oodle_dir(
    project_root: Path,
    exe_parent: Path,
    fmodel_info: Optional[Dict[str, Any]] = None,
    ue_info: Optional[Dict[str, Any]] = None,
) -> Optional[Path]:
    """Locate an existing Oodle runtime directory (`oodle-data-shared.dll` or `oo2core_9_win64.dll`) without bundling proprietary DLLs in git."""
    search_dirs: List[Path] = [
        project_root / "runtime" / "native",
        exe_parent / "native",
        exe_parent,
    ]
    if fmodel_info and fmodel_info.get("data_dir"):
        search_dirs.append(Path(fmodel_info["data_dir"]))
    appdata = os.environ.get("APPDATA")
    if appdata:
        search_dirs.append(Path(appdata) / "FModel" / "Output" / ".data")
    if ue_info:
        for inst in ue_info.get("detected_installs") or []:
            loc = inst.get("location")
            if loc:
                oo_root = Path(loc) / "Engine" / "Binaries" / "ThirdParty" / "Oodle" / "Win64"
                if oo_root.is_dir():
                    for dll in oo_root.rglob("oo2core_9_win64.dll"):
                        search_dirs.append(dll.parent)
                        break

    for nd in search_dirs:
        if nd and nd.is_dir():
            if (nd / "oodle-data-shared.dll").is_file() or (nd / "oo2core_9_win64.dll").is_file():
                return nd.resolve()
    return None


def detect_ww_extract(
    project_root: Path,
    fmodel_info: Optional[Dict[str, Any]] = None,
    ue_info: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Detect bundled headless CUE4Parse extractor (`ww-extract.exe`) and run its self-test."""
    candidates = [
        project_root / "bin" / "ww-extract" / "ww-extract.exe",
        project_root / "ww-extract-src" / "bin" / "Release" / "net10.0" / "win-x64" / "publish" / "ww-extract.exe",
        project_root / "ww-extract-src" / "bin" / "Release" / "net10.0" / "ww-extract.exe",
    ]
    exe: Optional[Path] = None
    for c in candidates:
        if c.is_file():
            exe = c.resolve()
            break

    if exe is None:
        return {
            "found": False,
            "ok": False,
            "core_decoders_ok": False,
            "oodle_ok": False,
            "executable": None,
            "error": "Bundled ww-extract.exe not found",
        }

    native_dir = _find_host_oodle_dir(project_root, exe.parent, fmodel_info, ue_info)
    env = os.environ.copy()

    cmd = [str(exe), "self-test"]
    if native_dir:
        cmd.extend(["--native-dir", str(native_dir)])

    res = run_watched(cmd, env=env, hard_timeout_s=25, io_idle_timeout_s=20, max_retries=1, label="ww-extract-selftest")
    parsed: Dict[str, Any] = {}
    if res.stdout.strip():
        try:
            parsed = json.loads(res.stdout)
        except Exception:
            parsed = {"raw_stdout": res.stdout[:500]}

    nat = parsed.get("native", {}) if isinstance(parsed, dict) else {}
    core_decoders_ok = bool(
        nat.get("zlib", {}).get("ok")
        and nat.get("detex", {}).get("ok")
        and nat.get("acl", {}).get("ok")
        and nat.get("skiasharp", {}).get("ok")
    )
    oodle_ok = bool(nat.get("oodle", {}).get("ok"))

    return {
        "found": True,
        "ok": bool(res.ok and parsed.get("ok")),
        "core_decoders_ok": core_decoders_ok,
        "oodle_ok": oodle_ok,
        "executable": str(exe),
        "native_dir": str(native_dir) if native_dir else None,
        "self_test": parsed,
        "stderr": res.stderr.strip()[:500] if not core_decoders_ok else "",
    }


def detect_blender_addons(blender_info: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    """Discover host-installed and bundled UEFormat Blender addon."""
    bundled_root = project_root / "bundled_addons"
    appdata = Path(os.environ.get("APPDATA", "")) if os.environ.get("APPDATA") else None
    mm = blender_info.get("major_minor") if blender_info.get("found") else None

    host_ext_dir = appdata / "Blender Foundation" / "Blender" / mm / "extensions" / "user_default" if (appdata and mm) else None
    host_addons_dir = appdata / "Blender Foundation" / "Blender" / mm / "scripts" / "addons" if (appdata and mm) else None

    def _find_addon(names: List[str], bundled_name: str) -> Dict[str, Any]:
        host_path: Optional[Path] = None
        host_kind: Optional[str] = None
        for base, kind in [(host_ext_dir, "extension"), (host_addons_dir, "legacy_addon")]:
            if base and base.is_dir():
                for nm in names:
                    p = base / nm
                    if p.is_dir() and (p / "__init__.py").is_file():
                        host_path = p
                        host_kind = kind
                        break
                if host_path:
                    break
        bundled_path = bundled_root / bundled_name
        has_bundled = bundled_path.is_dir() and (bundled_path / "__init__.py").is_file()
        selected = host_path or (bundled_path if has_bundled else None)
        selected_source = "host" if host_path else ("bundled" if has_bundled else "missing")
        return {
            "found": selected is not None,
            "selected_source": selected_source,
            "selected_path": str(selected) if selected else None,
            "host_path": str(host_path) if host_path else None,
            "host_kind": host_kind,
            "bundled_path": str(bundled_path) if has_bundled else None,
        }

    ueformat = _find_addon(["io_scene_ueformat", "UEFormat"], "io_scene_ueformat")
    return {"ueformat": ueformat}


def detect_optional_ue_info() -> Dict[str, Any]:
    """Informational-only check for Unreal Engine. UE is NOT required for this showcase/handoff pipeline."""
    launcher_dat = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Epic" / "UnrealEngineLauncher" / "LauncherInstalled.dat"
    installs: List[Dict[str, str]] = []
    if launcher_dat.is_file():
        try:
            data = json.loads(launcher_dat.read_text(encoding="utf-8-sig"))
            for item in data.get("InstallationList", []):
                if str(item.get("NamespaceId", "")).lower() == "ue":
                    installs.append(
                        {
                            "app_name": str(item.get("AppName", "")),
                            "version": str(item.get("AppVersion", "")),
                            "location": str(item.get("InstallLocation", "")),
                        }
                    )
        except Exception:
            pass
    return {
        "required": False,
        "note": "Unreal Engine is NOT required by this Blender showcase & handoff pipeline; a separate downstream handoff plugin handles UE import.",
        "detected_installs": installs,
    }


def detect_full_environment(
    project_root: Path,
    *,
    game_dir: Optional[str | Path] = None,
    blender_path: Optional[str | Path] = None,
    fmodel_dir: Optional[str | Path] = None,
    fmodel_appsettings_path: Optional[Path] = None,
    extra_keys_file: Optional[str | Path] = None,
    work_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run complete Stage 0 environment inventory (directly uses existing local keys; pauses only when no local keys exist)."""
    from .aes_resolver import load_user_key_bundle_file

    ww = detect_wuthering_waves(game_dir)
    blender = detect_blender(blender_path, project_root)
    fmodel = detect_fmodel(ww, fmodel_dir, project_root, appsettings_override=fmodel_appsettings_path)
    ue_optional = detect_optional_ue_info()
    ww_extract = detect_ww_extract(project_root, fmodel, ue_optional)
    addons = detect_blender_addons(blender, project_root)

    if work_dir and (work_dir / "keys.json").is_file():
        wd_k = str((work_dir / "keys.json").resolve())
        if wd_k not in fmodel["detected_local_key_files"] and load_user_key_bundle_file(wd_k).get("ok"):
            fmodel["detected_local_key_files"].append(wd_k)
            fmodel["has_local_keys_ready"] = True

    user_keys_probe: Dict[str, Any] = {"provided": bool(extra_keys_file), "ok": False}
    if extra_keys_file:
        user_keys_probe = {"provided": True, **load_user_key_bundle_file(extra_keys_file)}
    user_keys_valid = bool(user_keys_probe.get("ok"))

    consent_actions: List[Dict[str, Any]] = []
    if ww["found"]:
        if not blender["found"]:
            consent_actions.append(
                {
                    "action_id": "download_blender",
                    "flag": "--consent-download blender",
                    "required": True,
                    "download_plan": {
                        "version": "5.2.3",
                        "url": "https://download.blender.org/release/Blender5.2/blender-5.2.3-windows-x64.zip",
                        "sha256_url": "https://download.blender.org/release/Blender5.2/blender-5.2.3.sha256",
                        "approx_size_mb": 390,
                        "target_dir": str((project_root / "runtime" / "blender" / "5.2.3").resolve()),
                    },
                    "reason": "未检测到 Blender；需征得宿主机同意后下载官方便携版 Blender 5.2.3 LTS (~390 MB，官方 SHA256 校验) 到隔离目录 runtime/blender/。",
                }
            )
        if ww_extract["core_decoders_ok"] and not ww_extract["oodle_ok"]:
            consent_actions.append(
                {
                    "action_id": "download_oodle",
                    "flag": "--consent-download oodle",
                    "required": True,
                    "download_plan": {
                        "version": "2.9.16",
                        "url": "https://github.com/WorkingRobot/OodleUE/releases/download/2026-06-04-1357/clang-cl-x64-release.zip",
                        "expected_dll_sha256": "cba19529d0a3b5ec9c630e95652af01e123ae29a34a8a5f7507f5bcf23d9e82b",
                        "approx_size_mb": 0.5,
                        "target_dir": str((project_root / "runtime" / "native").resolve()),
                    },
                    "reason": (
                        "开源仓库按合规要求不随包分发专有 Oodle 动态库，且本机未检测到 FModel/UE 现成解码库；"
                        "需征得宿主机同意后按需下载 Oodle 运行库（SHA256 校验）到项目隔离目录 runtime/native/。"
                    ),
                }
            )
        # Only pause for keys when NO valid local key exists anywhere on host and none was validly supplied
        if (not fmodel.get("has_local_keys_ready")) and (not user_keys_valid):
            target_cfg_str = str(
                fmodel_appsettings_path
                or fmodel.get("appsettings_path")
                or (Path(os.environ.get("APPDATA", "")) / "FModel" / "AppSettings.json")
            )
            consent_actions.append(
                {
                    "action_id": "provide_keys_and_link_fmodel",
                    "flag": "--keys-file \"<本地 .json / .zip / .txt 或目录路径>\" --consent-link-fmodel",
                    "required": True,
                    "download_plan": {
                        "appsettings_path": target_cfg_str,
                        "ww_content_dir": ww.get("content_dir"),
                        "backup_before_write": True,
                        "accepted_key_formats": [".json", ".zip (in-memory read only)", ".txt/.key", "local folder containing keys.json"],
                    },
                    "reason": (
                        "检测到本机 FModel 尚未关联《鸣潮》目录或未发现可用的本地密钥配置，工作已暂停。"
                        "本插件不提供、亦不代为联网搜索密钥；如尚未准备，可先临时关闭本插件并另开新会话执行，或由宿主机手动寻找并准备好本地密钥文件。"
                        "如本机已有现成密钥文件/压缩包/目录，请直接传入 `--keys-file \"<本地路径>\" --consent-link-fmodel`，"
                        "插件将不询问来源，自动备份原 AppSettings.json 后直接完成本地 FModel 关联并使用。"
                    ),
                }
            )
        if not fmodel["found"]:
            consent_actions.append(
                {
                    "action_id": "download_fmodel",
                    "flag": "--consent-download fmodel",
                    "required": False,
                    "download_plan": {
                        "api_url": "https://api.github.com/repos/4sval/FModel/releases/latest",
                        "target_dir": str((project_root / "runtime" / "fmodel").resolve()),
                    },
                    "reason": "未检测到 FModel GUI（可选）；如需同步安装官方 FModel 图形界面，可在同意后自动下载至隔离目录 runtime/fmodel/。",
                }
            )

    return {
        "wuthering_waves": ww,
        "blender": blender,
        "fmodel": fmodel,
        "ww_extract": ww_extract,
        "addons": addons,
        "user_keys_probe": user_keys_probe,
        "unreal_engine_optional": ue_optional,
        "consent_actions": consent_actions,
    }
