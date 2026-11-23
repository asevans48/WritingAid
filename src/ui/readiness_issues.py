"""What the readiness checks found in one chapter (piece 2.1, under the
scorecard's grid).

Click a chapter in the scorecard and this lists every issue in it, check by
check: the passage, the sentence around it, why it was flagged, the
suggested fixes, and a link to that place in the chapter. Click a cell and
it shows that check alone. Overly descriptive sentences also link to the
existing "ways to expand" window.
"""

from __future__ import annotations

import html
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWidgets import QSizePolicy, QTextBrowser

from src.ui.ui_kit import PALETTE, STAGE_COLOURS

MAX_PER_CHECK = 60          # groups shown per check; the rest are counted
STATUS_WORDS = {"ready": "ready", "needs_work": "needs work", "problem": "a problem",
                "needs_model": "needs a model to judge", "could_not_check": "could not check",
                "info": "information"}


def _per_1000(name: str) -> bool:
    """Whether a check's measure is a rate per 1,000 words."""
    from src.ai import readiness as rd
    t = rd._thresholds().get(name)
    return bool(t is not None and t.per_1000)


def _e(text: Any) -> str:
    return html.escape(str(text or ""))


class ChapterIssues(QTextBrowser):
    # chapter id, passage, offset in the chapter
    show_requested = pyqtSignal(str, str, int)
    # chapter id, chapter title, sentence, offset (the Critique's expand signal)
    expand_requested = pyqtSignal(str, str, str, int)
    show_all_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._on_link)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._links: List[Tuple[str, Any]] = []
        self._chapter = None

    # ── Showing ──────────────────────────────────────────────────

    def show_chapter(self, chapter_report, checks: Optional[Sequence[str]] = None,
                     text: Optional[str] = None,
                     titles: Optional[Dict[str, str]] = None) -> None:
        """List the issues of ``chapter_report`` for ``checks`` (all when
        None). ``text`` is the chapter's text, for the sentence around each
        issue; it is used only if it is the text that was checked."""
        from src.ai import readiness as rd
        self._chapter = chapter_report
        self._links = []
        self._titles = titles or {}
        ch = chapter_report
        if text is not None and ch.text_hash and rd.text_hash(text) != ch.text_hash:
            text, stale = None, True
        else:
            stale = False
        title = f"{ch.number}. {ch.title}" if ch.number else ch.title
        parts = [f"<div style='font-size:14px; font-weight:bold; color:{PALETTE['ink']}'>"
                 f"{_e(title)}</div>",
                 f"<div style='color:{PALETTE['ink_faint']}'>{ch.words:,} words"
                 + (" · the opening chapter" if ch.is_opening else "")
                 + (" · checks that look across every chapter" if ch.chapter_id == rd.BOOK_ROW
                    else "") + "</div>"]
        names = ([s.name for s in rd.checks_for() if s.name in ch.results] if checks is None
                 else [n for n in checks if n in ch.results])
        if checks is not None:
            labels = ", ".join(rd.REGISTRY[n].label for n in names if n in rd.REGISTRY)
            parts.append(f"<p style='color:{PALETTE['ink_soft']}'>Showing {_e(labels)} · "
                         f"<a href='{self._link('all', None)}'>show every check for this "
                         "chapter</a></p>")
        if stale:
            parts.append(f"<p style='color:{PALETTE['warning']}'>The chapter has changed since "
                         "this check; click Check readiness for current results.</p>")
        for name in names:
            parts.append(self._check_html(name, ch.results[name], text, ch))
        if ch.chapter_id != rd.BOOK_ROW:
            parts.append(f"<p style='color:{PALETTE['ink_faint']}'>For this chapter's full "
                         "reports (pacing, voice, dialogue and the rest), <b>Run Critique</b> "
                         "below; it is set to this chapter.</p>")
        self.setHtml("".join(parts))
        self._fit()

    def show_message(self, text: str) -> None:
        self._chapter = None
        self._links = []
        self.setHtml(f"<p style='color:{PALETTE['ink_faint']}'><i>{_e(text)}</i></p>")
        self._fit()

    def _check_html(self, name: str, result, text: Optional[str], ch) -> str:
        from src.ai import readiness as rd
        spec = rd.REGISTRY.get(name)
        label = spec.label if spec else name
        stage = spec.stage if spec else ""
        colour = STAGE_COLOURS.get(stage, PALETTE["ink"])
        display = getattr(spec, "display", "count") if spec else "count"
        if result.status == "info":
            summary = "information, not counted"
        elif display == "measure" and result.measure is not None:
            summary = f"{STATUS_WORDS.get(result.status, result.status)}: {result.measure:g}"
        else:
            rate = (f", {result.measure:g} per 1,000 words"
                    if result.measure is not None and result.status != "could_not_check"
                    and spec is not None and _per_1000(spec.name) else "")
            summary = (f"{STATUS_WORDS.get(result.status, result.status)}: "
                       f"{result.count} found{rate}")
        head = (f"<div style='margin-top:10px'><span style='color:{colour}; font-weight:bold'>"
                f"{_e(rd.STAGE_LABELS.get(stage, stage))} › {_e(label)}</span> "
                f"<span style='color:{PALETTE['ink_soft']}'>— {_e(summary)}</span></div>")
        out = [head]
        if result.message:
            out.append(f"<div style='color:{PALETTE['ink_faint']}'>{_e(result.message)}</div>")
        items = [i for i in result.items if i.verdict != "cleared"]
        if result.status == "could_not_check":
            out.append(f"<div style='color:{PALETTE['error']}'>{_e(result.error)}</div>")
            return "".join(out)
        if result.status == "info" and not items:
            return "".join(out)
        if not items:
            out.append(f"<div style='color:{PALETTE['success']}'>Nothing found.</div>")
            return "".join(out)
        groups = self._group(items)
        out.append("<ol style='margin-top:4px'>")
        for key, group in list(groups.items())[:MAX_PER_CHECK]:
            out.append("<li style='margin-bottom:6px'>" + self._item_html(name, group, text, ch)
                       + "</li>")
        out.append("</ol>")
        more = len(groups) - MAX_PER_CHECK
        if more > 0:
            out.append(f"<div style='color:{PALETTE['ink_faint']}'>…and {more} more.</div>")
        if len(result.items) < result.found:
            out.append(f"<div style='color:{PALETTE['ink_faint']}'>Only the first "
                       f"{len(result.items)} of {result.found} are kept.</div>")
        return "".join(out)

    @staticmethod
    def _group(items) -> "OrderedDict[str, list]":
        """The same word or rule repeated is one entry with a count."""
        groups: "OrderedDict[str, list]" = OrderedDict()
        for i in items:
            key = i.key if i.kind in ("spelling", "grammar") and i.key else i.text.strip()
            groups.setdefault(key, []).append(i)
        return groups

    def _item_html(self, name: str, group, text: Optional[str], ch) -> str:
        first = group[0]
        where = ""
        if first.chapter_id and first.chapter_id != ch.chapter_id:
            chapters = list(dict.fromkeys(i.chapter_id for i in group if i.chapter_id))
            names = [self._titles.get(c, "") for c in chapters if self._titles.get(c)]
            if names:
                where = (f"<br><span style='color:{PALETTE['ink_faint']}'>In: "
                         + _e(", ".join(names[:6])) + (" …" if len(names) > 6 else "") + "</span>")
        times = f" <span style='color:{PALETTE['ink_faint']}'>×{len(group)}</span>" \
            if len(group) > 1 else ""
        bits = []
        if name == "overdescribed":
            bits.append(f"“{_e(first.text)}”{times}")
            bits.append(f"<br><span style='color:{PALETTE['ink_soft']}'>{_e(first.reason)}</span>")
            if first.suggestions:
                bits.append(f"<br><span style='color:{PALETTE['ink_faint']}'>A trim: "
                            f"“{_e(first.suggestions[0])}”</span>")
            bits.append(f"<br><a href='{self._link('show', first)}'>Show in chapter</a> · "
                        f"<a href='{self._link('expand', first)}'>Ways to expand it…</a>")
            return "".join(bits) + where
        kind = {"spelling": "Spelling", "grammar": "Grammar"}.get(first.kind, first.kind.title())
        bits.append(f"<b>{_e(first.text)}</b>{times} "
                    f"<span style='color:{PALETTE['ink_faint']}'>{_e(kind)}</span>")
        reason = first.reason
        if reason and reason.lower() not in ("possible misspelling.", kind.lower()):
            bits.append(f" — <span style='color:{PALETTE['ink_soft']}'>{_e(reason)}</span>")
        sentence = _sentence(text, first.start, first.end)
        if sentence:
            before, word, after = sentence
            bits.append(f"<br><span style='color:{PALETTE['ink_soft']}'>…{_e(before)}"
                        f"<b style='background:{PALETTE['primary_tint']}'>{_e(word)}</b>"
                        f"{_e(after)}…</span>")
        if first.suggestions:
            bits.append(f"<br><span style='color:{PALETTE['ink_faint']}'>Try: "
                        + ", ".join(f"“{_e(s)}”" for s in first.suggestions[:4]) + "</span>")
        if first.end > first.start or first.chapter_id:
            bits.append(f"<br><a href='{self._link('show', first)}'>Show in chapter</a>")
        return "".join(bits) + where

    # ── Links ────────────────────────────────────────────────────

    def _link(self, kind: str, item) -> str:
        self._links.append((kind, item))
        return f"issue:{len(self._links) - 1}"

    def _on_link(self, url: QUrl) -> None:
        try:
            index = int(url.toString().split(":", 1)[1])
            kind, item = self._links[index]
        except (ValueError, IndexError):
            return
        ch = self._chapter
        if kind == "all":
            self.show_all_requested.emit()
        elif ch is not None and kind == "show":
            self.show_requested.emit(item.chapter_id or ch.chapter_id, item.text, item.start)
        elif ch is not None and kind == "expand":
            cid = item.chapter_id or ch.chapter_id
            self.expand_requested.emit(cid, self._titles.get(cid, ch.title), item.text, item.start)

    def _fit(self) -> None:
        """As tall as the list, up to about 45% of the window; then it
        scrolls."""
        doc = self.document()
        doc.setTextWidth(max(200, self.viewport().width()))
        height = int(doc.size().height()) + 2 * self.frameWidth() + 8
        window = self.window().height() if self.window() is not None else 900
        cap = max(160, int(window * 0.45))
        if self.height() != min(height, cap):
            self.setFixedHeight(min(height, cap))
            from src.ui.ui_kit import relayout
            relayout(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.document() is not None and not self.document().isEmpty():
            self._fit()


def _sentence(text: Optional[str], start: int, end: int,
              reach: int = 90) -> Optional[Tuple[str, str, str]]:
    """(before, the flagged text, after) within its sentence, trimmed to
    about ``reach`` characters each side."""
    if not text or not (0 <= start < end <= len(text)):
        return None
    left = max(text.rfind(c, 0, start) for c in ".!?\n") + 1
    rights = [i for i in (text.find(c, end) for c in ".!?\n") if i != -1]
    right = min(rights) + 1 if rights else len(text)
    before = text[max(left, start - reach):start].lstrip()
    after = text[end:min(right, end + reach)].rstrip()
    return before, text[start:end], after


def show_passage(main_window, chapter_id: str, passage: str, offset: int) -> None:
    """Open the chapter in Write and select the passage nearest ``offset``
    (used by the issue links). The editor's hover card then offers its
    fixes, as for any underlined word."""
    import re
    me = getattr(main_window, "manuscript_editor", None)
    if me is None:
        return
    main_window.tab_widget.setCurrentWidget(me)
    ce = me.current_chapter_editor
    if chapter_id and (ce is None or getattr(ce.chapter, "id", None) != chapter_id):
        me.open_chapter(chapter_id)
        ce = me.current_chapter_editor
    if ce is None:
        return
    text = ce.editor.toPlainText()
    hits = [m.start() for m in re.finditer(re.escape(passage), text)] if passage else []
    if not hits:
        main_window.statusBar().showMessage(
            "That passage has changed since the check; check readiness again.", 5000)
        return
    start = min(hits, key=lambda i: abs(i - offset))
    from src.ai.passage_critique import py_to_qt_index
    cursor = ce.editor.textCursor()
    cursor.setPosition(py_to_qt_index(text, start))
    cursor.setPosition(py_to_qt_index(text, start + len(passage)), cursor.MoveMode.KeepAnchor)
    ce.editor.setTextCursor(cursor)
    ce.editor.ensureCursorVisible()
    ce.editor.setFocus()
