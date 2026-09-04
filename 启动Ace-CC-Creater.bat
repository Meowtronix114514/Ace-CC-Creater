@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw "gui\main.py"
) else (
    echo Python not found. Please install Python and add to PATH.
    pause
)