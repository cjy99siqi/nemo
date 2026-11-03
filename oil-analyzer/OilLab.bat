@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem 用 pythonw 启动：不显示控制台窗口，任务栏只保留 OilLab 程序图标
if exist "%~dp0pythonw.exe" (
    start "" "%~dp0pythonw.exe" "%~dp0oil_monitor_gui.py"
    exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "%~dp0oil_monitor_gui.py"
    exit /b
)
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0oil_monitor_gui.py"
    exit /b
)
where python >nul 2>nul
if %errorlevel%==0 (
    start "" python "%~dp0oil_monitor_gui.py"
    exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
    start "" py -3 "%~dp0oil_monitor_gui.py"
    exit /b
)
echo [x] 未找到 Python，请先安装 Python 3.9+（安装时勾选 Add to PATH）
pause
