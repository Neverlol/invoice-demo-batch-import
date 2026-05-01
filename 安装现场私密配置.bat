@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

title 智能开票助手 - 安装现场私密配置

echo.
echo ========================================
echo   智能开票助手 - 安装现场私密配置
echo ========================================
echo.
echo 本步骤用于安装 MiMo / 阿里云同步 / 云端客户档案配置。
echo 请确认当前文件夹内存在：
echo   _现场私密配置\onsite_secrets.json
echo.

if not exist "%~dp0_现场私密配置\onsite_secrets.json" (
  echo 未找到私密配置文件：
  echo   %~dp0_现场私密配置\onsite_secrets.json
  echo.
  echo 请先把“现场私密配置包”解压到本文件夹，再重新运行。
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\install_onsite_secrets.ps1" -ProjectRoot "%~dp0"
if errorlevel 1 (
  echo.
  echo 私密配置安装失败，请联系技术人员。
  pause
  exit /b 1
)

echo.
echo 私密配置已安装完成。
echo 建议下一步运行：
echo   首次安装智能开票助手.bat
echo 或：
echo   启动智能开票助手.bat
echo.
pause
