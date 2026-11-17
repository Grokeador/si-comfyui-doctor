# SI-ComfyUI-Doctor

**Fix ComfyUI & Flux CUDA Out-of-Memory, Silent Window Crashes, 99% `VAEDecode` OOM & Custom Node Package Conflicts on Windows — 100% Free Open Source (Zero External Dependencies).**

## 4 Real Windows ComfyUI / Flux Problems Solved

1. **Dynamic VRAM / `aimdo` False CUDA OOM (`patch_comfyui_bat_flags`)**: Safely backs up `run_nvidia_gpu.bat` (SHA-256 `.bak`) and injects calibrated `--disable-dynamic-vram` / `--lowvram` flags matching your GPU VRAM.
2. **Flux T5-XXL Silent Window Vanish Crash (`audit_windows_memory_and_gpu`)**: Measures Windows physical RAM + Virtual Commit/Pagefile (`GlobalMemoryStatusEx`) and warns when Commit Limit `< 48GB` + recommends exact FP8/GGUF quantization fit.
3. **99% `VAEDecode` CUDA OOM (`patch_workflow_tiled_vae`)**: Converts `VAEDecode` nodes inside both LiteGraph UI `.json` and API prompt `.json` workflows directly into `VAEDecodeTiled` (`512px` tiles, `64px` overlap) with SHA-256 backup + 1-Click Rollback.
4. **`custom_nodes` Package Clashes (`scan_custom_nodes_conflicts`)**: Scans every `custom_nodes/*/requirements.txt` to detect `numpy<2` vs `numpy>=2` clashes and hard-pinned `torch==` ABI breakages before you launch.

## Quick Start
Double-click `Launch_SI_ComfyUI_Doctor.bat` or run:
```powershell
python -m unittest test_comfyui_doctor.py -v
```
