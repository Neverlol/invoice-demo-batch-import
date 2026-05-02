@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "README_ONSITE_CN.md" (
  start "" notepad "README_ONSITE_CN.md"
) else (
  echo Guide file not found: README_ONSITE_CN.md
  pause
)
