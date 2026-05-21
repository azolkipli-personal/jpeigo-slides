@echo off
REM ============================================================================
REM Build script for jpeigo-slides — Windows executable
REM Requires: Node.js 18+, Python 3.10+, and PyInstaller
REM ============================================================================
setlocal enabledelayedexpansion

set ROOT_DIR=%~dp0
set FRONTEND_OUT=%ROOT_DIR%backend\app\frontend

echo === jpeigo-slides Portable Build (Windows) ===
echo.

REM Step 1: Build frontend
echo === 1/3 Building frontend ===
cd /d "%ROOT_DIR%"
call npm install
call npm run build
echo   ✅ Frontend built
echo.

REM Step 2: Copy static files to backend
echo === 2/3 Copying to backend ===
if exist "%FRONTEND_OUT%" rmdir /s /q "%FRONTEND_OUT%"
mkdir "%FRONTEND_OUT%"
xcopy /e /i /q "%ROOT_DIR%out\*" "%FRONTEND_OUT%"
echo   ✅ Copied
echo.

REM Step 3: Build executable with PyInstaller
echo === 3/3 Building executable ===
cd /d "%ROOT_DIR%backend"
pip install pyinstaller -q

pyinstaller ^
  --onefile ^
  --name "jpeigo-slides" ^
  --add-data ".;backend" ^
  --add-data "%FRONTEND_OUT%;backend\app\frontend" ^
  --hidden-import "uvicorn.logging" ^
  --hidden-import "uvicorn.loops.auto" ^
  --hidden-import "uvicorn.protocols.http.auto" ^
  --hidden-import "uvicorn.protocols.websocket.auto" ^
  --hidden-import "lxml._elementpath" ^
  --collect-submodules "pptx" ^
  --collect-submodules "lxml" ^
  --add-data ".env.example;." ^
  --add-data "app\templates\setup.html;app\templates" ^
  app\run.py

echo.
echo === Build Complete ===
echo Executable: %ROOT_DIR%backend\dist\jpeigo-slides.exe
echo.
echo To ship:
echo   1. Create folder: jpeigo-slides-portable\
echo   2. Copy jpeigo-slides.exe into it
echo   3. Create backend\ subfolder with .env.example inside
echo   4. Zip and distribute!
echo.
pause
