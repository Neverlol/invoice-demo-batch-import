@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

title Invoice Assistant - Install Private Config

echo.
echo ========================================
echo   Invoice Assistant - Install Private Config
echo ========================================
echo.
echo This step installs MiMo, sync center, and cloud profile config.
echo.

if not exist "%PROJECT_ROOT%\tools\install_onsite_secrets.ps1" (
  echo Missing tools\install_onsite_secrets.ps1
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\tools\install_onsite_secrets.ps1" -ProjectRoot "%PROJECT_ROOT%"
if errorlevel 1 (
  echo.
  echo Private config install failed. Please contact technical support.
  echo Expected private config at one of:
  echo   _onsite_private_config\onsite_secrets.json
  echo   Chinese private config folder\onsite_secrets.json
  pause
  exit /b 1
)

echo.
echo Private config installed.
echo Next step:
echo   00_FIRST_INSTALL.bat
echo or:
echo   02_START_INVOICE_ASSISTANT.bat
echo.
pause
