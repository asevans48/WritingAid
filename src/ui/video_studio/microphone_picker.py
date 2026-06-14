"""Microphone picker — a tiny combo wrapper used by the slide
editor + video editor.

Both editors expose the same control: a QComboBox listing every
detected audio input, an optional initial selection by device
description, and a ``selected_device()`` accessor that returns the
matching ``QAudioDevice`` instance (falling back to the system
default when nothing matches).
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtMultimedia import QAudioDevice, QMediaDevices
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget


class MicrophonePicker(QWidget):
    """Combo + label that lets the writer pick which input device
    feeds the recorder. Emits ``device_changed(description)``
    whenever the writer picks a new entry so the host can persist
    the choice on the project file."""

    device_changed = pyqtSignal(str)

    def __init__(
        self,
        initial_description: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("🎤 Mic:"))
        self._combo = QComboBox()
        self._combo.setToolTip(
            "Pick which microphone feeds the recorder. The choice "
            "is saved on the project so it survives a close and "
            "reopen.")
        layout.addWidget(self._combo, stretch=1)
        self._populate()
        if initial_description:
            idx = self._find_by_description(initial_description)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
        self._combo.currentIndexChanged.connect(
            lambda _: self.device_changed.emit(
                self.selected_description()))

    def _populate(self) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        # First entry is the system default — keeps writers from
        # having to guess what gets used when nothing is saved.
        default = QMediaDevices.defaultAudioInput()
        default_label = (
            default.description() if default else "")
        self._combo.addItem(
            f"System default ({default_label})"
            if default_label else "System default",
            "")
        for dev in QMediaDevices.audioInputs():
            self._combo.addItem(dev.description(), dev.id())
        self._combo.blockSignals(False)

    def _find_by_description(self, description: str) -> int:
        # Skip the synthetic "(system default)" entry at index 0.
        for i in range(1, self._combo.count()):
            if (self._combo.itemText(i) or "") == description:
                return i
        return -1

    def selected_device(self) -> QAudioDevice:
        """Return the matching ``QAudioDevice``, falling back to
        the system default when the user picked the synthetic
        default entry or when the saved device is no longer
        connected (e.g. the writer's USB mic is unplugged)."""
        chosen_id = self._combo.currentData()
        if not chosen_id:
            return QMediaDevices.defaultAudioInput()
        for dev in QMediaDevices.audioInputs():
            if dev.id() == chosen_id:
                return dev
        return QMediaDevices.defaultAudioInput()

    def selected_description(self) -> str:
        """Description of the picked device — what we persist on
        the project file. Empty string when the writer is using
        the system default."""
        if self._combo.currentIndex() <= 0:
            return ""
        return self._combo.currentText() or ""

    def refresh(self) -> None:
        """Re-enumerate devices (call when the writer plugs in or
        unplugs a mic). Keeps the writer's selection when the same
        device description is still present."""
        keep = self.selected_description()
        self._populate()
        if keep:
            idx = self._find_by_description(keep)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
