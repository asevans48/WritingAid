"""Secondary window for displaying detached tabs."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QTabWidget,
    QSplitter, QToolBar, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QAction

from src.ui.chat_widget import ChatWidget
from src.ui.window_manager import WindowManager
from src.ui.styles import get_modern_style, get_icon


class SecondaryWindow(QMainWindow):
    """Secondary window for displaying detached tabs."""

    window_closing = pyqtSignal()
    content_changed = pyqtSignal()
    tab_merge_requested = pyqtSignal(object, str)  # widget, label

    def __init__(self, project_name: str = "Writer Platform", parent=None):
        """Initialize the secondary window."""
        super().__init__(parent)
        self._project_name = project_name

        # Apply modern stylesheet
        self.setStyleSheet(get_modern_style())

        self._init_ui()
        self._create_toolbar()

        # Register with window manager
        WindowManager().register_window(self)

        # Set window properties
        self.setMinimumSize(800, 600)
        self.resize(1000, 700)

    def _init_ui(self):
        """Initialize user interface."""
        self.setWindowTitle(f"Writer Platform - {self._project_name}")

        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create splitter for main content and chat
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Create tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setDocumentMode(True)
        self.tab_widget.setMovable(True)

        # Enable context menu on tab bar
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

        # Create chat widget
        self.chat_widget = ChatWidget()
        self.chat_widget.setMaximumWidth(400)
        self.chat_widget.setMinimumWidth(300)

        # Add to splitter
        self.main_splitter.addWidget(self.tab_widget)
        self.main_splitter.addWidget(self.chat_widget)

        # Set initial splitter sizes (3:1 ratio)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self.main_splitter)

    def _create_toolbar(self):
        """Create minimal toolbar."""
        toolbar = QToolBar("Secondary Window Toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        self.addToolBar(toolbar)

        # Window title/project name
        self.window_label = QLabel(f"{get_icon('manuscript')} {self._project_name}")
        self.window_label.setStyleSheet("padding: 4px 12px; font-size: 16px; font-weight: 600;")
        toolbar.addWidget(self.window_label)

        toolbar.addSeparator()

        # AI toggle
        ai_action = QAction(f"{get_icon('ai')} AI", self)
        ai_action.setToolTip("Toggle AI Assistant")
        ai_action.triggered.connect(self._toggle_chat)
        toolbar.addAction(ai_action)

    def _toggle_chat(self):
        """Toggle chat widget visibility."""
        self.chat_widget.setVisible(not self.chat_widget.isVisible())

    def _show_tab_context_menu(self, pos):
        """Show context menu for tab."""
        from PyQt6.QtWidgets import QMenu

        tab_bar = self.tab_widget.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index == -1:
            return

        menu = QMenu(self)

        merge_action = menu.addAction("Merge to Main Window")
        merge_action.triggered.connect(lambda: self._merge_tab_to_main(tab_index))

        menu.exec(tab_bar.mapToGlobal(pos))

    def _merge_tab_to_main(self, tab_index: int):
        """Merge a tab back to main window."""
        if tab_index < 0 or tab_index >= self.tab_widget.count():
            return

        widget = self.tab_widget.widget(tab_index)
        label = self.tab_widget.tabText(tab_index)

        # Remove from this window
        widget.setParent(None)
        self.tab_widget.removeTab(tab_index)

        # Signal to main window to add this tab
        self.tab_merge_requested.emit(widget, label)

        # Close if no tabs left
        if self.tab_widget.count() == 0:
            self.close()

    def add_tab(self, widget: QWidget, label: str):
        """Add a tab to this window."""
        self.tab_widget.addTab(widget, label)

    def update_project_name(self, name: str):
        """Update the project name displayed."""
        self._project_name = name
        self.setWindowTitle(f"Writer Platform - {name}")
        self.window_label.setText(f"{get_icon('manuscript')} {name}")

    def closeEvent(self, event: QCloseEvent):
        """Handle window close - merge all tabs back to main window."""
        self.window_closing.emit()

        # Merge all remaining tabs back to main window
        while self.tab_widget.count() > 0:
            widget = self.tab_widget.widget(0)
            label = self.tab_widget.tabText(0)
            widget.setParent(None)
            self.tab_widget.removeTab(0)
            self.tab_merge_requested.emit(widget, label)

        # Unregister from window manager
        WindowManager().unregister_window(self)

        event.accept()

    def get_tab_count(self) -> int:
        """Get the number of tabs."""
        return self.tab_widget.count()
