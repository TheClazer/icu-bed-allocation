@echo off
title City ICU Bed Allocation
cd /d "%~dp0"

echo.
echo  City ICU Bed Allocation System
echo  ==============================
echo.

rem ---- 1. Docker running? start Docker Desktop if not -----------------------
docker info >nul 2>&1
if not errorlevel 1 goto dockerok

echo  [1/3] Docker is not running, starting Docker Desktop...
set "DD="
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" set "DD=%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
if exist "%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe" set "DD=%LocalAppData%\Programs\Docker\Docker\Docker Desktop.exe"
if exist "D:\Docker\App\Docker Desktop.exe" set "DD=D:\Docker\App\Docker Desktop.exe"
if not defined DD goto nodocker
start "" "%DD%"
set /a n=0

:waitdocker
ping -n 4 127.0.0.1 >nul
docker info >nul 2>&1
if not errorlevel 1 goto dockerok
set /a n+=1
if %n% geq 60 goto dockerslow
goto waitdocker

:dockerok
echo  [1/3] Docker is running.

rem ---- 2. start MySQL primary, replica, Redis and both app instances ---------
echo  [2/3] Starting containers (first run builds images and seeds MySQL, 1 to 3 minutes)...
docker compose up -d --build
if errorlevel 1 goto composefail

rem ---- 3. wait until the app answers, then open the browser -----------------
echo  [3/3] Waiting for the application...
set /a n=0

:waitapp
curl -s -f http://localhost:8000/api/ping >nul 2>&1
if not errorlevel 1 goto ready
set /a n+=1
if %n% geq 90 goto appslow
ping -n 3 127.0.0.1 >nul
goto waitapp

:ready
start "" http://localhost:8000
echo.
echo  Ready.
echo    Application (app-1) ......... http://localhost:8000
echo    Second instance (app-2) ..... http://localhost:8001
echo    Live database console ....... http://localhost:8000/console
echo    MySQL primary / replica ..... localhost:3307 / 3308  (root / rootpass)
echo.
echo  To stop everything, run stop.bat
echo.
pause
exit /b 0

:nodocker
echo  Could not find Docker Desktop. Start it by hand, then run this file again.
pause
exit /b 1

:dockerslow
echo  Docker did not start within 3 minutes. Open Docker Desktop and try again.
pause
exit /b 1

:composefail
echo  docker compose failed, see the messages above.
pause
exit /b 1

:appslow
echo  The app did not answer within 3 minutes. Check: docker compose logs app
pause
exit /b 1
