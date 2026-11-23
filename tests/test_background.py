"""R.2: one way to run background work."""

import gc
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _wait_for(app, cond, timeout=5.0):
    end = time.time() + timeout
    while not cond() and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    return cond()


def test_result_arrives_on_the_gui_thread(app):
    from src.ui import background
    got = {}
    gui = threading.get_ident()

    def done(result, error):
        got.update(result=result, error=error, thread=threading.get_ident())
    background.run_background(lambda: threading.get_ident(), done)
    assert _wait_for(app, lambda: "result" in got)
    assert got["error"] == "" and got["thread"] == gui and got["result"] != gui


def test_an_exception_reaches_the_caller_as_a_message(app):
    from src.ui import background
    got = {}

    def work():
        raise ValueError("the model refused")
    background.run_background(work, lambda r, e: got.update(result=r, error=e))
    assert _wait_for(app, lambda: "error" in got)
    assert got == {"result": None, "error": "the model refused"}


def test_closing_the_window_mid_run_does_not_crash_or_deliver(app):
    from PyQt6.QtWidgets import QLabel
    from src.ui import background
    window = QLabel("Suggestions")
    window.show()
    release = threading.Event()
    delivered = []

    def work():
        release.wait(5)
        return "late result"
    task = background.run_background(work, lambda r, e: window.setText(r) or delivered.append(r),
                                     owner=window)
    window.close()
    window.deleteLater()
    del window
    _wait_for(app, lambda: False, timeout=0.1)     # let the window be destroyed
    gc.collect()
    release.set()
    assert _wait_for(app, lambda: task not in background._RUNNING)
    assert delivered == []


def test_stop_drops_the_result_and_the_work_can_see_it(app):
    from src.ui import background
    seen, delivered = [], []
    started = threading.Event()

    def work(task):
        started.set()
        while not task.stopping:
            time.sleep(0.01)
        seen.append("stopped")
        return "unused"
    task = background.run_background(work, lambda r, e: delivered.append(r))
    started.wait(2)
    task.stop()
    assert _wait_for(app, lambda: task not in background._RUNNING)
    assert seen == ["stopped"] and delivered == []


def test_progress_is_reported(app):
    from src.ui import background
    messages, done = [], []

    def work(task):
        task.report("Reading the chapter…")
        return 1
    background.run_background(work, lambda r, e: done.append(r), on_progress=messages.append)
    assert _wait_for(app, lambda: done)
    assert messages == ["Reading the chapter…"]


def test_a_worker_with_its_own_finished_signal_is_kept_alive(app):
    """Like RephraseWorker: shadows QThread.finished. Dropping the only
    reference while it runs must not destroy a running thread."""
    from PyQt6.QtCore import QThread, pyqtSignal
    from src.ui import background
    release = threading.Event()

    class Worker(QThread):
        finished = pyqtSignal(object)

        def run(self):
            release.wait(5)
            self.finished.emit("done")

    w = Worker()
    background.start(w)
    assert w in background._RUNNING
    del w
    gc.collect()                       # the window that held it has closed
    release.set()
    assert _wait_for(app, lambda: not any(isinstance(t, Worker) for t in background._RUNNING))


def test_a_fake_that_never_starts_a_thread_is_not_kept(app):
    from PyQt6.QtCore import QThread
    from src.ui import background

    class Now(QThread):
        def start(self):
            self.run()

        def run(self):
            pass
    w = background.start(Now())
    assert w not in background._RUNNING


def test_old_names_still_work(app):
    from src.ui import background, companion_panel, overdescription_panel, passage_critique_dialog
    from src.ui import rephrase_dialog, rewrite_chat_panel
    assert companion_panel.BackgroundTask is background.Task
    for mod in (companion_panel, overdescription_panel, passage_critique_dialog, rewrite_chat_panel):
        assert mod._RUNNING is background._RUNNING
    assert rephrase_dialog._RUNNING_MOMENTS is background._RUNNING
