@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title Invoice Assistant - Workbench

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist ".venv\Scripts\python.exe" if exist "..\invoice-demo\.venv\Scripts\python.exe" set "PYTHON_EXE=..\invoice-demo\.venv\Scripts\python.exe"

echo.
echo ========================================
echo   Invoice Assistant - Workbench
echo ========================================
echo.
echo Starting workbench. Keep this black window open.
echo Browser will open: http://127.0.0.1:5012
echo.
echo If the page is not ready, wait 5-10 seconds and refresh.
echo.

start "" http://127.0.0.1:5012
%PYTHON_EXE% start_lean_workbench.py

echo.
echo Workbench stopped. Double click this file again to restart.
pause
