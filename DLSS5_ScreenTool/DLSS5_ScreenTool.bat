@echo off
setlocal
rem DLSS5_ScreenTool launcher - relative paths, folder can be moved anywhere
rem Python search order: WorkBuddy py312 venv -> py launcher 3.12 -> PATH python
set "SCRIPT=%~dp0DLSS5_ScreenTool.py"

rem --- 1) WorkBuddy py312 venv (if present) ---
set "PY1=C:\Users\apple\.workbuddy\binaries\python\envs\py312\Scripts\python.exe"
if exist "%PY1%" (
    "%PY1%" -c "import numpy, cv2" >nul 2>&1
    if not errorlevel 1 (
        "%PY1%" "%SCRIPT%" %*
        goto end
    )
)

rem --- 2) py launcher with any Python 3.12 ---
where py >nul 2>&1
if not errorlevel 1 (
    py -3.12 -c "import numpy, cv2" >nul 2>&1
    if not errorlevel 1 (
        py -3.12 "%SCRIPT%" %*
        goto end
    )
)

rem --- 3) python on PATH ---
where python >nul 2>&1
if not errorlevel 1 (
    python -c "import numpy, cv2" >nul 2>&1
    if not errorlevel 1 (
        python "%SCRIPT%" %*
        goto end
    )
)

echo [DLSS5_ScreenTool] No Python 3.12 environment with numpy + opencv found.
echo Install Python 3.12 and run: pip install numpy opencv-python
pause
:end
