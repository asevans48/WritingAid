@echo off
echo =====================================
echo   Writer Platform - Build Executable
echo =====================================
echo.

:: Activate virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo ERROR: Virtual environment not found.
    echo Please run install.bat first.
    pause
    exit /b 1
)

:: Check for PyInstaller
echo Checking PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: Failed to install PyInstaller
        pause
        exit /b 1
    )
)
echo.

:: Generate icon if needed
if not exist "assets\icon.ico" (
    echo Generating application icon...
    python create_icon.py
)

:: Build the executable
echo Building executable...
echo This may take a few minutes...
echo.

pyinstaller --name "WriterPlatform" ^
    --icon "assets\icon.ico" ^
    --windowed ^
    --onedir ^
    --add-data "assets;assets" ^
    --hidden-import "PyQt6" ^
    --hidden-import "PyQt6.QtWidgets" ^
    --hidden-import "PyQt6.QtCore" ^
    --hidden-import "PyQt6.QtGui" ^
    --hidden-import "pyttsx3" ^
    --hidden-import "edge_tts" ^
    --hidden-import "keyring" ^
    --hidden-import "markdown" ^
    --hidden-import "python-docx" ^
    --collect-all "PyQt6" ^
    --noconfirm ^
    main.py

if errorlevel 1 (
    echo.
    echo ERROR: Build failed
    pause
    exit /b 1
)

echo.
echo =====================================
echo   Build Complete!
echo =====================================
echo.
echo Executable created in: dist\WriterPlatform\
echo Run: dist\WriterPlatform\WriterPlatform.exe
echo.
pause
