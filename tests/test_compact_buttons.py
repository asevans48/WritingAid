"""Narrow buttons show their symbol under the app's style sheet.

The app gives every push button 16 px of padding each side, so a button
capped at 20–48 px drew blank (the Critique's model-reload button did)."""

import ast
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def styled_app():
    from PyQt6.QtWidgets import QApplication
    from src.ui.styles import get_modern_style
    app = QApplication.instance() or QApplication([])
    before = app.styleSheet()
    app.setStyleSheet(get_modern_style())
    yield app
    app.setStyleSheet(before)


@pytest.mark.parametrize("own", ["", "font-size: 11px; padding: 3px 6px;",
                                 "QPushButton { padding: 2px 8px; } QPushButton:hover { }"])
def test_a_narrow_button_fits_its_symbol(styled_app, own):
    from PyQt6.QtWidgets import QPushButton
    from src.ui.ui_kit import compact_button
    plain = QPushButton("🗑")
    plain.setStyleSheet(own)
    plain.ensurePolished()
    fixed = QPushButton("🗑")
    fixed.setStyleSheet(own)
    compact_button(fixed)
    fixed.ensurePolished()
    assert fixed.minimumSizeHint().width() <= 28                   # fits a 28 px button
    if not own:
        assert plain.minimumSizeHint().width() > 28                # blank without the fix


def _narrow_push_buttons():
    """(file, line, name) of every push button capped at 48 px or less, and
    whether ``compact_button`` is called on it in the same function."""
    out = []
    for f in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(f.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            made = set()
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and \
                        getattr(node.value.func, "id", getattr(node.value.func, "attr", "")) == "QPushButton":
                    made.update(ast.unparse(t) for t in node.targets)
            compacted = {ast.unparse(n.args[0]) for n in ast.walk(fn)
                         if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "compact_button"
                         and n.args}
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                        node.func.attr in ("setMaximumWidth", "setFixedWidth", "setFixedSize"):
                    tgt = ast.unparse(node.func.value)
                    if tgt in made and node.args and isinstance(node.args[0], ast.Constant) \
                            and isinstance(node.args[0].value, int) and node.args[0].value <= 48:
                        out.append((f.relative_to(ROOT), node.lineno, tgt, tgt in compacted))
    return out


def test_every_narrow_push_button_is_compact():
    found = _narrow_push_buttons()
    assert len(found) >= 30
    missing = [f"{f}:{line} {name}" for f, line, name, ok in found if not ok]
    assert not missing, "narrow buttons that would draw blank: " + ", ".join(missing)
