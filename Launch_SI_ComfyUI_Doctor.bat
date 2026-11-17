@echo off
title SI-ComfyUI-Doctor - Fix Flux & ComfyUI CUDA OOM Crashes
echo ========================================================================
echo   SI-ComfyUI-Doctor - Starting Rescue Studio (http://127.0.0.1:8796)
echo   Zero External Dependencies | Fixes OOM, Pagefile & Custom Nodes
echo ========================================================================
cd /d "%~dp0"
python "%~dp0si_comfyui_doctor.py" ui %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Python 3.10+ required. Verify with: python --version
    pause
)
