@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

title Invoice Assistant - Start

echo.
echo ========================================
echo   Invoice Assistant - Start
echo ========================================
echo.
echo Step 1: starting tax browser CDP...
start "Invoice Tax Browser CDP" "%PROJECT_ROOT%\start_edge_cdp.bat"

echo Waiting a few seconds for CDP startup...
timeout /t 5 /nobreak >nul

echo Step 2: starting workbench...
start "Invoice Workbench" "%PROJECT_ROOT%\start_lean_workbench.bat"

echo.
echo Startup requested.
echo If the page does not open, visit: http://127.0.0.1:5012
echo Keep the Edge CDP and workbench windows open.
echo.
pause
