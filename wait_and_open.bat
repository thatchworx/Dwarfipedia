@echo off
REM wait_and_open.bat — waits for the server, then opens the browser.
REM
REM Deliberately a STANDALONE .bat file: labels and goto embedded inside a
REM quoted `cmd /c "..."` string are unreliable in real cmd.exe, which was
REM the original cause of autolaunch silently breaking.
REM
REM The port is no longer hardcoded. Windows reserves blocks of ports for
REM Hyper-V, WSL and Docker, so 5000 is not always bindable; the server picks
REM a free one and writes it to the .port file next to this script. We wait
REM for that file, then poll whatever port it names.

setlocal enabledelayedexpansion
set PORT=5000
set TRIES=0

:waitport
if exist "%~dp0.port" goto readport
set /a TRIES+=1
if %TRIES% GEQ 20 goto pollnow
timeout /t 1 /nobreak >nul
goto waitport

:readport
set /p PORT=<"%~dp0.port"

:pollnow
set TRIES=0

:retry
curl -s -o nul http://localhost:!PORT!/
if !errorlevel!==0 goto ready

set /a TRIES+=1
if !TRIES! GEQ 40 goto giveup

timeout /t 1 /nobreak >nul
goto retry

:ready
start "" http://localhost:!PORT!
exit /b

:giveup
echo.
echo   Couldn't confirm the server started in time.
echo   Open this address manually:  http://localhost:!PORT!
echo.
echo   If the server window showed a socket permissions error, a reserved
echo   Windows port range is in the way. The server now moves to a free
echo   port automatically — check its window for the address it chose.
echo.
exit /b
