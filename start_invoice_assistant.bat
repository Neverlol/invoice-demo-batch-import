@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

title Invoice Assistant - Start

echo.
echo ========================================
echo   智能开票助手 - 一键启动
echo ========================================
echo.
echo 第一步：启动税局专用浏览器...
start "Invoice Tax Browser" "%~dp0start_edge_cdp.bat"

echo 等待浏览器启动...
timeout /t 3 /nobreak >nul

echo 第二步：启动开票工作台...
start "Invoice Workbench" "%~dp0start_lean_workbench.bat"

echo.
echo 已发起启动。
echo 如果网页没有自动打开，请手动访问：http://127.0.0.1:5012
echo.
echo 请保留两个黑色窗口，不要关闭。
echo.
pause
