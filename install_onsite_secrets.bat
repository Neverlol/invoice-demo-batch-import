@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Invoice Assistant - Install Private Config

echo.
echo ========================================
echo   Invoice Assistant - Install Private Config
echo ========================================
echo.
echo This step installs MiMo, sync center, and cloud profile config.
echo Please make sure this file exists:
echo   _onsite_private_config\onsite_secrets.json
echo.

set "SECRET_DIR=%~dp0_onsite_private_config"

if not exist "%SECRET_DIR%\onsite_secrets.json" (
  echo Missing private config file:
  echo   _onsite_private_config\onsite_secrets.json
  echo.
  echo Copy the private config folder into this project folder, then run this again.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_onsite_secrets.ps1" -ProjectRoot "%~dp0" -SecretDir "%SECRET_DIR%"
if errorlevel 1 (
  echo.
  echo Private config install failed. Please contact technical support.
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
