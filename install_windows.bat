@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "PY_CMD="
set "PYTHON_PATH="
set "BUNDLE_ROOT=%~dp0"
set "WHEEL_DIR=%BUNDLE_ROOT%windows_bootstrap\wheels"
set "REQ_FILE=%BUNDLE_ROOT%windows_bootstrap\requirements-windows.txt"
set "PYTHON_INSTALLER=%BUNDLE_ROOT%windows_bootstrap\installers\python-3.11.9-amd64.exe"
set "EDGE_PATH="

where py >nul 2>nul
if %errorlevel%==0 set "PY_CMD=py -3"
if not defined PY_CMD (
  where python >nul 2>nul
  if %errorlevel%==0 (
    for /f "delims=" %%I in ('where python') do (
      if not defined PYTHON_PATH set "PYTHON_PATH=%%I"
    )
    echo %PYTHON_PATH% | find /i "WindowsApps\\python.exe" >nul
    if errorlevel 1 (
      set "PY_CMD=python"
    )
  )
)
if not defined PY_CMD (
  echo Python 3 was not found.
  if defined PYTHON_PATH (
    echo Detected only the Microsoft Store alias:
    echo   %PYTHON_PATH%
    echo Please install the real Windows Python, then rerun this script.
  )
  if exist "%PYTHON_INSTALLER%" (
    echo Bundled installer detected:
    echo   %PYTHON_INSTALLER%
  )
  echo Please install Python first, then rerun this script.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating Windows virtual environment...
  %PY_CMD% -m venv .venv
)

echo [2/4] Activating virtual environment...
call ".venv\Scripts\activate.bat"

echo [3/4] Installing Python dependencies...
python -m pip install --upgrade pip
if exist "%REQ_FILE%" (
  echo Attempting offline install from bundled wheels...
  python -m pip install --no-index --find-links "%WHEEL_DIR%" -r "%REQ_FILE%"
  if errorlevel 1 (
    echo Offline wheel install failed. Falling back to online install...
    python -m pip install -r "%REQ_FILE%"
  )
) else (
  python -m pip install flask playwright openpyxl pillow xlrd pypdf
)

if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined EDGE_PATH if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

if defined EDGE_PATH (
  echo [4/4] Microsoft Edge detected:
  echo         !EDGE_PATH!
  echo         Batch import live tests will use real Edge through CDP.
  echo         Skipping Playwright Chromium download for now.
) else (
  echo [4/4] Microsoft Edge was not detected. Installing Playwright Chromium fallback...
  python -m playwright install chromium
)

where tesseract >nul 2>nul
if %errorlevel%==0 (
  echo [Optional] Tesseract OCR detected in PATH. Image OCR is available for the workbench.
) else (
  echo [Optional] Tesseract OCR not found.
  echo            Workbench can still run for Excel/PDF/text inputs.
  echo            To enable pasted image OCR, install Tesseract OCR and add it to PATH.
)

echo.
echo Windows batch-import workbench environment is ready.
echo Next:
echo   1. Double-click start_edge_cdp.bat and log in to the tax bureau manually.
echo   2. Double-click start_lean_workbench.bat to launch the local workbench.
pause
