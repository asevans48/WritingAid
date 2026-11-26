"""The Prose Profile tab's "This chapter" panel.

Below the project targets, the chapter open in Write, measured against
them (``src/ai/prose_snapshot``, no model): sentence length and variety,
dialogue, adverbs, passive voice, readability and length, each beside the
genre's target. It refreshes when the tab is shown, when another chapter
is opened, and a moment after the genre is edited.

One line of links, so no buttons or sections are added (rule 13):

* **Full review in the Critique**: Analyze ▸ Prose for this chapter, the
  "Prose profile fit" report (tone, style, voice; needs a model);
* **Send the summary to the chat**: the same summary in the AI chat, to
  discuss;
* **Refresh**.

Wired with one call line in ``MainWindow`` (``install``).
"""

from __future__ import annotations

import html
from typing import Any, Callable, Optional

from PyQt6.QtCore import QObject, QEvent, Qt, QTimer
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout

from src.ui.ui_kit import PALETTE

_MARK = {"on target": ("✓", "success"), "above": ("▲", "warning"), "below": ("▼", "warning")}


class ChapterProfilePanel(QFrame):
    def __init__(self, profile_widget, main_window):
        super().__init__(profile_widget)
        self.profile_widget = profile_widget
        self.main_window = main_window
        self.snapshot = None
        self.setObjectName("chapterProfilePanel")
        self.setStyleSheet(
            f"#chapterProfilePanel {{ background: {PALETTE.get('surface', '#ffffff')};"
            f" border: 1px solid {PALETTE.get('border', '#e5e7eb')}; border-radius: 6px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(6)
        self.title = QLabel("This chapter")
        self.title.setStyleSheet("font-weight: bold; font-size: 14px;")
        lay.addWidget(self.title)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.body)
        self.links = QLabel(
            "<a href='review'>Full review in the Critique</a> · "
            "<a href='chat'>Send the summary to the chat</a> · "
            "<a href='refresh'>Refresh</a>")
        self.links.setToolTip(
            "Full review: Analyze ▸ Prose for this chapter, read against the tone, style and "
            "voice above (needs a model). The measures here need none.")
        self.links.linkActivated.connect(self._on_link)
        lay.addWidget(self.links)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(800)
        self._timer.timeout.connect(self.refresh)

    # ── What it reads ──────────────────────────────────────────────────

    def chapter_editor(self):
        me = getattr(self.main_window, "manuscript_editor", None)
        return getattr(me, "current_chapter_editor", None)

    def _project(self):
        project = getattr(self.main_window, "current_project", None)
        if project is None:
            return None
        try:            # the targets as typed, before they are saved
            return project.model_copy(update={"prose_profile": self.profile_widget.get_data()})
        except Exception:
            return project

    # ── Drawing ────────────────────────────────────────────────────────

    def refresh(self) -> None:
        from src.ai import prose_snapshot
        ce = self.chapter_editor()
        project = self._project()
        if ce is None or project is None or getattr(ce, "chapter", None) is None:
            self.snapshot = None
            self.title.setText("This chapter")
            self.body.setText("Open a chapter in Write and its measures show here, beside "
                              "these targets.")
            self.links.setVisible(False)
            return
        chapter = ce.chapter
        title = chapter.title or f"Chapter {getattr(chapter, 'number', '')}".strip()
        try:
            self.snapshot = prose_snapshot.measure(
                project, ce.editor.toPlainText(), title,
                getattr(project, "active_subproject_id", None))
        except Exception as e:                       # never break the tab
            print(f"[prose profile] could not measure the chapter: {e}")
            self.snapshot = None
            self.body.setText("The chapter could not be measured just now.")
            return
        self.title.setText(f"This chapter: {html.escape(title)}")
        self.body.setText(self._html(self.snapshot))
        self.links.setVisible(True)

    @staticmethod
    def _html(snap) -> str:
        head = f"<p>{html.escape(snap.headline())}</p>"
        if not snap.rows:
            return head
        muted = PALETTE.get("text_muted", "#737373")
        rows = []
        for r in snap.rows:
            mark, tone = _MARK.get(r.verdict, ("·", "text_muted"))
            colour = PALETTE.get(tone, muted)
            target = f"target {html.escape(r.target)}" if r.target else "no target"
            source = f" <span style='color:{muted}'>({html.escape(r.source)})</span>" if r.source else ""
            rows.append(f"<tr><td style='color:{colour}; padding-right:6px'>{mark}</td>"
                        f"<td style='padding-right:10px'><b>{html.escape(r.label)}</b></td>"
                        f"<td style='padding-right:10px'>{html.escape(r.value)}</td>"
                        f"<td>{target}{source}</td></tr>")
        return (head + "<table cellspacing='2'>" + "".join(rows) + "</table>"
                f"<p style='color:{muted}'>Measured against {html.escape(snap.genre_label)}. "
                "Tone, style and voice need the full review.</p>")

    # ── Links ──────────────────────────────────────────────────────────

    def _on_link(self, which: str) -> None:
        try:
            if which == "refresh":
                self.refresh()
            elif which == "review":
                ce = self.chapter_editor()
                if ce is not None:
                    from src.ui import analysis_menu
                    analysis_menu.run(ce, "prose")
            elif which == "chat":
                send_to_chat(self.main_window, self.snapshot)
        except Exception as e:                       # never let an exception escape a slot
            print(f"[prose profile] {which} failed: {e}")


def _current(main_window):
    """(chapter editor, snapshot) for the chapter open in Write, or (None, None)."""
    from src.ai import prose_snapshot
    me = getattr(main_window, "manuscript_editor", None)
    ce = getattr(me, "current_chapter_editor", None)
    project = getattr(main_window, "current_project", None)
    if ce is None or project is None or getattr(ce, "chapter", None) is None:
        return None, None
    chapter = ce.chapter
    title = chapter.title or f"Chapter {getattr(chapter, 'number', '')}".strip()
    return ce, prose_snapshot.measure(project, ce.editor.toPlainText(), title,
                                      getattr(project, "active_subproject_id", None))


def context_for(main_window) -> str:
    """The chat context's "current chapter measured" block ("" when none)."""
    try:
        _ce, snap = _current(main_window)
        return snap.context_text() if snap is not None else ""
    except Exception as e:
        print(f"[prose profile] chat context: {e}")
        return ""


def run_chat(main_window, intent: dict, message: str) -> bool:
    """The chat's "prose profile" / "review my prose" (``prose_chat``)."""
    chat = main_window.chat_widget
    try:
        ce, snap = _current(main_window)
    except Exception as e:
        chat.add_message("Assistant", f"The chapter could not be measured just now ({e}).")
        return True
    if snap is None:
        chat.add_message("Assistant", "Open a chapter in Write first, and I'll measure it "
                                      "against the Prose Profile.")
        return True
    review = intent.get("depth") == "review"
    text = snap.markdown(review_hint=not review)
    if review:
        from src.ui import analysis_menu
        started = analysis_menu.run(ce, "prose")
        text += ("\n\nThe full review (tone, style and voice against the profile) is running "
                 "in the Critique as the **Prose profile fit** report." if started else
                 "\n\nThe full review could not start just now; Analyze ▸ Prose in Write runs it.")
    chat.add_message("Assistant", text)
    try:
        main_window._record_chat_turn(message, text)
    except Exception:
        pass
    return True


def send_to_chat(main_window, snapshot) -> bool:
    """Post a snapshot's summary in the AI chat and bring the chat forward."""
    chat = getattr(main_window, "chat_widget", None)
    if chat is None or snapshot is None:
        return False
    text = snapshot.markdown()
    chat.add_message("Assistant", text)
    try:
        main_window._record_chat_turn("", text)
    except Exception:
        pass
    _show_chat(main_window, chat)
    return True


def _show_chat(main_window, chat) -> None:
    """Open the side panel on the AI chat (as the other "ask the chat" entries do)."""
    try:
        main_window.sidebar_container.expand()
    except Exception:
        pass
    tabs = getattr(main_window, "sidebar_tabs", None)
    if tabs is not None:
        idx = tabs.indexOf(chat)
        if idx >= 0:
            tabs.setCurrentIndex(idx)


class _Watch(QObject):
    """Refresh when the tab is shown; and soon after the genre changes."""

    def __init__(self, panel: ChapterProfilePanel):
        super().__init__(panel)
        self.panel = panel

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Show:
            self.panel.refresh()
        return False


def install(main_window) -> Optional[ChapterProfilePanel]:
    """Add the panel to the Prose Profile tab (one call line in MainWindow)."""
    widget = getattr(main_window, "prose_profile_widget", None)
    if widget is None or getattr(widget, "chapter_panel", None) is not None:
        return getattr(widget, "chapter_panel", None)
    panel = ChapterProfilePanel(widget, main_window)
    layout = getattr(widget, "content_layout", None) or widget.layout()
    layout.insertWidget(max(layout.count() - 1, 0), panel)       # above the stretch
    widget.chapter_panel = panel
    widget.installEventFilter(_Watch(panel))
    for edit in (widget.genre_edit, widget.tone_edit, widget.style_edit, widget.voice_edit):
        edit.textChanged.connect(lambda *_: panel._timer.start())
    me = getattr(main_window, "manuscript_editor", None)
    for name in ("chapter_switched",):
        sig = getattr(me, name, None)
        if sig is not None and hasattr(sig, "connect"):
            sig.connect(lambda *_: panel.isVisible() and panel._timer.start())
            break
    return panel
