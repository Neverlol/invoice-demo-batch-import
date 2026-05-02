@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

title Invoice Assistant - Export Private Config

echo.
echo ========================================
echo   智能开票助手 - 导出本机私密配置
echo ========================================
echo.
echo 本工具会从当前电脑读取：
echo   1. 环境变量 TAX_INVOICE_MIMO_API_KEY
echo   2. 当前目录 sync_client.local.json
echo.
echo 然后生成：
echo   _onsite_private_config\onsite_secrets.json
echo.
echo 注意：生成的 onsite_secrets.json 是私密文件，不要发群、不要截图。
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\export_onsite_secrets_from_this_pc.ps1" -ProjectRoot "%~dp0"
if errorlevel 1 (
  echo.
  echo 导出失败。请确认：
  echo   1. 本机已经配置 TAX_INVOICE_MIMO_API_KEY
  echo   2. 当前目录存在 sync_client.local.json
  echo.
  pause
  exit /b 1
)

echo.
echo 导出完成。
echo 请单独保存这个文件夹：
echo   _onsite_private_config
echo.
echo 到新电脑后，把它复制到智能开票助手目录，再运行：
echo   01_INSTALL_PRIVATE_CONFIG.bat
echo.
pause
