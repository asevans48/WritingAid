"""Listen and mark (piece 6.1).

The chapter is read aloud one sentence at a time, with the sentence being
read highlighted. Space pauses and resumes, M marks the sentence being
read (M again unmarks it), Esc stops. Marks are kept per chapter in the
project's companion file (``src/data/listen_marks.py``).

**One sentence at a time.** The speech service (``TTSService``) reports
only that it started and that it finished, never where it is. So each
sentence is spoken on its own, and the next one starts when the service
says it has finished: the app always knows which sentence is playing.

**The highlight is not an edit.** It is an extra selection on the
editor, so nothing reaches the undo stack, the saved text or the
modified flag. Each sentence is held by a ``QTextCursor``, which follows
any typing the writer does while listening.

**Where it is:** "👂 Listen and mark" in the Write toolbar's
"🗣 Read Aloud ▾" menu, and "Marks in this chapter" beside it (only when
there are marks) to go to a marked sentence. While listening, the
Read Aloud button pauses and resumes and its ⏹ Stop reading stops.
No new button.

**Tiers:** uses whichever speech engine Read Aloud is set to. With none,
the menu entry says so and does nothing else. No model is used here (the
optional "enhance text for speech" model step of Read Aloud is not used:
it would cost one model call per sentence).

Tests use a fake speaker (see ``Speaker``); nothing here is audible in
tests.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import QEvent, QObject, Qt, QTimer
from PyQt6.QtGui import QColor, QTextCharFormat, QTextCursor, QTextFormat
from PyQt6.QtWidgets import QTextEdit

from src.data import listen_marks
from src.ui.styles import COLORS

TICK_MS = 100
CURRENT_COLOUR = COLORS["warning_border"]       # the sentence being read
MARKED_COLOUR = COLORS["violet_tint"]           # a marked sentence
MARKED_INK = COLORS["violet"]
_MINE = int(QTextFormat.Property.UserProperty) + 61   # tags our extra selections

_MODIFIERS = (Qt.KeyboardModifier.ControlModifier, Qt.KeyboardModifier.AltModifier,
              Qt.KeyboardModifier.MetaModifier, Qt.KeyboardModifier.ShiftModifier)

KEYS_HINT = "Space pauses or resumes · M marks the sentence (again to unmark) · Esc stops"
NO_VOICE = ("Listening needs a speech voice, and none is set up on this computer. "
            "Read Aloud's voice settings (right-click → More → 🔊 Text to Speech → "
            "Voice Settings…) show what can be installed.")


# ── Speaking ───────────────────────────────────────────────────────────

class Speaker:
    """What a listening session needs from a speech engine. Tests pass a
    fake; the app uses ``SystemSpeaker``."""

    error: str = ""

    def available(self) -> bool: return True
    def begin(self) -> None: ...
    def end(self) -> None: ...
    def speak(self, text: str) -> None: ...
    def pause(self) -> bool: return False
    def resume(self) -> bool: return False
    def stop(self) -> None: ...

    @property
    def is_speaking(self) -> bool: return False

    def stopped_elsewhere(self) -> bool:
        """Was the reading stopped by something other than this session?"""
        return False


class SystemSpeaker(Speaker):
    """Read Aloud's own speech service, with its engine and voice."""

    def __init__(self, text_editor: Any):
        self._ed = text_editor
        self._svc = getattr(text_editor, "_tts_service", None)
        self._saved = None
        self.error = ""

    def available(self) -> bool:
        try:
            return bool(self._ed.is_tts_available()) and self._svc is not None
        except Exception:
            return False

    def begin(self) -> None:
        # The editor's start and end callbacks would reset the Read Aloud
        # button after every sentence; they are set aside while listening.
        try:
            self._ed._apply_tts_settings()
        except Exception as e:                      # noqa: BLE001
            print(f"[listen] voice settings not applied: {e}")
        s = self._svc
        self._saved = (s._on_start, s._on_end, s._on_error, s._on_progress)
        s.set_callbacks(on_error=self._on_error)

    def _on_error(self, message: str) -> None:      # speech thread
        self.error = str(message or "speech failed")

    def end(self) -> None:
        s, saved = self._svc, self._saved
        self._saved = None
        if s is None or saved is None:
            return
        # Restore only if nobody else (a newer editor) has set its own.
        if s._on_start is None and s._on_end is None:
            s.set_callbacks(*saved)

    def speak(self, text: str) -> None:
        from src.utils.markdown_editor import strip_markdown
        self._svc.speak(strip_markdown(text) or text)

    def pause(self) -> bool:
        return bool(self._svc.pause())

    def resume(self) -> bool:
        return bool(self._svc.resume())

    def stop(self) -> None:
        if self._svc is not None and (self._svc.is_speaking or self._svc.is_paused):
            self._svc.stop()

    @property
    def is_speaking(self) -> bool:
        return bool(self._svc is not None and self._svc.is_speaking)

    def stopped_elsewhere(self) -> bool:
        return bool(getattr(self._svc, "_stop_requested", False))


# ── Sentences ──────────────────────────────────────────────────────────

def sentence_spans(text: str) -> List[tuple]:
    """(start, end) of each sentence worth reading (some letter or digit)."""
    from src.ai.overdescription import sentence_spans as spans
    return [(s, e) for s, e in spans(text) if any(c.isalnum() for c in text[s:e])]


def _cursor(doc, start: int, end: int) -> QTextCursor:
    c = QTextCursor(doc)
    c.setPosition(start)
    c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
    return c


def _text(c: QTextCursor) -> str:
    return c.selectedText().replace(" ", "\n")


# ── A session ──────────────────────────────────────────────────────────

class ListenSession(QObject):
    """Reads ``editor``'s text from ``from_pos`` to the end, a sentence at
    a time, and keeps the marks made on the way."""

    def __init__(self, editor: QTextEdit, speaker: Speaker, project: Any = None,
                 chapter_id: str = "", on_change: Optional[Callable[[], None]] = None,
                 on_finish: Optional[Callable[[str], None]] = None, parent=None):
        super().__init__(parent or editor)
        self.editor, self.speaker = editor, speaker
        self.project, self.chapter_id = project, chapter_id
        self.on_change, self.on_finish = on_change, on_finish
        self.cursors: List[QTextCursor] = []
        self.index = -1
        self.running = self.paused = False
        self._restart = False             # the engine could not pause: say it again
        self._marked: Dict[int, str] = {}  # sentence index → mark id
        self.marks_made = 0
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # The state, for the button and for tests.
    @property
    def total(self) -> int:
        return len(self.cursors)

    def current_text(self) -> str:
        return _text(self.cursors[self.index]) if 0 <= self.index < self.total else ""

    def current_span(self) -> tuple:
        if not 0 <= self.index < self.total:
            return (-1, -1)
        c = self.cursors[self.index]
        return (c.selectionStart(), c.selectionEnd())

    def marked_indices(self) -> List[int]:
        return sorted(self._marked)

    # ── Start and stop ──
    def start(self, from_pos: int = 0) -> bool:
        doc = self.editor.document()
        text = self.editor.toPlainText()
        spans = sentence_spans(text)
        if not spans:
            return False
        self.cursors = [_cursor(doc, s, e) for s, e in spans]
        self._marked = {}
        by_start = {s: i for i, (s, _e) in enumerate(spans)}
        for m in listen_marks.marks(self.project, self.chapter_id):
            s, _e, status = listen_marks.resolve(m, text)
            if status != listen_marks.CHANGED and s in by_start:
                self._marked.setdefault(by_start[s], m["id"])
        first = next((i for i, (_s, e) in enumerate(spans) if e > from_pos), 0)
        if self.speaker.is_speaking:
            self.speaker.stop()
        self.speaker.begin()
        self.running, self.paused = True, False
        self.index = first
        self.editor.installEventFilter(self)
        self._say()
        self._timer.start()
        return True

    def stop(self, finished: bool = False) -> None:
        if not self.running:
            return
        self.running = self.paused = False
        self._timer.stop()
        try:
            self.editor.removeEventFilter(self)
        except RuntimeError:
            pass
        try:
            self.speaker.stop()
        finally:
            self.speaker.end()
        self._paint(clear=True)
        self._changed()
        if self.on_finish:
            self.on_finish("finished" if finished else (self.speaker.error or "stopped"))

    # ── Playing ──
    def _say(self) -> None:
        # Skip sentences the writer deleted while listening.
        while 0 <= self.index < self.total and not self.cursors[self.index].hasSelection():
            self.index += 1
        if self.index >= self.total:
            self.stop(finished=True)
            return
        self._restart = False
        self._paint()
        self.speaker.speak(self.current_text())
        self._changed()

    def _tick(self) -> None:
        try:
            if not self.running or self.paused:
                return
            if self.speaker.error:
                self.stop()
                return
            if self.speaker.is_speaking:
                return
            if self.speaker.stopped_elsewhere():
                self.stop()
                return
            self.index += 1
            self._say()
        except Exception as e:                      # noqa: BLE001 (rule 7)
            print(f"[listen] {e}")
            self.stop()

    def pause(self) -> None:
        if not self.running or self.paused:
            return
        if not self.speaker.pause():
            # This engine cannot pause: stop, and say the sentence again.
            self._restart = True
            self.speaker.stop()
        self.paused = True
        self._changed()

    def resume(self) -> None:
        if not self.running or not self.paused:
            return
        self.paused = False
        if self._restart or not self.speaker.resume():
            self._say()
        self._changed()

    def toggle_pause(self) -> None:
        self.resume() if self.paused else self.pause()

    # ── Marking ──
    def mark(self) -> Optional[bool]:
        """Mark the sentence being read (or unmark it). True: marked,
        False: unmarked, None: nothing being read."""
        if not self.running or not 0 <= self.index < self.total:
            return None
        c = self.cursors[self.index]
        if self.index in self._marked:
            listen_marks.remove(self.project, self.chapter_id, self._marked.pop(self.index))
            result = False
        else:
            m = listen_marks.new_mark(_text(c), c.selectionStart(), c.selectionEnd(),
                                      QTextCursor(c).block().blockNumber())
            listen_marks.add(self.project, self.chapter_id, m)
            self._marked[self.index] = m["id"]
            self.marks_made += 1
            result = True
        self._paint()
        self._changed()
        return result

    # ── Keys while listening ──
    def eventFilter(self, obj, event) -> bool:
        try:
            et = event.type()
            if et not in (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride):
                return False
            mods = event.modifiers()
            if any(bool(mods & m) for m in _MODIFIERS):
                return False
            key = event.key()
            if key not in (Qt.Key.Key_Space, Qt.Key.Key_M, Qt.Key.Key_Escape):
                return False
            if et == QEvent.Type.ShortcutOverride:
                event.accept()          # ours, not a window shortcut's
                return True
            if key == Qt.Key.Key_Space:
                self.toggle_pause()
            elif key == Qt.Key.Key_M:
                self.mark()
            else:
                self.stop()
            return True
        except Exception as e:                      # noqa: BLE001 (rule 7)
            print(f"[listen] {e}")
            return False

    # ── Drawing ──
    def _paint(self, clear: bool = False) -> None:
        try:
            others = [s for s in self.editor.extraSelections()
                      if not s.format.property(_MINE)]
        except RuntimeError:
            return
        mine = []
        if not clear:
            for i in sorted(self._marked):
                if i != self.index and self.cursors[i].hasSelection():
                    mine.append(self._selection(self.cursors[i], MARKED_COLOUR, underline=True))
            if 0 <= self.index < self.total:
                mine.append(self._selection(self.cursors[self.index], CURRENT_COLOUR,
                                            underline=self.index in self._marked))
        self.editor.setExtraSelections(others + mine)
        if not clear and 0 <= self.index < self.total:
            self._scroll_to(self.cursors[self.index])

    @staticmethod
    def _selection(cursor: QTextCursor, colour: str, underline: bool = False):
        sel = QTextEdit.ExtraSelection()
        sel.cursor = QTextCursor(cursor)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(colour))
        if underline:
            fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
            fmt.setUnderlineColor(QColor(MARKED_INK))
        fmt.setProperty(_MINE, True)
        sel.format = fmt
        return sel

    def _scroll_to(self, cursor: QTextCursor) -> None:
        """Keep the sentence on screen without moving the writer's cursor."""
        c = QTextCursor(cursor)
        c.setPosition(cursor.selectionStart())
        rect = self.editor.cursorRect(c)
        view = self.editor.viewport().rect()
        if view.top() + 20 <= rect.top() and rect.bottom() <= view.bottom() - 20:
            return
        bar = self.editor.verticalScrollBar()
        bar.setValue(bar.value() + rect.top() - view.height() // 3)

    def _changed(self) -> None:
        if self.on_change:
            try:
                self.on_change()
            except Exception as e:                  # noqa: BLE001
                print(f"[listen] {e}")


# ── In the chapter editor (call lines in manuscript_editor.py) ─────────

def _session(owner) -> Optional[ListenSession]:
    s = getattr(owner, "_listen_session", None)
    return s if s is not None and s.running else None


def install(owner, menu) -> None:
    """Add "👂 Listen and mark" and "Marks in this chapter" to the Read
    Aloud ▾ menu, before "Read chapters…"."""
    from PyQt6.QtGui import QAction
    from PyQt6.QtWidgets import QMenu
    before = getattr(owner, "tts_read_range_btn", None)
    act = QAction("👂 Listen and mark", menu)
    act.setToolTip("Read the chapter aloud from the cursor, a sentence at a time. "
                   + KEYS_HINT)
    act.triggered.connect(lambda: _safe(start, owner))
    sub = QMenu("Marks in this chapter", menu)
    if before is not None:
        menu.insertAction(before, act)
        menu.insertMenu(before, sub)
    else:
        menu.addAction(act)
        menu.addMenu(sub)
    owner.listen_action, owner.listen_marks_menu = act, sub
    sub.menuAction().setVisible(False)          # shown once there are marks
    menu.aboutToShow.connect(lambda: _safe(_fill_marks_menu, owner))


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception as e:                          # noqa: BLE001 (rule 7)
        print(f"[listen] {e}")


def _chapter_id(owner) -> str:
    return getattr(getattr(owner, "chapter", None), "id", "") or ""


def _fill_marks_menu(owner) -> None:
    """One entry per mark; choosing one selects its sentence. A mark whose
    sentence has changed is listed as such."""
    sub = owner.listen_marks_menu
    sub.clear()
    text = owner.editor.toPlainText()
    ms = listen_marks.marks(getattr(owner, "project", None), _chapter_id(owner))
    for m in ms:
        s, e, status = listen_marks.resolve(m, text)
        words = m["text"] if len(m["text"]) <= 60 else m["text"][:57].rstrip() + "…"
        label = words + (f"  ({listen_marks.CHANGED_LABEL})"
                         if status == listen_marks.CHANGED else "")
        a = sub.addAction(label.replace("&", "&&"))
        if status == listen_marks.CHANGED:
            a.setToolTip(f"Marked: “{m['text']}”. That sentence is no longer in the "
                         "chapter as it was; the mark is kept.")
        a.triggered.connect(lambda _=False, s=s, e=e: _select(owner, s, e))
    sub.setTitle(f"Marks in this chapter ({len(ms)})" if ms else "Marks in this chapter")
    sub.menuAction().setVisible(bool(ms))
    if getattr(owner, "listen_action", None) is not None:
        owner.listen_action.setEnabled(_session(owner) is None)


def _select(owner, start: int, end: int) -> None:
    n = len(owner.editor.toPlainText())
    c = owner.editor.textCursor()
    c.setPosition(min(start, n))
    c.setPosition(min(end, n), QTextCursor.MoveMode.KeepAnchor)
    owner.editor.setTextCursor(c)
    owner.editor.ensureCursorVisible()
    owner.editor.setFocus()


def start(owner, speaker: Optional[Speaker] = None) -> Optional[ListenSession]:
    """Start listening from the cursor's sentence (the whole chapter when
    the cursor is at the top)."""
    from src.ui import notify
    if _session(owner) is not None:
        return _session(owner)
    speaker = speaker or SystemSpeaker(owner.editor)
    if not speaker.available():
        notify.empty(owner, "No speech voice", NO_VOICE)
        return None
    if not owner.editor.toPlainText().strip():
        notify.empty(owner, "No Text", "The chapter is empty: nothing to listen to.")
        return None
    timer = getattr(owner, "_tts_poll_timer", None)
    if timer is not None:
        timer.stop()                    # a Read Aloud in progress is replaced
    session = ListenSession(owner.editor, speaker, getattr(owner, "project", None),
                            _chapter_id(owner), on_change=lambda: _show(owner),
                            on_finish=lambda why: _finished(owner, why), parent=owner)
    owner._listen_session = session
    # The chapter editor is deleted when another chapter opens: stop then.
    owner.destroyed.connect(lambda *_: _quiet_stop(speaker))
    if not session.start(owner.editor.textCursor().position()):
        owner._listen_session = None
        notify.empty(owner, "No Text", "No sentences to listen to in this chapter.")
        return None
    owner.editor.setFocus()
    if notify._main_window(owner) is not None:
        notify.notice(owner, "Listening", "Listening. " + KEYS_HINT)
    return session


def _quiet_stop(speaker: Speaker) -> None:
    try:
        speaker.stop()
        speaker.end()
    except Exception:
        pass


def on_read_aloud_click(owner) -> bool:
    """The Read Aloud button while listening: pause or resume. True when
    it was handled here."""
    s = _session(owner)
    if s is None:
        return False
    s.toggle_pause()
    return True


def stop(owner) -> None:
    """⏹ Stop reading while listening."""
    s = _session(owner)
    if s is not None:
        s.stop()


def _show(owner) -> None:
    """The Read Aloud button shows where listening is."""
    s = getattr(owner, "_listen_session", None)
    btn = getattr(owner, "tts_speak_btn", None)
    if btn is None or s is None:
        return
    if not s.running:
        return
    place = f"{min(s.index + 1, s.total)}/{s.total}"
    marked = f" · {len(s._marked)} marked" if s._marked else ""
    btn.setText(("▶ Resume " if s.paused else "⏸ ") + place + marked)
    btn.setToolTip("Listening. " + KEYS_HINT)
    for name, on in (("tts_stop_btn", True), ("tts_read_range_btn", False)):
        w = getattr(owner, name, None)
        if w is not None:
            w.setEnabled(on)
    if getattr(owner, "listen_action", None) is not None:
        owner.listen_action.setEnabled(False)


def _finished(owner, why: str) -> None:
    from src.ui import notify
    s = getattr(owner, "_listen_session", None)
    owner._listen_session = None
    btn = getattr(owner, "tts_speak_btn", None)
    if btn is not None:
        btn.setToolTip("Read the chapter aloud (or the selection)")
    reset = getattr(owner, "_reset_tts_buttons", None)
    if reset is not None:
        reset()
    if getattr(owner, "listen_action", None) is not None:
        owner.listen_action.setEnabled(True)
    made = s.marks_made if s is not None else 0
    from src.ui import heard_notes; heard_notes.refresh(owner)     # the marks as notes (6.2)
    if why not in ("finished", "stopped"):
        notify.empty(owner, "Listening stopped", f"Listening stopped: {why}")
    elif notify._main_window(owner) is not None:
        tail = f" {made} sentence{'s' if made != 1 else ''} marked." if made else ""
        notify.done(owner, "Listening",
                    ("Finished the chapter." if why == "finished" else "Stopped listening.")
                    + tail)
