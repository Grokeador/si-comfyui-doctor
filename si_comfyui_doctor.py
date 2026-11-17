#!/usr/bin/env python3
"""
SI-ComfyUI-Doctor — Fix ComfyUI & Flux CUDA Out-of-Memory, Silent Pagefile Crashes,
99% VAE Decode OOM & Custom Nodes Package Conflicts on Windows (100% Python Stdlib).
"""

from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from comfyui_doctor_engine import (
    audit_windows_memory_and_gpu,
    default_state_dir,
    discover_comfyui_roots,
    ensure_sample_comfy_workspace,
    patch_comfyui_bat_flags,
    patch_workflow_tiled_vae,
    rollback_file_from_backup,
    scan_custom_nodes_conflicts,
)


APP_VERSION = "1.0.0"


def _render_ui(
    view: str = "audit",
    custom_home: Path | None = None,
    banner: str = "",
    last_patch: dict[str, Any] | None = None,
    last_wf: dict[str, Any] | None = None,
    last_nodes: dict[str, Any] | None = None,
) -> str:
    sdir = default_state_dir(custom_home)
    sample = ensure_sample_comfy_workspace(sdir / "sample_comfyui")
    hw = audit_windows_memory_and_gpu()
    installs = discover_comfyui_roots(extra_paths=[sample["root"]], custom_home=custom_home)

    tabs = [
        ("audit", "Step 1: GPU, Pagefile & ComfyUI Audit"),
        ("vram", "Step 2: Fix Dynamic VRAM & Workflow 99% OOM"),
        ("nodes", "Step 3: Scan Broken Custom Nodes"),
        ("bonus", "Bonus: 1-Click Rollback & Flux Profile"),
    ]
    tab_html = "".join(f'<a href="/?view={k}" class="tab {"active" if view == k else ""}">{html.escape(lbl)}</a>' for k, lbl in tabs)
    banner_html = f'<div class="banner">{html.escape(banner)}</div>' if banner else ""

    if view == "vram":
        bat_txt = last_patch.get("after_preview", Path(sample["bat"]).read_text(encoding="utf-8", errors="ignore")) if last_patch else Path(sample["bat"]).read_text(encoding="utf-8", errors="ignore")
        wf_txt = json.dumps(last_wf, indent=2) if last_wf else Path(sample["workflow"]).read_text(encoding="utf-8", errors="ignore")
        content = f"""
        <div class="grid-2">
          <div class="panel">
            <h2>Step 2A: Fix ComfyUI Dynamic VRAM / aimdo OOM Crash</h2>
            <p class="sub">Automatically saves SHA-256 backup before adding calibrated flags for your GPU ({html.escape(str(hw['recommended_flags']))}).</p>
            <form method="POST" action="/api/patch-bat" style="display:flex;gap:8px;margin-bottom:12px;">
              <input class="inp" type="text" name="bat_path" value="{html.escape(str(sample['bat']))}" />
              <button class="btn primary" type="submit">1-Click Patch .BAT Safely</button>
            </form>
            <pre class="code">{html.escape(bat_txt)}</pre>
          </div>
          <div class="panel">
            <h2>Step 2B: Convert VAEDecode &rarr; VAEDecodeTiled (99% Crash Fix)</h2>
            <p class="sub">Stops Flux workflows from crashing right at 99% decode completion while preserving every link.</p>
            <form method="POST" action="/api/patch-workflow" style="display:flex;gap:8px;margin-bottom:12px;">
              <input class="inp" type="text" name="wf_path" value="{html.escape(str(sample['workflow']))}" />
              <button class="btn primary" type="submit">Patch Workflow JSON Now</button>
            </form>
            <pre class="code">{html.escape(wf_txt[:900])}</pre>
          </div>
        </div>
        """
    elif view == "nodes":
        nodes_res = last_nodes or scan_custom_nodes_conflicts(sample["custom_nodes"])
        content = f"""
        <div class="grid-2">
          <div class="panel">
            <h2>Step 3: Custom Nodes Package Conflict Scanner</h2>
            <p class="sub">Finds nodes forcing NumPy 1.x vs 2.x clashes or pinned PyTorch versions that silently kill CUDA.</p>
            <form method="POST" action="/api/scan-nodes" style="display:flex;gap:8px;margin-bottom:12px;">
              <input class="inp" type="text" name="nodes_dir" value="{html.escape(str(sample['custom_nodes']))}" />
              <button class="btn primary" type="submit">Scan custom_nodes Now</button>
            </form>
            <div class="metrics">
              <div class="m"><span>Nodes Scanned</span><strong>{nodes_res.get('total_custom_nodes', 0)}</strong></div>
              <div class="m"><span>Conflicts Found</span><strong style="color:#f87171">{nodes_res.get('conflict_count', 0)}</strong></div>
              <div class="m"><span>NumPy 1x vs 2x Clash</span><strong style="color:#fbbf24">{nodes_res.get('numpy_1x_vs_2x_clash', False)}</strong></div>
              <div class="m"><span>Status</span><strong style="color:#34d399">Backup Ready</strong></div>
            </div>
          </div>
          <div class="panel">
            <h2>Detected Dependency Traps</h2>
            <pre class="code">{html.escape(json.dumps(nodes_res, indent=2)[:1100])}</pre>
          </div>
        </div>
        """
    elif view == "bonus":
        bkp_files = sorted((sdir / "sample_comfyui" / "_si_comfy_backups").glob("*.bak"))
        bkp_txt = "\n".join(f"{p.name} ({p.stat().st_size} B)" for p in bkp_files) or "No backups modified yet — run Step 2 first!"
        content = f"""
        <div class="grid-2">
          <div class="panel">
            <h2>Bonus: 1-Click SHA-256 Rollback &amp; Exact Flux Profile</h2>
            <p class="sub">Recommended for your GPU: <strong>{html.escape(hw['flux_profile'])}</strong></p>
            <form method="POST" action="/api/rollback-last" style="margin-bottom:12px;">
              <button class="btn warn" type="submit">1-Click Restore Original .BAT &amp; Workflow</button>
            </form>
            <pre class="code">Saved SHA-256 Backups:
{html.escape(bkp_txt)}</pre>
          </div>
          <div class="panel">
            <h2>Pagefile &amp; Flux Silent Crash Prevention Checklist</h2>
            <pre class="code">1. T5-XXL FP16 consumes 24GB+ commit RAM silently -> Use T5-XXL FP8!
2. Set Windows Virtual Pagefile >= 48GB on NVMe SSD to stop silent Python kills
3. Add --disable-dynamic-vram if CUDA OOM triggers with free VRAM
4. Use VAEDecodeTiled (512px tiles) above 1.2 Megapixels</pre>
          </div>
        </div>
        """
    else:
        inst_txt = "\n".join(f"- Root: {i['root']}\n  bat={i['bat_path']} | custom_nodes={i['custom_nodes_dir']}" for i in installs)
        pf_color = "#f87171" if hw["flux_pagefile_crash_risk"] else "#34d399"
        content = f"""
        <div class="grid-2">
          <div class="panel">
            <h2>Step 1: Windows VRAM, RAM &amp; Pagefile Audit</h2>
            <div class="metrics">
              <div class="m"><span>GPU</span><strong style="color:#38bdf8">{html.escape(hw['gpu_name'][:26])}</strong></div>
              <div class="m"><span>Physical RAM</span><strong>{hw['ram_free_gb']} / {hw['ram_total_gb']} GB free</strong></div>
              <div class="m"><span>Windows Commit Limit</span><strong style="color:{pf_color}">{hw['commit_limit_gb']} GB</strong></div>
              <div class="m"><span>Pagefile Silent-Crash Risk</span><strong style="color:{pf_color}">{hw['flux_pagefile_crash_risk']}</strong></div>
            </div>
            <pre class="code">Calibrated Profile:
{html.escape(hw['flux_profile'])}

Recommended Flags: {' '.join(hw['recommended_flags'])}</pre>
          </div>
          <div class="panel">
            <h2>Detected ComfyUI Installations &amp; Quick Test Rig</h2>
            <pre class="code" style="min-height:220px;">{html.escape(inst_txt)}</pre>
          </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" /><title>SI-ComfyUI-Doctor {APP_VERSION}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, sans-serif; }}
  body {{ background: #060a13; color: #f8fafc; padding: 20px 28px; }}
  .topbar {{ display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; background: #0d1526; border: 2px solid #1e293b; border-radius: 12px; margin-bottom: 14px; }}
  .brand {{ font-size: 22px; font-weight: 800; }}
  .brand span {{ color: #a78bfa; }}
  .badge {{ font-size: 13px; padding: 5px 12px; border-radius: 999px; border: 1px solid #34d399; color: #34d399; font-weight: 700; }}
  .tabs {{ display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }}
  .tab {{ text-decoration: none; padding: 9px 15px; border-radius: 8px; background: #0d1526; border: 2px solid #1e293b; color: #94a3b8; font-weight: 700; font-size: 14px; }}
  .tab.active {{ background: #111c33; border-color: #a78bfa; color: #f8fafc; }}
  .banner {{ padding: 11px 16px; margin-bottom: 14px; border-radius: 8px; border: 2px solid #34d399; background: #0f2922; color: #ecfdf5; font-weight: 600; font-size: 14px; }}
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}
  .panel {{ background: #0d1526; border: 2px solid #1e293b; border-radius: 12px; padding: 18px; }}
  h2 {{ font-size: 18px; margin-bottom: 10px; color: #a78bfa; }}
  .sub {{ color: #94a3b8; font-size: 13px; margin-bottom: 12px; }}
  .metrics {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 12px; }}
  .m {{ background: #04070e; border: 1px solid #1e293b; border-radius: 8px; padding: 10px; }}
  .m span {{ display: block; font-size: 11px; color: #94a3b8; text-transform: uppercase; }}
  .m strong {{ font-size: 14px; }}
  pre.code {{ background: #04070e; border: 1px solid #1e293b; border-radius: 8px; padding: 12px; font-family: 'Cascadia Code', Consolas, monospace; font-size: 13px; line-height: 1.45; white-space: pre-wrap; color: #e2e8f0; }}
  .btn {{ cursor: pointer; padding: 10px 14px; border-radius: 8px; border: 1px solid #334155; background: #1e293b; color: #f8fafc; font-weight: 700; font-size: 13px; }}
  .btn.primary {{ border-color: #a78bfa; background: #a78bfa; color: #020617; }}
  .btn.warn {{ border-color: #f59e0b; background: #f59e0b; color: #1c1917; }}
  .inp {{ flex: 1; padding: 8px 12px; border-radius: 8px; border: 1px solid #334155; background: #04070e; color: #f8fafc; font-size: 13px; }}
</style></head>
<body>
  <div class="topbar">
    <div class="brand">SI-ComfyUI-<span>Doctor {APP_VERSION}</span> &bull; Flux &amp; CUDA OOM Rescue Suite</div>
    <span class="badge">SHA-256 Safe Patcher + 1-Click Rollback</span>
  </div>
  <div class="tabs">{tabs_html}</div>
  {banner_html}
  {content}
</body></html>"""


def start_ui_server(port: int = 8796, custom_home: Path | None = None) -> ThreadingHTTPServer:
    state: dict[str, Any] = {
        "banner": "",
        "last_patch": None,
        "last_wf": None,
        "last_nodes": None,
        "undo_pairs": [],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _redirect(self, loc: str, msg: str) -> None:
            state["banner"] = msg
            self.send_response(303)
            self.send_header("Location", loc)
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            view = (qs.get("view") or ["audit"])[0]
            msg = state["banner"]
            state["banner"] = ""
            body = _render_ui(
                view=view,
                custom_home=custom_home,
                banner=msg,
                last_patch=state["last_patch"],
                last_wf=state["last_wf"],
                last_nodes=state["last_nodes"],
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            cl = int(self.headers.get("Content-Length", "0") or "0")
            raw = self.rfile.read(cl).decode("utf-8", errors="ignore")
            form = urllib.parse.parse_qs(raw)

            if self.path == "/api/patch-bat":
                bpath = (form.get("bat_path") or [""])[0].strip().strip('"')
                hw = audit_windows_memory_and_gpu()
                res = patch_comfyui_bat_flags(bpath, flags=hw["recommended_flags"])
                if res.get("ok"):
                    res["after_preview"] = Path(bpath).read_text(encoding="utf-8", errors="ignore")
                    state["last_patch"] = res
                    state["undo_pairs"].append((bpath, res["backup_path"]))
                    self._redirect("/?view=vram", f"Patched {Path(bpath).name} with {hw['recommended_flags']} (SHA-256 backup saved)!")
                else:
                    self._redirect("/?view=vram", f"Patch error: {res.get('error')}")
            elif self.path == "/api/patch-workflow":
                wpath = (form.get("wf_path") or [""])[0].strip().strip('"')
                res = patch_workflow_tiled_vae(wpath)
                state["last_wf"] = res
                if res.get("ok"):
                    state["undo_pairs"].append((wpath, res["backup_path"]))
                    self._redirect("/?view=vram", f"Converted {res['vae_nodes_converted_to_tiled']} VAEDecode node(s) -> VAEDecodeTiled cleanly!")
                else:
                    self._redirect("/?view=vram", f"Workflow error: {res.get('error')}")
            elif self.path == "/api/scan-nodes":
                ndir = (form.get("nodes_dir") or [""])[0].strip().strip('"')
                res = scan_custom_nodes_conflicts(ndir)
                state["last_nodes"] = res
                self._redirect("/?view=nodes", f"Scanned {res.get('total_custom_nodes', 0)} custom_nodes -> {res.get('conflict_count', 0)} conflict(s) detected.")
            elif self.path == "/api/rollback-last":
                restored = []
                for tgt, bkp in state["undo_pairs"]:
                    r = rollback_file_from_backup(tgt, bkp)
                    if r.get("ok"):
                        restored.append(Path(tgt).name)
                state["undo_pairs"].clear()
                self._redirect("/?view=bonus", f"Restored cleanly: {', '.join(restored) if restored else 'No pending changes to undo.'}")
            else:
                self._redirect("/?view=audit", "OK")

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="SI-ComfyUI-Doctor CLI & Studio UI")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("audit", help="Inspect Windows RAM/VRAM/Pagefile and ComfyUI roots")
    p_bat = sub.add_parser("patch-bat", help="Safely patch run_nvidia_gpu.bat for Dynamic VRAM")
    p_bat.add_argument("bat_path", type=Path)

    p_wf = sub.add_parser("patch-workflow", help="Convert VAEDecode -> VAEDecodeTiled in workflow JSON")
    p_wf.add_argument("workflow_json", type=Path)

    p_nd = sub.add_parser("scan-nodes", help="Scan custom_nodes for PyTorch/NumPy conflicts")
    p_nd.add_argument("custom_nodes_dir", type=Path)

    p_ui = sub.add_parser("ui", help="Start Studio Web UI on port 8796")
    p_ui.add_argument("--port", type=int, default=8796)

    args = parser.parse_args()
    cmd = args.cmd or "ui"
    if cmd == "audit":
        hw = audit_windows_memory_and_gpu()
        print(json.dumps({"hardware": hw, "installs": discover_comfyui_roots()}, indent=2))
    elif cmd == "patch-bat":
        print(json.dumps(patch_comfyui_bat_flags(args.bat_path), indent=2))
    elif cmd == "patch-workflow":
        print(json.dumps(patch_workflow_tiled_vae(args.workflow_json), indent=2))
    elif cmd == "scan-nodes":
        print(json.dumps(scan_custom_nodes_conflicts(args.custom_nodes_dir), indent=2))
    else:
        srv = start_ui_server(port=args.port)
        url = f"http://127.0.0.1:{srv.server_address[1]}/"
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        if edge.exists():
            subprocess.Popen([str(edge), f"--app={url}", "--window-size=1480,920"])
        else:
            webbrowser.open(url)
        print(f"SI-ComfyUI-Doctor active at {url}")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            srv.shutdown()


if __name__ == "__main__":
    main()
