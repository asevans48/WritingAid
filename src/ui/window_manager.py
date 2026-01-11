"""Window manager for handling multiple application windows."""

from typing import List, Optional
from PyQt6.QtWidgets import QMainWindow


class WindowManager:
    """Singleton manager for tracking all application windows."""

    _instance: Optional['WindowManager'] = None

    def __new__(cls):
        """Ensure only one instance exists (singleton pattern)."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._windows: List[QMainWindow] = []
            cls._instance._main_window: Optional[QMainWindow] = None
            cls._instance._multi_window_mode: bool = False
        return cls._instance

    def set_main_window(self, window: QMainWindow):
        """Set the main application window."""
        self._main_window = window
        if window not in self._windows:
            self._windows.append(window)

    def get_main_window(self) -> Optional[QMainWindow]:
        """Get the main application window."""
        return self._main_window

    def register_window(self, window: QMainWindow):
        """Register a new secondary window."""
        if window not in self._windows:
            self._windows.append(window)

    def unregister_window(self, window: QMainWindow):
        """Unregister a window (don't unregister main window)."""
        if window in self._windows and window != self._main_window:
            self._windows.remove(window)

    def get_all_windows(self) -> List[QMainWindow]:
        """Get all registered windows."""
        return list(self._windows)

    def get_secondary_windows(self) -> List[QMainWindow]:
        """Get all secondary windows (excluding main window)."""
        return [w for w in self._windows if w != self._main_window]

    def is_multi_window_mode(self) -> bool:
        """Check if multi-window mode is enabled."""
        return self._multi_window_mode

    def set_multi_window_mode(self, enabled: bool):
        """Set multi-window mode."""
        self._multi_window_mode = enabled

    def close_all_secondary_windows(self):
        """Close all secondary windows."""
        for window in self.get_secondary_windows():
            window.close()
