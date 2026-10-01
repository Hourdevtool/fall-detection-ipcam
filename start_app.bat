@echo off
title Fall Guard System
cd /d "%~dp0"

echo ===================================================
echo   Fall Guard - Fall Detection ^& IPCam System
echo ===================================================
echo [1/2] Checking Python environment...
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found: .venv\Scripts\python.exe
    echo Please make sure the virtual environment exists.
    pause
    exit /b 1
)

echo [2/2] Launching Fall Guard Application...
.venv\Scripts\python.exe main.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Application exited with error code %ERRORLEVEL%.
    pause
)
