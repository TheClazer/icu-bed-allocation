@echo off
title City ICU Bed Allocation - stop
cd /d "%~dp0"
echo Stopping all containers (data is kept for next time)...
docker compose stop
echo Done.
pause
