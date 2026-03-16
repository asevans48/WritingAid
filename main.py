"""
Writer Platform - Main Application Entry Point
A comprehensive platform for writers to organize books, short stories, and media.
"""

import sys
import os
from pathlib import Path

# Check Python version and warn if incorrect
def check_python_version():
    """Warn if using wrong Python version."""
    version_info = sys.version_info
    version_str = f"{version_info.major}.{version_info.minor}.{version_info.micro}"

    # Check if free-threaded Python
    is_free_threaded = hasattr(sys, '_is_gil_enabled')

    # Warnings
    if is_free_threaded:
        print("=" * 70)
        print("⚠️  WARNING: Running with FREE-THREADED Python!")
        print("=" * 70)
        print(f"Current Python: {version_str} (free-threaded)")
        print(f"Location: {sys.executable}")
        print()
        print("❌ Local models will NOT work with free-threaded Python!")
        print()
        print("✅ Solution: Run with the virtual environment:")
        print("   ./run.sh")
        print("   OR")
        print("   source venv/bin/activate && python main.py")
        print("=" * 70)
        print()

    if version_info.major == 3 and version_info.minor < 10:
        print("=" * 70)
        print(f"⚠️  WARNING: Python {version_str} is too old!")
        print("=" * 70)
        print(f"Current Python: {version_str}")
        print(f"Location: {sys.executable}")
        print()
        print("❌ MLX and modern transformers require Python 3.10+")
        print()
        print("✅ Solution: Run with the virtual environment:")
        print("   ./run.sh")
        print("=" * 70)
        print()

    # Success message for correct version
    if version_info.major == 3 and 10 <= version_info.minor <= 13 and not is_free_threaded:
        print(f"✓ Using Python {version_str} (correct version)")
        print(f"  Location: {sys.executable}")
        # Check if we're in venv
        in_venv = hasattr(sys, 'prefix') and sys.prefix != sys.base_prefix
        if in_venv:
            print(f"  Running in virtual environment ✓")
        else:
            print(f"  ⚠️  NOT running in virtual environment - this may cause issues!")

check_python_version()

# Check for required packages
def check_required_packages():
    """Check if required packages are installed."""
    missing = []

    try:
        import PyQt6
    except ImportError:
        missing.append("PyQt6")

    try:
        import huggingface_hub
    except ImportError:
        missing.append("huggingface_hub")

    try:
        import transformers
    except ImportError:
        missing.append("transformers")

    if missing:
        print("=" * 70)
        print("⚠️  WARNING: Missing required packages!")
        print("=" * 70)
        print(f"Python: {sys.executable}")
        print(f"Missing packages: {', '.join(missing)}")
        print()
        print("✅ Solution: Run with the virtual environment:")
        print("   ./run.sh")
        print("   OR")
        print("   source venv/bin/activate && python main.py")
        print("=" * 70)
        print()
        return False
    return True

if not check_required_packages():
    print("Some packages are missing. The app may not work correctly.")
    print()

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QFont, QIcon
from src.ui.main_window import MainWindow
from src.ui.styles import SYSTEM_FONT


def qt_message_handler(mode, context, message):
    """Custom Qt message handler to suppress known harmless warnings."""
    # Suppress the QFont point size warning - it's a cosmetic Qt issue
    # that doesn't affect functionality
    if "QFont::setPointSize: Point size <= 0" in message:
        return  # Silently ignore this warning

    # For all other messages, print them normally
    if mode == QtMsgType.QtDebugMsg:
        print(f"Qt Debug: {message}")
    elif mode == QtMsgType.QtInfoMsg:
        print(f"Qt Info: {message}")
    elif mode == QtMsgType.QtWarningMsg:
        print(f"Qt Warning: {message}")
    elif mode == QtMsgType.QtCriticalMsg:
        print(f"Qt Critical: {message}", file=sys.stderr)
    elif mode == QtMsgType.QtFatalMsg:
        print(f"Qt Fatal: {message}", file=sys.stderr)


def main():
    """Initialize and run the Writer Platform application."""
    # Install custom message handler to suppress known Qt warnings
    qInstallMessageHandler(qt_message_handler)

    # Enable high DPI scaling for better display on various screens
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Writer Platform")
    app.setOrganizationName("WriterPlatform")

    # Set application icon
    icon_path = Path(__file__).parent / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Set default application font with valid point size
    default_font = QFont(SYSTEM_FONT, 10)
    if default_font.pointSize() <= 0:
        default_font.setPointSize(10)
    app.setFont(default_font)

    # Create and show main window
    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()