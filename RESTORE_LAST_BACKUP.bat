@echo off
setlocal
cd /d "%~dp0"

echo Invoice Assistant restore last backup
echo.
echo Please close the workbench window before continuing.
echo.
if not exist "tools\restore_last_backup.ps1" (
  echo Missing tools\restore_last_backup.ps1
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\restore_last_backup.ps1"
set EXITCODE=%ERRORLEVEL%
if not "%EXITCODE%"=="0" (
  echo.
  echo Restore failed. Check update_logs for details.
  pause
  exit /b %EXITCODE%
)

echo.
echo Restore completed. Restart 02_START_INVOICE_ASSISTANT.bat and press Ctrl+F5 in browser.
pause
endlocal
