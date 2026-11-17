import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

from comfyui_doctor_engine import (
    audit_windows_memory_and_gpu,
    ensure_sample_comfy_workspace,
    patch_comfyui_bat_flags,
    patch_workflow_tiled_vae,
    rollback_file_from_backup,
    scan_custom_nodes_conflicts,
)
from si_comfyui_doctor import start_ui_server


class SiComfyUiDoctorTests(unittest.TestCase):
    def test_bat_patch_and_sha256_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = ensure_sample_comfy_workspace(Path(tmp) / "ComfyUI_windows_portable")
            orig = ws["bat"].read_text(encoding="utf-8")
            res = patch_comfyui_bat_flags(ws["bat"], flags=["--disable-dynamic-vram", "--lowvram"])
            self.assertTrue(res["ok"])
            self.assertTrue(res["patched"])
            updated = ws["bat"].read_text(encoding="utf-8")
            self.assertIn("--disable-dynamic-vram", updated)
            self.assertIn("--lowvram", updated)

            rb = rollback_file_from_backup(ws["bat"], res["backup_path"])
            self.assertTrue(rb["ok"])
            self.assertEqual(ws["bat"].read_text(encoding="utf-8"), orig)

    def test_workflow_vae_tiled_conversion_both_formats_and_nodes_scanner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            td = Path(tmp)
            ws = ensure_sample_comfy_workspace(td / "Comfy")
            # UI LiteGraph workflow
            wf_res = patch_workflow_tiled_vae(ws["workflow"])
            self.assertTrue(wf_res["ok"])
            self.assertEqual(wf_res["vae_nodes_converted_to_tiled"], 1)
            self.assertGreaterEqual(len(wf_res["high_res_warnings"]), 1)
            patched_json = json.loads(ws["workflow"].read_text(encoding="utf-8"))
            self.assertEqual(patched_json["nodes"][2]["type"], "VAEDecodeTiled")

            # API Prompt JSON format
            api_wf = td / "api_prompt.json"
            api_wf.write_text(json.dumps({
                "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1600, "height": 1200}},
                "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            }), encoding="utf-8")
            api_res = patch_workflow_tiled_vae(api_wf)
            self.assertEqual(api_res["vae_nodes_converted_to_tiled"], 1)
            api_after = json.loads(api_wf.read_text(encoding="utf-8"))
            self.assertEqual(api_after["8"]["class_type"], "VAEDecodeTiled")
            self.assertEqual(api_after["8"]["inputs"]["tile_size"], 512)

            # Custom nodes conflict detector
            nd_res = scan_custom_nodes_conflicts(ws["custom_nodes"])
            self.assertTrue(nd_res["ok"])
            self.assertTrue(nd_res["numpy_1x_vs_2x_clash"])
            self.assertGreaterEqual(nd_res["conflict_count"], 2)

    def test_hw_audit_and_web_studio_ui_routes(self) -> None:
        hw = audit_windows_memory_and_gpu()
        self.assertTrue(hw["ok"])
        self.assertIn("flux_profile", hw)

        with tempfile.TemporaryDirectory() as tmp:
            srv = start_ui_server(port=0, custom_home=Path(tmp))
            port = srv.server_address[1]
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/?view=audit", timeout=5) as r:
                    self.assertEqual(r.status, 200)
                    self.assertIn("SI-ComfyUI-", r.read().decode("utf-8"))
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/?view=nodes", timeout=5) as r2:
                    self.assertEqual(r2.status, 200)
                    self.assertIn("numpy_1x_vs_2x_clash", r2.read().decode("utf-8"))
            finally:
                srv.shutdown()
                srv.server_close()


if __name__ == "__main__":
    unittest.main()
