@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

title Invoice Assistant - Tax Browser CDP

set "EDGE_PATH="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined EDGE_PATH if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if not defined EDGE_PATH if exist "%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"
if not defined EDGE_PATH (
  for /f "delims=" %%I in ('where msedge 2^>nul') do (
    if not defined EDGE_PATH set "EDGE_PATH=%%I"
  )
)

if not defined EDGE_PATH (
  echo Microsoft Edge was not found.
  echo Please install Microsoft Edge or contact technical support.
  pause
  exit /b 1
)

set "CDP_PROFILE=%PROJECT_ROOT%\output\edge-cdp-profile"
if not exist "%CDP_PROFILE%" mkdir "%CDP_PROFILE%"

echo.
echo ========================================
echo   Invoice Assistant - Tax Browser CDP
echo ========================================
echo.
echo Edge path:
echo   %EDGE_PATH%
echo.
echo Starting Edge with remote debugging port 9222...
echo Keep this Edge window open.
echo.

start "" "%EDGE_PATH%" --remote-debugging-port=9222 --user-data-dir="%CDP_PROFILE%" --no-first-run --no-default-browser-check "about:blank"

echo Waiting for CDP port 9222...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(15); do { try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 http://127.0.0.1:9222/json/version; if ($r.StatusCode -eq 200) { exit 0 } } catch { Start-Sleep -Milliseconds 500 } } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo.
  echo CDP port 9222 is not ready.
  echo Please close the tax Edge window if it opened, then run this file again.
  echo If it still fails, restart Windows and try again.
  echo.
  pause
  exit /b 1
)

echo.
echo CDP is ready: http://127.0.0.1:9222
echo Next: open the workbench and click the regional tax button.
echo.
pause
