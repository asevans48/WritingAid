@echo off
echo =====================================
echo Writer Platform - Installation
echo =====================================
echo.

echo Checking Python installation...
python --version
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10 or higher from python.org
    pause
    exit /b 1
)
echo.

echo Installing dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install dependencies
    pause
    exit /b 1
)
echo.

echo =====================================
echo Installation complete!
echo =====================================
echo.
echo To run the application, execute:
echo     python main.py
echo.
echo Or double-click run.bat
echo.
pause
