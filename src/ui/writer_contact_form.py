"""The one place the writer types their name, phone, email and address
(9.2 addendum, 24 Nov 2026), for the standard manuscript title page.

Shown in the Publishing tab under the publishing route, and in Settings
("Your Details"). The details are the writer's, kept once for every book
(``src.data.writer_contact``); the pen name is this project's byline (the
manuscript's existing ``author``), so that row shows only with a project.

In the Publishing tab each field is stored as it is typed (no buttons). In
Settings (``live=False``) the fields are stored when Save is pressed, like
the rest of that dialog.
"""

from __future__ import annotations

from typing import Any, Dict

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QGridLayout, QLabel, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget

from src.data import writer_contact as wc
from src.ui.ui_kit import GAP, section_header


class ContactForm(QWidget):
    """Name, pen name (with a project), phone, email and address."""

    changed = pyqtSignal()           # the project's byline changed (it is saved with the project)

    def __init__(self, parent=None, *, live: bool = True, config: Any = None):
        super().__init__(parent)
        self.live = live
        self.config = config
        self.project: Any = None
        self._loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(GAP)
        head = section_header("YOUR DETAILS FOR THE TITLE PAGE")
        head.setToolTip("Kept for all your books. Empty fields are left off the title page.\n"
                        "The pen name is this book's byline; blank uses your name.")
        outer.addWidget(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(GAP * 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.fields: Dict[str, Any] = {}
        self.name = self._line("name", "Your real name, as on contracts")
        self.pen = QLineEdit()
        self.pen.setPlaceholderText("Byline for this book (blank = your name)")
        self.pen.textChanged.connect(self._pen_changed)
        self.phone = self._line("phone", "")
        self.email = self._line("email", "")
        self.address = QPlainTextEdit()
        self.address.setPlaceholderText("Street\nTown, postcode, country (as many lines as you need)")
        self.address.setTabChangesFocus(True)
        lines = self.address.fontMetrics().lineSpacing()
        self.address.setMaximumHeight(lines * 3 + 12)        # three lines, scales with the text
        self.address.textChanged.connect(lambda: self._field_changed("address"))
        self.fields["address"] = self.address

        self._pen_label = QLabel("Pen name:")
        grid.addWidget(QLabel("Name:"), 0, 0)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(self._pen_label, 0, 2)
        grid.addWidget(self.pen, 0, 3)
        grid.addWidget(QLabel("Phone:"), 1, 0)
        grid.addWidget(self.phone, 1, 1)
        grid.addWidget(QLabel("Email:"), 1, 2)
        grid.addWidget(self.email, 1, 3)
        grid.addWidget(QLabel("Address:"), 2, 0)
        grid.addWidget(self.address, 2, 1, 1, 3)
        outer.addLayout(grid)
        self._show_pen()
        self.refresh()

    def _line(self, field: str, placeholder: str) -> QLineEdit:
        edit = QLineEdit()
        if placeholder:
            edit.setPlaceholderText(placeholder)
        edit.textChanged.connect(lambda _t, f=field: self._field_changed(f))
        self.fields[field] = edit
        return edit

    # ── values ──

    def values(self) -> Dict[str, str]:
        return {f: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text())
                for f, w in self.fields.items()}

    def set_project(self, project: Any) -> None:
        self.project = project
        self._show_pen()
        self.refresh()

    def _show_pen(self) -> None:
        for w in (self._pen_label, self.pen):
            w.setVisible(self.project is not None)

    def showEvent(self, event):
        if self.live:
            self.refresh()                   # edits made in Settings meanwhile
        super().showEvent(event)

    def refresh(self) -> None:
        self._loading = True
        try:
            stored = wc.load(self.config)
            for f, w in self.fields.items():
                now = w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()
                if now != stored[f]:
                    w.setPlainText(stored[f]) if isinstance(w, QPlainTextEdit) else w.setText(stored[f])
            pen = wc.pen_name(self.project) if self.project is not None else ""
            if self.pen.text() != pen:
                self.pen.setText(pen)
        finally:
            self._loading = False

    # ── storing ──

    def _field_changed(self, field: str) -> None:
        if self._loading or not self.live:
            return
        try:
            wc.set_field(field, self.values()[field], self.config)
        except Exception as e:               # an exception escaping a slot aborts PyQt6
            print(f"[writer-contact] could not save: {e}")

    def _pen_changed(self, text: str) -> None:
        if self._loading or self.project is None:
            return
        try:
            wc.set_pen_name(self.project, text)
            self.changed.emit()
        except Exception as e:
            print(f"[writer-contact] could not set the pen name: {e}")

    def save(self) -> None:
        """Store every field (Settings' Save). Only fields that differ are written."""
        stored = wc.load(self.config)
        for field, value in self.values().items():
            if value != stored[field]:
                wc.set_field(field, value, self.config)


def settings_page(config: Any = None) -> QWidget:
    """The same form as a Settings page; ``page.form.save()`` on Save."""
    page = QWidget()
    layout = QVBoxLayout(page)
    page.form = ContactForm(live=False, config=config)
    layout.addWidget(page.form)
    layout.addStretch(1)
    return page
