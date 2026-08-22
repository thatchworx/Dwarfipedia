@echo off
title DwarfWiki
cd /d "%~dp0server"

echo.
echo   ==========================================
echo     D W A R F W I K I
echo     a local legends viewer
echo   ==========================================
echo.

REM --- check Python ---
where python >nul 2>nul
if errorlevel 1 (
  echo   Python was not found on your PATH.
  echo   Install it from  https://www.python.org/downloads/
  echo   ^(tick "Add python.exe to PATH" in the installer^), then run this again.
  echo.
  pause
  exit /b
)

REM --- check Flask + lxml, install once if missing ---
python -c "import flask, lxml" >nul 2>nul
if errorlevel 1 (
  echo   Installing required libraries ^(one-time setup^)...
  python -m pip install flask lxml
  echo.
)

REM --- import any new worlds (prints progress; skips ones already done) ---
python parser.py

REM --- wait until the server actually answers, then open the browser.
REM     This now lives in its own real .bat file (wait_and_open.bat) with
REM     genuine labels/goto, rather than embedded inside a quoted cmd /c
REM     string. That embedding was the actual cause of autolaunch quietly
REM     failing on some machines — labels/goto inside a quoted argument
REM     passed to cmd /c are not reliable in real-world cmd.exe. A real
REM     standalone .bat file doesn't have that problem. ---
start "" "%~dp0wait_and_open.bat"

echo.
echo   Starting server... your browser will open automatically once it's ready.
echo   ^(Keep this window open while you use DwarfWiki. Close it or press
echo   Ctrl+C here to stop the server.^)
echo.

REM --- run the server (this window stays open) ---
python server.py

pause
