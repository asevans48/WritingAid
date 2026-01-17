"""
Writer Platform - Main Application Entry Point
A comprehensive platform for writers to organize books, short stories, and media.
"""

import sys
import os
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QtMsgType, qInstallMessageHandler
from PyQt6.QtGui import QFont, QIcon
from src.ui.main_window import MainWindow


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
    default_font = QFont("Segoe UI", 10)
    if default_font.pointSize() <= 0:
        default_font.setPointSize(10)
    app.setFont(default_font)

    # Create and show main window
    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()