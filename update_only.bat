@echo off
setlocal
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Git for Windows。
  pause
  exit /b 1
)

if not exist ".git" (
  echo 当前目录还不是 Git 工作目录。
  echo 请先按 GIT_SYNC_SETUP.md 完成首次 Git 绑定。
  pause
  exit /b 1
)

echo [1/2] Fetching latest code...
git fetch origin
if errorlevel 1 (
  echo git fetch 失败。
  pause
  exit /b 1
)

echo [2/2] Pulling latest code...
git pull --ff-only
if errorlevel 1 (
  echo git pull 失败，请先手动处理冲突。
  pause
  exit /b 1
)

echo 已更新到最新代码。
pause

endlocal

