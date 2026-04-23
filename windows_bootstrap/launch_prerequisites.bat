@echo off
setlocal
cd /d "%~dp0"

if not exist "installers\python-3.11.9-amd64.exe" (
  echo Bundled Python installer was not found.
  pause
  exit /b 1
)

if not exist "installers\tesseract-ocr-w64-setup-5.4.0.20240606.exe" (
  echo Bundled Tesseract installer was not found.
  pause
  exit /b 1
)

echo Step 1/2: Launching Python installer...
start /wait "" "installers\python-3.11.9-amd64.exe"

echo Step 2/2: Launching Tesseract installer...
start /wait "" "installers\tesseract-ocr-w64-setup-5.4.0.20240606.exe"

echo.
echo Base installers have finished.
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
  echo Microsoft Edge detected:
  echo   %ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe
) else (
  if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
    echo Microsoft Edge detected:
    echo   %ProgramFiles%\Microsoft\Edge\Application\msedge.exe
  ) else (
    echo Microsoft Edge was not detected in the default install path.
    echo The app can still fall back to Playwright Chromium, but Windows live tax tests should prefer Edge when available.
  )
)
echo Next:
echo   1. Run install_tessdata_if_needed.bat
echo   2. Run ..\install_windows.bat
pause
