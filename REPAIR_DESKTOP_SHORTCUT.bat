@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

title Invoice Assistant - Repair Desktop Shortcut

echo.
echo ========================================
echo   Invoice Assistant - Repair Desktop Shortcut
echo ========================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $lnk=Join-Path $desktop 'Invoice Assistant.lnk'; $icon=Join-Path '%PROJECT_ROOT%' 'static\invoice_assistant.ico'; $s=(New-Object -COM WScript.Shell).CreateShortcut($lnk); $s.TargetPath=$env:ComSpec; $s.Arguments='/c ""%PROJECT_ROOT%\02_START_INVOICE_ASSISTANT.bat""'; $s.WorkingDirectory='%PROJECT_ROOT%'; if (Test-Path $icon) { $s.IconLocation=$icon + ',0' } else { $s.IconLocation=$env:SystemRoot + '\System32\shell32.dll,44' }; $s.Save()"
if errorlevel 1 (
  echo Failed to repair desktop shortcut.
  pause
  exit /b 1
)

echo Created desktop shortcut: Invoice Assistant
echo Use this new shortcut. The old Chinese shortcut can be deleted manually.
echo.
pause
