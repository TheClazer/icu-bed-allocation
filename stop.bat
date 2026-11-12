@echo off
title City ICU Bed Allocation - stop
cd /d "%~dp0"
echo Stopping the app, Redis and both MySQL servers (data is kept for next time)...
".venv\Scripts\python.exe" -m app.services down
echo Done.
pause
