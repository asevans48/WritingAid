"""Find and Replace dialog for the text editor."""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QLabel, QCheckBox, QWidget, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextDocument, QTextCursor


class FindReplaceDialog(QDialog):
    """Dialog for Find and Find/Replace functionality."""

    # Signals for find/replace operations
    find_next = pyqtSignal(str, bool, bool)  # text, case_sensitive, whole_word
    replace_next = pyqtSignal(str, str, bool, bool)  # find, replace, case_sensitive, whole_word
    replace_all = pyqtSignal(str, str, bool, bool)  # find, replace, case_sensitive, whole_word

    def __init__(self, parent=None, replace_mode: bool = False):
        """Initialize the dialog.

        Args:
            parent: Parent widget
            replace_mode: If True, show replace fields. If False, find only.
        """
        super().__init__(parent)
        self.replace_mode = replace_mode
        self._setup_ui()
        self._connect_signals()

        # Set window properties
        title = "Find and Replace" if replace_mode else "Find"
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setMinimumWidth(400)

    def _setup_ui(self):
        """Set up the dialog UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Find row
        find_layout = QHBoxLayout()
        find_label = QLabel("Find:")
        find_label.setMinimumWidth(60)
        self.find_input = QLineEdit()
        self.find_input.setPlaceholderText("Enter text to find...")
        find_layout.addWidget(find_label)
        find_layout.addWidget(self.find_input)
        layout.addLayout(find_layout)

        # Replace row (only in replace mode)
        if self.replace_mode:
            replace_layout = QHBoxLayout()
            replace_label = QLabel("Replace:")
            replace_label.setMinimumWidth(60)
            self.replace_input = QLineEdit()
            self.replace_input.setPlaceholderText("Enter replacement text...")
            replace_layout.addWidget(replace_label)
            replace_layout.addWidget(self.replace_input)
            layout.addLayout(replace_layout)
        else:
            self.replace_input = None

        # Options row
        options_layout = QHBoxLayout()
        self.case_sensitive_cb = QCheckBox("Case sensitive")
        self.whole_word_cb = QCheckBox("Whole word")
        options_layout.addWidget(self.case_sensitive_cb)
        options_layout.addWidget(self.whole_word_cb)
        options_layout.addStretch()
        layout.addLayout(options_layout)

        # Separator
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        # Status label
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        # Buttons row
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        self.find_next_btn = QPushButton("Find Next")
        self.find_next_btn.setDefault(True)
        button_layout.addWidget(self.find_next_btn)

        if self.replace_mode:
            self.replace_btn = QPushButton("Replace")
            self.replace_all_btn = QPushButton("Replace All")
            button_layout.addWidget(self.replace_btn)
            button_layout.addWidget(self.replace_all_btn)

        self.close_btn = QPushButton("Close")
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _connect_signals(self):
        """Connect internal signals."""
        self.find_next_btn.clicked.connect(self._on_find_next)
        self.close_btn.clicked.connect(self.close)
        self.find_input.returnPressed.connect(self._on_find_next)

        if self.replace_mode:
            self.replace_btn.clicked.connect(self._on_replace)
            self.replace_all_btn.clicked.connect(self._on_replace_all)
            self.replace_input.returnPressed.connect(self._on_replace)

    def _on_find_next(self):
        """Handle Find Next button."""
        text = self.find_input.text()
        if not text:
            self.status_label.setText("Please enter text to find")
            return
        self.find_next.emit(
            text,
            self.case_sensitive_cb.isChecked(),
            self.whole_word_cb.isChecked()
        )

    def _on_replace(self):
        """Handle Replace button."""
        find_text = self.find_input.text()
        replace_text = self.replace_input.text() if self.replace_input else ""
        if not find_text:
            self.status_label.setText("Please enter text to find")
            return
        self.replace_next.emit(
            find_text,
            replace_text,
            self.case_sensitive_cb.isChecked(),
            self.whole_word_cb.isChecked()
        )

    def _on_replace_all(self):
        """Handle Replace All button."""
        find_text = self.find_input.text()
        replace_text = self.replace_input.text() if self.replace_input else ""
        if not find_text:
            self.status_label.setText("Please enter text to find")
            return
        self.replace_all.emit(
            find_text,
            replace_text,
            self.case_sensitive_cb.isChecked(),
            self.whole_word_cb.isChecked()
        )

    def set_status(self, message: str):
        """Set the status label text."""
        self.status_label.setText(message)

    def set_find_text(self, text: str):
        """Pre-populate the find field with selected text."""
        if text:
            self.find_input.setText(text)
            self.find_input.selectAll()

    def showEvent(self, event):
        """Focus the find input when dialog is shown."""
        super().showEvent(event)
        self.find_input.setFocus()
        self.find_input.selectAll()
