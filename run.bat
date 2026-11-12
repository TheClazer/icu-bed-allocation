@echo off
title City ICU Bed Allocation
cd /d "%~dp0"

echo.
echo  City ICU Bed Allocation System
echo  ==============================
echo  Runs MySQL 8 (primary + replica), Redis 7 and two app instances as normal
echo  Windows programs. No Docker, no admin rights. The first run downloads
echo  MySQL and Redis once (about 260 MB) into the runtime folder.
echo.

rem ---- 1. Python environment ------------------------------------------------
if exist ".venv\Scripts\python.exe" goto venvok
echo  [1/3] Creating the Python environment (one time only)...
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY goto nopython
%PY% -m venv .venv
if errorlevel 1 goto nopython
".venv\Scripts\python.exe" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto pipfail
:venvok
echo  [1/3] Python environment ready.

rem ---- 2. MySQL primary, replica, Redis, app-1, app-2 ----------------------
echo  [2/3] Starting the database servers and the app...
".venv\Scripts\python.exe" -m app.services up
if errorlevel 1 goto upfail

rem ---- 3. open the browser --------------------------------------------------
echo  [3/3] Opening the browser.
start "" http://localhost:8000
echo.
echo  Ready.
echo    Application (app-1) ......... http://localhost:8000
echo    Second instance (app-2) ..... http://localhost:8001
echo    Live database console ....... http://localhost:8000/console
echo    MySQL primary / replica ..... localhost:3307 / 3308  (root / rootpass)
echo.
echo  Everything keeps running after you close this window.
echo  To stop it, run stop.bat
echo.
pause
exit /b 0

:nopython
echo  Python 3.10 or newer is needed. Install it from python.org, tick "Add to PATH", then run this again.
pause
exit /b 1

:pipfail
echo  Installing Python packages failed, see the messages above.
rmdir /s /q .venv
pause
exit /b 1

:upfail
echo  Start-up failed, see the message above. Logs are in runtime\logs
pause
exit /b 1
