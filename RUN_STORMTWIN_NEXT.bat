
@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment not found.
    echo Run the Python setup commands first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" dashboard_server.py

pause
