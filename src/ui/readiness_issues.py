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
MAX_PLACES = 12             # links to each place of a repeated finding
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
    # chapter id, check label, items: work through them in the Companion (2.2)
    companion_requested = pyqtSignal(str, str, object)
    # "edit" | "remove" | "restore", the fact: the writer changes the style sheet
    sheet_change_requested = pyqtSignal(str, object)
    # "write" | "show": the editorial letter (8.2)
    letter_requested = pyqtSignal(str)
    # chapter id: show that chapter's row (a link in the letter)
    chapter_requested = pyqtSignal(str)
    # the item, the check's name, True (intended) or False (take it back)
    intended_requested = pyqtSignal(object, str, bool)
    # save the editor's brief (the document to send with the manuscript)
    brief_requested = pyqtSignal()
    # "menu" (change the chapter's stage) or a stage to move it to (3.1).
    stage_requested = pyqtSignal(str)
    # a toned-down check's name: bring it back (4.3)
    restore_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.anchorClicked.connect(self._on_link)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._links: List[Tuple[str, Any]] = []
        self._chapter = None
        # The book's style sheet (story_ledger facts), shown from the
        # Whole manuscript row; the scorecard sets it.
        self.style_sheet: List[Dict[str, Any]] = []
        self.style_sheet_removed: List[Dict[str, Any]] = []
        # The last editorial letter (editorial_letter.stored), or None.
        self.letter: Optional[Dict[str, Any]] = None
        # Where the manuscript stands before an editor (editor_pass.plan), or None.
        self.editor_plan = None
        # {check: why it is toned down} (4.3, ``check_outcomes``); the scorecard sets it.
        self.toned: Dict[str, str] = {}

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
        self._shown = (chapter_report, checks, text, titles)
        live_text = text                           # the outline reads the text as it is (7.1)
        ch = chapter_report
        if text is not None and ch.text_hash and rd.text_hash(text) != ch.text_hash:
            text, stale = None, True
        else:
            stale = False
        title = f"{ch.number}. {ch.title}" if ch.number else ch.title
        parts = [f"<div style='font-size:14px; font-weight:bold; color:{PALETTE['ink']}'>"
                 f"{_e(title)}</div>",
                 f"<div style='color:{PALETTE['ink_faint']}'>{ch.words:,} words"
                 + ({rd.BOOK_ROW: " · checks that look across every chapter",
                     rd.OPENING_ROW: " · the first pages, read as an agent reads them"}.get(
                     ch.chapter_id, " · the opening chapter, held to a stricter bar"
                     if ch.is_opening else "")) + "</div>"]
        if ch.chapter_id not in (rd.BOOK_ROW, rd.OPENING_ROW):
            parts.append(self._stage_html(ch))
            from src.ui import outline_section
            parts.append(outline_section.html(self, ch, live_text))
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
        # The big picture first: major issues, then other factors, then polish.
        tier_of = lambda n: rd.REGISTRY[n].tier if n in rd.REGISTRY else "factor"
        names = sorted(names, key=lambda n: rd.TIERS.index(tier_of(n)))
        shown_tier = None
        for name in names:
            if checks is None and tier_of(name) != shown_tier:
                shown_tier = tier_of(name)
                parts.append(f"<div style='margin-top:14px; font-size:11px; font-weight:bold; "
                             f"letter-spacing:1px; color:{PALETTE['ink_faint']}'>"
                             f"{_e(rd.TIER_LABELS[shown_tier].upper())}</div>")
            parts.append(self._check_html(name, ch.results[name], text, ch))
        if ch.chapter_id == rd.BOOK_ROW and self.editor_plan is not None:
            plan = self.editor_plan
            colour = PALETTE["success"] if plan.ready else PALETTE["ink"]
            parts.append(f"<div style='margin-top:10px; font-weight:bold; color:{colour}'>"
                         f"Before an editor: {_e(plan.title)}</div>"
                         f"<div style='color:{PALETTE['ink_faint']}'>So an editor's time goes "
                         "to the book, not to the mechanical work. In order:</div><ol "
                         "style='margin-top:2px'>")
            for step in plan.steps:
                mark = "✓ " if step.done else ""
                go = (f" <a href='{self._link('chapter', step.chapter_id)}'>Start there</a>"
                      if step.chapter_id and not step.done else "")
                parts.append(f"<li><b>{mark}{_e(step.title)}.</b> {_e(step.line)}{go}</li>")
            parts.append(f"</ol><p style='color:{PALETTE['ink_soft']}'><b>Editor's brief:</b> "
                         "the state of the manuscript, open questions, your deliberate "
                         "choices, the style sheet and the outline, to send with it. "
                         f"<a href='{self._link('brief', None)}'>Save the editor's brief…</a></p>")
        if ch.chapter_id == rd.BOOK_ROW:
            if self.letter:
                state = (" (the book has changed since)" if self.letter.get("stale") else "")
                links = (f"<a href='{self._link('letter-show', None)}'>Show the letter</a> · "
                         f"<a href='{self._link('letter-write', None)}'>write it again</a>")
                made = f"written {_e(self.letter.get('made_at', ''))}{state}. "
            else:
                made = ("the three to five most important issues across the book, each "
                        "with where it shows. ")
                links = f"<a href='{self._link('letter-write', None)}'>Write the letter</a>"
            parts.append(f"<p style='color:{PALETTE['ink_soft']}'><b>Editorial letter:</b> "
                         f"{made}{links}</p>")
        if ch.chapter_id == rd.BOOK_ROW and self.style_sheet:
            chapters = len({f.get("chapter_id") for f in self.style_sheet})
            parts.append(
                f"<p style='color:{PALETTE['ink_soft']}'><b>Style sheet:</b> "
                f"{len(self.style_sheet)} facts recorded from {chapters} "
                f"chapter{'s' if chapters != 1 else ''}; each later chapter is read against "
                f"them. <a href='{self._link('sheet', None)}'>Show the style sheet</a></p>")
        if ch.chapter_id not in (rd.BOOK_ROW, rd.OPENING_ROW):
            parts.append(f"<p style='color:{PALETTE['ink_faint']}'>For this chapter's full "
                         "reports (pacing, voice, dialogue and the rest), <b>Run Critique</b> "
                         "below; it is set to this chapter.</p>")
        self.setHtml("".join(parts))
        self._fit()

    def show_style_sheet(self) -> None:
        """The facts the model recorded, by character, place or thing, with
        the words that establish each (click to go there)."""
        from src.ai.story_ledger import grouped
        self._links = []
        parts = [f"<div style='font-size:14px; font-weight:bold; color:{PALETTE['ink']}'>"
                 "Style sheet</div>",
                 f"<div style='color:{PALETTE['ink_faint']}'>What each chapter establishes, "
                 "as the model recorded it. Later chapters are read against these, so "
                 "reword or remove any that are wrong. · "
                 f"<a href='{self._link('all', None)}'>back to the checks</a></div>"]
        for subject, facts in grouped(self.style_sheet).items():
            parts.append(f"<div style='margin-top:10px; font-weight:bold; "
                         f"color:{PALETTE['ink']}'>{_e(subject)}</div>")
            for f in facts:
                parts.append(
                    f"<div style='margin-left:12px'>{_e(f.get('fact', ''))} "
                    f"<span style='color:{PALETTE['ink_faint']}'>· {_e(f.get('chapter', ''))} · "
                    f"</span><a href='{self._link('fact', f)}' style='color:"
                    f"{PALETTE['ink_soft']}'>“{_e(f.get('quote', ''))}”</a> · "
                    f"<a href='{self._link('sheet-edit', f)}'>reword</a> · "
                    f"<a href='{self._link('sheet-remove', f)}'>remove</a></div>")
        if self.style_sheet_removed:
            parts.append(f"<div style='margin-top:14px; font-weight:bold; "
                         f"color:{PALETTE['ink_faint']}'>Removed by you</div>")
            for f in self.style_sheet_removed:
                parts.append(
                    f"<div style='margin-left:12px; color:{PALETTE['ink_faint']}'>"
                    f"{_e(f.get('subject', ''))}: {_e(f.get('fact', ''))} · "
                    f"{_e(f.get('chapter', ''))} · "
                    f"<a href='{self._link('sheet-restore', f)}'>put back</a></div>")
        self.setHtml("".join(parts))
        self._fit()

    def show_letter(self, titles: Optional[Dict[str, str]] = None) -> None:
        """The editorial letter; a chapter's name opens its row."""
        from src.ai.editorial_letter import to_html
        if not self.letter:
            return
        self._links = []
        if titles:
            self._titles = titles
        back = (f"<div style='color:{PALETTE['ink_faint']}'>"
                f"<a href='{self._link('all', None)}'>back to the checks</a> · "
                f"<a href='{self._link('letter-write', None)}'>write it again</a></div>")
        self.setHtml(to_html(self.letter, getattr(self, "_titles", {}) or {},
                             lambda cid: self._link("chapter", cid), PALETTE) + back)
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
        unread = result.status == "needs_model" and not result.found
        if result.status == "info":
            summary = "information, not counted"
        elif unread:
            summary = "not read yet"
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
        if name in self.toned:                          # 4.3: why it is fainter, and the way back
            out.append(f"<div style='color:{PALETTE['ink_faint']}'>{_e(self.toned[name])} "
                       f"<a href='{self._link('restore', name)}'>Bring it back</a></div>")
        if result.status in ("needs_work", "problem") and spec is not None and spec.description:
            out.append(f"<div style='color:{PALETTE['ink_faint']}'>What it looks for: "
                       f"{_e(spec.description[:240])}</div>")
        if result.message:
            out.append(f"<div style='color:{PALETTE['ink_faint']}'>{_e(result.message)}</div>")
        cleared = [i for i in result.items if i.verdict == "cleared"]
        meant = [i for i in result.items if i.verdict != "cleared" and i.dismissed]
        items = [i for i in result.items if i.verdict != "cleared" and not i.dismissed]
        if result.status == "could_not_check":
            out.append(f"<div style='color:{PALETTE['error']}'>{_e(result.error)}</div>")
            return "".join(out)
        if result.status == "info" and not items:
            return "".join(out)
        fixable = [i for i in items if i.end > i.start]
        if fixable and result.status in ("needs_work", "problem", "needs_model"):
            out.append(f"<div><a href='{self._link('companion', name)}'>Work through these in "
                       "the Companion →</a></div>")
        if unread:
            out.append(f"<div style='color:{PALETTE['ink_faint']}'>Use “Check the book with "
                       "the model…” to read for this.</div>")
            return "".join(out)
        if not items:
            out.append(f"<div style='color:{PALETTE['success']}'>"
                       + ("Nothing left: the model cleared them all." if cleared
                          else "Nothing left: you said the rest is intended." if meant
                          else "Nothing found.") + "</div>")
            return "".join(out) + self._meant_html(name, meant) + self._cleared_html(cleared)
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
        return "".join(out) + self._meant_html(name, meant) + self._cleared_html(cleared)

    def _stage_html(self, ch) -> str:
        """The chapter's stage, a link to change it, and the suggestion
        to move on when every check of the stage passes (3.1)."""
        from src.ai import chapter_stages as cst
        stage = getattr(ch, "stage", "") or ""
        out = (f"<div style='color:{PALETTE['ink_soft']}'>Stage: <b>{_e(cst.label(stage))}</b>"
               f" · <a href='{self._link('stage', 'menu')}'>change</a>")
        nxt = cst.suggestion(ch)
        if nxt:
            out += (f"<br><span style='color:{PALETTE['success']}'>Every "
                    f"{_e(cst.label(stage))} check passes.</span> "
                    f"<a href='{self._link('stage', nxt)}'>Move it to {_e(cst.label(nxt))}</a>")
        return out + "</div>"

    def _meant_html(self, name: str, meant) -> str:
        """What the writer said is intended: listed, not counted, undoable."""
        if not meant:
            return ""
        rows = "".join(
            f"<div style='margin-left:12px'>“{_e(i.text[:120])}” · "
            f"<a href='{self._link('unintend', (i, name))}'>take that back</a></div>"
            for i in meant[:12])
        return (f"<div style='color:{PALETTE['ink_faint']}; margin-top:4px'>You said these are "
                f"intended or not a problem; they don't count (what's intended goes in the "
                f"editor's brief):{rows}</div>")

    def _cleared_html(self, cleared) -> str:
        """What the model judged fine: shown, not counted."""
        if not cleared:
            return ""
        rows = "".join(f"<li>“{_e(i.text[:90])}” — {_e(i.note or 'fine as written')}</li>"
                       for i in cleared[:20])
        more = f"<li>…and {len(cleared) - 20} more</li>" if len(cleared) > 20 else ""
        return (f"<div style='color:{PALETTE['ink_faint']}; margin-top:4px'>Cleared by the "
                f"model (not counted):<ul style='margin-top:2px'>{rows}{more}</ul></div>")

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
        kind = {"spelling": "Spelling", "grammar": "Grammar"}.get(first.kind, "")
        showable = self._showable(first, ch)
        shown = (f"<a href='{self._link('show', first)}'><b>{_e(first.text)}</b></a>"
                 if showable else f"<b>{_e(first.text)}</b>")
        bits.append(f"{shown}{times} "
                    + (f"<span style='color:{PALETTE['ink_faint']}'>{_e(kind)}</span>"
                       if kind else ""))
        reason = first.reason
        if reason and reason.lower() not in ("possible misspelling.", (kind or "-").lower()):
            bits.append(f" — <span style='color:{PALETTE['ink_soft']}'>{_e(reason)}</span>")
        sentence = _sentence(text, first.start, first.end)
        if sentence:
            before, word, after = sentence
            bits.append(f"<br><span style='color:{PALETTE['ink_soft']}'>…{_e(before)}"
                        f"<b style='background:{PALETTE['primary_tint']}'>{_e(word)}</b>"
                        f"{_e(after)}…</span>")
        if first.verdict == "problem" and first.note:
            bits.append(f"<br><span style='color:{PALETTE['ink_soft']}'>The model: {_e(first.note)}"
                        "</span>")
        if first.suggestions:
            bits.append(f"<br><span style='color:{PALETTE['ink_faint']}'>Try: "
                        + ", ".join(f"“{_e(s)}”" for s in first.suggestions[:4]) + "</span>")
        links = []
        if showable:
            links.append(f"<a href='{self._link('show', first)}'>Show in chapter</a>")
        places = self._places_html(group, ch)
        if places:
            links.append(places)
        from src.ai.editor_pass import is_query
        if is_query(first) and first.key:
            links.append(f"<a href='{self._link('intend', (first, name))}'>That's intended</a>")
        if links:
            bits.append("<br>" + " · ".join(links))
        return "".join(bits) + where

    @staticmethod
    def _showable(item, ch) -> bool:
        """Can "Show in chapter" find it: it has a place, or a chapter, or
        it is quoted from the chapter shown."""
        from src.ai import readiness as rd
        if item.end > item.start or item.chapter_id:
            return True
        return bool((item.text or "").strip()) and \
            getattr(ch, "chapter_id", None) not in (None, rd.BOOK_ROW, rd.OPENING_ROW)

    def _places_html(self, group, ch) -> str:
        """For a finding repeated in several places: a link to each."""
        spots = [i for i in group if i.end > i.start]
        if len(spots) < 2:
            return ""
        links = [f"<a href='{self._link('show', i)}'>{n}</a>"
                 for n, i in enumerate(spots[:MAX_PLACES], 1)]
        more = f" (+{len(spots) - MAX_PLACES})" if len(spots) > MAX_PLACES else ""
        return "Each place: " + " ".join(links) + more

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
        elif kind == "outline":                    # open or close the scene outline (7.1)
            self.outline_open = not getattr(self, "outline_open", False)
            if getattr(self, "_shown", None):
                self.show_chapter(*self._shown)
        elif kind == "plan":                       # change a scene's planned events (7.3)
            from src.ui import plan_section; plan_section.on_link(self, item)
        elif kind == "sheet":
            self.show_style_sheet()
        elif kind in ("intend", "unintend"):
            self.intended_requested.emit(item[0], item[1], kind == "intend")
        elif kind == "brief":
            self.brief_requested.emit()
        elif kind == "restore":
            self.restore_requested.emit(item)
        elif kind == "stage":
            self.stage_requested.emit(item)
        elif kind.startswith("letter-"):
            self.letter_requested.emit(kind[7:])
        elif kind == "chapter":
            self.chapter_requested.emit(item)
        elif kind.startswith("sheet-"):
            self.sheet_change_requested.emit(kind[6:], item)
        elif kind == "fact":
            self.show_requested.emit(item.get("chapter_id", ""), item.get("quote", ""), 0)
        elif ch is not None and kind == "companion":
            self.request_companion(ch, [item])
        elif ch is not None and kind == "show":
            self.show_requested.emit(item.chapter_id or ch.chapter_id, item.text, item.start)
        elif ch is not None and kind == "expand":
            cid = item.chapter_id or ch.chapter_id
            self.expand_requested.emit(cid, self._titles.get(cid, ch.title), item.text, item.start)

    def request_companion(self, chapter_report, check_names) -> bool:
        """Ask for these checks' findings in the Companion. For the whole-book
        and opening rows, the chapter is that of the first finding."""
        from src.ai import readiness as rd
        items, labels = [], []
        for name in check_names:
            r = chapter_report.results.get(name)
            if r is None:
                continue
            spec = rd.REGISTRY.get(name)
            labels.append(spec.label if spec else name)
            items += [i for i in r.items if i.verdict != "cleared" and i.end > i.start]
        if not items:
            return False
        cid = chapter_report.chapter_id
        if cid in (rd.BOOK_ROW, rd.OPENING_ROW):
            cid = next((i.chapter_id for i in items if i.chapter_id), "")
            items = [i for i in items if i.chapter_id == cid]
        if not cid:
            return False
        self.companion_requested.emit(cid, " / ".join(labels), items)
        return True

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

    def loadResource(self, kind, name):
        """The scene outline's chart (7.3); everything else as before."""
        if name.scheme() == "wa-chart":
            from src.ui import plan_section
            image = plan_section.load_chart(self, name.toString())
            if image is not None:
                return image
        return super().loadResource(kind, name)

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
    """Open the chapter in Write and select the passage nearest ``offset``.
    Kept for callers; the work is the revision controller's (R.5)."""
    from src.ui.revision_controller import RevisionController
    RevisionController(main_window).show_passage(chapter_id, passage, offset)
