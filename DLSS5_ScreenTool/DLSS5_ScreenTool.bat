@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
rem ================================================================
rem  DLSS5_ScreenTool portable launcher
rem  可在任意机器运行:
rem    1) 优先使用本目录已有的 .venv (首次配置后秒启动)
rem    2) 否则自动搜索 Python (优先自带 tkinter 的官方版):
rem       py 启动器 -> PATH -> 常见安装目录
rem    3) 找到后自动创建 .venv 并安装 numpy + opencv-python (需联网, 仅一次)
rem  GUI 模式需要 tkinter (python.org 官方安装包默认包含)
rem ================================================================
set "SCRIPT=%~dp0DLSS5_ScreenTool.py"
set "VENV=%~dp0.venv"
set "VPY=%VENV%\Scripts\python.exe"

rem GUI 模式需要 tkinter; --input 命令行模式不需要
set "GUI=1"
if /i "%~1"=="--input" set "GUI=0"

rem ---- 0) 本目录已有可用 .venv: 直接运行 ----
if exist "%VPY%" (
    "%VPY%" -c "import numpy, cv2" >nul 2>&1
    if not errorlevel 1 (
        if "%GUI%"=="0" (
            "%VPY%" "%SCRIPT%" %*
            goto end
        )
        "%VPY%" -c "import tkinter" >nul 2>&1
        if not errorlevel 1 (
            "%VPY%" "%SCRIPT%" %*
            goto end
        )
    )
)

rem ---- 搜索基础 Python: 第一轮优先带 tkinter 的 ----
call :findpy "import sys, tkinter"
if not defined PYEXE if "%GUI%"=="0" call :findpy "import sys"
if not defined PYEXE goto nopython

rem ---- 若基础 Python 已带依赖: 免安装直接运行 ----
"%PYEXE%" %PYARG% -c "import numpy, cv2" >nul 2>&1
if not errorlevel 1 (
    if "%GUI%"=="0" (
        "%PYEXE%" %PYARG% "%SCRIPT%" %*
        goto end
    )
    "%PYEXE%" %PYARG% -c "import tkinter" >nul 2>&1
    if not errorlevel 1 (
        "%PYEXE%" %PYARG% "%SCRIPT%" %*
        goto end
    )
)

rem ---- 首次运行: 创建 .venv 并安装依赖 ----
echo [DLSS5_ScreenTool] 首次运行: 正在创建本地环境 .venv ...
"%PYEXE%" %PYARG% -m venv "%VENV%"
if not exist "%VPY%" (
    echo [DLSS5_ScreenTool] .venv 创建失败 ^(Python: %PYEXE% %PYARG%^)
    pause
    goto end
)
echo [DLSS5_ScreenTool] 正在安装 numpy + opencv-python ^(需要联网, 仅此一次^) ...
"%VPY%" -m pip install --quiet --no-input numpy opencv-python >nul 2>&1
"%VPY%" -c "import numpy, cv2" >nul 2>&1
if errorlevel 1 (
    echo [DLSS5_ScreenTool] 依赖校验未通过, 正在重试完整安装 ...
    "%VPY%" -m pip install --no-input --force-reinstall numpy opencv-python
    "%VPY%" -c "import numpy, cv2" >nul 2>&1
    if errorlevel 1 (
        echo [DLSS5_ScreenTool] 依赖安装失败, 请检查网络/代理后重新运行本脚本。
        pause
        goto end
    )
)
"%VPY%" "%SCRIPT%" %*
goto end

:nopython
echo [DLSS5_ScreenTool] 未找到可用的 Python 3.10+ 。
echo 请从 https://www.python.org/downloads/ 安装 Python ^(勾选 tcl/tk^) 后重试。
pause
goto end

rem ================================================================
rem :findpy  在 py 启动器 / PATH / 常见目录中搜索能通过导入检查的 Python
rem          结果写入 PYEXE (可执行文件) 与 PYARG (附加参数)
rem ================================================================
:findpy
set "CHK=%~1"
set "PYEXE="
set "PYARG="
for %%V in (3.13 3.12 3.11 3.10 3) do (
    if not defined PYEXE (
        py -%%V -c "%CHK%" >nul 2>&1
        if not errorlevel 1 (
            set "PYEXE=py"
            set "PYARG=-%%V"
        )
    )
)
if not defined PYEXE (
    python -c "%CHK%" >nul 2>&1
    if not errorlevel 1 set "PYEXE=python"
)
if not defined PYEXE (
    for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if not defined PYEXE if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
)
if not defined PYEXE (
    for /d %%D in ("C:\Program Files\Python3*" "C:\Python3*") do (
        if not defined PYEXE if exist "%%D\python.exe" set "PYEXE=%%D\python.exe"
    )
)
goto :eof

:end
endlocal
