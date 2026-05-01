@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

title 智能开票助手 - 启动开票工作台

set "PYTHON_EXE=python"
if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"
if not exist ".venv\Scripts\python.exe" if exist "..\invoice-demo\.venv\Scripts\python.exe" set "PYTHON_EXE=..\invoice-demo\.venv\Scripts\python.exe"

echo.
echo ========================================
echo   智能开票助手 - 开票工作台
echo ========================================
echo.
echo 正在启动工作台，请不要关闭这个黑色窗口。
echo 浏览器会自动打开：http://127.0.0.1:5012
echo.
echo 如果页面暂时打不开，请等待 5-10 秒后刷新。
echo.

start "" http://127.0.0.1:5012
%PYTHON_EXE% start_lean_workbench.py

echo.
echo 工作台已停止。如需继续使用，请重新双击本文件。
pause
