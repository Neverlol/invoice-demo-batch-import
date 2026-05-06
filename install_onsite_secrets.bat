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

set "SECRET_DIR=%PROJECT_ROOT%\_现场私密配置"
if not exist "%SECRET_DIR%\onsite_secrets.json" set "SECRET_DIR=%PROJECT_ROOT%\_onsite_private_config"

if not exist "%SECRET_DIR%\onsite_secrets.json" (
  echo Missing private config file:
  echo   _现场私密配置\onsite_secrets.json
  echo or:
  echo   _onsite_private_config\onsite_secrets.json
  echo.
  echo Open _现场私密配置, copy onsite_secrets.template.json to onsite_secrets.json, fill the real keys, then run this again.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\tools\install_onsite_secrets.ps1" -ProjectRoot "%PROJECT_ROOT%" -SecretDir "%SECRET_DIR%"
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
