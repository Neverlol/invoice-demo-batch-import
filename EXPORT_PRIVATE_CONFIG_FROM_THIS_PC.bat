@echo off
setlocal EnableExtensions

set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

title Invoice Assistant - Export Private Config

echo.
echo ========================================
echo   Invoice Assistant - Export Private Config
echo ========================================
echo.
echo This tool reads from this PC:
echo   1. Windows env var TAX_INVOICE_MIMO_API_KEY
echo   2. sync_client.local.json in this folder
echo.
echo It will create:
echo   _onsite_private_config\onsite_secrets.json
echo.
echo WARNING: onsite_secrets.json contains private keys. Do not share it in public chats.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PROJECT_ROOT%\tools\export_onsite_secrets_from_this_pc.ps1" -ProjectRoot "%PROJECT_ROOT%"
if errorlevel 1 (
  echo.
  echo Export failed. Please check:
  echo   1. TAX_INVOICE_MIMO_API_KEY exists on this PC
  echo   2. sync_client.local.json exists in this folder
  echo.
  pause
  exit /b 1
)

echo.
echo Export completed.
echo Save this folder separately:
echo   _onsite_private_config
echo.
echo On the new PC, copy it into the Invoice Assistant folder and run:
echo   01_INSTALL_PRIVATE_CONFIG.bat
echo.
pause
