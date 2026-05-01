@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "现场操作说明.md" (
  start "" notepad "现场操作说明.md"
) else (
  echo 没有找到 现场操作说明.md
  pause
)
