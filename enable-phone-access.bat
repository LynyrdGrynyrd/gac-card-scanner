@echo off
REM Turns on phone access: creates an HTTPS certificate so phones on the same Wi-Fi can use the scanner and camera.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (echo Run start.bat once first ^(it installs the components^). & pause & exit /b 1)
".venv\Scripts\python.exe" -m app.make_cert
echo.
echo Now close the scanner window ^(if open^) and double-click start.bat again.
echo To turn phone access off again, delete the "certs" folder.
pause
