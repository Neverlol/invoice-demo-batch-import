@echo off
setlocal
cd /d "%~dp0"

set "TARGET_DIR="
set "TESS_EXE="

where tesseract >nul 2>nul
if %errorlevel%==0 (
  for /f "delims=" %%I in ('where tesseract') do (
    if not defined TESS_EXE set "TESS_EXE=%%I"
  )
)

if defined TESS_EXE (
  for %%I in ("%TESS_EXE%") do set "TARGET_DIR=%%~dpItessdata"
)

if not defined TARGET_DIR if exist "C:\Program Files\Tesseract-OCR" set "TARGET_DIR=C:\Program Files\Tesseract-OCR\tessdata"
if not defined TARGET_DIR if exist "C:\Program Files (x86)\Tesseract-OCR" set "TARGET_DIR=C:\Program Files (x86)\Tesseract-OCR\tessdata"

if defined TARGET_DIR if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

if not defined TARGET_DIR (
  echo Tesseract tessdata directory was not found.
  echo Please finish installing Tesseract first, then rerun this script.
  echo.
  echo Check:
  echo   1. C:\Program Files\Tesseract-OCR\tesseract.exe
  echo   2. Or run: where tesseract
  pause
  exit /b 1
)

echo Copying bundled tessdata files to:
echo   %TARGET_DIR%
copy /Y "tessdata\eng.traineddata" "%TARGET_DIR%\eng.traineddata"
copy /Y "tessdata\chi_sim.traineddata" "%TARGET_DIR%\chi_sim.traineddata"

echo.
echo Done.
pause
