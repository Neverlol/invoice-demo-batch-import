@echo off
setlocal
cd /d "%~dp0"

echo [1/4] Checking Git...
where git >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Git for Windows。
  echo 请先安装 Git，再重新运行本脚本。
  pause
  exit /b 1
)

if not exist ".git" (
  echo 当前目录还不是 Git 工作目录。
  echo 请先按 GIT_SYNC_SETUP.md 完成首次 Git 绑定。
  pause
  exit /b 1
)

echo [2/4] Fetching latest code...
git fetch origin
if errorlevel 1 (
  echo git fetch 失败，请检查网络或远端仓库配置。
  pause
  exit /b 1
)

echo [3/4] Pulling latest code...
git pull --ff-only
if errorlevel 1 (
  echo git pull 失败。
  echo 如有本地改动冲突，请先手动处理：
  echo   git status
  echo   git stash   或   git restore / git reset
  pause
  exit /b 1
)

echo [4/4] Starting lean workbench...
call start_lean_workbench.bat

endlocal

