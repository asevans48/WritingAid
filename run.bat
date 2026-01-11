@echo off
echo Starting Writer Platform...
python main.py
if errorlevel 1 (
    echo.
    echo ERROR: Failed to start application
    echo Please ensure dependencies are installed: run install.bat
    pause
)
