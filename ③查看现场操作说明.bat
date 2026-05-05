@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "docs\PRODUCT_USER_GUIDE_CN.html" (
  start "" "docs\PRODUCT_USER_GUIDE_CN.html"
) else if exist "现场操作说明.md" (
  start "" notepad "现场操作说明.md"
) else (
  echo 没有找到现场操作说明。
  pause
)
