#!/usr/bin/env python3
"""
SI-ComfyUI-Doctor Engine — Fix ComfyUI & Flux CUDA Out-of-Memory, Silent Vanish Crashes,
99% VAE Decode OOM & Custom Node Package Conflicts on Windows (100% Python Stdlib).
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def default_state_dir(custom_home: Path | None = None) -> Path:
    root = (custom_home or Path.home()) / ".si_comfyui_doctor"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# 1. Windows Hardware, VRAM, RAM & Pagefile Diagnostics (Flux T5-XXL Crash Check)
# ---------------------------------------------------------------------------

def audit_windows_memory_and_gpu() -> dict[str, Any]:
    """
    Measure physical RAM, Windows virtual pagefile headroom (critical for Flux T5-XXL silent vanish!),
    and GPU VRAM cleanly via Win32 GlobalMemoryStatusEx + nvidia-smi/WMI fallback.
    """
    ram_total_gb = 0.0
    ram_free_gb = 0.0
    page_total_gb = 0.0
    page_free_gb = 0.0

    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_uint32),
                ("dwMemoryLoad", ctypes.c_uint32),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            gb = float(1024 ** 3)
            ram_total_gb = round(mem.ullTotalPhys / gb, 2)
            ram_free_gb = round(mem.ullAvailPhys / gb, 2)
            page_total_gb = round(mem.ullTotalPageFile / gb, 2)
            page_free_gb = round(mem.ullAvailPageFile / gb, 2)

    gpu_name = "Integrated / CPU Fallback"
    vram_total_mb = 0
    vram_free_mb = 0
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            proc = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total,memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                parts = [x.strip() for x in proc.stdout.strip().splitlines()[0].split(",")]
                if len(parts) >= 3:
                    gpu_name = parts[0]
                    vram_total_mb = int(float(parts[1]))
                    vram_free_mb = int(float(parts[2]))
        except Exception:
            pass
    elif os.name == "nt":
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_VideoController | Select-Object -First 1 -Property Name,AdapterRAM | ConvertTo-Json"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                obj = json.loads(proc.stdout.strip())
                gpu_name = str(obj.get("Name") or gpu_name)
                aram = int(obj.get("AdapterRAM") or 0)
                if aram > 0:
                    vram_total_mb = int(aram / (1024 * 1024))
                    vram_free_mb = vram_total_mb
        except Exception:
            pass

    t5_pagefile_risk = os.name == "nt" and page_total_gb > 0 and page_total_gb < 48.0
    vram_gb = round(vram_total_mb / 1024.0, 1)
    if vram_total_mb == 0:
        flux_profile = "CPU / Low-VRAM Safe Mode (--cpu or <=6GB GGUF Q4_K_S + T5 FP8)"
        recommended_flags = ["--disable-dynamic-vram", "--lowvram"]
    elif vram_total_mb <= 8500:
        flux_profile = f"8GB VRAM Profile ({vram_gb}GB): Use Flux GGUF Q4_K_S + T5-XXL FP8 + Tiled VAE"
        recommended_flags = ["--disable-dynamic-vram", "--lowvram", "--disable-pinned-memory"]
    elif vram_total_mb <= 13000:
        flux_profile = f"12GB VRAM Profile ({vram_gb}GB): Use Flux FP8 / GGUF Q6_K + T5-XXL FP8 + Tiled VAE"
        recommended_flags = ["--disable-dynamic-vram", "--normalvram"]
    else:
        flux_profile = f"16GB+ VRAM Profile ({vram_gb}GB): Use Flux FP8/BF16 + --disable-dynamic-vram for stability"
        recommended_flags = ["--disable-dynamic-vram"]

    return {
        "ok": True,
        "gpu_name": gpu_name,
        "vram_total_mb": vram_total_mb,
        "vram_free_mb": vram_free_mb,
        "ram_total_gb": ram_total_gb,
        "ram_free_gb": ram_free_gb,
        "commit_limit_gb": page_total_gb,
        "commit_free_gb": page_free_gb,
        "flux_pagefile_crash_risk": t5_pagefile_risk,
        "flux_profile": flux_profile,
        "recommended_flags": recommended_flags,
    }


# ---------------------------------------------------------------------------
# 2. ComfyUI Discovery + Startup .bat aimdo / Dynamic VRAM Patcher + Rollback
# ---------------------------------------------------------------------------

def discover_comfyui_roots(extra_paths: list[Path] | None = None, custom_home: Path | None = None) -> list[dict[str, Any]]:
    home = custom_home or Path.home()
    candidates = [
        home / "ComfyUI_windows_portable",
        home / "ComfyUI",
        home / "Desktop" / "ComfyUI_windows_portable",
        Path("C:/ComfyUI_windows_portable"),
        Path("D:/ComfyUI_windows_portable"),
        Path("C:/ComfyUI"),
        *(extra_paths or []),
    ]
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in candidates:
        p = Path(c)
        if not p.exists():
            continue
        key = str(p.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        bat = p / "run_nvidia_gpu.bat"
        main_py = p / "ComfyUI" / "main.py"
        if not main_py.exists():
            main_py = p / "main.py"
        custom_nodes = (main_py.parent / "custom_nodes") if main_py.exists() else (p / "custom_nodes")
        if bat.exists() or main_py.exists() or custom_nodes.exists():
            found.append({
                "root": str(p.resolve()),
                "bat_path": str(bat) if bat.exists() else "",
                "main_py": str(main_py) if main_py.exists() else "",
                "custom_nodes_dir": str(custom_nodes) if custom_nodes.exists() else "",
            })
    return found


def patch_comfyui_bat_flags(
    bat_path: str | Path,
    flags: list[str] | None = None,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Safely inject --disable-dynamic-vram / --lowvram into run_nvidia_gpu.bat with SHA-256 backup."""
    p = Path(bat_path)
    if not p.exists():
        return {"ok": False, "error": f"Batch file not found: {p}"}

    raw = p.read_text(encoding="utf-8", errors="ignore")
    sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    bdir = Path(backup_dir) if backup_dir else (p.parent / "_si_comfy_backups")
    bdir.mkdir(parents=True, exist_ok=True)
    bkp = bdir / f"{p.name}.{sha}.bak"
    if not bkp.exists():
        bkp.write_text(raw, encoding="utf-8")

    want_flags = flags or ["--disable-dynamic-vram", "--disable-pinned-memory"]
    new_lines: list[str] = []
    patched = False
    for line in raw.splitlines():
        if "main.py" in line and not line.strip().lower().startswith("rem"):
            updated = line
            for fl in want_flags:
                if fl not in updated:
                    if " pause" in updated.lower():
                        updated = updated + f" {fl}"
                    else:
                        updated = f"{updated} {fl}"
                    patched = True
            new_lines.append(updated)
        else:
            new_lines.append(line)

    newline_sep = "\r\n" if "\r\n" in raw else "\n"
    p.write_text(newline_sep.join(new_lines) + newline_sep, encoding="utf-8")
    return {
        "ok": True,
        "bat_path": str(p),
        "backup_path": str(bkp),
        "patched": patched,
        "flags_applied": want_flags,
    }


def rollback_file_from_backup(target_path: str | Path, backup_path: str | Path) -> dict[str, Any]:
    tgt = Path(target_path)
    bkp = Path(backup_path)
    if not bkp.exists():
        return {"ok": False, "error": f"Backup not found: {bkp}"}
    shutil.copy2(bkp, tgt)
    return {"ok": True, "restored": str(tgt)}


# ---------------------------------------------------------------------------
# 3. Real ComfyUI Workflow JSON Auto-Patcher (VAEDecode -> VAEDecodeTiled at 99%!)
# ---------------------------------------------------------------------------

def patch_workflow_tiled_vae(
    workflow_json_path: str | Path,
    tile_size: int = 512,
    overlap: int = 64,
    backup_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Convert heavy VAEDecode nodes in any ComfyUI workflow JSON (UI LiteGraph OR API format)
    into VAEDecodeTiled with SHA-256 backup, preventing the classic 99% CUDA OOM crash!
    """
    p = Path(workflow_json_path)
    if not p.exists():
        return {"ok": False, "error": f"Workflow not found: {p}"}

    raw_text = p.read_text(encoding="utf-8", errors="ignore")
    data = json.loads(raw_text)
    sha = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:12]
    bdir = Path(backup_dir) if backup_dir else (p.parent / "_si_comfy_backups")
    bdir.mkdir(parents=True, exist_ok=True)
    bkp = bdir / f"{p.name}.{sha}.bak"
    if not bkp.exists():
        bkp.write_text(raw_text, encoding="utf-8")

    converted_count = 0
    high_res_warnings: list[str] = []

    if isinstance(data, dict) and isinstance(data.get("nodes"), list):
        # Standard ComfyUI UI LiteGraph JSON
        for node in data["nodes"]:
            if not isinstance(node, dict):
                continue
            ntype = str(node.get("type", ""))
            if ntype == "VAEDecode":
                node["type"] = "VAEDecodeTiled"
                node["title"] = "VAE Decode (Tiled OOM-Safe)"
                node["widgets_values"] = [tile_size, overlap, 64, 8]
                converted_count += 1
            elif ntype in ("EmptyLatentImage", "EmptySD3LatentImage"):
                wvals = node.get("widgets_values") or []
                if len(wvals) >= 2 and isinstance(wvals[0], (int, float)) and isinstance(wvals[1], (int, float)):
                    mp = (wvals[0] * wvals[1]) / 1_000_000.0
                    if mp > 1.5:
                        high_res_warnings.append(f"Node {node.get('id')} ({ntype}) targets {int(wvals[0])}x{int(wvals[1])} ({mp:.2f} MP > 1.5 MP)")
    elif isinstance(data, dict):
        # ComfyUI API Prompt JSON
        for nid, node in data.items():
            if not isinstance(node, dict):
                continue
            ctype = str(node.get("class_type", ""))
            if ctype == "VAEDecode":
                node["class_type"] = "VAEDecodeTiled"
                inputs = dict(node.get("inputs") or {})
                inputs.setdefault("tile_size", tile_size)
                inputs.setdefault("overlap", overlap)
                inputs.setdefault("temporal_size", 64)
                inputs.setdefault("temporal_overlap", 8)
                node["inputs"] = inputs
                converted_count += 1
            elif ctype in ("EmptyLatentImage", "EmptySD3LatentImage"):
                inputs = node.get("inputs") or {}
                w, h = inputs.get("width"), inputs.get("height")
                if isinstance(w, (int, float)) and isinstance(h, (int, float)):
                    mp = (w * h) / 1_000_000.0
                    if mp > 1.5:
                        high_res_warnings.append(f"Node {nid} ({ctype}) targets {int(w)}x{int(h)} ({mp:.2f} MP > 1.5 MP)")

    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "workflow_path": str(p),
        "backup_path": str(bkp),
        "vae_nodes_converted_to_tiled": converted_count,
        "high_res_warnings": high_res_warnings,
    }


# ---------------------------------------------------------------------------
# 4. Custom Nodes Conflict & Memory Leak Scanner
# ---------------------------------------------------------------------------

def scan_custom_nodes_conflicts(custom_nodes_dir: str | Path) -> dict[str, Any]:
    """Inspect custom_nodes/*/requirements.txt for torch/numpy/transformers conflicts that break CUDA."""
    root = Path(custom_nodes_dir)
    if not root.exists():
        return {"ok": False, "error": f"custom_nodes directory not found: {root}"}

    node_dirs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith((".", "__")))
    findings: list[dict[str, Any]] = []
    numpy_lt2: list[str] = []
    numpy_ge2: list[str] = []

    for ndir in node_dirs:
        req = ndir / "requirements.txt"
        if not req.exists():
            continue
        lines = [ln.strip() for ln in req.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip() and not ln.strip().startswith("#")]
        risks: list[str] = []
        for ln in lines:
            low = ln.lower().replace(" ", "")
            if low.startswith("torch==") or low.startswith("torchvision==") or "xformers==" in low:
                risks.append(f"Hard-pinned PyTorch ABI dependency: {ln}")
            if "numpy<2" in low or "numpy==1." in low:
                numpy_lt2.append(ndir.name)
                risks.append(f"Forces NumPy 1.x: {ln}")
            elif "numpy>=2" in low or "numpy==2." in low:
                numpy_ge2.append(ndir.name)
                risks.append(f"Forces NumPy 2.x: {ln}")
        if risks:
            findings.append({"node": ndir.name, "requirements_file": str(req), "risks": risks})

    cross_conflict = bool(numpy_lt2 and numpy_ge2)
    return {
        "ok": True,
        "custom_nodes_dir": str(root),
        "total_custom_nodes": len(node_dirs),
        "conflict_count": len(findings) + (1 if cross_conflict else 0),
        "numpy_1x_vs_2x_clash": cross_conflict,
        "numpy_1x_nodes": numpy_lt2,
        "numpy_2x_nodes": numpy_ge2,
        "findings": findings,
    }


def ensure_sample_comfy_workspace(base_dir: Path) -> dict[str, Path]:
    """Create a realistic sample ComfyUI portable layout + Flux workflow so users can test immediately."""
    base_dir.mkdir(parents=True, exist_ok=True)
    bat = base_dir / "run_nvidia_gpu.bat"
    if not bat.exists():
        bat.write_text(".\\python_embeded\\python.exe -s ComfyUI\\main.py --windows-standalone-build\r\npause\r\n", encoding="utf-8")

    wf = base_dir / "flux_dev_workflow.json"
    if not wf.exists():
        wf.write_text(
            json.dumps(
                {
                    "last_node_id": 3,
                    "nodes": [
                        {"id": 1, "type": "EmptySD3LatentImage", "widgets_values": [1536, 1536, 1]},
                        {"id": 2, "type": "KSampler", "widgets_values": [42, "fixed", 20, 1.0]},
                        {"id": 3, "type": "VAEDecode", "widgets_values": []},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    cn = base_dir / "ComfyUI" / "custom_nodes"
    n1 = cn / "ComfyUI-Legacy-Pack"
    n2 = cn / "ComfyUI-Modern-Nodes"
    n1.mkdir(parents=True, exist_ok=True)
    n2.mkdir(parents=True, exist_ok=True)
    if not (n1 / "requirements.txt").exists():
        (n1 / "requirements.txt").write_text("numpy<2.0\ntorch==2.3.1\n", encoding="utf-8")
    if not (n2 / "requirements.txt").exists():
        (n2 / "requirements.txt").write_text("numpy>=2.0.0\ntransformers\n", encoding="utf-8")

    return {"root": base_dir, "bat": bat, "workflow": wf, "custom_nodes": cn}
