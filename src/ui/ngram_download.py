"""Settings ▸ Language: LanguageTool's extra data, download and remove (P.6).

One entry in the style of the NLTK resources beside it: name and size,
what it is for, a progress bar while it downloads, and one button that is
"Download" without the data, "Stop" while it downloads and "Remove" with it.
The download itself lives in ``src.utils.lt_ngrams`` on a plain thread, so
closing Settings mid-download is safe; reopening shows its progress.
"""

from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout,
)

from src.ui.ui_kit import PALETTE, plain_qss
from src.utils import lt_ngrams


class NgramDataGroup(QGroupBox):
    def __init__(self, parent=None, confirm=None) -> None:
        super().__init__("LanguageTool Extra Data", parent)
        # ``confirm(title, text) -> bool``; tests pass a stand-in.
        self._confirm = confirm or self._ask
        layout = QVBoxLayout(self)

        desc = QLabel(
            "Word-sequence counts that let the grammar check catch more "
            "confused words (“their” for “there”, "
            "“breaks” for “brakes”). Optional: without it, "
            "grammar checking works as before.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-size: 11px; padding-bottom: 8px;")
        layout.addWidget(desc)

        frame = QFrame()
        frame.setObjectName("ngramEntry")     # style the box, not the labels in it
        frame.setStyleSheet(f"QFrame#ngramEntry {{ background-color: {PALETTE['surface_soft']}; border: 1px solid {PALETTE['border']};"
                            " border-radius: 6px; padding: 8px; margin: 2px 0; }")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 8, 8, 8)
        fl.setSpacing(4)
        row = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: 500;")
        self.title_label.setWordWrap(True)
        row.addWidget(self.title_label, 1)
        self.action_btn = QPushButton()
        self.action_btn.setStyleSheet(plain_qss(size=13, pad="8px 16px"))
        self.action_btn.clicked.connect(self._on_action)
        row.addWidget(self.action_btn)
        fl.addLayout(row)
        self.detail_label = QLabel()
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-size: 11px;")
        fl.addWidget(self.detail_label)
        used = QLabel("Used for: grammar check (confused words)")
        used.setStyleSheet(f"color: {PALETTE['primary_dark']}; font-size: 10px;")
        fl.addWidget(used)
        layout.addWidget(frame)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(f"color: {PALETTE['ink_faint']}; font-size: 11px;")
        layout.addWidget(self.status_label)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    # ── state ──
    def refresh(self) -> None:
        try:
            st = lt_ngrams.state()
            installed = lt_ngrams.is_installed()
            size = lt_ngrams.human_size(lt_ngrams.NGRAM_ZIP_BYTES)
            on_disk = lt_ngrams.human_size(lt_ngrams.NGRAM_UNPACKED_BYTES)
            self.title_label.setText(
                f"English n-gram data (~{size} download, ~{on_disk} on disk)")
            self.detail_label.setText(
                f"From languagetool.org. {lt_ngrams.NGRAM_LICENCE}. "
                f"Kept in {lt_ngrams.ngram_root()}. A fast disk (SSD) is "
                "recommended; the first check after starting takes longer.")
            if st.running:
                self.action_btn.setText("Stop")
                self.progress.setVisible(True)
                self.progress.setValue(st.percent)
                self.status_label.setText(st.message)
                if not self._timer.isActive():
                    self._timer.start()
                return
            self._timer.stop()
            self.progress.setVisible(False)
            self.action_btn.setText("Remove" if installed else "Download")
            if installed:
                self.status_label.setText("✓ Installed. The grammar check uses it.")
            elif st.phase in ("failed", "cancelled"):
                self.status_label.setText(st.message)
            else:
                self.status_label.setText("Not installed.")
        except Exception as e:       # never escape a Qt slot
            self.status_label.setText(f"Could not read the data's state: {e}")

    def _on_action(self) -> None:
        try:
            if lt_ngrams.state().running:
                lt_ngrams.cancel()
            elif lt_ngrams.is_installed():
                if self._confirm("Remove LanguageTool Extra Data",
                                 "Remove the n-gram data? The grammar check goes "
                                 "back to its rules alone. You can download it again."):
                    lt_ngrams.remove()
            else:
                need = lt_ngrams.human_size(lt_ngrams.space_needed())
                if self._confirm("Download LanguageTool Extra Data",
                                 f"Download {lt_ngrams.human_size(lt_ngrams.NGRAM_ZIP_BYTES)}? "
                                 f"It needs about {need} free while it unpacks. "
                                 "It runs in the background; you can close Settings."):
                    lt_ngrams.start_download()
                    if lt_ngrams.state().running:
                        self._timer.start()
        except Exception as e:
            self.status_label.setText(f"Something went wrong: {e}")
        self.refresh()

    def _ask(self, title: str, text: str) -> bool:
        return QMessageBox.question(self, title, text) == QMessageBox.StandardButton.Yes
