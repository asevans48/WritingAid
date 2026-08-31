"""A tiny generic form dialog for editing a sub-record (a law, a
court, an agency, a public service) as a set of named fields.

Keeps the justice / government / services builders compact: instead of
a bespoke editor per sub-type, each declares a field spec and reuses
this dialog.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
    QTextEdit, QVBoxLayout,
)

# A field spec is (key, label, kind, options).
#   kind: "line" | "text" | "choice"
#   options: list[str] for "choice", else ignored.
FieldSpec = Tuple[str, str, str, Optional[List[str]]]


class RecordDialog(QDialog):
    """Edit a flat record of string fields. ``values`` seeds the form;
    ``get_values()`` returns the edited dict after ``exec()``."""

    def __init__(
        self,
        title: str,
        fields: List[FieldSpec],
        values: Optional[Dict[str, str]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 380)
        self._fields = fields
        self._widgets: Dict[str, object] = {}
        values = values or {}

        v = QVBoxLayout(self)
        form = QFormLayout()
        for key, label, kind, options in fields:
            cur = values.get(key, "")
            if kind == "text":
                w = QTextEdit()
                w.setPlainText(cur)
                w.setMaximumHeight(90)
            elif kind == "choice":
                w = QComboBox()
                w.setEditable(True)
                for opt in (options or []):
                    w.addItem(opt)
                if cur:
                    w.setCurrentText(cur)
                else:
                    w.setCurrentIndex(-1)
            else:
                w = QLineEdit()
                w.setText(cur)
            self._widgets[key] = w
            form.addRow(f"{label}:", w)
        v.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

    def get_values(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for key, _label, kind, _options in self._fields:
            w = self._widgets[key]
            if kind == "text":
                out[key] = w.toPlainText().strip()
            elif kind == "choice":
                out[key] = w.currentText().strip()
            else:
                out[key] = w.text().strip()
        return out


def edit_record(
    parent, title: str, fields: List[FieldSpec],
    values: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, str]]:
    """Show a RecordDialog; return the edited values dict, or None if
    cancelled or the first field is left blank."""
    dlg = RecordDialog(title, fields, values, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    out = dlg.get_values()
    first_key = fields[0][0]
    if not out.get(first_key):
        return None
    return out
