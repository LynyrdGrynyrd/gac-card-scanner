@echo off
REM Optional AI double-check: run the llama-server command from HANDOFF.md (models folder), port 8090.
REM GAC Card Scanner - double-click to start (Windows). Leave this window open while you work.
title GAC Card Scanner (internal pilot)
cd /d "%~dp0"
set PORT=8765
echo === Greater Akron Chamber - Card Scanner (internal pilot) ===
set SCHEME=http
set HOST=127.0.0.1
if not "%GAC_HOST%"=="" set HOST=%GAC_HOST%
set SSL=
if exist "certs\cert.pem" if exist "certs\key.pem" (
  set SCHEME=https
  set HOST=0.0.0.0
  set SSL=--ssl-certfile certs\cert.pem --ssl-keyfile certs\key.pem
  echo Phone access is ON ^(https^). Phones on the same Wi-Fi can use the scanner.
  echo If Windows asks about the firewall, allow access on PRIVATE networks only.
)
set URL=%SCHEME%://localhost:%PORT%/ui
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python 3 is not installed. Install it from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH"^), then double-click this file again.
  pause & exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo First-time setup ^(takes a few minutes^)...
  %PY% -m venv .venv || (echo Could not create environment. & pause & exit /b 1)
)
".venv\Scripts\python.exe" -m pip install -q --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (echo Installing components failed - check the internet connection. & pause & exit /b 1)
set "TESS="
where tesseract >nul 2>nul && set TESS=1
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" (set TESS=1& set "PATH=%PATH%;C:\Program Files\Tesseract-OCR")
if not defined TESS (
  echo.
  echo !! The card-reading engine ^(Tesseract^) is not installed.
  echo    Ask IT to install it from https://github.com/UB-Mannheim/tesseract/wiki
  echo    ^(default folder C:\Program Files\Tesseract-OCR^). The app will open, but scanning
  echo    will fail until it is installed.
  echo.
)
start "" /b cmd /c "timeout /t 5 >nul & start "" %URL%"
echo Starting... your browser will open %URL%
echo First time? The browser asks you to create the admin account.
echo To stop the scanner, close this window.
".venv\Scripts\python.exe" -m uvicorn app.main:app --host %HOST% --port %PORT% %SSL%
pause
