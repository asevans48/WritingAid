"""The Improve window's Suggestions and Critique helpers (D.2b): the worker
that asks for a critique of the highlighted passage with three rewrites,
and the functions the window shares for the critique, Talk it through,
ratings and avoided phrases.

The old Suggestions window (``PassageCritiqueDialog``) that lived here was
deleted in D.12: nothing opened it after D.11; the Improve window's
💡 Suggestions and 📝 Critique tabs do everything it did."""

from __future__ import annotations

import html
from typing import Any, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from src.ai.passage_critique import PassageCritique, build_context, critique_passage

EXPANDED_ANGLE = "your text, expanded"

# A QThread destroyed while running aborts the app, so running workers are
# kept here until they finish even if their dialog is closed.
# Running workers are kept alive by the shared helper (R.2); the name stays
# for existing imports.
from src.ui import background  # noqa: E402

_RUNNING = background._RUNNING


def _project_path(project: Any) -> str:
    return str(getattr(project, "project_path", "") or "") if project is not None else ""


def _build_llm():
    from src.ai.task_llm import build_critique_llm, build_default_llm, no_model_message
    llm = build_critique_llm() or build_default_llm()
    return llm, ("" if llm is not None else no_model_message())


def _project_search(project: Any):
    """``query → text`` over the project's notes, or None."""
    try:
        from src.ai.enhanced_rag import EnhancedRAGSystem
        from src.ai.semantic_search import SearchMethod
        rag = EnhancedRAGSystem(project=project)
        rag.rebuild_index()
        return lambda query: rag.get_context_for_ai(
            query=query, max_tokens=500, method=SearchMethod.HYBRID)
    except Exception as e:
        print(f"[suggestions] project search unavailable: {e}")
        return None


class SuggestionWorker(QThread):
    progress = pyqtSignal(str)
    done = pyqtSignal(object, str)          # PassageCritique | None, error
    # Overly descriptive statements (overdescription.Review), sent after
    # ``done``; the word scan alone when there's no model.
    overdescribed = pyqtSignal(object)

    def __init__(self, project, chapter, text: str, start: int, end: int, focus: str,
                 llm_factory=_build_llm, search_factory=_project_search, review: bool = True):
        super().__init__()
        self.args = (project, chapter, text, start, end)
        self.focus = focus
        self.llm_factory, self.search_factory = llm_factory, search_factory
        self.llm = self.ctx = self.voice = None
        # False when the overly-descriptive review already ran (the Improve
        # window's Expand tab, D.2b): no second model call for it.
        self.review = review

    def run(self):
        try:
            self._critique()
        finally:
            if self.review:
                self._overdescription()

    def _overdescription(self):
        from src.ai import overdescription as od
        project, chapter, text, start, end = self.args
        try:
            if self.ctx is None or self.llm is None:
                review = od.Review(od.scan(text[start:end]), error="no model")
            else:
                review = od.review_passage(self.llm, self.ctx, self.voice,
                                           progress=self.progress.emit)
        except Exception as e:
            print(f"[suggestions] overly-descriptive review failed: {e}")
            review = od.Review(od.scan(text[start:end]), error=str(e))
        self.overdescribed.emit(review)

    def _critique(self):
        try:
            project, chapter, text, start, end = self.args
            self.progress.emit("Loading the model…")
            llm, error = self.llm_factory()
            if llm is None:
                self.done.emit(None, error)
                return
            from src.ai.chapter_analysis_agent import is_local_llm
            self.progress.emit("Gathering characters, world and plot…")
            search = self.search_factory(project) if project is not None else None
            from src.ai.rewrite_quality import examples_prompt
            from src.ai.writer_voice import project_voice
            voice = project_voice(project, chapter, text, selection=text[start:end])
            self.examples_from = {}
            examples = examples_prompt(text[start:end], _project_path(project), before=text[:start],
                                       after=text[end:], note=self.examples_from)
            ctx = build_context(project, chapter, text, start, end,
                                compact=is_local_llm(llm), related=search,
                                voice=voice, examples=examples)
            # Kept for the conversation that follows (and the
            # overly-descriptive review, even if the critique fails).
            self.llm, self.ctx, self.voice = llm, ctx, voice
            result = critique_passage(llm, ctx, self.focus, self.progress.emit, voice=voice)
            if result.empty:
                self.done.emit(None, "The model's reply couldn't be read as a critique. "
                                     "Try again, or pick another model in Settings.")
                return
            self.done.emit(result, "")
        except Exception as e:
            self.done.emit(None, f"Couldn't get suggestions: {e}")


def _short(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ── Shared with the Improve window (D.2b) ─────────────────────────────
# Moved out of the old Suggestions window unchanged (D.2b); the window
# itself went in D.12.

def widened_note(text: str, start: int, end: int, selection) -> str:
    """"Your highlight was widened to whole sentences: added …", or ""."""
    if not selection:
        return ""
    s, e = selection
    added_before = text[start:s].strip()
    added_after = text[e:end].strip()
    if not (added_before or added_after):
        return ""
    bits = []
    if added_before:
        bits.append(f"the start of the sentence (“{_short(added_before)}”)")
    if added_after:
        bits.append(f"the end of the sentence (“{_short(added_after)}”)")
    return "Your highlight was widened to whole sentences: added " + " and ".join(bits) + "."


def discussion_html(result: PassageCritique) -> str:
    def section(title, items, color, mark):
        if not items:
            return ""
        rows = "".join(f"<li>{html.escape(i)}</li>" for i in items)
        return f"<h3 style='color:{color}'>{mark} {title}</h3><ul>{rows}</ul>"
    body = (section("What works", result.works, "#2e7d32", "✓")
            + section("What doesn't work", result.issues, "#c62828", "✗")
            + section("Dialogue", getattr(result, "dialogue", []), "#7c3aed", "💬")
            + section("Order and flow", result.order, "#1d4ed8", "⇅"))
    return body or "<p><i>No discussion — see the suggestions below.</i></p>"


def chat_context(ctx, result):
    """(context blocks, rules) for Talk it through about a critique."""
    from src.ai import passage_critique as pc
    r = result
    critique = []
    for title, items in (("What works", r.works), ("What doesn't work", r.issues),
                         ("Dialogue", getattr(r, "dialogue", [])), ("Order and flow", r.order)):
        if items:
            critique.append(f"{title}:\n" + "\n".join(f"- {i}" for i in items))
    blocks = [(t, b) for t, b in ctx.sections() if b]
    blocks.append(("THE SCENE (the passage is marked)", ctx.scene(1500)))
    from src.ai.event_order import events_prompt
    timeline = events_prompt(ctx.passage)
    if timeline:
        head, _, body = timeline.partition(":\n")
        blocks.append((head, body))
    if ctx.speakers:
        blocks.append(("WHO SPEAKS EACH LINE", ctx.speakers))
    if critique:
        blocks.append(("YOUR CRITIQUE OF THE PASSAGE", "\n\n".join(critique)))
    rules = pc._SCOPE_RULES + "\n" + pc._REWRITE_RULES + "- " + pc._avoid_line()
    return blocks, rules


def chat_turn_fn(llm, ctx, voice, result, versions, turns, message):
    """The callable that runs one Talk it through turn (in a worker)."""
    from src.ai import passage_critique as pc
    from src.ai.rewrite_chat import chat_turn
    blocks, rules = chat_context(ctx, result)

    def check(found):
        return pc._check_all(ctx, found, voice, message)

    def turn():
        return chat_turn(llm, system=pc.SYSTEM_PROMPT, context=blocks, passage=ctx.passage,
                         versions=versions, turns=turns, message=message, check=check,
                         rules=rules)
    return turn


def log_rating(project, text: str, start: int, end: int, output: str, rating: str,
               accepted: bool, style: str = "suggestion") -> bool:
    """A rated rewrite of ``text[start:end]``, saved as Suggestions saves it
    (when data collection is on)."""
    from src.ai.rewrite_quality import log_rated_rewrite
    genre = getattr(getattr(project, "prose_profile", None), "genre", "") or ""
    return log_rated_rewrite(text[start:end], output, rating, accepted=accepted,
                             project_path=_project_path(project), style=style,
                             before=text[max(0, start - 500):start],
                             after=text[end:end + 500], genre=genre)


def avoid_phrase(parent, edit, phrase: Optional[str] = None) -> Optional[str]:
    """🚫 Avoid a phrase: the phrase selected in ``edit``, or asked for.
    The message to show, or None when the writer cancelled."""
    from src.ai.rewrite_quality import add_avoid_phrase
    if phrase is None:
        phrase = edit.textCursor().selectedText().strip()
    if not phrase:
        from PyQt6.QtWidgets import QInputDialog
        phrase, ok = QInputDialog.getText(
            parent, "Avoid a phrase", "Phrase Suggestions and Rephrase should never use:")
        if not ok:
            return None
    try:
        added = add_avoid_phrase(phrase)
    except Exception as e:
        return f"Couldn't save: {e}"
    return (f"Won't suggest “{phrase.strip()}” again." if added
            else "Already avoided (or too short).")
