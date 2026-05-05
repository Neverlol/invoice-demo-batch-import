@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "docs\PRODUCT_USER_GUIDE_CN.html" (
  start "" "docs\PRODUCT_USER_GUIDE_CN.html"
) else if exist "README_ONSITE_CN.md" (
  start "" notepad "README_ONSITE_CN.md"
) else (
  echo Guide file not found.
  pause
)
