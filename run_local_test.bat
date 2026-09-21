@echo off
setlocal enabledelayedexpansion

echo =================================================================
echo        CVAT Local Test Launcher (No Docker, No Database)
echo =================================================================
echo.
echo [*] Starting Local Backend Server on http://127.0.0.1:7000...
start "CVAT Local Server" python cvat_local_server.py

timeout /t 2 /nobreak >nul

echo [*] Starting CVAT Frontend Web Server on http://localhost:3000...
echo.
call corepack yarn workspace cvat-ui run start

echo.
pause
