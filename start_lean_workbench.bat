@echo off
setlocal
cd /d "%~dp0"

set PYTHON_EXE=python
if exist ".venv\Scripts\python.exe" set PYTHON_EXE=.venv\Scripts\python.exe
if not exist ".venv\Scripts\python.exe" if exist "..\invoice-demo\.venv\Scripts\python.exe" set PYTHON_EXE=..\invoice-demo\.venv\Scripts\python.exe

start "" http://127.0.0.1:5012
%PYTHON_EXE% start_lean_workbench.py
pause
