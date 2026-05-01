@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

title 智能开票助手 - 启动税局浏览器

set "EDGE_PATH="
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined EDGE_PATH if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

if not defined EDGE_PATH (
  echo 没有在默认位置找到 Microsoft Edge。
  echo 请先安装 Edge，或联系技术人员检查浏览器路径。
  pause
  exit /b 1
)

set "CDP_PROFILE=%~dp0output\edge-cdp-profile"
if not exist "%CDP_PROFILE%" mkdir "%CDP_PROFILE%"

echo.
echo ========================================
echo   智能开票助手 - 税局专用浏览器
echo ========================================
echo.
echo 正在启动税局专用 Edge 浏览器...
echo 请保留这个浏览器窗口，不要关闭。
echo.

start "" "%EDGE_PATH%" --remote-debugging-port=9222 --user-data-dir="%CDP_PROFILE%" "about:blank"

echo 已启动。
echo.
echo 下一步：
echo   1. 双击 “②启动开票工作台.bat”
echo   2. 在工作台首页点击 “打开辽宁/吉林/北京税局”
echo   3. 登录税局后点击 “识别当前税局主体 / 加载档案”
echo.
echo 如果浏览器已经打开，可直接切换到浏览器继续操作。
echo.
pause
