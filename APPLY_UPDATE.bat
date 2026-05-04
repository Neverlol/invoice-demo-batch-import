@echo off
setlocal
cd /d "%~dp0"

echo Invoice Assistant onsite update
echo.
echo Please close the workbench window before continuing.
echo Update package expected at: updates\latest.zip
echo.
if not exist "tools\apply_update.ps1" (
  echo Missing tools\apply_update.ps1
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\apply_update.ps1"
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Update failed. Check update_logs for details.
  pause
  exit /b %EXITCODE%
)

echo.
echo Update completed. Restart 02_START_INVOICE_ASSISTANT.bat and press Ctrl+F5 in browser.
pause
endlocal
