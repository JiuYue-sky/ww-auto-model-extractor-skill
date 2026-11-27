"""Comprehensive automated unit, contract, security & compliance regression test suite for ww-auto-core."""

from __future__ import annotations

import ast
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if (ROOT / "core").is_dir():
    sys.path.insert(0, str(ROOT))
    import core  # type: ignore
else:
    import importlib.util

    pkg_dir = ROOT / "ww-auto-core"
    spec = importlib.util.spec_from_file_location("core", str(pkg_dir / "__init__.py"), submodule_search_locations=[str(pkg_dir)])
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["core"] = mod
    spec.loader.exec_module(mod)

from core.addon_sandbox import patch_python_source_compat, scan_python_source_compat
from core.aes_resolver import resolve_and_verify_aes_keys, validate_aes_key_bundle
from core.asset_extractor import _match_characters_detailed, classify_animation_bake_status, inspect_ueanim_binary
from core.blender_runner import detect_host_blender_ui_language
from core.config_rules import classify_texture_suffix, resolve_character_query_tokens, resolve_character_query_variants
from core.delivery_packager import _generate_ue_handoff_reference_script
from core.env_bootstrap import (
    apply_consented_bootstrap,
    download_blender_portable,
    download_oodle_runtime,
    link_fmodel_to_wuthering_waves,
)
from core.env_detector import WUTHERING_WAVES_UE_VERSION_INT, detect_blender, detect_wuthering_waves
from core.self_audit import run_package_self_audit
from core.texture_auditor import audit_and_process_textures, parse_material_instance_json
from core.watchdog import run_watched


class TestSafetyAndConsentPolicies(unittest.TestCase):
    def test_missing_game_triggers_fatal_abort_no_download(self):
        with tempfile.TemporaryDirectory() as td:
            res = detect_wuthering_waves(override_dir=Path(td) / "nonexistent_ww")
            self.assertFalse(res["found"])
            self.assertTrue(res["fatal"])
            self.assertEqual(res["code"], "FATAL_MISSING_WUTHERING_WAVES")
            self.assertFalse(res["auto_download_allowed"])

            fake_env = {
                "wuthering_waves": {"found": False, "fatal": True, "auto_download_allowed": False},
                "blender": {"found": False},
                "ww_extract": {"oodle_ok": False},
                "fmodel": {"found": False},
            }
            acts = apply_consented_bootstrap(Path(td), fake_env, consent_downloads=["wuthering_waves", "blender"])
            self.assertEqual(len(acts), 1)
            self.assertEqual(acts[0]["status"], "REFUSED")
            self.assertEqual(acts[0]["component"], "wuthering_waves")

    def test_blender_and_oodle_download_blocked_without_consent(self):
        with tempfile.TemporaryDirectory() as td:
            res = download_blender_portable(Path(td), consent_granted=False)
            self.assertEqual(res["status"], "CONSENT_REQUIRED")
            self.assertIn("plan", res)

            res_oo = download_oodle_runtime(Path(td), consent_granted=False)
            self.assertEqual(res_oo["status"], "CONSENT_REQUIRED")
            self.assertIn("expected_dll_sha256", res_oo["plan"])

    def test_fmodel_link_requires_consent_imports_zip_keys_in_memory_and_creates_backup(self):
        import zipfile
        from core.aes_resolver import load_user_key_bundle_file
        from core.env_detector import detect_fmodel

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            fake_ww_root = td_p / "WW"
            fake_ww_content = fake_ww_root / "Client" / "Content"
            (fake_ww_content / "Paks").mkdir(parents=True)
            app_settings = td_p / "AppSettings.json"
            app_settings.write_text(json.dumps({"ExistingKey": 123, "PerDirectory": {}}), encoding="utf-8")

            # Build a .zip key package containing BOTH a valid keys.json AND a decoy .exe (must NEVER be extracted!)
            key_zip = td_p / "user_keys_pkg.zip"
            sample_keys = {
                "mainKey": "0x" + "AB" * 32,
                "dynamicKeys": [{"guid": "00112233-4455-6677-8899-aabbccddeeff", "key": "0x" + "CD" * 32}],
            }
            with zipfile.ZipFile(key_zip, "w") as zf:
                zf.writestr("decoy_trojan.exe", b"MZ_NEVER_EXTRACT")
                zf.writestr("nested/keys.json", json.dumps(sample_keys))

            loaded = load_user_key_bundle_file(key_zip)
            self.assertTrue(loaded["ok"])
            self.assertEqual(loaded["source_type"], "zip_in_memory")
            self.assertEqual(loaded["total_keys"], 2)
            self.assertFalse((td_p / "decoy_trojan.exe").exists())

            # Zip containing ONLY executables (no .json) must be rejected cleanly
            bad_zip = td_p / "only_exe.zip"
            with zipfile.ZipFile(bad_zip, "w") as zf:
                zf.writestr("runme.exe", b"MZ")
            self.assertFalse(load_user_key_bundle_file(bad_zip)["ok"])

            ww_info = {"found": True, "client_dir": str(fake_ww_root / "Client"), "content_dir": str(fake_ww_content)}

            r0 = link_fmodel_to_wuthering_waves(ww_info, consent_granted=False, appsettings_path=app_settings, keys_bundle_path=key_zip)
            self.assertEqual(r0["status"], "CONSENT_REQUIRED")
            self.assertEqual(json.loads(app_settings.read_text(encoding="utf-8"))["ExistingKey"], 123)

            r1 = link_fmodel_to_wuthering_waves(ww_info, consent_granted=True, appsettings_path=app_settings, keys_bundle_path=key_zip)
            self.assertEqual(r1["status"], "LINKED")
            self.assertEqual(r1["imported_key_count"], 2)
            self.assertTrue(Path(r1["backup_path"]).is_file())
            updated = json.loads(app_settings.read_text(encoding="utf-8"))
            self.assertEqual(updated["ExistingKey"], 123)
            entry = updated["PerDirectory"][str(fake_ww_content.resolve())]
            self.assertEqual(entry["UeVersion"], WUTHERING_WAVES_UE_VERSION_INT)
            self.assertNotIn("Endpoints", entry)
            self.assertEqual(entry["AesKeys"]["mainKey"], "0x" + "AB" * 32)
            self.assertEqual(len(entry["AesKeys"]["dynamicKeys"]), 1)

            # Verify detect_fmodel now recognizes both link and imported AesKeys!
            fm_det = detect_fmodel(ww_info, appsettings_override=app_settings)
            self.assertTrue(fm_det["linked_to_local_ww"])
            self.assertEqual(fm_det["aes_key_count"], 2)


class TestBlenderAddonASTCompat(unittest.TestCase):
    def test_detects_and_patches_36_to_52_preserving_future_imports(self):
        legacy_src = (
            '"""Mock legacy Blender 3.6 addon."""\n'
            "from __future__ import annotations\n"
            "import bpy\n\n"
            "def setup(nodes, mesh, action):\n"
            "    mix = nodes.new('ShaderNodeMixRGB')\n"
            "    bsdf = nodes.new('ShaderNodeBsdfPrincipled')\n"
            "    bsdf.inputs['Specular'].default_value = 0.5\n"
            "    bsdf.inputs['Subsurface'].default_value = 0.1\n"
            "    bsdf.inputs['Transmission'].default_value = 0.2\n"
            "    mesh.use_auto_smooth = True\n"
            "    return list(action.fcurves)\n"
        )
        issues = scan_python_source_compat(legacy_src, "legacy.py", (5, 2, 3))
        rule_ids = {i.rule_id for i in issues}
        self.assertIn("B40_MIXRGB_REMOVED", rule_ids)
        self.assertIn("B40_BSDF_SOCKET_SPECULAR", rule_ids)
        self.assertIn("B41_USE_AUTO_SMOOTH_REMOVED", rule_ids)
        self.assertIn("B50_ACTION_FCURVES_REMOVED", rule_ids)

        patched, applied = patch_python_source_compat(legacy_src, (5, 2, 3))
        self.assertGreaterEqual(len(applied), 5)
        ast.parse(patched)
        remaining = scan_python_source_compat(patched, "legacy.py", (5, 2, 3))
        self.assertEqual(len(remaining), 0, f"Unexpected remaining issues: {remaining}")

    def test_no_false_positive_on_version_guarded_code(self):
        modern_src = (
            "from __future__ import annotations\n"
            "import bpy\n"
            "def f(mesh, action):\n"
            "    if bpy.app.version < (4, 1, 0):\n"
            "        mesh.use_auto_smooth = True\n"
            "    if bpy.app.version < (5, 0, 0):\n"
            "        return action.fcurves.new('x')\n"
        )
        issues = scan_python_source_compat(modern_src, "modern.py", (5, 2, 3))
        self.assertEqual(len(issues), 0)


class TestAesLocalOnlyAndWatchdog(unittest.TestCase):
    def test_aes_validation_and_local_only_pause_and_link_reminder(self):
        self.assertFalse(validate_aes_key_bundle({"mainKey": "invalid"})["valid"])
        valid_payload = {
            "mainKey": "0x" + "1A" * 32,
            "dynamicKeys": [{"guid": "00000000000000000000000000000001", "key": "0x" + "2B" * 32}],
        }
        self.assertTrue(validate_aes_key_bundle(valid_payload)["valid"])

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            fake_probe_py = td_p / "fake_probe.py"
            fake_probe_py.write_text(
                'import json; print(json.dumps({"ok": True, "aes": {"status": "FAILED", "mounted_paks": 0, "total_paks": 10, "missing_guids": ["G1"]}}))\n',
                encoding="utf-8",
            )
            # Missing explicit --keys-file fails cleanly before probing
            fake_env = {
                "wuthering_waves": {"found": True, "game_root": str(td_p), "client_version": "3.8.0", "pak_counts": {"total": 10}},
                "ww_extract": {"ok": True, "executable": sys.executable},
                "fmodel": {},
            }
            r_missing = resolve_and_verify_aes_keys(fake_env, td_p, extra_keys_file=td_p / "no_such_keys.json")
            self.assertEqual(r_missing["status"], "FAIL")
            self.assertIn("keys.json", r_missing["host_notice"])

            # Mock _probe_paks returning 0 mounted -> verifies pause-and-link reminder & zero remote fetch!
            import core.aes_resolver as ar

            orig_probe = ar._probe_paks
            try:
                ar._probe_paks = lambda *a, **kw: {
                    "ok": True,
                    "aes": {"status": "FAILED", "mounted_paks": 0, "total_paks": 12, "missing_guids": ["G1"]},
                }
                r_zero = resolve_and_verify_aes_keys(fake_env, td_p, ignore_fmodel_keys=True)
                self.assertEqual(r_zero["status"], "CONSENT_REQUIRED")
                self.assertEqual(r_zero["code"], "HOST_KEYS_REQUIRED")
                self.assertFalse(r_zero["remote_refreshed"])
                self.assertIn("--keys-file", r_zero["host_notice"])
                self.assertIn("--consent-link-fmodel", r_zero["host_notice"])
            finally:
                ar._probe_paks = orig_probe

    def test_watchdog_kills_hung_process_on_idle_timeout(self):
        res = run_watched(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            hard_timeout_s=10.0,
            io_idle_timeout_s=1.2,
            max_retries=1,
            poll_interval_s=0.1,
            label="hang-test",
        )
        self.assertFalse(res.ok)
        self.assertTrue(res.idle_killed)
        self.assertLess(res.elapsed_s, 6.0)
        self.assertTrue(len(res.killed_pids) >= 1)


class TestTextureAuditorAndBinaryChecks(unittest.TestCase):
    def test_character_aliases_and_suffix_priority(self):
        self.assertIn("jinxi", resolve_character_query_tokens("今汐"))
        self.assertIn("kmola", resolve_character_query_tokens("珂莱塔"))
        self.assertIn("bailian", resolve_character_query_tokens("白芷"))
        self.assertIn("jueyuan", resolve_character_query_tokens("维里奈"))
        self.assertEqual(classify_texture_suffix("T_R2T1JinxiMd10011Down_ID.png")[0], "_id")
        self.assertEqual(classify_texture_suffix("T_R2T1JinxiMd10011Down_D.png")[0], "_d")
        self.assertEqual(classify_texture_suffix("T_R2T1JinxiMd10011Down_N.png")[0], "_n")

    def test_ueanim_binary_verifier_rejects_empty_tracks(self):
        def fstr(s: str) -> bytes:
            b = s.encode("utf-8")
            return struct.pack("<i", len(b)) + b

        meta_body = struct.pack("<if", 30, 30.0)
        tracks_body = struct.pack("<i", 0)
        payload = (
            b"UEFORMAT"
            + fstr("UEANIM")
            + bytes([10])
            + fstr("EmptyAnim")
            + fstr("/Game/EmptyAnim")
            + bytes([0])
            + struct.pack("<i", 2)
            + fstr("METADATA") + struct.pack("<i", len(meta_body)) + meta_body
            + fstr("TRACKS") + struct.pack("<i", len(tracks_body)) + tracks_body
        )
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "EmptyAnim.ueanim"
            p.write_bytes(payload)
            chk = inspect_ueanim_binary(p)
            self.assertFalse(chk["valid"])
            self.assertEqual(chk["track_count"], 0)

    def test_synthetic_texture_audit_n_split_sdf_mirror_and_rgb_repair(self):
        bl = detect_blender(project_root=ROOT)
        if not bl.get("found"):
            self.skipTest("Blender embedded Python not available on test runner")

        emb_py = bl["embedded_python"]
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            gen_code = f"""
import numpy as np, OpenImageIO as oiio
from pathlib import Path
out = Path({str(td_p)!r})
def save(name, arr):
    h, w, c = arr.shape
    o = oiio.ImageOutput.create(str(out / name))
    o.open(str(out / name), oiio.ImageSpec(w, h, c, oiio.UINT8))
    o.write_image(np.ascontiguousarray(arr, dtype=np.uint8))
    o.close()

d = np.full((64, 64, 3), 180, dtype=np.uint8)
save("T_TestBody_D.png", d)

n = np.zeros((64, 64, 4), dtype=np.uint8)
n[:, :, 0] = 128
n[:, :, 1] = 128
n[:, :, 2] = np.tile(np.linspace(0, 220, 64, dtype=np.uint8), (64, 1))
n[:, :, 3] = np.tile(np.linspace(40, 240, 64, dtype=np.uint8)[:, None], (1, 64))
save("T_TestBody_N.png", n)

sdf = np.zeros((64, 64, 4), dtype=np.uint8)
grad = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
sdf[:, :, 0] = grad
sdf[:, :, 1] = np.fliplr(grad)
sdf[:, :, 3] = 255
save("T_TestFace_SDF.png", sdf)

save("T_Test_Skin.png", np.zeros((16, 128, 4), dtype=np.uint8))
"""
            rgen = run_watched([emb_py, "-c", gen_code], hard_timeout_s=30, io_idle_timeout_s=20, max_retries=1)
            self.assertTrue(rgen.ok, rgen.stderr)

            mi_path = td_p / "MI_TestBody.json"
            mi_path.write_text(
                json.dumps(
                    {
                        "BlendMode": 0,
                        "Textures": {
                            "MainTex": {"ObjectName": "Texture2D'T_TestBody_D'", "ObjectPath": "T_TestBody_D.0"},
                            "Normal_Roughness_Metallic": {"ObjectName": "Texture2D'T_TestBody_N'", "ObjectPath": "T_TestBody_N.0"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            idx_path = td_p / "extraction_index.json"
            idx_path.write_text(
                json.dumps(
                    {
                        "materials": [str(mi_path)],
                        "textures": [
                            {"disk_path": str(td_p / "T_TestBody_D.png")},
                            {"disk_path": str(td_p / "T_TestBody_N.png")},
                            {"disk_path": str(td_p / "T_TestFace_SDF.png")},
                            {"disk_path": str(td_p / "T_Test_Skin.png")},
                        ],
                    }
                ),
                encoding="utf-8",
            )

            res = audit_and_process_textures(idx_path, td_p / "audit", blender_info=bl)
            self.assertEqual(res["status"], "PASS")
            audit_doc = json.loads(Path(res["audit_report_path"]).read_text(encoding="utf-8"))
            by_name = {t["name"]: t for t in audit_doc["textures"]}

            self.assertTrue(Path(by_name["T_TestBody_D"]["pixel_audit"]["derived_files"]["repaired_rgba"]).is_file())
            self.assertEqual(by_name["T_TestBody_N"]["final_ue_settings"]["compression"], "TC_BC7")
            self.assertTrue(Path(by_name["T_TestBody_N"]["pixel_audit"]["derived_files"]["split_normal_bc5"]).is_file())
            self.assertTrue(Path(by_name["T_TestBody_N"]["pixel_audit"]["derived_files"]["split_mr_bc7"]).is_file())
            self.assertEqual(by_name["T_TestFace_SDF"]["pixel_audit"]["sdf_audit"]["strategy"], "KEEP_SINGLE_CHANNEL_MIRROR_UV")
            self.assertIn("T_Test_Skin", audit_doc["summary"]["all_zero_textures"])

    def test_ue_handoff_reference_script_valid_ast(self):
        code = _generate_ue_handoff_reference_script()
        tree = ast.parse(code)
        func_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        self.assertIn("import_from_handoff_manifest", func_names)

    def test_fur_shader_mi_detection_for_fur_cards(self):
        with tempfile.TemporaryDirectory() as td:
            mi_p = Path(td) / "MI_TestTail.json"
            mi_p.write_text(
                json.dumps(
                    {
                        "BlendMode": 1,
                        "Switches": {"UseFurry": True, "UseTranslucent": True},
                        "Scalars": {"OpacityMaskClipValue": 0.3333},
                        "Textures": {
                            "MainTex": {"ObjectName": "Texture2D'T_TestTail_D'", "ObjectPath": "T_TestTail_D.0"},
                            "TypeMask": {"ObjectName": "Texture2D'T_TestTail_ID'", "ObjectPath": "T_TestTail_ID.0"},
                            "Fur_Tex": {"ObjectName": "Texture2D'T_Test_M'", "ObjectPath": "T_Test_M.0"},
                        },
                    }
                ),
                encoding="utf-8",
            )
            parsed = parse_material_instance_json(mi_p)
            self.assertTrue(parsed["is_hair_or_masked"])
            self.assertTrue(parsed["is_fur_shader"])
            self.assertEqual(parsed["bound_textures"]["TypeMask"]["semantic_slot"], "id_mask")
            self.assertEqual(parsed["bound_textures"]["Fur_Tex"]["semantic_slot"], "fur_mask")

    def test_d4_unbaked_animation_classifier_and_d3_aerial_loop(self):
        unbaked = {
            "track_count": 197,
            "single_key_tracks": 196,
            "single_key_ratio": 0.9949,
            "moving_tracks": 1,
            "non_root_moving_tracks": 0,
            "root_pos_span_cm": 1501.86,
            "bytes": 25493,
            "control_curves_only": True,
        }
        r_unbaked = classify_animation_bake_status(unbaked, "BaseAnim", "Land_Roll_Attack01_2", sibling_max_bytes=2_300_000)
        self.assertTrue(r_unbaked["needs_ue_bake"])
        self.assertFalse(r_unbaked["blender_showcase_acceptance"])
        self.assertGreaterEqual(len(r_unbaked["reasons"]), 3)

        baked_small = {
            "track_count": 140,
            "single_key_tracks": 70,
            "single_key_ratio": 0.50,
            "moving_tracks": 61,
            "non_root_moving_tracks": 60,
            "root_pos_span_cm": 0.0,
            "bytes": 42000,
            "control_curves_only": False,
        }
        r_walk = classify_animation_bake_status(baked_small, "BaseAnim", "Walk_F", sibling_max_bytes=1_500_000)
        self.assertFalse(r_walk["needs_ue_bake"])
        self.assertFalse(r_walk["is_aerial_loop"])
        self.assertTrue(r_walk["blender_showcase_acceptance"])

        r_jump = classify_animation_bake_status(baked_small, "BaseAnim", "Jump_Loop", sibling_max_bytes=1_500_000)
        self.assertFalse(r_jump["needs_ue_bake"])
        self.assertTrue(r_jump["is_aerial_loop"])
        self.assertFalse(r_jump["blender_showcase_acceptance"])

        r_rib = classify_animation_bake_status(unbaked, "RibbonAnim", "Rib_Stand1_Action01", sibling_max_bytes=2_300_000)
        self.assertFalse(r_rib["needs_ue_bake"])

    def test_kuro_data_alpha_down_d_guarded_from_false_clip(self):
        bl = detect_blender(project_root=ROOT)
        if not bl.get("found"):
            self.skipTest("Blender embedded Python not available on test runner")
        emb_py = bl["embedded_python"]
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            gen_code = f"""
import numpy as np, OpenImageIO as oiio
from pathlib import Path
out = Path({str(td_p)!r})
arr = np.full((100, 100, 4), 200, dtype=np.uint8)
arr[:, :, 3] = 102
arr[:11, :, 3] = 0
arr[99, :30, 3] = 255
o = oiio.ImageOutput.create(str(out / "T_TestDown_D.png"))
o.open(str(out / "T_TestDown_D.png"), oiio.ImageSpec(100, 100, 4, oiio.UINT8))
o.write_image(np.ascontiguousarray(arr, dtype=np.uint8))
o.close()
"""
            rgen = run_watched([emb_py, "-c", gen_code], hard_timeout_s=30, io_idle_timeout_s=20, max_retries=1)
            self.assertTrue(rgen.ok, rgen.stderr)
            mi_p = td_p / "MI_TestDown.json"
            mi_p.write_text(
                json.dumps(
                    {
                        "BlendMode": 1,
                        "Switches": {"UseTranslucent": True, "UseToonMask": True, "UseMainTexA": True},
                        "Textures": {"MainTex": {"ObjectName": "Texture2D'T_TestDown_D'", "ObjectPath": "T_TestDown_D.0"}},
                    }
                ),
                encoding="utf-8",
            )
            idx_p = td_p / "extraction_index.json"
            idx_p.write_text(
                json.dumps({"materials": [str(mi_p)], "textures": [{"disk_path": str(td_p / "T_TestDown_D.png")}]}),
                encoding="utf-8",
            )
            res = audit_and_process_textures(idx_p, td_p / "audit", blender_info=bl)
            self.assertEqual(res["status"], "PASS")
            audit_doc = json.loads(Path(res["audit_report_path"]).read_text(encoding="utf-8"))
            trec = audit_doc["textures"][0]
            self.assertEqual(trec["pixel_audit"]["alpha_semantics"], "data_channel_shadow_mask")
            self.assertLessEqual(trec["pixel_audit"]["alpha_profile"]["p99"], 0.55)


class TestSelfAuditCatchesPackageDefects(unittest.TestCase):
    def test_self_audit_catches_leaked_key_and_syntax_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "core").mkdir()
            (p / "core" / "broken.py").write_text("def broken(:\n    pass\n", encoding="utf-8")
            (p / "core" / "leak.py").write_text('KEY = "0x' + 'A' * 64 + '"\n', encoding="utf-8")
            res = run_package_self_audit(p, check_binary=False)
            self.assertEqual(res["status"], "FAIL")
            failed_checks = {c["check"] for c in res["checks"] if not c["ok"]}
            self.assertIn("python_ast_syntax", failed_checks)
            self.assertIn("no_bundled_aes_keys", failed_checks)

    def test_self_audit_catches_invalid_dsh_cordis4_inject(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "core").mkdir()
            (p / "core" / "__init__.py").write_text("", encoding="utf-8")
            (p / "lib").mkdir()
            (p / "lib" / "index.js").write_text(
                'export const inject = { optional: ["tools"] };\nexport async function apply(ctx) {}\n',
                encoding="utf-8",
            )
            (p / "package.json").write_text(
                json.dumps({"name": "dsh-test", "main": "./lib/index.js", "icon": "./icon.png", "engines": {"dsh": ">=0.2.2"}, "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}}),
                encoding="utf-8",
            )
            (p / "cordis.patch.yml").write_text("plugins: {}\n", encoding="utf-8")
            (p / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            res = run_package_self_audit(p, check_binary=False)
            self.assertEqual(res["status"], "FAIL")
            failed_checks = {c["check"] for c in res["checks"] if not c["ok"]}
            self.assertIn("dsh_cordis4_plugin_contract", failed_checks)

    def test_character_catalog_cache_hit_and_invalidation(self):
        from core.asset_extractor import list_available_characters

        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            ww_info = {"game_root": "X:\\FakeWW", "client_version": "3.8.0", "pak_counts": {"total": 436}}
            env_report = {"wuthering_waves": ww_info, "ww_extract": {"executable": "nonexistent.exe"}}
            cache_file = wd / "character_catalog_cache.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "fingerprint": {"game_root": "X:\\FakeWW", "client_version": "3.8.0", "pak_total": 436, "mounted_paks": 436},
                        "count": 2,
                        "characters": [
                            {"BodyType": "FemaleM", "CharacterFolder": "Jinxi", "ModelId": "R2T1JinxiMd10011", "ModelPath": "p1", "MaterialCount": 5, "TextureCount": 12},
                            {"BodyType": "FemaleMS", "CharacterFolder": "Kmola", "ModelId": "R2T1KamolaMd10011", "ModelPath": "p2", "MaterialCount": 5, "TextureCount": 12},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            res = list_available_characters(env_report, [], query="珂莱塔", work_dir=wd)
            self.assertTrue(res["ok"])
            self.assertTrue(res["from_cache"])
            self.assertEqual(res["characters"][0]["ModelId"], "R2T1KamolaMd10011")

            from core.asset_extractor import _try_load_catalog_cache

            ww_changed = {**ww_info, "pak_counts": {"total": 440}}
            self.assertIsNone(_try_load_catalog_cache(wd, ww_changed))

    def test_legal_disclaimer_and_docs_hygiene_audit(self):
        from core.version import LEGAL_NOTICE, LEGAL_NOTICE_ZH

        for kw in ("非官方", "个人学习", "测试服", "商业", "交易", "库洛科技"):
            self.assertIn(kw, LEGAL_NOTICE_ZH)
        for kw in ("unofficial", "personal", "beta", "commercial", "trading", "Kuro Games"):
            self.assertIn(kw.lower(), LEGAL_NOTICE.lower())

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "core").mkdir()
            (p / "core" / "__init__.py").write_text("", encoding="utf-8")
            (p / "AGENT_START_HERE.md").write_text("Stage 0 --step 0 --self-audit 同意\n", encoding="utf-8")
            (p / "PIPELINE_MANIFEST.json").write_text(
                json.dumps({"safety_policies": {"never_auto_download_game": True, "unreal_engine_required": False, "no_remote_aes_fetch": True}, "stages": [{"id": i} for i in range(5)]}),
                encoding="utf-8",
            )
            (p / "SKILL.md").write_text("---\nname: ww-auto-model-extractor\ndescription: 鸣潮风格化展示\n---\n[broken](docs/NO_SUCH_FILE.md)\n", encoding="utf-8")
            (p / "README.md").write_text("# Test\n[missing](docs/MISSING.md)\n", encoding="utf-8")
            res = run_package_self_audit(p, check_binary=False)
            self.assertEqual(res["status"], "FAIL")
            failed = {c["check"] for c in res["checks"] if not c["ok"]}
            self.assertIn("agent_pack_docs_links_and_compliance", failed)

        with tempfile.TemporaryDirectory() as td:
            p = Path(td)
            (p / "core").mkdir()
            (p / "core" / "__init__.py").write_text("", encoding="utf-8")
            (p / "lib").mkdir()
            (p / "lib" / "index.js").write_text('export const inject = ["tools"];\nexport function apply(ctx) {}\n', encoding="utf-8")
            (p / "locale").mkdir()
            (p / "locale" / "en.json").write_text(json.dumps({"meta": {"title": "T", "description": "D"}}), encoding="utf-8")
            (p / "locale" / "zh-CN.json").write_text(json.dumps({"meta": {"title": "中文", "description": "中文"}}), encoding="utf-8")
            (p / "package.json").write_text(
                json.dumps({"name": "dsh-test", "description": "中文简介", "main": "./lib/index.js", "icon": "./icon.png", "engines": {"dsh": ">=0.2.1-rc.2 <0.4.0-0"}, "dsh": {"bundle": {"patch": "./cordis.patch.yml"}}}),
                encoding="utf-8",
            )
            (p / "cordis.patch.yml").write_text("[]\n", encoding="utf-8")
            (p / "icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (p / "README.md").write_text("[不可点文档](docs/USER_GUIDE_AND_NOTICES.md)\n", encoding="utf-8")
            res = run_package_self_audit(p, check_binary=False)
            self.assertEqual(res["status"], "FAIL")
            failed = {c["check"] for c in res["checks"] if not c["ok"]}
            self.assertIn("dsh_package_json_spec", failed)
            self.assertIn("dsh_locale_zh_en_spec", failed)
            self.assertIn("dsh_readme_inline_and_compliance", failed)


class TestMultiformChineseCharacterFolderMatching(unittest.TestCase):
    """Comprehensive tests for Chinese -> Chinese / lowercase English / Capitalized English direct folder matching."""

    def _sample_playable_catalog(self):
        def _entry(body: str, folder: str, model_id: str, mats: int = 16, texs: int = 48):
            return {
                "BodyType": body,
                "CharacterFolder": folder,
                "ModelId": model_id,
                "ModelPath": f"Client/Content/Aki/Character/Role/{body}/{folder}/{model_id}/Model/{model_id}.uasset",
                "MaterialCount": mats,
                "TextureCount": texs,
            }

        return [
            _entry("FemaleMS", "Lili", "R2T1LiliMd10011"),
            _entry("FemaleM", "Aimisi", "R2T1AimisiMd10011"),
            _entry("FemaleMS", "Xigelika", "R2T1XigelikaMd10011"),
            _entry("MaleXL", "Luhesi", "R2T1LuhesiMd10011"),
            _entry("FemaleMS", "Daniya", "R2T1DaniyaMd10011"),
            _entry("FemaleXL", "Luosela", "R2T1LuoselaMd10011"),
            _entry("FemaleM", "Yangyang", "R2T1YangyangMd10011"),
            _entry("FemaleM", "Yangyang", "R2T1YangyangwumaoMd10011", mats=0, texs=0),
            _entry("FemaleXL", "TaiDaoNv", "R2T1TaidaonvMd10011"),
            _entry("FemaleM", "Fuluoluo", "R2T1FuluoluoMd10011"),
            _entry("FemaleM", "LinNai", "R2T1LinnaeaMd20011"),
            _entry("FemaleMS", "Mone", "R2T1MoneMd10011"),
            _entry("FemaleM", "Qianxia", "R2T1QianXiaMd10011"),
            _entry("FemaleM", "Jinxi", "R2T1JinxiMd10011"),
            _entry("FemaleM", "Jinxi", "R2T1JinxiMd20011"),
            _entry("FemaleXL", "ChangLi", "R2T1ChangLiMd10011"),
            _entry("FemaleM", "Jianxin", "R2T1JianxinMd10011"),
            _entry("FemaleS", "Jueyuan", "R2T1JueyuanMd10011"),
            _entry("FemaleM", "Micai", "R2T1MicaiMd10011"),
            _entry("FemaleMS", "Katixiya", "R2T1KatixiyaMd10011"),
            _entry("FemaleZ", "Fuludelisi", "R2T1FuludelisiMd10011"),
        ]

    def test_chinese_query_expands_to_chinese_lower_and_capitalized_variants(self):
        v_lili = resolve_character_query_variants("莉莉")
        self.assertIn("莉莉", v_lili["chinese"])
        self.assertIn("lili", v_lili["english_lower"])
        self.assertIn("Lili", v_lili["english_capitalized"])
        self.assertIn("LiLi", v_lili["english_capitalized"])

        v_new = resolve_character_query_variants("苍澜")
        self.assertEqual(v_new["matched_alias_canonical"], [])
        self.assertIn("苍澜", v_new["chinese"])
        self.assertIn("canglan", v_new["english_lower"])
        self.assertIn("Canglan", v_new["english_capitalized"])
        self.assertIn("CangLan", v_new["english_capitalized"])

        v_poly = resolve_character_query_variants("长歌")
        self.assertIn("changge", v_poly["english_lower"])
        self.assertIn("Changge", v_poly["english_capitalized"])
        self.assertIn("ChangGe", v_poly["english_capitalized"])

    def test_unlisted_chinese_matches_chinese_lower_capitalized_pascal_and_modelpath_folders(self):
        base = self._sample_playable_catalog()
        cases = [
            ("星月", "chinese_folder_exact"),
            ("xingyue", "english_lower_folder_exact"),
            ("Xingyue", "english_capitalized_folder_exact"),
            ("XingYue", "english_capitalized_folder_exact"),
            ("Xing_Yue", "english_compact_folder_exact"),
        ]
        for folder_name, exp_channel in cases:
            entry = {
                "BodyType": "FemaleM",
                "CharacterFolder": folder_name,
                "ModelId": f"R2T1{folder_name}Md10011",
                "ModelPath": f"Client/Content/Aki/Character/Role/FemaleM/{folder_name}/R2T1{folder_name}Md10011/Model/{folder_name}.uasset",
                "MaterialCount": 14,
                "TextureCount": 40,
            }
            matched, details = _match_characters_detailed(base + [entry], "星月")
            self.assertTrue(matched, f"Expected match for folder {folder_name}")
            self.assertEqual(matched[0]["CharacterFolder"], folder_name)
            self.assertEqual(details[0]["match_channel"], exp_channel)

        path_only_entry = {
            "BodyType": "FemaleM",
            "ModelId": "R2T1CanglanMd10011",
            "ModelPath": "Client/Content/Aki/Character/Role/FemaleM/Canglan/R2T1CanglanMd10011/Model/R2T1CanglanMd10011.uasset",
            "MaterialCount": 10,
            "TextureCount": 20,
        }
        matched_p, details_p = _match_characters_detailed(base + [path_only_entry], "苍澜")
        self.assertEqual(matched_p[0]["ModelId"], "R2T1CanglanMd10011")
        self.assertEqual(details_p[0]["character_folder"], "Canglan")
        self.assertEqual(details_p[0]["match_channel"], "english_capitalized_folder_exact")

    def test_released_characters_codenames_disambiguation_and_traditional(self):
        chars = self._sample_playable_catalog()
        assertions = [
            ("莉莉", "Lili", "R2T1LiliMd10011"),
            ("黎丽", "Lili", "R2T1LiliMd10011"),
            ("lili", "Lili", "R2T1LiliMd10011"),
            ("Lili", "Lili", "R2T1LiliMd10011"),
            ("Lily", "Lili", "R2T1LiliMd10011"),
            ("爱弥斯", "Aimisi", "R2T1AimisiMd10011"),
            ("愛彌斯", "Aimisi", "R2T1AimisiMd10011"),
            ("西格莉卡", "Xigelika", "R2T1XigelikaMd10011"),
            ("希格丽卡", "Xigelika", "R2T1XigelikaMd10011"),
            ("陆·赫斯", "Luhesi", "R2T1LuhesiMd10011"),
            ("洛瑟菈", "Luosela", "R2T1LuoselaMd10011"),
            ("罗塞拉", "Luosela", "R2T1LuoselaMd10011"),
            ("达妮娅", "Daniya", "R2T1DaniyaMd10011"),
            ("绯雪", "TaiDaoNv", "R2T1TaidaonvMd10011"),
            ("弗洛洛", "Fuluoluo", "R2T1FuluoluoMd10011"),
            ("秧秧", "Yangyang", "R2T1YangyangMd10011"),
            ("琳奈", "LinNai", "R2T1LinnaeaMd20011"),
            ("莫宁", "Mone", "R2T1MoneMd10011"),
            ("千咲", "Qianxia", "R2T1QianXiaMd10011"),
            ("長離", "ChangLi", "R2T1ChangLiMd10011"),
            ("维里奈", "Jueyuan", "R2T1JueyuanMd10011"),
            ("丹瑾", "Micai", "R2T1MicaiMd10011"),
            ("卡提", "Katixiya", "R2T1KatixiyaMd10011"),
            ("大卡提", "Fuludelisi", "R2T1FuludelisiMd10011"),
            ("R2T1JinxiMd20011", "Jinxi", "R2T1JinxiMd20011"),
        ]
        for query, exp_folder, exp_model in assertions:
            matched, _ = _match_characters_detailed(chars, query)
            self.assertTrue(matched, f"Query {query!r} returned no matches")
            self.assertEqual(matched[0]["CharacterFolder"], exp_folder, f"Query {query!r} folder mismatch")
            self.assertEqual(matched[0]["ModelId"], exp_model, f"Query {query!r} model mismatch")

        m_yy, _ = _match_characters_detailed(chars, "秧秧")
        self.assertNotIn("R2T1YangyangwumaoMd10011", [c["ModelId"] for c in m_yy])

    def test_list_available_characters_cache_integration_for_lili_and_unlisted(self):
        from core.asset_extractor import list_available_characters

        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            ww_info = {"game_root": "X:\\FakeWW", "client_version": "3.8.0", "pak_counts": {"total": 438}}
            env_report = {"wuthering_waves": ww_info, "ww_extract": {"executable": "nonexistent.exe"}}
            chars = self._sample_playable_catalog() + [
                {
                    "BodyType": "FemaleM",
                    "CharacterFolder": "xingyue",
                    "ModelId": "R2T1xingyueMd10011",
                    "ModelPath": "Client/Content/Aki/Character/Role/FemaleM/xingyue/R2T1xingyueMd10011/Model/R2T1xingyueMd10011.uasset",
                    "MaterialCount": 10,
                    "TextureCount": 20,
                }
            ]
            (wd / "character_catalog_cache.json").write_text(
                json.dumps(
                    {
                        "fingerprint": {"game_root": "X:\\FakeWW", "client_version": "3.8.0", "pak_total": 438, "mounted_paks": 438},
                        "count": len(chars),
                        "characters": chars,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            r_lili = list_available_characters(env_report, [], query="莉莉", work_dir=wd)
            self.assertTrue(r_lili["ok"])
            self.assertEqual(r_lili["characters"][0]["ModelId"], "R2T1LiliMd10011")

            r_unlisted = list_available_characters(env_report, [], query="星月", work_dir=wd)
            self.assertTrue(r_unlisted["ok"])
            self.assertEqual(r_unlisted["characters"][0]["CharacterFolder"], "xingyue")
            self.assertEqual(r_unlisted["match_details"][0]["match_channel"], "english_lower_folder_exact")

            r_miss = list_available_characters(env_report, [], query="完全不存在的角色XYZ", work_dir=wd)
            self.assertTrue(r_miss["ok"])
            self.assertEqual(r_miss["count"], 0)
            self.assertIn("Lili", r_miss["available_character_folders"])


class TestBlenderWorkspaceLocalization(unittest.TestCase):
    """Tests host-locale detection and real headless Blender workspace localization without host config mutation."""

    def test_host_blender_ui_language_mapping_and_env_override(self):
        self.assertEqual(detect_host_blender_ui_language("zh-CN")["blender_languages"], ["zh_HANS", "zh_CN"])
        self.assertEqual(detect_host_blender_ui_language("zh_SG.UTF-8")["blender_languages"], ["zh_HANS", "zh_CN"])
        self.assertEqual(detect_host_blender_ui_language("zh-TW")["blender_languages"], ["zh_HANT", "zh_TW"])
        self.assertEqual(detect_host_blender_ui_language("zh-HK")["blender_languages"], ["zh_HANT", "zh_TW"])
        self.assertEqual(detect_host_blender_ui_language("ja-JP")["blender_languages"], ["ja_JP"])
        self.assertEqual(detect_host_blender_ui_language("ko-KR")["blender_languages"], ["ko_KR"])
        self.assertEqual(detect_host_blender_ui_language("en-US")["blender_languages"], ["en_US"])
        self.assertEqual(detect_host_blender_ui_language("C")["blender_languages"], ["en_US"])

        prev = os.environ.get("WW_BLENDER_UI_LANGUAGE")
        try:
            os.environ["WW_BLENDER_UI_LANGUAGE"] = "ja_JP"
            res = detect_host_blender_ui_language()
            self.assertEqual(res["source"], "env:WW_BLENDER_UI_LANGUAGE")
            self.assertEqual(res["blender_languages"], ["ja_JP"])
        finally:
            if prev is None:
                os.environ.pop("WW_BLENDER_UI_LANGUAGE", None)
            else:
                os.environ["WW_BLENDER_UI_LANGUAGE"] = prev

    def test_blender_workspace_localization_end_to_end_and_reopen(self):
        bl = detect_blender(project_root=ROOT)
        if not bl.get("found"):
            self.skipTest("Blender executable not available on test runner")

        assemble_mod_dir = (ROOT / "core") if (ROOT / "core").is_dir() else (ROOT / "ww-auto-core")
        with tempfile.TemporaryDirectory(prefix="ww_ws_loc_") as td:
            td_p = Path(td)
            zh_blend = td_p / "loc_zh.blend"
            en_blend = td_p / "loc_en.blend"
            out_json = td_p / "loc_result.json"

            driver = f"""
import bpy, json, sys
sys.path.insert(0, {str(assemble_mod_dir)!r})
import blender_assemble

bpy.ops.wm.read_factory_settings(use_empty=True)
orig_lang = bpy.context.preferences.view.language
res_zh = blender_assemble.localize_workspaces_for_host(["zh_HANS", "zh_CN"])
lang_after_zh = bpy.context.preferences.view.language
bpy.ops.wm.save_as_mainfile(filepath={str(zh_blend)!r})

bpy.ops.wm.read_factory_settings(use_empty=True)
res_en = blender_assemble.localize_workspaces_for_host(["en_US"])
bpy.ops.wm.save_as_mainfile(filepath={str(en_blend)!r})

with open({str(out_json)!r}, "w", encoding="utf-8") as f:
    json.dump({{"orig_lang": orig_lang, "lang_after_zh": lang_after_zh, "res_zh": res_zh, "res_en": res_en}}, f, ensure_ascii=False)
"""
            r1 = run_watched(
                [bl["executable"], "--background", "--factory-startup", "--python-expr", driver],
                hard_timeout_s=60,
                io_idle_timeout_s=30,
                max_retries=1,
                label="test-ws-loc-save",
            )
            self.assertTrue(r1.ok, r1.stderr[-800:])
            doc = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(doc["orig_lang"], doc["lang_after_zh"])
            self.assertTrue(doc["res_zh"]["applied"])
            self.assertEqual(doc["res_zh"]["renamed_count"], 11)
            self.assertEqual(doc["res_zh"]["active_workspace"], "布局")
            for exp_ws in ("布局", "建模", "雕刻", "UV编辑", "纹理绘制", "着色", "动画", "渲染", "合成", "几何节点", "脚本"):
                self.assertIn(exp_ws, doc["res_zh"]["workspaces"])
            self.assertFalse(doc["res_en"]["applied"])
            self.assertIn("Layout", doc["res_en"]["workspaces"])

            reopen_json = td_p / "reopen.json"
            reopen_code = f"""
import bpy, json
with open({str(reopen_json)!r}, "w", encoding="utf-8") as f:
    json.dump({{"workspaces": [w.name for w in bpy.data.workspaces], "active": bpy.context.workspace.name if bpy.context.workspace else None}}, f, ensure_ascii=False)
"""
            r2 = run_watched(
                [bl["executable"], "--background", "--factory-startup", str(zh_blend), "--python-expr", reopen_code],
                hard_timeout_s=60,
                io_idle_timeout_s=30,
                max_retries=1,
                label="test-ws-loc-reopen",
            )
            self.assertTrue(r2.ok, r2.stderr[-800:])
            rdoc = json.loads(reopen_json.read_text(encoding="utf-8"))
            self.assertEqual(rdoc["active"], "布局")
            self.assertEqual(len(rdoc["workspaces"]), 11)
            self.assertIn("动画", rdoc["workspaces"])
            self.assertNotIn("Layout", rdoc["workspaces"])

    def test_blender_viewport_auto_framing_and_action_editor(self):
        bl = detect_blender(project_root=ROOT)
        if not bl.get("found"):
            self.skipTest("Local Blender not installed; skipping viewport framing test")

        core_dir = ROOT / "core" if (ROOT / "core").is_dir() else ROOT / "ww-auto-core"
        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            framed_blend = td_p / "framed.blend"
            out_json = td_p / "frame_out.json"
            py_code = f"""
import bpy, json, sys
sys.path.insert(0, {str(core_dir)!r})
import blender_assemble as ba

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete()
bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.675))
obj = bpy.context.active_object
obj.scale = (0.25, 0.15, 0.675)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

cam_d = bpy.data.cameras.new('WW_Showcase_Camera')
cam_o = bpy.data.objects.new('WW_Showcase_Camera', cam_d)
bpy.context.scene.collection.objects.link(cam_o)
bpy.context.scene.camera = cam_o

res = ba.configure_showcase_viewports([obj], None)
bpy.ops.wm.save_as_mainfile(filepath={str(framed_blend)!r})
with open({str(out_json)!r}, 'w', encoding='utf-8') as f:
    json.dump(res, f, ensure_ascii=False)
"""
            r = run_watched(
                [bl["executable"], "--background", "--factory-startup", "--python-expr", py_code],
                hard_timeout_s=60,
                io_idle_timeout_s=30,
                max_retries=1,
                label="test-vp-framing",
            )
            self.assertTrue(r.ok, r.stderr[-800:])
            doc = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertGreater(doc["view3d_configured"], 0)
            self.assertGreater(doc["action_editors_configured"], 0)
            self.assertLess(doc["view_distance_m"], 4.0)

            reopen_json = td_p / "reopen_vp.json"
            reopen_code = f"""
import bpy, json
layout_ws = bpy.data.workspaces.get('Layout')
anim_ws = bpy.data.workspaces.get('Animation')
l_dist, l_shade, a_mode = None, None, None
if layout_ws:
    for area in layout_ws.screens[0].areas:
        if area.type == 'VIEW_3D':
            l_dist = round(area.spaces.active.region_3d.view_distance, 3)
            l_shade = area.spaces.active.shading.type
            break
if anim_ws:
    for area in anim_ws.screens[0].areas:
        if area.type == 'DOPESHEET_EDITOR':
            a_mode = area.spaces.active.mode
            break
with open({str(reopen_json)!r}, 'w', encoding='utf-8') as f:
    json.dump({{'l_dist': l_dist, 'l_shade': l_shade, 'a_mode': a_mode}}, f)
"""
            r2 = run_watched(
                [bl["executable"], "--background", "--factory-startup", str(framed_blend), "--python-expr", reopen_code],
                hard_timeout_s=60,
                io_idle_timeout_s=30,
                max_retries=1,
                label="test-vp-reopen",
            )
            self.assertTrue(r2.ok, r2.stderr[-800:])
            rd = json.loads(reopen_json.read_text(encoding="utf-8"))
            self.assertIsNotNone(rd["l_dist"])
            self.assertLess(rd["l_dist"], 3.5)
            self.assertEqual(rd["l_shade"], "MATERIAL")
            self.assertEqual(rd["a_mode"], "ACTION")


class TestSecurityAndPrivacyHardening(unittest.TestCase):
    def test_zip_slip_and_symlink_blocked(self):
        import zipfile
        from core.env_bootstrap import safe_extract_zip

        with tempfile.TemporaryDirectory() as td:
            td_p = Path(td)
            dest = td_p / "extract_root"

            evil_zip = td_p / "zip_slip.zip"
            with zipfile.ZipFile(evil_zip, "w") as zf:
                zf.writestr("../../escaped.txt", "pwned")
            with self.assertRaises(ValueError):
                safe_extract_zip(evil_zip, dest)
            self.assertFalse((td_p / "escaped.txt").exists())

            evil_abs = td_p / "zip_abs.zip"
            with zipfile.ZipFile(evil_abs, "w") as zf:
                zf.writestr("C:/Windows/Temp/evil.txt", "pwned")
            with self.assertRaises(ValueError):
                safe_extract_zip(evil_abs, dest)

            evil_sym = td_p / "zip_sym.zip"
            with zipfile.ZipFile(evil_sym, "w") as zf:
                zi = zipfile.ZipInfo("link_out")
                zi.external_attr = (0o120777 << 16)
                zf.writestr(zi, "/etc/passwd")
            with self.assertRaises(ValueError):
                safe_extract_zip(evil_sym, dest)

            good_zip = td_p / "good.zip"
            with zipfile.ZipFile(good_zip, "w") as zf:
                zf.writestr("sub/hello.txt", "ok")
            extracted = safe_extract_zip(good_zip, dest)
            self.assertEqual(len(extracted), 1)
            self.assertEqual((dest / "sub" / "hello.txt").read_text(encoding="utf-8"), "ok")

    def test_https_and_host_allowlist_enforced(self):
        from core.env_bootstrap import _validate_https_url

        self.assertTrue(_validate_https_url("https://download.blender.org/release/Blender5.2/blender.zip").startswith("https://"))
        self.assertTrue(_validate_https_url("https://api.github.com/repos/4sval/FModel/releases/latest").startswith("https://"))
        self.assertTrue(_validate_https_url("https://github.com/WorkingRobot/OodleUE/releases/download/2026-06-04-1357/clang-cl-x64-release.zip").startswith("https://"))

        with self.assertRaises(ValueError):
            _validate_https_url("http://download.blender.org/release/Blender5.2/blender.zip")
        with self.assertRaises(ValueError):
            _validate_https_url("https://evil.example.com/blender.zip")
        with self.assertRaises(ValueError):
            _validate_https_url("file:///C:/Windows/System32/drivers/etc/hosts")

    def test_safe_slug_blocks_traversal_and_win_reserved_names(self):
        from core.pipeline import _safe_slug

        self.assertEqual(_safe_slug("../../Windows/System32"), "Windows_System32")
        self.assertEqual(_safe_slug("..\\..\\evil; calc.exe"), "evil_calc_exe")
        self.assertEqual(_safe_slug("CON"), "char_CON")
        self.assertEqual(_safe_slug("nul"), "char_nul")
        self.assertEqual(_safe_slug("COM1"), "char_COM1")
        self.assertEqual(_safe_slug("LPT9"), "char_LPT9")
        self.assertEqual(_safe_slug("...---___"), "character")
        self.assertLessEqual(len(_safe_slug("A" * 500)), 64)
        self.assertNotIn("\x00", _safe_slug("Lili\x00evil"))

    def test_self_audit_catches_injected_secrets_paths_and_banned_tokens(self):
        from core.self_audit import BANNED_COMPLIANCE_TOKENS_RE, HARDCODED_AES_HEX_RE, LEAKED_DEV_PATH_PATTERNS, LEAKED_SECRET_TOKEN_RE

        self.assertTrue(any(p.search(r"C:\Users\alice\Documents\secret.py") for p in LEAKED_DEV_PATH_PATTERNS))
        self.assertFalse(any(p.search(r"C:\Users\<YourName>\AppData") for p in LEAKED_DEV_PATH_PATTERNS))
        self.assertIsNotNone(HARDCODED_AES_HEX_RE.search("0x" + "AB" * 32))
        self.assertIsNotNone(LEAKED_SECRET_TOKEN_RE.search("ghp_" + "A" * 30))
        self.assertIsNotNone(LEAKED_SECRET_TOKEN_RE.search("https://www.bilibili.com/video/BV1xx?vd_source=0123456789abcdef0123"))
        self.assertIsNotNone(LEAKED_SECRET_TOKEN_RE.search("-----BEGIN PRIVATE KEY-----"))
        self.assertIsNotNone(BANNED_COMPLIANCE_TOKENS_RE.search("https://example.com/wuwa-keys/keys.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
