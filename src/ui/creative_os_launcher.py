"""CreativeOS launcher — the shell window users see on app startup.

Renders a grid of tool tiles. When the user has configured an LLM, an
"Ask CreativeOS what to do" prompt is shown above the grid; the user
types a request and the LLM picks the best matching tool.

Tools that aren't yet implemented appear with a "Coming soon" overlay.
"""

from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QFrame, QToolButton, QMessageBox, QSizePolicy,
)

from src.config.creativeos_config import (
    CreativeOSTool, default_tools, get_creativeos_config,
)


class _ToolTile(QFrame):
    """A clickable square tile representing one tool."""

    clicked = pyqtSignal(str)  # tool_id

    def __init__(self, tool: CreativeOSTool, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setObjectName("toolTile")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumSize(220, 180)
        self.setMaximumSize(280, 220)
        self.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor
                       if tool.available else Qt.CursorShape.ForbiddenCursor)

        bg = "#ffffff" if tool.available else "#f3f4f6"
        hover_bg = "#eef2ff" if tool.available else "#f3f4f6"
        border = "#e5e7eb"
        self.setStyleSheet(f"""
            QFrame#toolTile {{
                background-color: {bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QFrame#toolTile:hover {{
                background-color: {hover_bg};
                border: 1px solid #6366f1;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        icon = QLabel(tool.icon)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 44px;")
        layout.addWidget(icon)

        name = QLabel(tool.name)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_font = QFont()
        name_font.setPointSize(13)
        name_font.setBold(True)
        name.setFont(name_font)
        layout.addWidget(name)

        desc = QLabel(tool.description)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(desc)

        if not tool.available:
            badge = QLabel("Coming Soon")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                "color: #9ca3af; font-size: 10px; font-weight: 600; "
                "background-color: #e5e7eb; border-radius: 8px; padding: 2px 8px;")
            layout.addWidget(badge)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.tool.available:
            self.clicked.emit(self.tool.id)
        super().mousePressEvent(event)


class CreativeOSLauncher(QMainWindow):
    """Main launcher window for CreativeOS."""

    # Emitted when the user picks a tool to launch
    tool_selected = pyqtSignal(str)  # tool_id

    def __init__(self, tools: Optional[list[CreativeOSTool]] = None,
                 parent=None):
        super().__init__(parent)
        self.config = get_creativeos_config()
        self.tools = tools if tools is not None else default_tools()
        self._tools_by_id = {t.id: t for t in self.tools}
        self.setWindowTitle("CreativeOS")
        self.resize(900, 640)
        self._init_ui()

    # ── UI ──

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(40, 30, 40, 30)
        outer.setSpacing(20)

        # Header
        header = QHBoxLayout()
        title = QLabel("CreativeOS")
        title_font = QFont()
        title_font.setPointSize(28)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setStyleSheet("color: #1f2937;")
        header.addWidget(title)

        subtitle = QLabel("• Pick a tool to start creating")
        subtitle.setStyleSheet("color: #6b7280; font-size: 14px; "
                               "padding-left: 8px;")
        header.addWidget(subtitle)
        header.addStretch()

        self.settings_btn = QToolButton()
        self.settings_btn.setText("⚙")
        self.settings_btn.setToolTip(
            "CreativeOS settings — configure LLM access shared across tools")
        self.settings_btn.setStyleSheet("font-size: 20px; padding: 4px 10px;")
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)

        outer.addLayout(header)

        # Optional "Ask AI what to do" prompt — only shown when an LLM is
        # configured. The OS uses it to dispatch to the right tool.
        self.ask_panel = self._build_ask_panel()
        self.ask_panel.setVisible(self.config.has_llm_configured())
        outer.addWidget(self.ask_panel)

        if not self.config.has_llm_configured():
            hint = QLabel(
                "Configure an LLM in Settings to unlock the natural-language "
                "launcher (\"Ask CreativeOS what to do\"). Until then, click "
                "a tool below.")
            hint.setStyleSheet(
                "color: #6b7280; font-size: 12px; font-style: italic; "
                "background-color: #f9fafb; padding: 10px 14px; "
                "border-radius: 8px; border: 1px dashed #e5e7eb;")
            hint.setWordWrap(True)
            outer.addWidget(hint)

        # Tool grid
        grid_holder = QWidget()
        grid = QGridLayout(grid_holder)
        grid.setSpacing(20)
        grid.setContentsMargins(0, 10, 0, 10)
        cols = 3
        for idx, tool in enumerate(self.tools):
            tile = _ToolTile(tool)
            tile.clicked.connect(self._on_tile_clicked)
            grid.addWidget(tile, idx // cols, idx % cols)
        outer.addWidget(grid_holder)
        outer.addStretch()

        # Footer
        footer = QHBoxLayout()
        footer.addStretch()
        self.quit_btn = QPushButton("Quit")
        self.quit_btn.setStyleSheet("padding: 6px 18px;")
        self.quit_btn.clicked.connect(self.close)
        footer.addWidget(self.quit_btn)
        outer.addLayout(footer)

    def _build_ask_panel(self) -> QWidget:
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #f0f9ff;
                border: 1px solid #bae6fd;
                border-radius: 10px;
            }
        """)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        prompt_label = QLabel("💬")
        prompt_label.setStyleSheet("font-size: 20px; background: transparent; border: none;")
        layout.addWidget(prompt_label)

        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText(
            "Ask CreativeOS what you want to do — e.g. \"work on my novel\", "
            "\"draft a marketing email\"…")
        self.ask_input.setStyleSheet(
            "QLineEdit { background-color: #ffffff; border: 1px solid #93c5fd; "
            "border-radius: 6px; padding: 6px 10px; font-size: 13px; }")
        self.ask_input.returnPressed.connect(self._ask_submitted)
        layout.addWidget(self.ask_input, stretch=1)

        self.ask_btn = QPushButton("Go")
        self.ask_btn.setStyleSheet(
            "QPushButton { background-color: #3b82f6; color: white; "
            "border: none; border-radius: 6px; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #2563eb; }")
        self.ask_btn.clicked.connect(self._ask_submitted)
        layout.addWidget(self.ask_btn)

        return panel

    # ── Actions ──

    def _on_tile_clicked(self, tool_id: str):
        tool = self._tools_by_id.get(tool_id)
        if tool is None:
            return
        if not tool.available:
            QMessageBox.information(
                self, "Coming Soon",
                f"'{tool.name}' isn't ready yet. Stay tuned!")
            return
        self.tool_selected.emit(tool_id)

    def _ask_submitted(self):
        query = self.ask_input.text().strip()
        if not query:
            return
        match = self._match_tool_by_keywords(query)
        if match is None:
            QMessageBox.information(
                self, "No Match Yet",
                "I couldn't match that request to a tool. Try clicking a tile "
                "below, or rephrase your request.")
            return
        if not match.available:
            QMessageBox.information(
                self, "Coming Soon",
                f"'{match.name}' fits your request, but it isn't available yet.")
            return
        self.ask_input.clear()
        self.tool_selected.emit(match.id)

    def _match_tool_by_keywords(self, query: str) -> Optional[CreativeOSTool]:
        """Pick a tool whose keywords overlap most with the query.

        This is the fast offline fallback. When an LLM is configured we
        could swap in a real classifier; for now keyword matching is
        deterministic and instant.
        """
        q = query.lower()
        scored: list[tuple[int, CreativeOSTool]] = []
        for tool in self.tools:
            score = sum(1 for kw in tool.keywords if kw.lower() in q)
            # Bonus if the tool name itself appears
            if tool.name.lower() in q:
                score += 3
            if score > 0:
                scored.append((score, tool))
        if not scored:
            return None
        scored.sort(key=lambda x: (-x[0], not x[1].available))
        return scored[0][1]

    def _open_settings(self):
        from src.ui.creativeos_settings_dialog import CreativeOSSettingsDialog
        dlg = CreativeOSSettingsDialog(self)
        if dlg.exec():
            # User saved — re-evaluate whether the ask panel should be visible
            self.ask_panel.setVisible(self.config.has_llm_configured())
