@echo off
setlocal enabledelayedexpansion

echo =====================================
echo   Writer Platform - Installation
echo =====================================
echo.

:: Check for Python
echo [1/4] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10 or higher from python.org
    pause
    exit /b 1
)
python --version
echo.

:: Create virtual environment if it doesn't exist
echo [2/4] Setting up virtual environment...
if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment
        pause
        exit /b 1
    )
)
echo Virtual environment ready.
echo.

:: Activate virtual environment and install dependencies
echo [3/4] Installing dependencies...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

:: Generate icon if it doesn't exist
echo [4/4] Setting up application assets...
if not exist "assets\icon.ico" (
    echo Generating application icon...
    python create_icon.py
)
echo.

echo =====================================
echo   Installation Complete!
echo =====================================
echo.
echo To run the application:
echo   1. Double-click run.bat
echo   2. Or run: python main.py
echo.
echo To create a standalone executable:
echo   Run: build.bat
echo.
pause
