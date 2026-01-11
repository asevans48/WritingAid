"""Test script to debug startup issues."""
import sys
import traceback

# Must create QApplication BEFORE importing any widgets
print("Step 1: Creating QApplication...")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
app = QApplication(sys.argv)
print("  OK")

try:
    print("Step 2: Importing WindowManager...")
    from src.ui.window_manager import WindowManager
    print("  OK")

    print("Step 3: Importing SecondaryWindow...")
    from src.ui.secondary_window import SecondaryWindow
    print("  OK")

    print("Step 4: Importing MainWindow...")
    from src.ui.main_window import MainWindow
    print("  OK")

    print("Step 5: Creating MainWindow...")
    sys.stdout.flush()
    main_window = MainWindow()
    print("  OK")

    print("Step 6: Showing window...")
    main_window.show()
    print("  OK")

    print("\nAll steps passed! Starting event loop...")
    sys.exit(app.exec())

except Exception as e:
    print(f"\nERROR: {type(e).__name__}: {e}")
    traceback.print_exc()
    input("Press Enter to exit...")
    sys.exit(1)
