@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

title 智能开票助手 - 首次安装 / 环境检测

set "BUNDLE_ROOT=%~dp0"
set "WHEEL_DIR=%BUNDLE_ROOT%windows_bootstrap\wheels"
set "REQ_FILE=%BUNDLE_ROOT%windows_bootstrap\requirements-windows.txt"
set "PYTHON_INSTALLER=%BUNDLE_ROOT%windows_bootstrap\installers\python-3.11.9-amd64.exe"
set "TESS_INSTALLER=%BUNDLE_ROOT%windows_bootstrap\installers\tesseract-ocr-w64-setup-5.4.0.20240606.exe"
set "PYTHON_CMD="
set "EDGE_PATH="
set "TESS_EXE="

echo.
echo ========================================
echo   智能开票助手 - 首次安装 / 环境检测
echo ========================================
echo.
echo 本程序会自动检查并准备运行环境：
echo   1. Python 3.11
echo   2. Python 虚拟环境 .venv
echo   3. 开票助手依赖包
echo   4. Microsoft Edge / OCR 组件
echo   5. 桌面快捷方式
echo.

call :detect_python
if not defined PYTHON_CMD (
  echo [1/6] 未检测到可用 Python 3.11，准备安装包内 Python...
  if not exist "%PYTHON_INSTALLER%" (
    echo 未找到 Python 安装包：
    echo   %PYTHON_INSTALLER%
    echo 请联系技术人员重新提供完整交付包。
    pause
    exit /b 1
  )
  echo 正在静默安装 Python 3.11，请稍候...
  start /wait "" "%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_venv=1 SimpleInstall=1
  call :detect_python
)

if not defined PYTHON_CMD (
  echo Python 自动安装后仍未检测到可用命令。
  echo 可能需要重新打开本窗口，或手动运行安装包并勾选 Add Python to PATH。
  pause
  exit /b 1
)

echo [1/6] Python 已就绪：
%PYTHON_CMD% --version

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo [2/6] 正在创建 Python 虚拟环境 .venv...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 (
    echo 创建虚拟环境失败，请联系技术人员。
    pause
    exit /b 1
  )
) else (
  echo.
  echo [2/6] 已发现现有虚拟环境 .venv，跳过创建。
)

echo.
echo [3/6] 正在安装 / 检查 Python 依赖...
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if exist "%REQ_FILE%" (
  if exist "%WHEEL_DIR%" (
    echo 优先使用包内离线依赖安装...
    python -m pip install --no-index --find-links "%WHEEL_DIR%" -r "%REQ_FILE%"
    if errorlevel 1 (
      echo 离线安装失败，尝试联网安装依赖...
      python -m pip install -r "%REQ_FILE%"
      if errorlevel 1 (
        echo 依赖安装失败，请检查网络或交付包是否完整。
        pause
        exit /b 1
      )
    )
  ) else (
    echo 未发现离线依赖目录，尝试联网安装依赖...
    python -m pip install -r "%REQ_FILE%"
  )
) else (
  echo 未发现 requirements-windows.txt，安装基础依赖...
  python -m pip install flask playwright openpyxl pillow xlrd pypdf pywinauto pywin32 comtypes
)

echo.
echo [4/6] 检查 Microsoft Edge...
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not defined EDGE_PATH if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" set "EDGE_PATH=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if defined EDGE_PATH (
  echo 已检测到 Edge：
  echo   !EDGE_PATH!
  echo 税局现场主流程将使用真实 Edge，不下载 Playwright Chromium。
) else (
  echo 未检测到 Microsoft Edge。
  echo 将安装 Playwright Chromium 作为兜底浏览器；现场仍建议优先安装 Edge。
  python -m playwright install chromium
)

echo.
echo [5/6] 检查 OCR 组件 Tesseract...
call :detect_tesseract
if not defined TESS_EXE (
  if exist "%TESS_INSTALLER%" (
    echo 未检测到 Tesseract，准备安装包内 OCR 组件。
    echo 如系统弹出权限确认，请点击“是”。
    start /wait "" "%TESS_INSTALLER%" /SILENT /NORESTART
    call :detect_tesseract
  ) else (
    echo 未找到 Tesseract 安装包，跳过本地 OCR。
  )
)

if defined TESS_EXE (
  echo 已检测到 Tesseract：
  echo   !TESS_EXE!
  call :install_tessdata
) else (
  echo 未启用本地 Tesseract OCR。文本、Excel、PDF、MiMo 图片识别仍可继续使用。
)

echo.
echo [6/7] 准备本地客户档案工作区...
call :ensure_profile_workspace

echo.
echo [7/7] Create desktop shortcut...
call "%~dp0REPAIR_DESKTOP_SHORTCUT.bat"
if errorlevel 1 (
  echo Desktop shortcut creation failed. You can run 02_START_INVOICE_ASSISTANT.bat manually.
) else (
  echo Desktop shortcut created: Invoice Assistant
)

echo.
echo ========================================
echo   安装 / 环境检测完成
echo ========================================
echo.
echo 下一步：
echo   双击桌面“智能开票助手”
echo   或双击当前文件夹里的“启动智能开票助手.bat”
echo.
pause
exit /b 0

:ensure_profile_workspace
set "PROFILE_ROOT=%BUNDLE_ROOT%测试组客户档案储备"
if not exist "%PROFILE_ROOT%" mkdir "%PROFILE_ROOT%" >nul 2>nul
if not exist "%PROFILE_ROOT%\_收件箱\待处理" mkdir "%PROFILE_ROOT%\_收件箱\待处理" >nul 2>nul
if not exist "%PROFILE_ROOT%\_收件箱\已处理" mkdir "%PROFILE_ROOT%\_收件箱\已处理" >nul 2>nul
if not exist "%PROFILE_ROOT%\_收件箱\解析失败" mkdir "%PROFILE_ROOT%\_收件箱\解析失败" >nul 2>nul
if not exist "%PROFILE_ROOT%\_收件箱\重复文件" mkdir "%PROFILE_ROOT%\_收件箱\重复文件" >nul 2>nul
if not exist "%PROFILE_ROOT%\_档案库" mkdir "%PROFILE_ROOT%\_档案库" >nul 2>nul
if not exist "%PROFILE_ROOT%\_待确认" mkdir "%PROFILE_ROOT%\_待确认" >nul 2>nul
if errorlevel 1 (
  echo 客户档案工作区创建失败：%PROFILE_ROOT%
  echo 请确认安装目录有写入权限，建议使用 C:\InvoiceAssistant。
  pause
  exit /b 1
)
echo 客户档案工作区已就绪：
echo   %PROFILE_ROOT%
exit /b 0

:detect_python
set "PYTHON_CMD="
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
  if !errorlevel!==0 (
    set "PYTHON_CMD=py -3"
    exit /b 0
  )
)
for %%P in ("%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%ProgramFiles%\Python311\python.exe" "%ProgramFiles(x86)%\Python311\python.exe") do (
  if exist "%%~P" (
    "%%~P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if !errorlevel!==0 (
      set PYTHON_CMD="%%~P"
      exit /b 0
    )
  )
)
where python >nul 2>nul
if %errorlevel%==0 (
  for /f "delims=" %%I in ('where python') do (
    if not defined PYTHON_CMD (
      echo %%I | find /i "WindowsApps\python.exe" >nul
      if errorlevel 1 (
        "%%I" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
        if !errorlevel!==0 set PYTHON_CMD="%%I"
      )
    )
  )
)
exit /b 0

:detect_tesseract
set "TESS_EXE="
where tesseract >nul 2>nul
if %errorlevel%==0 (
  for /f "delims=" %%I in ('where tesseract') do (
    if not defined TESS_EXE set "TESS_EXE=%%I"
  )
)
if not defined TESS_EXE if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "TESS_EXE=C:\Program Files\Tesseract-OCR\tesseract.exe"
if not defined TESS_EXE if exist "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" set "TESS_EXE=C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
exit /b 0

:install_tessdata
set "TARGET_DIR="
for %%I in ("%TESS_EXE%") do set "TARGET_DIR=%%~dpItessdata"
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%" >nul 2>nul
if exist "%BUNDLE_ROOT%windows_bootstrap\tessdata\eng.traineddata" copy /Y "%BUNDLE_ROOT%windows_bootstrap\tessdata\eng.traineddata" "%TARGET_DIR%\eng.traineddata" >nul 2>nul
if exist "%BUNDLE_ROOT%windows_bootstrap\tessdata\chi_sim.traineddata" copy /Y "%BUNDLE_ROOT%windows_bootstrap\tessdata\chi_sim.traineddata" "%TARGET_DIR%\chi_sim.traineddata" >nul 2>nul
exit /b 0
