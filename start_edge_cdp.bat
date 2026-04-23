@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "EDGE_PATH="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined EDGE_PATH if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

if not defined EDGE_PATH (
  echo Microsoft Edge was not found in the default install path.
  echo Please install Edge or adjust the script path manually.
  pause
  exit /b 1
)

tasklist /FI "IMAGENAME eq msedge.exe" | find /I "msedge.exe" >nul
if not errorlevel 1 (
  echo Edge is already running.
  echo Close all Edge windows first, then rerun this script.
  echo The --remote-debugging-port flag is usually ignored if Edge is already running.
  pause
  exit /b 1
)

echo Launching Edge with remote debugging port 9222...
start "" "%EDGE_PATH%" --remote-debugging-port=9222 "about:blank"

echo.
echo Next:
echo   1. In the opened Edge window, manually open the correct province tax portal.
echo   2. Log in and switch to the target enterprise subject.
echo   3. Visit http://127.0.0.1:9222/json and confirm you see JSON.
echo   4. Then run start_lean_workbench.bat.
echo   5. Keep this Edge window open while the workbench executes.
pause
