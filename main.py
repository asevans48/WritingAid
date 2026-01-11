"""
Writer Platform - Main Application Entry Point
A comprehensive platform for writers to organize books, short stories, and media.
"""

import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from src.ui.main_window import MainWindow


def main():
    """Initialize and run the Writer Platform application."""
    # Enable high DPI scaling for better display on various screens
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Writer Platform")
    app.setOrganizationName("WriterPlatform")

    # Create and show main window
    main_window = MainWindow()
    main_window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()