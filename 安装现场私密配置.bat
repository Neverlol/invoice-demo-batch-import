@echo off
setlocal EnableExtensions

rem ASCII-only wrapper. Avoid Chinese text in cmd body to prevent codepage parsing issues.
set "PROJECT_ROOT=%~dp0"
if "%PROJECT_ROOT:~-1%"=="\" set "PROJECT_ROOT=%PROJECT_ROOT:~0,-1%"
cd /d "%PROJECT_ROOT%"

call "%PROJECT_ROOT%\install_onsite_secrets.bat"
