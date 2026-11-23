"""Run a long checkpoint job without freezing the app.

Creating or restoring a project checkpoint zips or unpacks the whole project
folder, which can be several gigabytes with a Video Studio. Done on the GUI
thread, it froze the app for minutes. ``run_with_progress`` runs the job on a
worker thread and shows a progress window while it waits:

* the window is application-modal, so nothing else can be edited meanwhile;
* auto-save is paused (the main window's ``_loading_project`` guard), so no
  save lands in the folder while it is being zipped or restored;
* the caller gets ``(result, error)`` back once the job is done, as if the
  call were synchronous.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

from PyQt6.QtCore import QEventLoop, QThread, Qt, pyqtSignal
from PyQt6.QtWidgets import QProgressDialog, QWidget

Work = Callable[[Callable[[int, int, str], None], Callable[[], bool]], Any]


class _Worker(QThread):
    progressed = pyqtSignal(int, str)        # permille, label
    finished_with = pyqtSignal(object, object)

    def __init__(self, work: Work):
        super().__init__()
        self._work = work
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        def progress(done: int, total: int, label: str) -> None:
            permille = int(1000 * done / total) if total else 0
            self.progressed.emit(max(0, min(1000, permille)), label or "")
        try:
            result = self._work(progress, lambda: self._cancel)
            self.finished_with.emit(result, None)
        except BaseException as e:            # noqa: BLE001 — returned to the caller
            self.finished_with.emit(None, e)


def _autosave_owner(widget: Optional[QWidget]):
    """The window that owns auto-save (has ``_loading_project``), if any."""
    w = widget
    while w is not None:
        if hasattr(w, "_loading_project"):
            return w
        w = w.parentWidget()
    return None


def _short(label: str, limit: int = 70) -> str:
    return label if len(label) <= limit else "…" + label[-(limit - 1):]


def run_with_progress(parent: Optional[QWidget], title: str, text: str, work: Work, *,
                      can_cancel: bool = True) -> Tuple[Any, Optional[BaseException]]:
    """Run ``work(progress, cancelled)`` on a worker thread and wait for it,
    keeping the app responsive. Returns ``(result, error)``."""
    dlg = QProgressDialog(text, "Cancel" if can_cancel else "", 0, 1000, parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    if not can_cancel:
        dlg.setCancelButton(None)
    dlg.setMinimumWidth(420)

    owner = _autosave_owner(parent)
    was_loading = getattr(owner, "_loading_project", False) if owner is not None else False
    if owner is not None:
        owner._loading_project = True        # pause auto-save

    worker = _Worker(work)
    outcome: dict = {}
    loop = QEventLoop()

    def on_progress(permille: int, label: str) -> None:
        try:
            dlg.setValue(permille)
            if label:
                dlg.setLabelText(f"{text}\n\n{_short(label)}")
        except Exception as e:                # an exception escaping a slot aborts PyQt6
            print(f"[checkpoint] {e}")

    def on_finished(result, error) -> None:
        outcome["result"], outcome["error"] = result, error
        loop.quit()

    def on_cancel() -> None:
        worker.cancel()
        dlg.setLabelText("Cancelling…")

    worker.progressed.connect(on_progress)
    worker.finished_with.connect(on_finished)
    if can_cancel:
        dlg.canceled.connect(on_cancel)
    else:
        # No way to close it early: a half-finished restore is worse than waiting.
        dlg.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

    try:
        dlg.show()
        worker.start()
        loop.exec()
        worker.wait()
    finally:
        if owner is not None:
            owner._loading_project = was_loading
        dlg.close()
        dlg.deleteLater()
    return outcome.get("result"), outcome.get("error")


def _gb(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f} GB"
    return f"{max(1, round(n / 1_000_000))} MB"


def ask_include_video_studio(parent: Optional[QWidget], project_dir, title: str):
    """Ask whether the checkpoint should include the Video Studio.

    Returns True (include, the default), False (writing only) or None
    (cancelled). Projects with no Video Studio are not asked: True.
    """
    from PyQt6.QtWidgets import QCheckBox, QMessageBox
    from src.services.project_checkpoint import video_studio_dirs, video_studio_size

    if not video_studio_dirs(project_dir):
        return True
    size = video_studio_size(project_dir)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText("Include the Video Studio in this checkpoint?")
    box.setInformativeText(
        f"The Video Studio holds {_gb(size)} of audio and video, so a checkpoint "
        f"with it can take several minutes.\n\n"
        f"Untick it for a writing-only checkpoint: chapters, plans and project "
        f"data, in seconds. Restoring a writing-only checkpoint leaves the Video "
        f"Studio as it is.")
    check = QCheckBox(f"Include Video Studio audio and video ({_gb(size)})")
    check.setChecked(True)
    box.setCheckBox(check)
    create = box.addButton("Create checkpoint", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(create)
    box.exec()
    if box.clickedButton() is not create:
        return None
    return check.isChecked()
