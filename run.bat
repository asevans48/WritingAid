@echo off
echo Starting Writer Platform...

:: Activate virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python main.py
if errorlevel 1 (
    echo.
    echo ERROR: Failed to start application
    echo Please ensure dependencies are installed: run install.bat
    pause
)
