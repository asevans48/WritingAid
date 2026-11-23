"""One way to run work in the background (piece R.2).

Model calls and long scans run off the GUI thread. Every screen used to
keep its own set of running threads, because a ``QThread`` that is garbage
collected while still running aborts the whole app. This module is the one
place that does it:

* ``start(worker)`` starts any ``QThread`` and keeps it alive until it has
  finished, even if the window that started it closes. Works for workers
  that shadow ``QThread.finished`` with a signal of their own.
* ``run_background(fn, on_done, ...)`` runs a plain function: ``on_done(result,
  error)`` is called on the GUI thread, ``error`` is a message when ``fn``
  raised. Optional ``on_progress(message)`` updates; optional ``owner``: when
  it is destroyed (its window closed) the result is dropped instead of being
  delivered to a dead widget. ``task.stop()`` asks the work to stop; work that
  takes a ``task`` argument can check ``task.stopping``.
* An exception in a callback never escapes a Qt slot (that would abort the
  app); it is printed instead.

This changes how work is run, never what is done with the result.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional, Set

from PyQt6.QtCore import QObject, QThread, pyqtSignal

# Threads still running. A QThread destroyed while running aborts the app,
# so every worker stays here until it has finished.
_RUNNING: Set[QThread] = set()


def _thread_finished(worker: QThread):
    """QThread's own ``finished`` signal, even when a subclass shadows the
    name with a signal of its own (``RephraseWorker.finished``)."""
    return QThread.finished.__get__(worker, QThread)


def keep_alive(worker: QThread) -> QThread:
    """Hold ``worker`` until its thread has finished."""
    _RUNNING.add(worker)
    _thread_finished(worker).connect(lambda w=worker: _RUNNING.discard(w))
    return worker


def start(worker: QThread) -> QThread:
    """Start ``worker``, kept alive until it finishes."""
    if not isinstance(worker, QThread):
        worker.start()                  # not a thread (a stand-in): nothing to keep alive
        return worker
    keep_alive(worker)
    worker.start()
    # A worker whose start() did the work directly (test fakes do) never
    # became a thread, so there is nothing to keep alive. A real thread is
    # running (or already finished) by the time start() returns.
    if not worker.isRunning() and not worker.isFinished():
        _RUNNING.discard(worker)
    return worker


def wait_all(timeout_ms: int = 5000) -> None:
    """Wait for every running worker (tests, and quitting the app)."""
    for worker in list(_RUNNING):
        try:
            worker.wait(timeout_ms)
        except RuntimeError:                # already deleted
            _RUNNING.discard(worker)


def safe(fn: Callable, label: str = "background") -> Callable:
    """``fn`` wrapped so an exception is printed, never raised into Qt."""
    def call(*args):
        try:
            return fn(*args)
        except Exception as e:              # an exception escaping a slot aborts PyQt6
            print(f"[{label}] {e}")
    return call


class Task(QThread):
    """Runs ``fn`` on a worker thread. ``done(result, error)``."""
    done = pyqtSignal(object, str)          # result, error ("" when it worked)
    progress = pyqtSignal(str)

    def __init__(self, fn: Callable[..., Any]):
        super().__init__()
        self.fn = fn
        self.stopping = False
        try:
            params = inspect.signature(fn).parameters
            self._pass_task = "task" in params
        except (TypeError, ValueError):
            self._pass_task = False

    def stop(self) -> None:
        """Ask the work to stop (it checks ``task.stopping``); its result is
        not delivered."""
        self.stopping = True

    def report(self, message: str) -> None:
        """Called from the work to show progress."""
        self.progress.emit(str(message))

    def run(self):
        try:
            result = self.fn(task=self) if self._pass_task else self.fn()
            self.done.emit(result, "")
        except Exception as e:
            # str(e) as before: an empty message lets callers show their own
            # fallback ("Couldn't read the chapter.").
            self.done.emit(None, str(e))


def run_background(fn: Callable[..., Any], on_done: Callable[[Any, str], None], *,
                   on_progress: Optional[Callable[[str], None]] = None,
                   owner: Optional[QObject] = None,
                   label: str = "background") -> Task:
    """Run ``fn`` in the background; ``on_done(result, error)`` on the GUI
    thread. See the module docstring."""
    task = Task(fn)
    alive = {"owner": True}
    if owner is not None:
        try:
            owner.destroyed.connect(lambda *_: alive.__setitem__("owner", False))
        except (AttributeError, RuntimeError):
            pass

    def deliver(result, error):
        if task.stopping or not alive["owner"]:
            return                          # stopped, or its window has gone
        on_done(result, error)

    task.done.connect(safe(deliver, label))
    if on_progress is not None:
        task.progress.connect(safe(lambda m: alive["owner"] and on_progress(m), label))
    start(task)
    return task


# The Companion's original name for a task, kept for existing imports.
BackgroundTask = Task
