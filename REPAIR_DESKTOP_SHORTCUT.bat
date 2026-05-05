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

powershell -NoProfile -ExecutionPolicy Bypass -Command "$desktop=[Environment]::GetFolderPath('Desktop'); $name=([char]0x667A)+([char]0x80FD)+([char]0x5F00)+([char]0x7968)+([char]0x52A9)+([char]0x624B)+'.lnk'; $lnk=Join-Path $desktop $name; $legacy=Join-Path $desktop 'Invoice Assistant.lnk'; if (Test-Path $lnk) { Remove-Item $lnk -Force }; if (Test-Path $legacy) { Remove-Item $legacy -Force }; Start-Sleep -Milliseconds 300; $icon=Join-Path '%PROJECT_ROOT%' 'static\neverlol_terminal_logo_20260505.ico'; $fallbackIcon=Join-Path '%PROJECT_ROOT%' 'static\invoice_assistant.ico'; $s=(New-Object -COM WScript.Shell).CreateShortcut($lnk); $s.TargetPath=$env:ComSpec; $s.Arguments='/c ""%PROJECT_ROOT%\02_START_INVOICE_ASSISTANT.bat""'; $s.WorkingDirectory='%PROJECT_ROOT%'; if (Test-Path $icon) { $s.IconLocation=$icon + ',0' } elseif (Test-Path $fallbackIcon) { $s.IconLocation=$fallbackIcon + ',0' } else { $s.IconLocation=$env:SystemRoot + '\System32\shell32.dll,44' }; $s.Save()"
if errorlevel 1 (
  echo Failed to repair desktop shortcut.
  pause
  exit /b 1
)

echo Recreated desktop shortcut: Chinese name Invoice Assistant.
echo Removed old Chinese and English shortcuts before recreating.
echo.
pause
