"""The "Across the book" section on a character's page (piece P.8).

One closed section under Personality Arc on Story ▸ Characters. Opened,
it reads the book in the background (cached by chapter hash, so the next
character opens at once) and shows, with no model:

* the chapters the character appears in, as a strip and as ranges, and
  each stretch they are away; the readiness check *Characters who drop
  out* in its own words when it flags them;
* the lines they speak and their share of the book's dialogue;
* whether their way of speaking holds, with each chapter where it changes
  sharply put as a question, quoting a line.

Chapter names and quoted lines are links: they open the chapter in Write
with the passage selected (the revision controller's ``show_passage``, as
the Critique's links do). The last line is the arc: "needs a model"
without one; with one, a link asks it once (in the background) and the
answer is shown in place. Nothing is stored in the project.
"""

from __future__ import annotations

from html import escape
from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from src.ui import ui_kit
from src.ui.ui_kit import COLORS, CollapsibleSection

OPEN_KEY = "characters/across_book_open"
ARC_LINK = "char:arc"


def _is_open() -> bool:
    try:
        return str(ui_kit._settings().value(OPEN_KEY, "false")).lower() == "true"
    except Exception:
        return False


def _remember(_key: str, collapsed: bool) -> None:
    try:
        ui_kit._settings().setValue(OPEN_KEY, "false" if collapsed else "true")
    except Exception:
        pass


def build(character_widget) -> CollapsibleSection:
    """The section for ``character_widget`` (a ``CharacterWidget``)."""
    section = CollapsibleSection("Across the book", OPEN_KEY)
    # The page is a long form in a scroll area that gives each part its
    # minimum height; keep the header readable there.
    section.header.setStyleSheet(section.header.styleSheet().replace(
        "min-height: 0;", "min-height: 16px;"))
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.TextFormat.RichText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
    label.setOpenExternalLinks(False)
    label.setStyleSheet(f"color: {COLORS['ink']}; font-size: 12px;")
    label.setToolTip("Counted from the text, no model: clues, not proof.")
    section.body_layout.addWidget(label)
    section.label = label
    section.owner = character_widget
    section.analysis = None
    section.arc = ""                 # the model's answer, once asked
    section.task = None
    label.linkActivated.connect(lambda url: _safe(on_link, section, url))
    section.toggled.connect(_remember)
    section.toggled.connect(lambda _k, collapsed: collapsed or _safe(refresh, section))
    section.set_open(False)
    if _is_open():
        section.set_open(True)
        refresh(section)
    return section


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception as e:                     # an exception escaping a Qt slot aborts PyQt6
        print(f"[characters] across the book: {e}")


def refresh(section, sync: bool = False) -> None:
    """Read the book (in the background unless ``sync``) and draw."""
    owner = section.owner
    project = getattr(owner, "_project", None)
    character = getattr(owner, "character", None)
    if project is None or character is None:
        section.label.setText(_quiet("Open a project to see where this character appears."))
        return
    from src.ai import character_analysis as ca
    # Chapter texts are read here, on the GUI thread (loading any from disk);
    # the background work only reads these strings.
    texts = {ch.id: t for _s, _n, chs in ca._texts(project) for ch, t in chs}
    name = character.name

    def work():
        return ca.for_character(project, name, texts)

    def done(result, error):
        if error:
            section.label.setText(_quiet(f"Couldn't read the book: {escape(error)}"))
            return
        section.analysis = result
        draw(section)

    if sync:
        done(work(), "")
        return
    section.label.setText(_quiet("Reading the book…"))
    from src.ui.background import run_background
    section.task = run_background(work, done, owner=section.label, label="characters")


def _quiet(text: str) -> str:
    return f"<span style='color:{COLORS['ink_faint']}; font-style:italic;'>{text}</span>"


def _link(chapter_id: str, passage: str, label: str) -> str:
    from src.ai.text_links import make_link
    url = make_link(chapter_id, passage or "", "x").split("](", 1)[1][:-1]
    return f"<a href='{escape(url, quote=True)}'>{escape(label)}</a>"


def _strip(book) -> str:
    """One mark per chapter: filled where they appear, warm where they are away."""
    present = {ap.index for ap in book.appearances}
    away = {i for g in book.gaps for i in range(g.after.index + 1, g.back.index)}
    cells = []
    for i in range(book.total):
        colour = (COLORS["primary"] if i in present else
                  COLORS["warning"] if i in away else COLORS["border_strong"])
        cells.append(f"<span style='color:{colour};'>{'█' if i in present else '▁'}</span>")
    return (f"<span style='font-family:Menlo, monospace; font-size:11px; letter-spacing:0;'>"
            + "".join(cells) + "</span>")


def _ranges(book) -> str:
    """Chapter numbers as linked ranges: 1–4, 15–30."""
    runs, run = [], []
    for ap in book.appearances:
        if run and ap.index != run[-1].index + 1:
            runs.append(run)
            run = []
        run.append(ap)
    if run:
        runs.append(run)
    out = []
    for r in runs:
        first = _link(r[0].chapter_id, r[0].first, str(r[0].index + 1))
        out.append(first if len(r) == 1 else
                   f"{first}–{_link(r[-1].chapter_id, r[-1].first, str(r[-1].index + 1))}")
    return ", ".join(out)


def html(analysis, arc_line: str) -> str:
    """The section's text for one character."""
    from src.ai.character_analysis import MIN_LINES
    a = analysis
    warn = f"color:{COLORS['warning_ink']};"
    parts = []
    if not a.books:
        parts.append(f"<p>{escape(a.name)} is not named in any chapter yet.</p>")
    for b in a.books:
        head = f"<b>{escape(b.book)}</b>: " if len(a.books) > 1 else ""
        parts.append(f"<p>{head}In {len(b.appearances)} of {b.total} chapters "
                     f"({_ranges(b)})<br>{_strip(b)}</p>")
        for g in b.gaps:
            parts.append(
                f"<p style='{warn}'>⚠ Away for {g.chapters} chapters: last seen in "
                f"{_link(g.after.chapter_id, g.after.first, g.after.title)}, back in "
                f"{_link(g.back.chapter_id, g.back.first, g.back.title)}. Is the "
                "absence intended?</p>")
        if b.dropped:
            last = next((ap for ap in b.appearances if ap.chapter_id == b.dropped_chapter),
                        None)
            where = (" " + _link(last.chapter_id, last.first, "Show")) if last else ""
            parts.append(f"<p style='{warn}'>⚠ {escape(b.dropped)}{where}</p>")
    if a.lines:
        parts.append(f"<p><b>Speech:</b> {a.lines} line{'s' if a.lines != 1 else ''}, "
                     f"{a.share:.0%} of the book's attributed dialogue "
                     f"({_ordinal(a.rank)} of {a.speakers} speakers).</p>")
    else:
        parts.append(f"<p><b>Speech:</b> no line of dialogue is attributed to "
                     f"{escape(a.name)}.</p>")
    parts.append(f"<p>{escape(a.consistency())}</p>")
    for s in a.shifts:
        quote = (f" “{_link(s.chapter_id, s.sample, _short(s.sample))}”" if s.sample else "")
        parts.append(f"<p style='{warn}'>⚠ In {_link(s.chapter_id, s.sample, s.title)}: "
                     + escape("; ".join(s.changes)) + f".{quote} Is the change intended?</p>")
    parts.append(f"<p><b>How they change:</b> {arc_line}</p>")
    parts.append(f"<p style='color:{COLORS['ink_faint']}; font-size:11px;'>Counted from the "
                 f"text, no model: a scan, not proof. Speech is compared in chapters where "
                 f"they have {MIN_LINES} lines or more.</p>")
    return "".join(parts)


def _ordinal(n: int) -> str:
    from src.ai.character_analysis import _ordinal as ordinal
    return ordinal(n)


def _short(text: str, n: int = 60) -> str:
    from src.ai.character_analysis import _short as short
    return short(text, n)


def model_available() -> bool:
    """Is AI on? (Cheap: reads settings, never builds or loads a model.)"""
    try:
        from src.ui.scorecard_model_run import ai_available
        return ai_available()
    except Exception:
        return False


def arc_line(section) -> str:
    from src.ai.character_analysis import NEEDS_MODEL
    name = escape(getattr(section.owner.character, "name", "") or "This character")
    if section.arc:
        return escape(section.arc).replace("\n", "<br>")
    if section.task is not None and getattr(section, "arc_running", False):
        return _quiet("Asking the model…")
    if not model_available():
        return escape(NEEDS_MODEL.format(name=name))
    return (f"<a href='{ARC_LINK}'>Ask the model how {name} changes across the book</a> "
            "(one request, in the background).")


def draw(section) -> None:
    if section.analysis is None:
        return
    section.label.setText(html(section.analysis, arc_line(section)))
    try:
        from src.ui.ui_kit import relayout
        relayout(section)
    except Exception:
        pass


def on_link(section, url: str) -> None:
    if url == ARC_LINK:
        ask_arc(section)
        return
    from src.ai.text_links import parse_link
    parsed = parse_link(url)
    if not parsed:
        return
    from src.ui.analysis_menu import main_window_of
    mw = main_window_of(section)
    if mw is None:
        return
    from src.ui.revision_controller import RevisionController
    RevisionController(mw).show_passage(parsed[0], parsed[1], 0)


def ask_arc(section, llm: Any = None, sync: bool = False) -> None:
    """Ask the model how the character changes (``llm`` for tests; else the
    Critique's model, then the default, built only now)."""
    from src.ai import character_analysis as ca
    owner = section.owner
    project, character = owner._project, owner.character
    texts = {ch.id: t for _s, _n, chs in ca._texts(project) for ch, t in chs}
    try:                     # built here, on the GUI thread, as the other screens do
        model = llm if llm is not None else ca.arc_llm()
    except Exception as e:
        print(f"[characters] no model for the arc: {e}")
        model = None

    def work():
        return ca.describe_arc(project, character, model, texts)

    def done(result, error):
        section.arc_running = False
        section.arc = (f"The model could not answer: {error}" if error
                       else (result or "The model gave no answer."))
        draw(section)

    if sync:
        try:
            done(work(), "")
        except Exception as e:
            done(None, str(e))
        return
    section.arc_running = True
    draw(section)
    from src.ui.background import run_background
    section.task = run_background(work, done, owner=section.label, label="characters")
