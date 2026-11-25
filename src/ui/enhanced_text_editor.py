"""Enhanced text editor with context menu, Word support, headers, spell checking, and TTS."""

from PyQt6.QtWidgets import (
    QTextEdit, QMenu, QDialog, QVBoxLayout, QLabel,
    QListWidget, QPushButton, QTextBrowser, QHBoxLayout,
    QMessageBox, QComboBox, QToolTip, QWidgetAction, QSlider,
    QGroupBox, QWidget
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer, QPoint, QEvent, QThread
from PyQt6.QtGui import (
    QAction, QTextCursor, QTextCharFormat, QColor, QFont,
    QTextBlockFormat, QSyntaxHighlighter, QTextDocument,
    QTextBlockUserData, QMouseEvent
)
from typing import Any, Optional, Callable, Iterable, List, Set, Dict, Tuple
from dataclasses import dataclass
from enum import Enum
from collections import Counter
import bisect
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from pathlib import Path
import re

# Markdown utilities
from src.utils.markdown_editor import (
    MarkdownStyle, STYLE_NAMES, STYLE_TO_NAME, get_line_style,
    apply_heading_to_line, strip_markdown
)

# TTS imports (lazy loaded)
try:
    from src.services.tts_service import get_tts_service, TTSEngine
    from src.services.tts_document_generator import (
        TTSDocumentGenerator, TTSDocumentConfig, TTSFormat,
        SpeakerConfig, get_tts_output_dir
    )
    TTS_AVAILABLE = True
except ImportError:
    TTS_AVAILABLE = False


class HeadingLevel(Enum):
    """Heading levels for document structure."""
    NORMAL = 0       # Regular paragraph
    TITLE = 1        # Document title (Heading 0 in Word)
    HEADING_1 = 2    # Chapter/Major section
    HEADING_2 = 3    # Section
    HEADING_3 = 4    # Subsection
    HEADING_4 = 5    # Minor subsection


class BlockData(QTextBlockUserData):
    """Custom block data to store heading level and other metadata."""

    def __init__(self, heading_level: HeadingLevel = HeadingLevel.NORMAL):
        super().__init__()
        self.heading_level = heading_level


# CheckMode, ErrorType, WritingError, issue_weight and the rules for which
# flags to show live in src/utils/editor_flags.py (piece R.6), with no Qt.
from src.utils.editor_flags import (  # noqa: E402,F401
    CheckMode, ErrorType, FlagRules, WritingError, _STYLE_WEIGHTS, issue_weight,
)


# The checkers live in src/utils/ (piece R.3), with no Qt, so a chapter can be
# checked without a window. Imported here so every existing
# ``from src.ui.enhanced_text_editor import ...`` keeps working.
from src.utils.spell_checker import SpellChecker, _apos  # noqa: E402,F401
from src.utils.overuse import OveruseDetector, _sentence_at, _sentences_with  # noqa: E402,F401
from src.utils.writing_stats import ProWritingAnalyzer, WritingStats  # noqa: E402,F401
from src.utils.grammar_checker import GrammarChecker  # noqa: E402,F401


# Running grammar workers, held here (not parented to an editor) so a
# chapter editor closed mid-check can't destroy a running thread.
_RUNNING_GRAMMAR_WORKERS: Set["_GrammarWorker"] = set()
_QUIT_HOOKED = False


def _wait_for_grammar_workers():
    for w in list(_RUNNING_GRAMMAR_WORKERS):
        w.wait(10000)


class _GrammarWorker(QThread):
    """Runs LanguageTool over a batch of paragraphs off the UI thread.

    Paragraphs are joined into a few large requests (one HTTP round trip
    each to the local LanguageTool server) and the matches mapped back to
    paragraph-relative offsets. Emits ``{paragraph_text: [GrammarIssue]}``.
    """
    results_ready = pyqtSignal(dict)
    status = pyqtSignal(str)

    CHUNK_CHARS = 20000

    def __init__(self, paragraphs: List[str], parent=None):
        super().__init__(parent)
        self.paragraphs = paragraphs

    def run(self):
        from src.utils.proofing import LanguageToolEngine
        engine = LanguageToolEngine.get()
        if engine.status != "ready":
            self.status.emit("Grammar: starting LanguageTool…")
        if not engine.ensure_started():
            self.status.emit(f"Grammar: {engine.describe()}")
            self.results_ready.emit({})
            return
        self.status.emit("Grammar: checking…")
        from src.utils.editor_flags import languagetool_issues
        results = languagetool_issues(self.paragraphs, engine, self.CHUNK_CHARS)
        self.status.emit("Grammar: LanguageTool")
        self.results_ready.emit(results)


class _ContextSuggestWorker(QThread):
    """One quick model call for in-context replacements of a word."""
    done = pyqtSignal(object, str)          # word_suggest.WordSuggestions | None, error

    def __init__(self, word: str, sentence, count: int):
        super().__init__()
        self.word, self.sentence, self.count = word, sentence, count

    def run(self):
        try:
            from src.ai import word_suggest as ws
            llm = ws.get_llm()
            if llm is None:
                from src.ai.task_llm import no_model_message
                self.done.emit(None, no_model_message())
                return
            self.done.emit(ws.suggest(llm, self.word, self.sentence, self.count), "")
        except Exception as e:
            self.done.emit(None, f"Couldn't get suggestions: {e}")


_RUNNING_SUGGESTERS: Set["_ContextSuggestWorker"] = set()


class _RepetitionWorker(QThread):
    """Asks the model which light repeats weaken the writing."""
    done = pyqtSignal(object, bool)          # verdicts, no model available

    def __init__(self, items, context: str = ""):
        super().__init__()
        self.items, self.context = items, context

    def run(self):
        try:
            from src.ai import repetition_judge as rj
            from src.ai import word_suggest as ws
            llm = ws.get_llm()
            if llm is None:
                self.done.emit({}, True)
                return
            self.done.emit(rj.judge(llm, self.items, self.context), False)
        except Exception as e:
            print(f"[repetition] review failed: {e}")
            self.done.emit({}, False)


_RUNNING_REVIEWERS: Set["_RepetitionWorker"] = set()


class _FlagReviewWorker(QThread):
    """Asks the model which style / grammar / spelling flags are real."""
    done = pyqtSignal(object, bool)          # verdicts, no model available

    def __init__(self, items, spelling_context: str = "", style_context: str = ""):
        super().__init__()
        self.items, self.spelling_context = items, spelling_context
        self.style_context = style_context

    def run(self):
        try:
            from src.ai import flag_judge as fj
            from src.ai import word_suggest as ws
            llm = ws.get_llm()
            if llm is None:
                self.done.emit({}, True)
                return
            verdicts = {}
            for category, items in self.items.items():
                context = self.spelling_context if category == "spelling" else self.style_context
                verdicts.update(fj.judge(llm, category, items, context))
            self.done.emit(verdicts, False)
        except Exception as e:
            print(f"[flags] review failed: {e}")
            self.done.emit({}, False)


class WritingHighlighter(QSyntaxHighlighter, FlagRules):
    """Syntax highlighter for spelling, grammar, and overuse checking.

    Modes per check: OFF, ON_DEMAND (green) and REALTIME (blue). Whenever
    a check is on, its underlines are drawn for every paragraph and
    survive edits and re-highlights:

      * Spelling is a fast dictionary lookup, applied live.
      * Grammar = built-in rules (live) + LanguageTool results cached per
        paragraph text. ON_DEMAND runs LanguageTool on load, when the
        check is switched on, and on Recheck; REALTIME also re-checks
        edited paragraphs after a typing pause.
      * Overuse uses the document statistics from the last refresh.
    """

    grammar_status = pyqtSignal(str)

    def __init__(
        self,
        document: QTextDocument,
        spell_checker: SpellChecker,
        grammar_checker: Optional[GrammarChecker] = None,
        overuse_detector: Optional[OveruseDetector] = None
    ):
        super().__init__(document)
        self.spell_checker = spell_checker
        self.grammar_checker = grammar_checker or GrammarChecker()
        self.overuse_detector = overuse_detector or OveruseDetector()

        # Check modes: ON_DEMAND (green), REALTIME (blue), OFF (white)
        # Start in ON_DEMAND mode - initial check only, then on recheck button
        self._spell_mode = CheckMode.ON_DEMAND
        self._grammar_mode = CheckMode.ON_DEMAND
        self._overuse_mode = CheckMode.ON_DEMAND

        # Flag to indicate we're doing an on-demand check (recheck button or initial)
        self._doing_on_demand_check = False

        # Full grammar check mode (for explicit recheck only)
        self._full_grammar_check = False

        # Store errors by block: block -> [WritingError]
        self._errors: Dict[int, List[WritingError]] = {}

        # Full document text for overuse analysis
        self._full_text = ""

        # Ignored errors by word only (more robust to text changes)
        # Format: word -> error_type (so we can ignore specific types)
        self._ignored_words: Dict[str, Set[ErrorType]] = {}

        # Track block content hashes to detect changes
        self._block_hashes: Dict[int, int] = {}

        # Style checks (passive, adverbs, wordiness, long / hard / sticky
        # sentences…). Off until switched on (toolbar "Sty" / Style panel).
        from src.utils.style_checks import DEFAULT_KINDS
        self._style_mode = CheckMode.OFF
        self._style_kinds: Set[str] = set(DEFAULT_KINDS)
        self._style_ignored: Set[Tuple[str, str]] = set()   # (kind, text lower)
        self._style_cache: Dict[Tuple[str, frozenset], list] = {}
        self._style_formats = self._build_style_formats()

        # LanguageTool results keyed by paragraph text (so they survive
        # edits elsewhere, block renumbering and re-highlights).
        self._lt_cache: Dict[str, list] = {}
        self._grammar_worker: Optional[_GrammarWorker] = None
        self._grammar_rerun = False
        # (block_number, position) of the word being typed — not flagged
        # until the writer moves past it.
        self._typing: Optional[Tuple[int, int]] = None
        # Overused-phrase positions come from a full-text snapshot; they
        # are only trusted while that snapshot matches the document.
        self._full_text_fresh = False

        # Connect to document changes to clear stale data
        document.contentsChange.connect(self._on_contents_change)

        # Check marks: a solid background highlight on the word (easy to
        # see) plus a thin underline in the same hue (still visible inside
        # a tinted style sentence). Highlights are recomputed per paragraph
        # as it changes, so they follow the words and vanish once fixed.
        self.spelling_format = self._mark_format("#fca5a5", QColor(255, 0, 0))      # red
        self.grammar_format = self._mark_format("#86efac", QColor(0, 180, 0))       # green
        self.overuse_format = self._mark_format("#bfdbfe", QColor(0, 120, 255))     # blue
        self.phrase_format = self._mark_format("#ddd6fe", QColor(148, 0, 211))      # purple
        # Master switch: hide every check mark without turning checks off.
        self._highlights_visible = True
        self.project = None             # for the writer's style sheet
        # Drafting shows spelling and grammar only (style and overuse wait);
        # revising shows every check. Focus keeps each paragraph's top issues.
        self.phase = "revising"
        self.focus = False
        self.focus_per_paragraph = 2
        self.learn_callback = None      # (signal, subject) — what the writer does
        self._suspended = False

        # Markdown heading formats
        self.md_title_format = QTextCharFormat()
        self.md_title_format.setFontPointSize(28)
        self.md_title_format.setFontWeight(QFont.Weight.Bold)

        self.md_h1_format = QTextCharFormat()
        self.md_h1_format.setFontPointSize(24)
        self.md_h1_format.setFontWeight(QFont.Weight.Bold)

        self.md_h2_format = QTextCharFormat()
        self.md_h2_format.setFontPointSize(18)
        self.md_h2_format.setFontWeight(QFont.Weight.Bold)

        self.md_h3_format = QTextCharFormat()
        self.md_h3_format.setFontPointSize(14)
        self.md_h3_format.setFontWeight(QFont.Weight.Bold)

        self.md_h4_format = QTextCharFormat()
        self.md_h4_format.setFontPointSize(12)
        self.md_h4_format.setFontWeight(QFont.Weight.Bold)

        # Markdown heading prefix format (hidden - very small and transparent)
        self.md_prefix_format = QTextCharFormat()
        self.md_prefix_format.setFontPointSize(1)  # Tiny font
        self.md_prefix_format.setForeground(QColor(255, 255, 255, 0))  # Fully transparent

        # Markdown bold format
        self.md_bold_format = QTextCharFormat()
        self.md_bold_format.setFontWeight(QFont.Weight.Bold)

        # Markdown italic format
        self.md_italic_format = QTextCharFormat()
        self.md_italic_format.setFontItalic(True)

        # Markdown bold+italic format
        self.md_bold_italic_format = QTextCharFormat()
        self.md_bold_italic_format.setFontWeight(QFont.Weight.Bold)
        self.md_bold_italic_format.setFontItalic(True)

        # Markdown marker format (hidden - very small and transparent)
        self.md_marker_format = QTextCharFormat()
        self.md_marker_format.setFontPointSize(1)  # Tiny font
        self.md_marker_format.setForeground(QColor(255, 255, 255, 0))  # Fully transparent

    def _on_contents_change(self, position: int, chars_removed: int, chars_added: int):
        """Handle document content changes to clear stale error data."""
        if chars_removed > 0 or chars_added > 0:
            # Find affected blocks
            doc = self.document()
            if not doc:
                return

            # Get block at position
            block = doc.findBlock(position)
            if not block.isValid():
                return

            # Clear errors for affected blocks and following blocks if content shifted
            start_block = block.blockNumber()

            # If chars were added or removed, block numbers after this point may have shifted
            # Clear all error data from this block onward to be safe
            blocks_to_clear = [bn for bn in self._errors.keys() if bn >= start_block]
            for bn in blocks_to_clear:
                if bn in self._errors:
                    del self._errors[bn]
                if bn in self._block_hashes:
                    del self._block_hashes[bn]
            self._full_text_fresh = False

    def set_spell_mode(self, mode: CheckMode):
        """Set spell checking mode (takes effect immediately)."""
        changed = mode != self._spell_mode
        self._spell_mode = mode
        if changed:
            self.rehighlight()

    def set_grammar_mode(self, mode: CheckMode):
        """Set grammar checking mode; switching it on runs a check."""
        was_off = self._grammar_mode == CheckMode.OFF
        changed = mode != self._grammar_mode
        self._grammar_mode = mode
        if changed:
            self.rehighlight()
        if mode != CheckMode.OFF and was_off:
            self.request_grammar_check()

    @staticmethod
    def _mark_format(background: str, underline: QColor) -> QTextCharFormat:
        fmt = QTextCharFormat()
        fmt.setBackground(QColor(background))
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SingleUnderline)
        fmt.setUnderlineColor(underline)
        return fmt

    def set_highlights_visible(self, visible: bool) -> None:
        """Show / hide all check highlights (checks keep their settings)."""
        if visible != self._highlights_visible:
            self._highlights_visible = visible
            self.rehighlight()

    def highlights_visible(self) -> bool:
        return self._highlights_visible

    def _lt_issues_for_block(self, text: str) -> list:
        """LanguageTool issues for this paragraph.

        Cached by paragraph text. When the paragraph was edited since the
        last LanguageTool pass, the previous issues are carried over
        through the edit: ones on untouched text shift with it, ones on
        changed text are dropped (the word was fixed or rewritten).
        """
        issues = self._lt_cache.get(text)
        data = self.currentBlockUserData()
        if issues is None:
            snap = getattr(data, "lt_snapshot", None)
            issues = self._remap_issues(snap[0], snap[1], text) if snap else []
        if data is None:
            data = BlockData()
            self.setCurrentBlockUserData(data)
        data.lt_snapshot = (text, issues)
        return issues

    # Above this many changed characters, skip the fine-grained diff: its
    # cost is quadratic, and the background grammar pass re-flags the span.
    _MAX_DIFF_CHARS = 2000

    @staticmethod
    def _diff_opcodes(old: str, new: str) -> list:
        """difflib-style opcodes, diffing only the region that changed."""
        import difflib
        limit = min(len(old), len(new))
        prefix = 0
        while prefix < limit and old[prefix] == new[prefix]:
            prefix += 1
        suffix = 0
        while suffix < limit - prefix and old[-1 - suffix] == new[-1 - suffix]:
            suffix += 1
        old_mid = old[prefix:len(old) - suffix]
        new_mid = new[prefix:len(new) - suffix]
        ops = [("equal", 0, prefix, 0, prefix)] if prefix else []
        if (old_mid and new_mid and len(old_mid) <= WritingHighlighter._MAX_DIFF_CHARS
                and len(new_mid) <= WritingHighlighter._MAX_DIFF_CHARS):
            matcher = difflib.SequenceMatcher(None, old_mid, new_mid, autojunk=False)
            ops += [(tag, i1 + prefix, i2 + prefix, j1 + prefix, j2 + prefix)
                    for tag, i1, i2, j1, j2 in matcher.get_opcodes()]
        if suffix:
            ops.append(("equal", len(old) - suffix, len(old), len(new) - suffix, len(new)))
        return ops

    @staticmethod
    def _remap_issues(old: str, issues: list, new: str) -> list:
        if not issues or old == new:
            return list(issues or [])
        import copy
        ops = WritingHighlighter._diff_opcodes(old, new)
        def boundary(text: str, i: int) -> bool:
            return not (0 <= i < len(text) and (text[i].isalnum() or text[i] in "'’"))

        out = []
        for issue in issues:
            for tag, i1, i2, j1, _j2 in ops:
                if tag == "equal" and i1 <= issue.start and issue.end <= i2:
                    shift = j1 - i1
                    ns, ne = issue.start + shift, issue.end + shift
                    # The flagged word itself must be unchanged — "walk" →
                    # "walked" leaves "walk" intact but it's a different word.
                    if (boundary(old, issue.start - 1) != boundary(new, ns - 1)
                            or boundary(old, issue.end) != boundary(new, ne)):
                        break
                    moved = copy.copy(issue)
                    moved.start, moved.end = ns, ne
                    out.append(moved)
                    break
        return out

    # ── Style checks ─────────────────────────────────────────────

    @staticmethod
    def _build_style_formats() -> Dict[str, QTextCharFormat]:
        from src.utils.style_checks import KINDS
        formats = {}
        for kind, (_label, color, sentence_level) in KINDS.items():
            fmt = QTextCharFormat()
            if sentence_level:
                fmt.setBackground(QColor(color))
            else:
                fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.DashUnderline)
                fmt.setUnderlineColor(QColor(color))
            formats[kind] = fmt
        return formats

    def set_style_mode(self, mode: CheckMode):
        changed = mode != self._style_mode
        self._style_mode = mode
        if changed:
            self.rehighlight()

    def get_style_mode(self) -> CheckMode:
        return self._style_mode

    def set_style_kinds(self, kinds) -> None:
        kinds = set(kinds)
        if kinds != self._style_kinds:
            self._style_kinds = kinds
            if self._style_mode != CheckMode.OFF:
                self.rehighlight()

    def ignore_style_issue(self, kind: str, text: str) -> None:
        self._style_ignored.add((kind, _apos((text or "").strip().lower())))
        if self.learn_callback is not None:
            self.learn_callback("ignore_style", kind)
        if self._style_mode != CheckMode.OFF:
            self.rehighlight()

    def set_overuse_mode(self, mode: CheckMode):
        """Set overuse detection mode (takes effect immediately)."""
        changed = mode != self._overuse_mode
        self._overuse_mode = mode
        if changed:
            self.rehighlight()

    def get_spell_mode(self) -> CheckMode:
        """Get current spell checking mode."""
        return self._spell_mode

    def get_grammar_mode(self) -> CheckMode:
        """Get current grammar checking mode."""
        return self._grammar_mode

    def get_overuse_mode(self) -> CheckMode:
        """Get current overuse detection mode."""
        return self._overuse_mode

    def update_full_text(self, text: str):
        """Update the full document text for overuse analysis."""
        self._full_text = text
        self._full_text_fresh = True

    def do_full_recheck(self):
        """Recheck everything: re-run LanguageTool on every paragraph."""
        self._lt_cache.clear()
        self.rehighlight()
        self.request_grammar_check()

    def suspend(self) -> None:
        """Skip highlighting during a bulk load; finish with a rehighlight."""
        self._suspended = True

    def resume(self) -> None:
        self._suspended = False

    def do_initial_check(self):
        """Perform initial check when document is loaded."""
        self.rehighlight()
        self.request_grammar_check()

    # ── LanguageTool (background) ─────────────────────────────────

    def request_grammar_check(self) -> None:
        """Check paragraphs LanguageTool hasn't seen yet, in the background."""
        if self._grammar_mode == CheckMode.OFF:
            return
        from src.utils.proofing import LanguageToolEngine
        if LanguageToolEngine.get().status in ("unavailable", "failed"):
            self.grammar_status.emit(f"Grammar: {LanguageToolEngine.get().describe()}")
            return
        if self._grammar_worker is not None and self._grammar_worker.isRunning():
            self._grammar_rerun = True
            return
        doc = self.document()
        if doc is None:
            return
        todo, seen = [], set()
        block = doc.begin()
        while block.isValid():
            t = block.text()
            if t.strip() and t not in self._lt_cache and t not in seen:
                seen.add(t)
                todo.append(t)
            block = block.next()
        if not todo:
            return
        global _QUIT_HOOKED
        # Collect pending garbage here, on the GUI thread. Otherwise the
        # collector can run on the worker thread (it allocates heavily)
        # and destroy discarded Qt widgets off the GUI thread — a crash.
        import gc
        gc.collect()
        worker = _GrammarWorker(todo)
        worker.results_ready.connect(self._on_grammar_results)
        # Signal-to-signal (not ``.emit``) so Qt drops the connection if
        # this highlighter is deleted while the worker is still running.
        worker.status.connect(self.grammar_status)
        worker.finished.connect(self._on_grammar_worker_finished)
        _RUNNING_GRAMMAR_WORKERS.add(worker)
        worker.finished.connect(lambda w=worker: _RUNNING_GRAMMAR_WORKERS.discard(w))
        if not _QUIT_HOOKED:
            from PyQt6.QtCore import QCoreApplication
            app = QCoreApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(_wait_for_grammar_workers)
                _QUIT_HOOKED = True
        self._grammar_worker = worker
        worker.start()

    def _on_grammar_results(self, results: dict) -> None:
        if not results:
            return
        self._lt_cache.update(results)
        if len(self._lt_cache) > 5000:
            # Keep only paragraphs still in the document.
            live = set()
            b = self.document().begin()
            while b.isValid():
                live.add(b.text())
                b = b.next()
            self._lt_cache = {k: v for k, v in self._lt_cache.items() if k in live}
        block = self.document().begin()
        while block.isValid():
            if block.text() in results:
                self.rehighlightBlock(block)
            block = block.next()

    def _on_grammar_worker_finished(self) -> None:
        if self._grammar_rerun:
            self._grammar_rerun = False
            QTimer.singleShot(0, self.request_grammar_check)

    def wait_for_grammar(self, timeout_ms: int = 60000) -> None:
        """Block until a running LanguageTool pass finishes (tests / export)."""
        if self._grammar_worker is not None:
            self._grammar_worker.wait(timeout_ms)
            from PyQt6.QtCore import QCoreApplication
            QCoreApplication.processEvents()

    def set_typing_position(self, block_number: Optional[int], pos: int = 0) -> None:
        """The word ending at (block, pos) is being typed — don't flag it yet."""
        prev = self._typing
        self._typing = (block_number, pos) if block_number is not None else None
        if prev is not None and (self._typing is None or prev[0] != self._typing[0]):
            b = self.document().findBlockByNumber(prev[0])
            if b.isValid():
                self.rehighlightBlock(b)

    def ignore_error(self, block_number: int, start: int, word: str, error_type: Optional[ErrorType] = None):
        """Ignore a specific error.

        Args:
            block_number: Block number (kept for API compatibility, but not used)
            start: Start position (kept for API compatibility, but not used)
            word: The word to ignore
            error_type: Optional specific error type to ignore for this word
        """
        word_lower = word.lower()
        if word_lower not in self._ignored_words:
            self._ignored_words[word_lower] = set()

        if error_type:
            # Ignore only this specific error type for this word
            self._ignored_words[word_lower].add(error_type)
        else:
            # Ignore all error types for this word
            self._ignored_words[word_lower].update([ErrorType.SPELLING, ErrorType.GRAMMAR, ErrorType.OVERUSE, ErrorType.OVERUSED_PHRASE])

        self.rehighlight()

    def clear_ignored(self):
        """Clear all ignored words."""
        self._ignored_words.clear()
        self.rehighlight()

    def get_error_at(self, block_number: int, position_in_block: int) -> Optional[WritingError]:
        """Get error at position (suggestions filled in on demand)."""
        if block_number not in self._errors:
            # Error records for this block were dropped when an edit
            # above it shifted block numbers; rebuild them.
            block = self.document().findBlockByNumber(block_number)
            if block.isValid():
                self.rehighlightBlock(block)
        # The most specific error wins (a misspelled word inside a long
        # sentence flagged for style is the misspelling).
        hits = [e for e in self._errors.get(block_number, [])
                if e.start <= position_in_block < e.end]
        if not hits:
            return None
        if all(e.error_type == ErrorType.OVERUSED_PHRASE for e in hits):
            # Overlapping repeated phrases: the longest is the one to fix.
            error = max(hits, key=lambda e: e.end - e.start)
        else:
            error = min(hits, key=lambda e: (e.end - e.start, e.error_type == ErrorType.STYLE))
        return self._fill_suggestions(block_number, error)

    def phrase_error_at(self, block_number: int, position_in_block: int) -> Optional[WritingError]:
        """The longest repeated phrase covering this position (it can sit
        under an overused word, which wins the click), suggestions filled in."""
        hits = [e for e in self._errors.get(block_number, [])
                if e.start <= position_in_block < e.end
                and e.error_type == ErrorType.OVERUSED_PHRASE]
        if not hits:
            return None
        return self._fill_suggestions(block_number,
                                      max(hits, key=lambda e: e.end - e.start))

    def _fill_suggestions(self, block_number: int, error: WritingError) -> WritingError:
        if error.suggestions is None:
            if error.error_type == ErrorType.SPELLING:
                error.suggestions = self.spell_checker.suggest(error.word)
            elif error.error_type == ErrorType.OVERUSE and self.overuse_detector:
                block = self.document().findBlockByNumber(block_number) if self.document() else None
                paragraph = block.text() if block is not None and block.isValid() else ""
                from src.ai.word_suggest import compound_around
                compound = compound_around(paragraph, error.start, error.end)
                if compound is not None:
                    # One word of a set phrase: replace the whole phrase, or nothing.
                    error.replace_span = (compound.start, compound.end)
                    error.suggestions = compound.synonyms
                    error.reason += (f" Here it's part of “{compound.phrase}” — suggestions "
                                     f"replace the whole phrase.")
                else:
                    error.suggestions = self.overuse_detector.contextual_synonyms(
                        error.word, paragraph, self._full_text or "", position=error.start)
            elif error.error_type == ErrorType.OVERUSED_PHRASE and self.overuse_detector:
                fix = self.overuse_detector.phrase_alternatives(error.word)
                if fix is not None:
                    sub_start, sub_end, options = fix
                    error.replace_span = (error.start + sub_start, error.start + sub_end)
                    error.suggestions = options
                else:
                    error.suggestions = []
            else:
                error.suggestions = []
        return error

    def _apply_markdown_formatting(self, text: str):
        """Apply visual formatting for Markdown syntax.

        This renders Markdown headings, bold, and italic with appropriate fonts
        while keeping the Markdown syntax visible (but dimmed).
        """
        # Check for heading prefixes at start of line
        stripped = text.lstrip()
        leading_spaces = len(text) - len(stripped)

        # Heading detection (most specific first)
        if stripped.startswith("##### "):
            # Heading 4
            prefix_len = 6 + leading_spaces
            self.setFormat(0, prefix_len, self.md_prefix_format)
            self.setFormat(prefix_len, len(text) - prefix_len, self.md_h4_format)
        elif stripped.startswith("#### "):
            # Heading 3
            prefix_len = 5 + leading_spaces
            self.setFormat(0, prefix_len, self.md_prefix_format)
            self.setFormat(prefix_len, len(text) - prefix_len, self.md_h3_format)
        elif stripped.startswith("### "):
            # Heading 2
            prefix_len = 4 + leading_spaces
            self.setFormat(0, prefix_len, self.md_prefix_format)
            self.setFormat(prefix_len, len(text) - prefix_len, self.md_h2_format)
        elif stripped.startswith("## "):
            # Heading 1
            prefix_len = 3 + leading_spaces
            self.setFormat(0, prefix_len, self.md_prefix_format)
            self.setFormat(prefix_len, len(text) - prefix_len, self.md_h1_format)
        elif stripped.startswith("# "):
            # Title
            prefix_len = 2 + leading_spaces
            self.setFormat(0, prefix_len, self.md_prefix_format)
            self.setFormat(prefix_len, len(text) - prefix_len, self.md_title_format)

        # Bold-italic (***text***) - must come before bold and italic
        for match in re.finditer(r'\*\*\*(.+?)\*\*\*', text):
            # Dim the markers
            self.setFormat(match.start(), 3, self.md_marker_format)
            self.setFormat(match.end() - 3, 3, self.md_marker_format)
            # Bold+italic the content
            self.setFormat(match.start() + 3, len(match.group(1)), self.md_bold_italic_format)

        # Bold (**text**)
        for match in re.finditer(r'\*\*(?!\*)(.+?)(?<!\*)\*\*', text):
            # Dim the markers
            self.setFormat(match.start(), 2, self.md_marker_format)
            self.setFormat(match.end() - 2, 2, self.md_marker_format)
            # Bold the content
            self.setFormat(match.start() + 2, len(match.group(1)), self.md_bold_format)

        # Italic (*text* but not **text**)
        for match in re.finditer(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', text):
            # Dim the markers
            self.setFormat(match.start(), 1, self.md_marker_format)
            self.setFormat(match.end() - 1, 1, self.md_marker_format)
            # Italic the content
            self.setFormat(match.start() + 1, len(match.group(1)), self.md_italic_format)

        # Italic with underscores (_text_)
        for match in re.finditer(r'(?<![_\w])_([^_]+)_(?![_\w])', text):
            # Dim the markers
            self.setFormat(match.start(), 1, self.md_marker_format)
            self.setFormat(match.end() - 1, 1, self.md_marker_format)
            # Italic the content
            self.setFormat(match.start() + 1, len(match.group(1)), self.md_italic_format)

    def highlightBlock(self, text: str):
        """Highlight errors in a block of text. What to flag is decided by
        ``FlagRules.paragraph_flags`` (no Qt); this only draws it."""
        if self._suspended:
            return
        block = self.currentBlock()
        block_number = block.blockNumber()

        # Store current block hash to track changes
        self._block_hashes[block_number] = hash(text)

        # Clear previous errors for this block
        self._errors[block_number] = []

        # Apply Markdown formatting first (before error checks)
        self._apply_markdown_formatting(text)
        if not self._highlights_visible:
            return

        def get_existing_format(pos: int) -> QTextCharFormat:
            """Document format at ``pos`` merged with what this highlighter
            already applied there (so a style tint survives a spelling
            underline drawn over it)."""
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + pos)
            fmt = cursor.charFormat()
            fmt.merge(self.format(pos))
            return fmt

        def draw(start: int, length: int, fmt_add: QTextCharFormat) -> None:
            merged = get_existing_format(start)
            merged.merge(fmt_add)
            self.setFormat(start, length, merged)

        errors, focus_keep = self.paragraph_flags(text, block_number, block.position())
        self._errors[block_number] = errors
        for e in errors:
            if e.error_type == ErrorType.STYLE:
                fmt_add = self._style_formats[e.style_kind]
                pos = e.start
                while pos < e.end:           # merge segment by segment
                    seg_end = pos + 1
                    base = self.format(pos)
                    while seg_end < e.end and self.format(seg_end) == base:
                        seg_end += 1
                    draw(pos, seg_end - pos, fmt_add)
                    pos = seg_end
            elif e.error_type == ErrorType.GRAMMAR:
                for seg_start, seg_end in getattr(e, "draw_segments", [(e.start, e.end)]):
                    draw(seg_start, seg_end - seg_start, self.grammar_format)
            else:
                draw(e.start, e.end - e.start, self._format_for(e))

        if focus_keep is not None:
            # Focus: only this paragraph's most important issues stay marked.
            self.setFormat(0, len(text), QTextCharFormat())
            self._apply_markdown_formatting(text)
            for e in focus_keep:
                fmt = self._format_for(e)
                if fmt is None or e.end <= e.start:
                    continue
                draw(e.start, e.end - e.start, fmt)

    def _format_for(self, error):
        if error.error_type == ErrorType.STYLE:
            return self._style_formats.get(getattr(error, "style_kind", ""))
        return {ErrorType.SPELLING: self.spelling_format, ErrorType.GRAMMAR: self.grammar_format,
                ErrorType.OVERUSE: self.overuse_format,
                ErrorType.OVERUSED_PHRASE: self.phrase_format}.get(error.error_type)


class ContextLookupDialog(QDialog):
    """Dialog for displaying context lookup results."""

    def __init__(self, title: str, content: str, parent=None):
        """Initialize context lookup dialog."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout(self)

        # Content display
        self.content_browser = QTextBrowser()
        self.content_browser.setMarkdown(content)
        self.content_browser.setOpenExternalLinks(False)
        layout.addWidget(self.content_browser)

        # Close button
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)


class QuickReferenceDialog(QDialog):
    """Dialog for quick reference selection."""

    def __init__(self, items: list, item_type: str, parent=None):
        """Initialize quick reference dialog."""
        super().__init__(parent)
        self.setWindowTitle(f"Select {item_type}")
        self.setMinimumSize(400, 300)
        self.selected_item = None

        layout = QVBoxLayout(self)

        label = QLabel(f"Select a {item_type} to view:")
        layout.addWidget(label)

        # Item list
        self.item_list = QListWidget()
        for item in items:
            self.item_list.addItem(item)
        self.item_list.itemDoubleClicked.connect(self._on_item_selected)
        layout.addWidget(self.item_list)

        # Buttons
        button_layout = QHBoxLayout()

        select_button = QPushButton("Select")
        select_button.clicked.connect(self._on_item_selected)
        button_layout.addWidget(select_button)

        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        layout.addLayout(button_layout)

    def _on_item_selected(self):
        """Handle item selection."""
        current_item = self.item_list.currentItem()
        if current_item:
            self.selected_item = current_item.text()
            self.accept()


class ErrorCard(QWidget):
    """Hover card for a highlighted issue: what's wrong, plus clickable
    fixes. Replaces the old read-only tooltip.

    Shown below the word; stays open while the mouse is on the word or the
    card, closes when the mouse leaves, on typing, or on a click elsewhere.
    """

    from src.ui.ui_kit import FLAG_COLOURS as COLORS   # one colour per kind, app-wide
    NAMES = {"spelling": "Spelling", "grammar": "Grammar", "overuse": "Overused word",
             "overused_phrase": "Repeated phrase", "style": "Style"}

    def __init__(self, editor: "EnhancedTextEditor"):
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.editor = editor
        self.error = None
        self.span: Tuple[int, int] = (0, 0)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)   # paint border + background
        self.setStyleSheet(
            "ErrorCard { background: #ffffff; border: 1px solid #d1d5db; border-radius: 6px; }"
            "QLabel { background: transparent; }"
            "QPushButton#fix { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe;"
            " border-radius: 4px; padding: 3px 8px; font-weight: bold; }"
            "QPushButton#fix:hover { background: #dbeafe; }"
            "QPushButton#act { background: transparent; color: #4b5563; border: none;"
            " padding: 2px 4px; text-decoration: underline; }")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 8, 10, 8)
        self._layout.setSpacing(6)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(350)
        self._hide_timer.timeout.connect(self._maybe_hide)

    # ── content ────────────────────────────────────────────────────

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            lay = item.layout()
            if w is not None:
                w.deleteLater()
            elif lay is not None:
                while lay.count():
                    sub = lay.takeAt(0).widget()
                    if sub is not None:
                        sub.deleteLater()

    def show_for(self, error, block, global_pos: QPoint, phrase=None) -> None:
        """``phrase``: a repeated phrase under an overused word, shown as a
        second section with its own fixes."""
        key = (block.position() + error.start, block.position() + error.end, error.reason,
               getattr(phrase, "start", None))
        if self.isVisible() and self.error is not None and key == getattr(self, "_key", None):
            self._hide_timer.stop()
            return
        self._key = key
        self.error = error
        self.block_number = block.blockNumber()
        self.span = (block.position() + error.start, block.position() + error.end)
        self._clear()
        kind = error.error_type.value
        color = self.COLORS.get(kind, "#374151")
        head = QLabel(f"<span style='color:{color}; font-weight:bold'>"
                      f"{self.NAMES.get(kind, 'Issue')}</span> · <b>{_html(error.word[:60])}</b>")
        self._layout.addWidget(head)
        reason = error.reason.split(": ", 1)[-1] if kind == "style" else error.reason
        why = QLabel(_html(reason))
        why.setWordWrap(True)
        why.setMaximumWidth(340)
        why.setStyleSheet("color: #4b5563;")
        self._layout.addWidget(why)

        self._block = block
        self._fix_row(error, block)
        if not error.suggestions and kind == "spelling":
            none = QLabel("<i>No suggestions.</i>")
            none.setStyleSheet("color: #6b7280;")
            self._layout.addWidget(none)
        elif not error.suggestions and kind == "overused_phrase":
            none = QLabel("<i>No standard fix — try ✨ Suggest in context.</i>")
            none.setStyleSheet("color: #6b7280;")
            self._layout.addWidget(none)

        actions = QHBoxLayout()
        actions.setSpacing(2)
        if kind in ("overuse", "overused_phrase"):
            self._action(actions, "✨ Suggest in context",
                         lambda _=False, e=error: self._suggest_in_context(e))
        self._action(actions, "💬 Ask", lambda _=False, e=error: self._ask(e))
        if kind == "style":
            self._action(actions, "✨ Rewrite with AI", self._rewrite)
        if kind == "spelling":
            self._action(actions, "Add to dictionary", self._add_word)
        from src.ui import fix_all; fix_all.add_to_card(self, actions, error)   # 3.4
        self._action(actions, "Ignore", self._ignore)
        from src.ui import write_toolbar; write_toolbar.fold_card_row(self, actions)   # D.7
        actions.addStretch()
        self._layout.addLayout(actions)

        if phrase is not None:
            line = QLabel(f"<span style='color:{self.COLORS['overused_phrase']}; "
                          f"font-weight:bold'>Repeated phrase</span> · "
                          f"<b>{_html(phrase.word[:60])}</b>")
            self._layout.addWidget(line)
            note = QLabel(_html(phrase.reason))
            note.setWordWrap(True)
            note.setMaximumWidth(340)
            note.setStyleSheet("color: #4b5563;")
            self._layout.addWidget(note)
            self._fix_row(phrase, block)
            more = QHBoxLayout()
            more.setSpacing(2)
            self._action(more, "✨ Suggest in context",
                         lambda _=False, e=phrase: self._suggest_in_context(e))
            self._action(more, "Ignore phrase", lambda _=False, e=phrase: self._ignore_one(e))
            more.addStretch()
            self._layout.addLayout(more)
        self.adjustSize()
        self._place(global_pos)
        self.show()
        self.raise_()

    def _fix_row(self, error, block) -> None:
        """Buttons for an issue's fixes; each replaces the issue's fix span."""
        suggestions = [s for s in (error.suggestions or [])][:5]
        if not suggestions:
            return
        start, end = error.replace_span or (error.start, error.end)
        span = (block.position() + start, block.position() + end)
        target = block.text()[start:end]
        row = QHBoxLayout()
        row.setSpacing(4)
        for sug in suggestions:
            btn = QPushButton(sug if sug else f"Delete “{target[:20]}”")
            btn.setObjectName("fix")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"Replace “{target}” with “{sug}”" if sug else f"Delete “{target}”")
            btn.clicked.connect(lambda _=False, s_=sug, e=error, sp=span, t=target:
                                self._apply(s_, e, sp, t))
            row.addWidget(btn)
        row.addStretch()
        self._layout.addLayout(row)

    def _ask(self, error) -> None:
        block = getattr(self, "_block", None)
        self.hide()
        if block is not None and block.isValid():
            self.editor.ask_about(block, error)

    def _suggest_in_context(self, error) -> None:
        block = getattr(self, "_block", None)
        self.hide()
        if block is not None and block.isValid():
            self.editor.suggest_in_context(block, error)

    def _ignore_one(self, error) -> None:
        self.hide()
        self.editor._ignore_error(self.block_number, error.start, error.word, error.error_type)

    def _action(self, row, text, slot) -> None:
        btn = QPushButton(text)
        btn.setObjectName("act")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(slot)
        row.addWidget(btn)

    def _place(self, global_pos: QPoint) -> None:
        cur = QTextCursor(self.editor.document())
        cur.setPosition(self.span[0])
        rect = self.editor.cursorRect(cur)
        anchor = self.editor.viewport().mapToGlobal(rect.bottomLeft()) + QPoint(0, 4)
        screen = self.editor.screen().availableGeometry() if self.editor.screen() else None
        x, y = anchor.x(), anchor.y()
        if screen is not None:
            x = max(screen.left(), min(x, screen.right() - self.width()))
            if y + self.height() > screen.bottom():
                y = self.editor.viewport().mapToGlobal(rect.topLeft()).y() - self.height() - 4
        self.move(x, y)

    # ── actions ────────────────────────────────────────────────────

    def _span_text(self) -> str:
        cur = QTextCursor(self.editor.document())
        cur.setPosition(self.span[0])
        cur.setPosition(self.span[1], QTextCursor.MoveMode.KeepAnchor)
        return cur.selectedText()

    def _apply(self, suggestion: str, error=None, span=None, target=None) -> None:
        error = error or self.error
        if error is None:
            return
        span = span or self.span
        target = error.word if target is None else target
        cur = QTextCursor(self.editor.document())
        cur.setPosition(span[0])
        cur.setPosition(span[1], QTextCursor.MoveMode.KeepAnchor)
        if cur.selectedText() != target:      # text changed since the card opened
            self.hide()
            return
        if suggestion and error.error_type == ErrorType.SPELLING:
            suggestion = _match_word_case(error.word, suggestion)
        self.hide()
        self.editor._apply_fix(cur, suggestion, error)
        self.editor.setFocus()

    def _add_word(self) -> None:
        if self.error is not None:
            word = self.error.word
            self.hide()
            self.editor._add_to_dictionary(word)

    def _ignore(self) -> None:
        error = self.error
        if error is None:
            return
        self.hide()
        if error.error_type == ErrorType.STYLE:
            self.editor.writing_highlighter.ignore_style_issue(
                getattr(error, "style_kind", ""), error.word)
        else:
            self.editor._ignore_error(self.block_number, error.start, error.word, error.error_type)

    def _rewrite(self) -> None:
        error = self.error
        if error is None:
            return
        self.hide()
        block = self.editor.document().findBlockByNumber(self.block_number)
        if block.isValid():
            self.editor._request_style_rewrite(block, error)

    # ── visibility ─────────────────────────────────────────────────

    def schedule_hide(self) -> None:
        if self.isVisible():
            self._hide_timer.start()

    def _maybe_hide(self) -> None:
        from src.ui.hover_card import near_card
        if not self.isVisible():
            return
        if near_card(self, self.editor):
            self._hide_timer.start()          # look again: the pointer may still leave
        else:
            self.hide()

    def wheelEvent(self, event):
        event.accept()                        # scrolling over the card keeps it open

    def enterEvent(self, event):
        self._hide_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.schedule_hide()
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._hide_timer.stop()
        from src.ui import fix_all; fix_all.card_hidden(self)   # 3.4
        super().hideEvent(event)


def _html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _match_word_case(original: str, replacement: str) -> str:
    # Keep the writer's apostrophe style ("did’nt" → "didn’t", not "didn't").
    from src.utils.proofing import APOSTROPHE_LIKE
    used = next((c for c in original if c in APOSTROPHE_LIKE), None)
    if used and "'" in replacement:
        replacement = replacement.replace("'", used)
    if original.isupper() and len(original) > 1:
        return replacement.upper()
    if original[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


class EnhancedTextEditor(QTextEdit):
    """Enhanced text editor with context menu, headers, spell/grammar/overuse check, Word support, and TTS."""

    context_lookup_requested = pyqtSignal(str)
    spell_check_toggled = pyqtSignal(bool)
    grammar_check_toggled = pyqtSignal(bool)
    overuse_check_toggled = pyqtSignal(bool)

    # TTS signals
    tts_started = pyqtSignal()
    tts_stopped = pyqtSignal()
    tts_error = pyqtSignal(str)
    tts_progress = pyqtSignal(str)  # Progress updates for VibeVoice
    # "✨ Rewrite with AI" on a style issue: (doc start, doc end, hint).
    style_rewrite_requested = pyqtSignal(int, int, str)
    # A style-sheet rule was learned (suggested) — message for the writer.
    style_sheet_changed = pyqtSignal(str)
    phase_changed = pyqtSignal(str)          # "drafting" | "revising"

    # Heading style definitions for display and export
    # Format: (font_size, bold, top_margin, bottom_margin, heading_level)
    HEADING_STYLES = {
        "Normal": (12, False, 0, 0, HeadingLevel.NORMAL),
        "Title": (28, True, 24, 12, HeadingLevel.TITLE),
        "Heading 1": (24, True, 18, 8, HeadingLevel.HEADING_1),
        "Heading 2": (18, True, 14, 6, HeadingLevel.HEADING_2),
        "Heading 3": (14, True, 10, 4, HeadingLevel.HEADING_3),
        "Heading 4": (12, True, 8, 4, HeadingLevel.HEADING_4),
    }

    # Legacy mapping for backward compatibility
    HEADER_SIZES = {
        "Normal": 12,
        "Title": 28,
        "Heading 1": 24,
        "Heading 2": 18,
        "Heading 3": 14,
        "Heading 4": 12,
    }

    def __init__(self, parent=None):
        """Initialize enhanced text editor."""
        super().__init__(parent)

        # Callbacks for context lookup
        self.lookup_worldbuilding_callback: Optional[Callable] = None
        self.lookup_characters_callback: Optional[Callable] = None
        self.lookup_plot_callback: Optional[Callable] = None
        self.lookup_context_callback: Optional[Callable] = None
        self.get_character_list_callback: Optional[Callable] = None
        self.get_worldbuilding_sections_callback: Optional[Callable] = None

        # Enable rich text
        self.setAcceptRichText(True)

        # Initialize checkers
        from src.utils.editor_flags import new_checkers
        self.spell_checker, self.grammar_checker, self.overuse_detector = new_checkers()
        self._project = None
        self.phase_setting = "revising"     # every check unless the writer chooses otherwise

        # Initialize combined highlighter
        self.writing_highlighter = WritingHighlighter(
            self.document(),
            self.spell_checker,
            self.grammar_checker,
            self.overuse_detector
        )

        # Enable mouse tracking for tooltips on both widget and viewport
        # On macOS, QTextEdit uses a viewport for rendering, so we must enable
        # mouse tracking there and handle tooltip events via viewportEvent()
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

        # Update overuse detection when text changes (with longer debounce for performance)
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        self._update_timer = QTimer()
        self._update_timer.setSingleShot(True)
        self._update_timer.timeout.connect(self._update_realtime_analysis)
        # Model review of light repeats, a moment after the text settles.
        self.writing_highlighter.learn_callback = self._learn
        self._review_timer = QTimer(self)
        self._review_timer.setSingleShot(True)
        self._review_timer.setInterval(2500)
        self._review_timer.timeout.connect(self._start_repetition_review)
        self._review_worker = None
        self._flag_worker = None
        self._review_rerun = False
        self._no_repetition_judge = False
        self._last_text_hash = 0

        # Set up context menu
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        # TTS setup
        self._tts_service = None
        self._tts_available = TTS_AVAILABLE
        if self._tts_available:
            self._init_tts()

    def _on_text_changed(self):
        """Handle text changes - debounce analysis for realtime modes."""
        # The word at the cursor is still being typed: don't underline it
        # until the writer moves on (space, punctuation, click away).
        cur = self.textCursor()
        block = cur.block()
        pos = cur.positionInBlock()
        if pos > 0 and block.text()[pos - 1:pos].isalpha():
            self.writing_highlighter.set_typing_position(block.blockNumber(), pos)
        else:
            self.writing_highlighter.set_typing_position(None)
        # Use longer debounce (1.5s) to avoid freezing during rapid typing
        self._update_timer.start(1500)

    def _on_cursor_moved(self):
        """Cursor moved without typing — the pending word is finished."""
        hl = self.writing_highlighter
        if hl._typing is None:
            return
        cur = self.textCursor()
        if (cur.block().blockNumber(), cur.positionInBlock()) != hl._typing:
            hl.set_typing_position(None)
            b = self.document().findBlockByNumber(cur.block().blockNumber())
            if b.isValid():
                hl.rehighlightBlock(b)

    def _update_realtime_analysis(self):
        """Typing paused: finish the pending word, refresh statistics, and
        (REALTIME grammar) check edited paragraphs with LanguageTool."""
        hl = self.writing_highlighter
        if hl._typing is not None:
            pending = hl._typing
            hl.set_typing_position(None)
            b = self.document().findBlockByNumber(pending[0])
            if b.isValid():
                hl.rehighlightBlock(b)
        current_text = self.toPlainText()
        current_hash = hash(current_text)

        # Only update if text actually changed
        if current_hash != self._last_text_hash:
            self._last_text_hash = current_hash
            # Update the cache in overuse detector
            self.overuse_detector.update_cache(current_text)
            hl.update_full_text(current_text)

            if hl.get_grammar_mode() == CheckMode.REALTIME:
                hl.request_grammar_check()
            # Overuse counts span the whole document — redraw in realtime.
            if hl.get_overuse_mode() == CheckMode.REALTIME:
                hl.rehighlight()
            self._review_timer.start()
        self._update_phase()

    # ── Drafting / revising ───────────────────────────────────────

    DRAFT_GROWTH_WORDS = 12          # words added at the end within the window
    PHASE_WINDOW_S = 180

    def set_phase_setting(self, setting: str) -> None:
        """"auto" (switch as you write), "drafting" or "revising"."""
        self.phase_setting = setting
        self._apply_phase(setting if setting != "auto" else "revising", force=True)

    def _apply_phase(self, phase: str, force: bool = False) -> None:
        hl = self.writing_highlighter
        if hl.phase == phase and not force:
            return
        hl.phase = phase
        hl.rehighlight()
        if phase == "revising":
            self._review_timer.start()
        self.phase_changed.emit(phase)

    def set_focus(self, on: bool) -> None:
        self.writing_highlighter.focus = on
        self.writing_highlighter.rehighlight()

    def _update_phase(self) -> None:
        """Auto: adding words at the end → drafting; editing inside the text
        or a pause in new writing → revising."""
        import time
        setting = getattr(self, "phase_setting", "auto")
        if setting != "auto":
            return
        now = time.monotonic()
        words = len(self.toPlainText().split())
        samples = self.__dict__.setdefault("_phase_samples", [])
        samples.append((now, words))
        while samples and now - samples[0][0] > self.PHASE_WINDOW_S:
            samples.pop(0)
        growth = words - samples[0][1]
        # Near the end: in the last paragraphs and the last few hundred characters
        # (one long paragraph must not count as "the end" everywhere).
        cursor = self.textCursor()
        near_end = (cursor.blockNumber() >= self.document().blockCount() - 2
                    and cursor.position() >= self.document().characterCount() - 400)
        if near_end and growth >= self.DRAFT_GROWTH_WORDS:
            self._apply_phase("drafting")
        elif not near_end or growth <= 2:
            self._apply_phase("revising")

    def set_project_vocabulary(self, project) -> None:
        """Teach the spell checker the project's names and dictionary."""
        from src.utils.editor_flags import project_vocabulary
        words, names = project_vocabulary(project)
        self.spell_checker.set_project_words(words)
        from src.utils import proof_store
        proof_store.load(project)      # a model's stored corrections (P.4)
        self._project = project
        self.writing_highlighter.project = project
        self.overuse_detector.set_names(names + self._allowed_words())
        text = self.toPlainText()
        self.overuse_detector.update_cache(text)
        self.writing_highlighter.update_full_text(text)
        self.writing_highlighter.rehighlight()

    # ── Personal style sheet ──────────────────────────────────────

    def _style_sheet_prompt(self) -> str:
        from src.ai.style_sheet import prompt_block
        project = getattr(self, "_project", None)
        return prompt_block(project) if project is not None else ""

    def _allowed_words(self) -> List[str]:
        from src.utils.editor_flags import allowed_words
        return allowed_words(getattr(self, "_project", None))

    def _learn(self, signal: str, subject: str) -> None:
        """Count what the writer does; a repeated pattern proposes a rule."""
        project = getattr(self, "_project", None)
        if project is None or not subject:
            return
        from src.ai import style_sheet as ss
        rule = ss.record(project, signal, subject)
        if rule is not None:
            self.style_sheet_changed.emit(f"💡 Suggested for your style sheet: {rule.text}")

    def _apply_fix(self, cursor: QTextCursor, suggestion: str, error) -> None:
        """Apply a suggested fix, and learn from which words get cut."""
        from src.ui import fix_all                                   # 3.4: "Fix all N" ticked
        if fix_all.everywhere(self, suggestion, error):
            return
        self._replace_word(cursor, suggestion)
        if error is not None and error.error_type in (ErrorType.OVERUSE, ErrorType.STYLE) \
                and len((error.word or "").split()) == 1:
            self._learn("fix_word", error.word)

    def refresh_style_sheet(self) -> None:
        """The style sheet changed: re-read it and redraw."""
        project = getattr(self, "_project", None)
        if project is not None:
            names = [c.name for c in getattr(project, "characters", None) or []]
            self.overuse_detector.set_names(names + self._allowed_words())
            text = self.toPlainText()
            self.overuse_detector.update_cache(text)
            self.writing_highlighter.update_full_text(text)
        self.writing_highlighter.__dict__.pop("_intended_cache", None)
        self.writing_highlighter._style_cache.clear()
        self.writing_highlighter.rehighlight()

    # ── Model review of light repeats ─────────────────────────────

    def _start_repetition_review(self) -> None:
        """Ask the model which light repeats weaken the writing (background);
        until it answers — or with no model — the quick rules apply. Then the
        same for the style, grammar and spelling flags."""
        try:
            self._start_flag_review()
        except Exception as e:
            print(f"[flags] {e}")
        hl = self.writing_highlighter
        if hl.get_overuse_mode() == CheckMode.OFF or self._no_repetition_judge:
            return
        from src.ai import repetition_judge as rj
        if not rj.enabled():
            return
        detector = self.overuse_detector
        if detector._cached_text_hash != hash(self.toPlainText()):
            detector.update_cache(self.toPlainText())
        items = detector.review_items()
        if not items:
            return
        known = rj.cached_verdicts(items)
        if known:
            self._apply_repetition_verdicts(known)
            items = [i for i in items if i["key"] not in known]
            if not items:
                return
        if self._review_worker is not None and self._review_worker.isRunning():
            self._review_rerun = True
            return
        import gc
        gc.collect()      # never let the worker's allocations collect Qt objects
        worker = _RepetitionWorker(items, self._style_sheet_prompt())
        worker.done.connect(self._on_repetition_verdicts)
        _RUNNING_REVIEWERS.add(worker)
        worker.finished.connect(lambda w=worker: _RUNNING_REVIEWERS.discard(w))
        self._review_worker = worker
        worker.start()

    def _start_flag_review(self) -> None:
        """Send the style / grammar / spelling flags near the writer to the
        model; hide the ones it judges false alarms."""
        from src.ai import flag_judge as fj
        if self._no_repetition_judge or not fj.enabled():
            return
        if self._flag_worker is not None and self._flag_worker.isRunning():
            return
        items = fj.collect(self.writing_highlighter, self.document(),
                           self.textCursor().blockNumber())
        if not items:
            return
        import gc
        gc.collect()
        sheet = self._style_sheet_prompt()
        worker = _FlagReviewWorker(items, "\n\n".join(
            b for b in (fj.spelling_context(getattr(self, "_project", None)), sheet) if b), sheet)
        worker.done.connect(self._on_flag_verdicts)
        _RUNNING_REVIEWERS.add(worker)
        worker.finished.connect(lambda w=worker: _RUNNING_REVIEWERS.discard(w))
        self._flag_worker = worker
        worker.start()

    def _on_flag_verdicts(self, verdicts, no_model: bool) -> None:
        try:
            if no_model:
                self._no_repetition_judge = True
                return
            if verdicts and any(not keep for keep, _ in verdicts.values()):
                self.__dict__.pop("_intended_cache", None)
                self.writing_highlighter.__dict__.pop("_intended_cache", None)
                self.writing_highlighter.rehighlight()
        except Exception as e:          # an exception escaping a slot aborts PyQt6
            print(f"[flags] could not apply verdicts: {e}")

    def _on_repetition_verdicts(self, verdicts, no_model: bool) -> None:
        try:
            if no_model:
                self._no_repetition_judge = True     # quick rules from now on
                return
            if verdicts:
                self._apply_repetition_verdicts(verdicts)
            if self._review_rerun:
                self._review_rerun = False
                self._review_timer.start()
        except Exception as e:          # an exception escaping a slot aborts PyQt6
            print(f"[repetition] could not apply verdicts: {e}")

    def _apply_repetition_verdicts(self, verdicts) -> None:
        self.overuse_detector.apply_verdicts(verdicts)
        text = self.toPlainText()
        self.writing_highlighter.update_full_text(text)
        if self.writing_highlighter.get_overuse_mode() != CheckMode.OFF:
            self.writing_highlighter.rehighlight()

    def _has_realtime_checks(self) -> bool:
        """Check if any writing check is in realtime mode."""
        return (
            self.writing_highlighter.get_spell_mode() == CheckMode.REALTIME or
            self.writing_highlighter.get_grammar_mode() == CheckMode.REALTIME or
            self.writing_highlighter.get_overuse_mode() == CheckMode.REALTIME
        )

    def do_initial_check(self):
        """Perform initial check when content is loaded."""
        current_text = self.toPlainText()
        self.overuse_detector.update_cache(current_text)
        self.writing_highlighter.update_full_text(current_text)
        self.writing_highlighter.do_initial_check()
        self._last_text_hash = hash(current_text)  # Update hash to avoid immediate re-check
        self._review_timer.start()

    def set_spell_mode(self, mode: CheckMode):
        """Set spell checking mode."""
        self.writing_highlighter.set_spell_mode(mode)

    def set_style_mode(self, mode: CheckMode):
        self.writing_highlighter.set_style_mode(mode)

    def set_highlights_visible(self, visible: bool) -> None:
        self.writing_highlighter.set_highlights_visible(visible)

    def highlights_visible(self) -> bool:
        return self.writing_highlighter.highlights_visible()

    def get_style_mode(self) -> CheckMode:
        return self.writing_highlighter.get_style_mode()

    def set_grammar_mode(self, mode: CheckMode):
        """Set grammar checking mode."""
        self.writing_highlighter.set_grammar_mode(mode)

    def set_overuse_mode(self, mode: CheckMode):
        """Set overuse detection mode."""
        self.writing_highlighter.set_overuse_mode(mode)

    def get_spell_mode(self) -> CheckMode:
        """Get current spell checking mode."""
        return self.writing_highlighter.get_spell_mode()

    def get_grammar_mode(self) -> CheckMode:
        """Get current grammar checking mode."""
        return self.writing_highlighter.get_grammar_mode()

    def get_overuse_mode(self) -> CheckMode:
        """Get current overuse detection mode."""
        return self.writing_highlighter.get_overuse_mode()

    def _error_at_viewport_pos(self, viewport_pos: QPoint):
        cursor = self.cursorForPosition(viewport_pos)
        block = cursor.block()
        # cursorForPosition snaps to the nearest gap; only count it as "on"
        # the word when the mouse is actually over text.
        rect = self.cursorRect(cursor)
        if abs(rect.center().y() - viewport_pos.y()) > rect.height():
            return None, block
        return (self.writing_highlighter.get_error_at(block.blockNumber(),
                                                      cursor.positionInBlock()), block)

    @property
    def error_card(self) -> ErrorCard:
        card = getattr(self, "_error_card", None)
        if card is None:
            card = self._error_card = ErrorCard(self)
            from src.ui.hover_card import watch_editor
            watch_editor(card, self)            # close on edits, not on redraws
            self.destroyed.connect(card.deleteLater)
        return card

    def _show_error_tooltip(self, global_pos: QPoint, viewport_pos: QPoint) -> bool:
        """Show the clickable issue card for the error under the mouse.
        Returns True when a card was shown."""
        error, block = self._error_at_viewport_pos(viewport_pos)
        if error is not None:
            QToolTip.hideText()
            phrase = None
            if error.error_type != ErrorType.OVERUSED_PHRASE:
                cursor = self.cursorForPosition(viewport_pos)
                phrase = self.writing_highlighter.phrase_error_at(block.blockNumber(),
                                                                  cursor.positionInBlock())
            self.error_card.show_for(error, block, global_pos, phrase=phrase)
            return True
        if getattr(self, "_error_card", None) is not None:
            self._error_card.schedule_hide()
        return False

    def _legacy_error_tooltip(self, global_pos: QPoint, viewport_pos: QPoint) -> bool:
        """Old read-only tooltip (kept for reference / fallback)."""
        error, block = self._error_at_viewport_pos(viewport_pos)
        if error:
            # Color-coded error type indicator
            color_map = {
                ErrorType.SPELLING: "#ff0000",  # Red
                ErrorType.GRAMMAR: "#00b400",   # Green
                ErrorType.OVERUSE: "#0078ff",   # Blue
                ErrorType.OVERUSED_PHRASE: "#9400d3",  # Purple
            }
            type_names = {
                ErrorType.SPELLING: "Spelling",
                ErrorType.GRAMMAR: "Grammar",
                ErrorType.OVERUSE: "Overused Word",
                ErrorType.OVERUSED_PHRASE: "Repeated Phrase",
            }
            color = color_map.get(error.error_type, "#000000")
            type_name = type_names.get(error.error_type, "Error")

            tooltip_text = f"<span style='color:{color}'><b>{type_name}:</b></span> {error.word}<br>{error.reason}"
            if error.suggestions:
                tooltip_text += f"<br><br><b>Suggestions:</b> {', '.join(error.suggestions[:5])}"
            tooltip_text += "<br><br><i>Right-click for options</i>"
            QToolTip.showText(global_pos, tooltip_text, self)
            return True
        else:
            QToolTip.hideText()
        return False

    def keyPressEvent(self, event):
        card = getattr(self, "_error_card", None)
        if card is not None and card.isVisible():
            card.hide()
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        card = getattr(self, "_error_card", None)
        if card is not None and card.isVisible():
            card.schedule_hide()              # stays while the pointer is on it or its word
        super().focusOutEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press - Shift+click extends existing selection."""
        if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                and event.button() == Qt.MouseButton.LeftButton
                and self.textCursor().hasSelection()):
            # Shift+click with existing selection: extend selection to click point
            click_pos = self.cursorForPosition(event.pos()).position()
            cursor = self.textCursor()
            anchor = cursor.anchor()
            cursor.setPosition(anchor)
            cursor.setPosition(click_pos, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double-click for range selection.

        Double-click: select from cursor position to end of chapter.
        Shift+double-click: select from beginning of chapter to cursor position.
        """
        modifiers = event.modifiers()
        click_pos = self.cursorForPosition(event.pos()).position()

        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Shift+double-click: select from start to click position
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.setPosition(click_pos, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)
        else:
            # Plain double-click: select from click position to end
            cursor = self.textCursor()
            cursor.setPosition(click_pos)
            cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
            self.setTextCursor(cursor)

    def viewportEvent(self, event: QEvent) -> bool:
        """Handle viewport events including tooltip display for writing errors.

        On macOS, QTextEdit renders in a viewport, so tooltip events arrive here
        rather than in event(). This ensures tooltips work cross-platform.
        """
        if event.type() == QEvent.Type.ToolTip:
            pos = event.pos()
            global_pos = event.globalPos()
            if self._show_error_tooltip(global_pos, pos):
                return True
        elif event.type() == QEvent.Type.MouseMove:
            card = getattr(self, "_error_card", None)
            if card is not None and card.isVisible():
                error, block = self._error_at_viewport_pos(event.position().toPoint())
                same = (error is not None and
                        (block.position() + error.start, block.position() + error.end) == card.span)
                if same:
                    card._hide_timer.stop()
                else:
                    card.schedule_hide()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.Wheel,
                              QEvent.Type.MouseButtonPress):
            card = getattr(self, "_error_card", None)
            if card is not None and card.isVisible():
                if event.type() == QEvent.Type.Leave:
                    card.schedule_hide()
                elif (event.type() == QEvent.Type.Wheel
                      and card.geometry().contains(event.globalPosition().toPoint())):
                    return True                # scrolling over the card: keep it, don't scroll
                else:
                    card.hide()

        return super().viewportEvent(event)

    def event(self, event: QEvent) -> bool:
        """Handle events including tooltip display for writing errors."""
        if event.type() == QEvent.Type.ToolTip:
            # Get position under cursor
            pos = event.pos()
            global_pos = event.globalPos()
            if self._show_error_tooltip(global_pos, pos):
                return True

        return super().event(event)

    def set_spell_check_enabled(self, enabled: bool):
        """Enable or disable spell checking (backward compatibility)."""
        mode = CheckMode.ON_DEMAND if enabled else CheckMode.OFF
        self.set_spell_mode(mode)
        self.spell_check_toggled.emit(enabled)

    def set_grammar_check_enabled(self, enabled: bool):
        """Enable or disable grammar checking (backward compatibility)."""
        mode = CheckMode.ON_DEMAND if enabled else CheckMode.OFF
        self.set_grammar_mode(mode)
        self.grammar_check_toggled.emit(enabled)

    def set_overuse_check_enabled(self, enabled: bool):
        """Enable or disable overuse detection (backward compatibility)."""
        mode = CheckMode.ON_DEMAND if enabled else CheckMode.OFF
        self.set_overuse_mode(mode)
        self.overuse_check_toggled.emit(enabled)

    def is_spell_check_enabled(self) -> bool:
        """Check if spell checking is enabled (not OFF)."""
        return self.get_spell_mode() != CheckMode.OFF

    def is_grammar_check_enabled(self) -> bool:
        """Check if grammar checking is enabled (not OFF)."""
        return self.get_grammar_mode() != CheckMode.OFF

    def is_overuse_check_enabled(self) -> bool:
        """Check if overuse detection is enabled (not OFF)."""
        return self.get_overuse_mode() != CheckMode.OFF

    def apply_heading(self, level: str):
        """Apply heading style to current block using Markdown prefixes.

        Args:
            level: One of "Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4"
        """
        cursor = self.textCursor()

        # Select entire block
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)

        current_line = cursor.selectedText()

        # Convert level name to MarkdownStyle
        md_style = STYLE_NAMES.get(level, MarkdownStyle.NORMAL)

        # Apply the Markdown heading prefix
        new_line = apply_heading_to_line(current_line, md_style)

        # Replace the line content
        cursor.insertText(new_line)

        # Move cursor to end of the new line
        self.setTextCursor(cursor)

    def get_current_heading(self) -> str:
        """Get the heading level of the current block by detecting Markdown prefix."""
        cursor = self.textCursor()
        block = cursor.block()
        line_text = block.text()

        # Detect heading from Markdown prefix
        md_style, _ = get_line_style(line_text)
        return STYLE_TO_NAME.get(md_style, "Normal")

    def get_block_heading_level(self, block) -> HeadingLevel:
        """Get the heading level of a specific block by detecting Markdown prefix."""
        line_text = block.text()
        md_style, _ = get_line_style(line_text)

        # Map MarkdownStyle to HeadingLevel
        style_to_level = {
            MarkdownStyle.NORMAL: HeadingLevel.NORMAL,
            MarkdownStyle.TITLE: HeadingLevel.TITLE,
            MarkdownStyle.HEADING_1: HeadingLevel.HEADING_1,
            MarkdownStyle.HEADING_2: HeadingLevel.HEADING_2,
            MarkdownStyle.HEADING_3: HeadingLevel.HEADING_3,
            MarkdownStyle.HEADING_4: HeadingLevel.HEADING_4,
        }
        return style_to_level.get(md_style, HeadingLevel.NORMAL)

    def add_flag_section(self, menu, position) -> bool:
        """The flagged word's part of a right-click menu (its fixes, Ask,
        Ignore, …), added to ``menu``. True when the click was on a flag.
        Used by this menu and by the Write tab's (D.1)."""
        # Get cursor position for error detection
        click_cursor = self.cursorForPosition(position)
        block = click_cursor.block()
        block_number = block.blockNumber()
        position_in_block = click_cursor.positionInBlock()

        # Check for any writing error at click position
        error = self.writing_highlighter.get_error_at(block_number, position_in_block)

        if error:
            # Create error-specific menu section
            type_names = {
                ErrorType.SPELLING: "Spelling",
                ErrorType.GRAMMAR: "Grammar",
                ErrorType.OVERUSE: "Overused Word",
                ErrorType.OVERUSED_PHRASE: "Repeated Phrase",
                ErrorType.STYLE: "Style",
            }
            type_name = type_names.get(error.error_type, "Error")

            # Header showing error type and word
            header_label = QLabel(f"<b>{type_name}:</b> {error.word}")
            header_label.setStyleSheet("padding: 5px; background-color: #f0f0f0;")
            header_action = QWidgetAction(self)
            header_action.setDefaultWidget(header_label)
            menu.addAction(header_action)

            # Reason
            reason_label = QLabel(f"<i>{error.reason}</i>")
            reason_label.setWordWrap(True)
            reason_label.setMaximumWidth(300)
            reason_label.setStyleSheet("padding: 5px; color: #666;")
            reason_action = QWidgetAction(self)
            reason_action.setDefaultWidget(reason_label)
            menu.addAction(reason_action)

            menu.addSeparator()

            # Suggestions as clickable menu items. Replace the flagged
            # span exactly (multi-word issues like "could of" / "in order
            # to" would lose words with a word-under-cursor selection).
            if error.suggestions:
                suggestions_label = menu.addAction("Replace with:")
                suggestions_label.setEnabled(False)
                span_start, span_end = error.replace_span or (error.start, error.end)
                span_cursor = QTextCursor(block)
                span_cursor.setPosition(block.position() + span_start)
                span_cursor.setPosition(block.position() + span_end,
                                        QTextCursor.MoveMode.KeepAnchor)
                replaced = block.text()[span_start:span_end] or error.word
                for suggestion in error.suggestions[:7]:
                    label = f"  {suggestion}" if suggestion else f"  Delete “{replaced}”"
                    action = menu.addAction(label)
                    action.triggered.connect(
                        lambda checked, s=suggestion, c=QTextCursor(span_cursor), e=error:
                            self._apply_fix(c, s, e)
                    )
                from src.ui import fix_all; fix_all.add_to_menu(self, menu, error)   # 3.4

                menu.addSeparator()

            if error.error_type == ErrorType.OVERUSE and error.replace_span and not error.suggestions:
                menu.addAction(f"Part of a set phrase — try ✨ Suggest in context").setEnabled(False)
            menu.addAction("💬 Ask about this…").triggered.connect(
                lambda checked=False, e=error, b=block: self.ask_about(b, e))
            if error.error_type in (ErrorType.OVERUSE, ErrorType.OVERUSED_PHRASE):
                in_context = menu.addAction("✨ Suggest in context…")
                in_context.setToolTip("Words that fit this sentence, and rewrites that avoid "
                                      "the word — one quick AI call.")
                in_context.triggered.connect(
                    lambda checked=False, e=error, b=block: self.suggest_in_context(b, e))
                menu.addSeparator()

            if error.error_type == ErrorType.STYLE:
                rewrite = menu.addAction("✨ Rewrite with AI…")
                rewrite.triggered.connect(
                    lambda checked=False, e=error, b=block: self._request_style_rewrite(b, e))
                ignore_style = menu.addAction("Ignore this issue")
                ignore_style.triggered.connect(
                    lambda checked=False, e=error: self.writing_highlighter.ignore_style_issue(
                        getattr(e, "style_kind", ""), e.word))
                menu.addSeparator()

            # A repeated phrase under an overused word: its fixes in a submenu.
            phrase = (self.writing_highlighter.phrase_error_at(block_number, position_in_block)
                      if error.error_type != ErrorType.OVERUSED_PHRASE else None)
            if phrase is not None:
                self._add_phrase_submenu(menu, block, block_number, phrase)

            # Ignore option
            ignore_action = menu.addAction(f"Ignore '{error.word}'")
            ignore_action.setVisible(error.error_type != ErrorType.STYLE)
            ignore_action.triggered.connect(
                lambda: self._ignore_error(block_number, error.start, error.word, error.error_type)
            )

            # Add to dictionary (for spelling errors)
            if error.error_type == ErrorType.SPELLING:
                add_dict_action = menu.addAction(f"Add '{error.word}' to Dictionary")
                add_dict_action.triggered.connect(lambda: self._add_to_dictionary(error.word))

            menu.addSeparator()
        return error is not None

    def _show_context_menu(self, position):
        """Show custom context menu with error handling options."""
        menu = QMenu(self)
        self.add_flag_section(menu, position)

        # Standard edit actions
        undo_action = QAction("Undo", self)
        undo_action.triggered.connect(self.undo)
        undo_action.setEnabled(self.document().isUndoAvailable())
        menu.addAction(undo_action)

        redo_action = QAction("Redo", self)
        redo_action.triggered.connect(self.redo)
        redo_action.setEnabled(self.document().isRedoAvailable())
        menu.addAction(redo_action)

        menu.addSeparator()

        cut_action = QAction("Cut", self)
        cut_action.triggered.connect(self.cut)
        cut_action.setEnabled(self.textCursor().hasSelection())
        menu.addAction(cut_action)

        copy_action = QAction("Copy", self)
        copy_action.triggered.connect(self.copy)
        copy_action.setEnabled(self.textCursor().hasSelection())
        menu.addAction(copy_action)

        paste_action = QAction("Paste", self)
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)

        menu.addSeparator()

        # Heading submenu
        heading_menu = menu.addMenu("Heading Style")
        for level in self.HEADING_STYLES.keys():
            action = heading_menu.addAction(level)
            action.triggered.connect(lambda checked, l=level: self.apply_heading(l))

        menu.addSeparator()

        # Context lookup menu
        cursor = self.textCursor()
        selected_text = cursor.selectedText()

        lookup_menu = menu.addMenu("Look Up Context")

        if selected_text:
            # Lookup selected text
            lookup_selected = QAction(f'Look Up "{selected_text[:30]}..."', self)
            lookup_selected.triggered.connect(lambda: self._lookup_selected_text(selected_text))
            lookup_menu.addAction(lookup_selected)
            lookup_menu.addSeparator()

        # Character lookup
        character_action = QAction("Character Reference", self)
        character_action.triggered.connect(self._lookup_character)
        lookup_menu.addAction(character_action)

        # Worldbuilding lookup
        worldbuilding_action = QAction("Worldbuilding Reference", self)
        worldbuilding_action.triggered.connect(self._lookup_worldbuilding)
        lookup_menu.addAction(worldbuilding_action)

        # Plot lookup
        plot_action = QAction("Plot Reference", self)
        plot_action.triggered.connect(self._lookup_plot)
        lookup_menu.addAction(plot_action)

        # Text-to-Speech menu
        if self.is_tts_available():
            menu.addSeparator()
            tts_menu = menu.addMenu("Read Aloud")

            # Read selection
            if selected_text:
                read_selection = QAction(f'Read Selection', self)
                read_selection.triggered.connect(self.speak_selection)
                tts_menu.addAction(read_selection)

            # Read from cursor
            read_from_cursor = QAction("Read from Cursor", self)
            read_from_cursor.triggered.connect(self.speak_from_cursor)
            tts_menu.addAction(read_from_cursor)

            # Read entire document
            read_all = QAction("Read Entire Document", self)
            read_all.triggered.connect(self.speak_document)
            tts_menu.addAction(read_all)

            tts_menu.addSeparator()

            # Stop if currently speaking
            if self.is_tts_speaking():
                stop_action = QAction("Stop Reading", self)
                stop_action.triggered.connect(self.stop_speaking)
                tts_menu.addAction(stop_action)

            # TTS Settings
            settings_action = QAction("Voice Settings...", self)
            settings_action.triggered.connect(self.show_tts_settings_dialog)
            tts_menu.addAction(settings_action)

            tts_menu.addSeparator()

            # Generate TTS Document
            if selected_text:
                gen_selection = QAction("Generate TTS Doc from Selection...", self)
                gen_selection.triggered.connect(lambda: self.show_tts_document_generator(selected_text))
                tts_menu.addAction(gen_selection)

            gen_all = QAction("Generate TTS Doc from Document...", self)
            gen_all.triggered.connect(lambda: self.show_tts_document_generator())
            tts_menu.addAction(gen_all)

        menu.exec(self.mapToGlobal(position))

    def _replace_word(self, cursor: QTextCursor, replacement: str):
        """Replace the selected span with ``replacement`` ("" deletes it,
        tidying the double space a deletion leaves behind)."""
        if replacement == "" and cursor.hasSelection():
            # Deleting a word: take one neighbouring space with it.
            doc = self.document()
            st, en = cursor.selectionStart(), cursor.selectionEnd()
            if st > 0 and doc.characterAt(st - 1) == " ":
                st -= 1
            elif doc.characterAt(en) == " ":
                en += 1
            cursor.setPosition(st)
            cursor.setPosition(en, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)

    def _add_phrase_submenu(self, menu, block, block_number: int, phrase) -> None:
        sub = menu.addMenu(f"Repeated phrase: “{phrase.word}”")
        sub.addAction(phrase.reason).setEnabled(False)
        if phrase.suggestions:
            start, end = phrase.replace_span or (phrase.start, phrase.end)
            span = QTextCursor(block)
            span.setPosition(block.position() + start)
            span.setPosition(block.position() + end, QTextCursor.MoveMode.KeepAnchor)
            replaced = block.text()[start:end]
            for s in phrase.suggestions[:7]:
                label = f"  {s}" if s else f"  Delete “{replaced}”"
                sub.addAction(label).triggered.connect(
                    lambda checked=False, t=s, c=QTextCursor(span): self._replace_word(c, t))
        sub.addAction("✨ Suggest in context…").triggered.connect(
            lambda checked=False, e=phrase, b=block: self.suggest_in_context(b, e))
        sub.addAction(f"Ignore this phrase").triggered.connect(
            lambda checked=False: self._ignore_error(block_number, phrase.start, phrase.word,
                                                     phrase.error_type))
        menu.addSeparator()

    # ── Context-aware suggestions for overused words ──────────────

    _ASK_CATEGORIES = {ErrorType.SPELLING: "spelling", ErrorType.GRAMMAR: "grammar",
                       ErrorType.STYLE: "style", ErrorType.OVERUSE: "overuse",
                       ErrorType.OVERUSED_PHRASE: "overuse"}

    def ask_about(self, block, error) -> None:
        """💬 Ask: talk about this flag, get a better sentence, or mark it
        deliberate (it goes into the style sheet)."""
        self.open_ask_dialog(block.text(), block.position(), error.start, error.end,
                             self._ASK_CATEGORIES.get(error.error_type, "note"), error.word,
                             error.reason, getattr(error, "style_kind", ""))

    def open_ask_dialog(self, paragraph: str, block_position: int, start: int, end: int,
                        category: str, word: str, reason: str, kind: str = "") -> None:
        from src.ai.passage_critique import py_to_qt_index
        from src.ui.flag_chat_dialog import FlagChatDialog

        def replace(sentence: str, new_text: str) -> bool:
            block = self.document().findBlock(block_position)
            if not block.isValid() or block.text() != paragraph:
                return False
            at = paragraph.find(sentence)
            if at < 0:
                return False
            cursor = QTextCursor(self.document())
            cursor.setPosition(block_position + py_to_qt_index(paragraph, at))
            cursor.setPosition(block_position + py_to_qt_index(paragraph, at + len(sentence)),
                               QTextCursor.MoveMode.KeepAnchor)
            cursor.insertText(new_text)
            return True

        def rule_added(rule) -> None:
            self.refresh_style_sheet()
            self.style_sheet_changed.emit(f"Added to your style sheet: {rule.text}")

        dialog = FlagChatDialog(paragraph=paragraph, start=start, end=end, category=category,
                                word=word, reason=reason, kind=kind,
                                project=getattr(self, "_project", None),
                                on_replace=replace, on_rule=rule_added, parent=self)
        self._ask_dialog = dialog
        dialog.exec()

    def suggest_in_context(self, block, error) -> None:
        """Ask the model for words that fit this sentence (and rewrites that
        avoid the word), then offer them in a menu at the word."""
        from src.ai import word_suggest as ws
        text = block.text()
        position = block.position()
        compound = (ws.compound_around(text, error.start, error.end)
                    if error.error_type == ErrorType.OVERUSE else None)
        if compound is not None:
            # Ask about the whole set phrase ("mobile home"), not one word of it.
            import copy
            error = copy.copy(error)
            error.word, error.start, error.end = compound.phrase, compound.start, compound.end
        sentence = ws.sentence_around(text, error.start, error.end)
        if error.error_type == ErrorType.OVERUSED_PHRASE:
            from src.utils.proofing import normalize_apostrophes
            phrases = getattr(self.overuse_detector, "_cached_phrase_counts", {}) or {}
            count = phrases.get(" ".join(normalize_apostrophes(error.word.lower()).split()), 0)
        else:
            counts = getattr(self.overuse_detector, "_cached_counts", {}) or {}
            count = counts.get(error.word.lower(), 0)
        cached = ws.cached(error.word, sentence.text)
        if cached is not None:
            self._show_context_suggestions(block, text, position, error, sentence, cached)
            return
        rect = self.cursorRect(self._cursor_at(position + error.start))
        from PyQt6.QtWidgets import QToolTip
        QToolTip.showText(self.viewport().mapToGlobal(rect.bottomLeft()),
                          f"Finding words that fit this sentence…", self.viewport())
        worker = _ContextSuggestWorker(error.word, sentence, count)
        worker.done.connect(
            lambda result, err, b=block, t=text, p=position, e=error, s=sentence:
                self._on_context_suggestions(b, t, p, e, s, result, err))
        _RUNNING_SUGGESTERS.add(worker)
        worker.finished.connect(lambda w=worker: _RUNNING_SUGGESTERS.discard(w))
        worker.start()

    def _cursor_at(self, pos: int) -> QTextCursor:
        c = QTextCursor(self.document())
        c.setPosition(max(0, min(pos, self.document().characterCount() - 1)))
        return c

    def _on_context_suggestions(self, block, text, position, error, sentence, result, err):
        try:
            from PyQt6.QtWidgets import QToolTip
            QToolTip.hideText()
            if result is None:
                QMessageBox.information(self, "Suggest in context", err or "No suggestions.")
                return
            self._show_context_suggestions(block, text, position, error, sentence, result)
        except Exception as e:              # an exception escaping a slot aborts PyQt6
            print(f"[overuse] could not show suggestions: {e}")

    def _show_context_suggestions(self, block, text, position, error, sentence, result) -> None:
        if not block.isValid() or block.text() != text:
            QMessageBox.information(self, "Suggest in context",
                                    "The paragraph changed — right-click the word again.")
            return
        from src.ai.passage_critique import py_to_qt_index
        menu = QMenu(self)
        words = result.words
        if self.overuse_detector:
            counts = getattr(self.overuse_detector, "_cached_counts", {}) or {}
            threshold = getattr(self.overuse_detector, "threshold", 3)
            words = [w for w in words if counts.get(w.lower(), 0) < threshold]
        if words:
            menu.addAction(f"Instead of “{error.word}”:").setEnabled(False)
            span = QTextCursor(self.document())
            span.setPosition(position + py_to_qt_index(text, error.start))
            span.setPosition(position + py_to_qt_index(text, error.end),
                             QTextCursor.MoveMode.KeepAnchor)
            for w in words:
                menu.addAction(f"  {w}").triggered.connect(
                    lambda checked=False, s=w, c=QTextCursor(span): self._replace_word(c, s))
        if result.rewrites:
            if words:
                menu.addSeparator()
            menu.addAction("Rewrite the sentence:").setEnabled(False)
            whole = QTextCursor(self.document())
            whole.setPosition(position + py_to_qt_index(text, sentence.start))
            whole.setPosition(position + py_to_qt_index(text, sentence.end),
                              QTextCursor.MoveMode.KeepAnchor)
            for r in result.rewrites:
                label = r if len(r) <= 90 else r[:89] + "…"
                menu.addAction(f"  {label}").triggered.connect(
                    lambda checked=False, s=r, c=QTextCursor(whole): self._replace_word(c, s))
        if not words and not result.rewrites:
            menu.addAction("No suggestions that fit — try Rephrase.").setEnabled(False)
        rect = self.cursorRect(self._cursor_at(position + py_to_qt_index(text, error.start)))
        self._context_menu = menu
        menu.popup(self.viewport().mapToGlobal(rect.bottomLeft()))

    def _request_style_rewrite(self, block, error) -> None:
        """Ask the host to AI-rewrite the sentence around a style issue."""
        from src.utils.style_checks import sentences_with_offsets, KINDS
        start, end = error.start, error.end
        for s0, e0, _ in sentences_with_offsets(block.text()):
            if s0 <= error.start < e0:
                start, end = min(start, s0), max(end, e0)
                break
        kind = getattr(error, "style_kind", "")
        hint = f"Fix this style issue: {error.reason}"
        if kind and kind in KINDS:
            hint = f"Fix the {KINDS[kind][0].lower()}: {error.reason.split(': ', 1)[-1]}"
        self.style_rewrite_requested.emit(block.position() + start, block.position() + end, hint)

    # Set by the host to persist "Add to Dictionary" (e.g. into the
    # project's dictionary so the word stays known next session).
    add_to_dictionary_callback: Optional[Callable[[str], None]] = None

    def _add_to_dictionary(self, word: str):
        """Add word to custom dictionary."""
        self.spell_checker.add_word(word)
        if self.add_to_dictionary_callback:
            try:
                self.add_to_dictionary_callback(word)
            except Exception as e:
                print(f"[spell] could not save '{word}' to the project dictionary: {e}")
        self.writing_highlighter.rehighlight()

    def _ignore_error(self, block_number: int, start: int, word: str, error_type: ErrorType):
        """Ignore a specific error."""
        self.writing_highlighter.ignore_error(block_number, start, word, error_type)
        if error_type in (ErrorType.SPELLING, ErrorType.OVERUSE):
            self._learn("ignore_word", word)

        # For overuse errors, also ignore the word in the overuse detector
        if error_type == ErrorType.OVERUSE:
            self.overuse_detector.ignore_word(word)

    def _lookup_selected_text(self, text: str):
        """Look up context for selected text."""
        if self.lookup_context_callback:
            result = self.lookup_context_callback(text)
            dialog = ContextLookupDialog(f"Context for: {text}", result, self)
            dialog.exec()

    def _lookup_character(self):
        """Look up character reference."""
        if not self.get_character_list_callback:
            QMessageBox.information(self, "Not Available", "Character lookup not configured.")
            return

        characters = self.get_character_list_callback()
        if not characters:
            QMessageBox.information(self, "No Characters", "No characters defined in your project yet.")
            return

        dialog = QuickReferenceDialog(characters, "Character", self)
        if dialog.exec() and dialog.selected_item:
            if self.lookup_characters_callback:
                result = self.lookup_characters_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Character: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_worldbuilding(self):
        """Look up worldbuilding reference."""
        if not self.get_worldbuilding_sections_callback:
            QMessageBox.information(self, "Not Available", "Worldbuilding lookup not configured.")
            return

        sections = self.get_worldbuilding_sections_callback()
        if not sections:
            QMessageBox.information(self, "No Worldbuilding", "No worldbuilding sections defined yet.")
            return

        dialog = QuickReferenceDialog(sections, "Worldbuilding Section", self)
        if dialog.exec() and dialog.selected_item:
            if self.lookup_worldbuilding_callback:
                result = self.lookup_worldbuilding_callback(dialog.selected_item)
                ref_dialog = ContextLookupDialog(f"Worldbuilding: {dialog.selected_item}", result, self)
                ref_dialog.exec()

    def _lookup_plot(self):
        """Look up plot reference."""
        if self.lookup_plot_callback:
            result = self.lookup_plot_callback()
            dialog = ContextLookupDialog("Plot Reference", result, self)
            dialog.exec()

    def import_from_docx(self, file_path: str) -> bool:
        """Replace the text with a Word document's, as the editor's Markdown
        (italics, bold and headings kept: ``docx_import``). One undo step
        puts the old text back (9.2: it used to clear the undo history)."""
        try:
            from src.export.docx_import import docx_to_markdown
            text = docx_to_markdown(file_path)
        except Exception as e:
            print(f"Error importing Word document: {e}")
            return False
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        return True

    def export_to_docx(self, file_path: str, title: str = "") -> bool:
        """Export content to Word document with full formatting preservation.

        Properly exports heading styles so they appear in Word's navigation pane
        and can be used for table of contents generation.
        """
        try:
            doc = Document()

            # Add title if provided (as document title, not heading)
            if title:
                doc.add_heading(title, 0)

            # Parse document block by block
            block = self.document().begin()

            while block.isValid():
                block_text = block.text()

                if not block_text.strip():
                    # Empty paragraph
                    doc.add_paragraph("")
                    block = block.next()
                    continue

                # Get heading level and content from Markdown
                md_style, content = get_line_style(block_text)
                heading_level = self.get_block_heading_level(block)

                # Map heading levels to Word heading styles
                if heading_level == HeadingLevel.TITLE:
                    doc.add_heading(content, 0)  # Title style
                elif heading_level == HeadingLevel.HEADING_1:
                    doc.add_heading(content, 1)
                elif heading_level == HeadingLevel.HEADING_2:
                    doc.add_heading(content, 2)
                elif heading_level == HeadingLevel.HEADING_3:
                    doc.add_heading(content, 3)
                elif heading_level == HeadingLevel.HEADING_4:
                    doc.add_heading(content, 4)
                else:
                    # Regular paragraph - process Markdown inline formatting
                    para = doc.add_paragraph()
                    self._add_markdown_runs_to_paragraph(para, block_text)

                block = block.next()

            doc.save(file_path)
            return True

        except Exception as e:
            print(f"Error exporting to Word: {e}")
            return False

    def _add_markdown_runs_to_paragraph(self, para, text: str):
        """Parse Markdown inline formatting and add runs to a Word paragraph.

        Handles **bold**, *italic*, ***bold italic***, and plain text
        (the parsing is shared: ``markdown_editor.inline_runs``).
        """
        from src.utils.markdown_editor import inline_runs
        for chunk, bold, italic in inline_runs(text):
            run = para.add_run(chunk)
            if bold:
                run.bold = True
            if italic:
                run.italic = True

    def set_callbacks(
        self,
        lookup_worldbuilding: Optional[Callable] = None,
        lookup_characters: Optional[Callable] = None,
        lookup_plot: Optional[Callable] = None,
        lookup_context: Optional[Callable] = None,
        get_character_list: Optional[Callable] = None,
        get_worldbuilding_sections: Optional[Callable] = None
    ):
        """Set callback functions for context lookup."""
        self.lookup_worldbuilding_callback = lookup_worldbuilding
        self.lookup_characters_callback = lookup_characters
        self.lookup_plot_callback = lookup_plot
        self.lookup_context_callback = lookup_context
        self.get_character_list_callback = get_character_list
        self.get_worldbuilding_sections_callback = get_worldbuilding_sections

    # ==================== Text-to-Speech Methods ====================

    def _init_tts(self):
        """Initialize TTS service."""
        try:
            self._tts_service = get_tts_service()
            self._tts_service.set_callbacks(
                on_start=self._on_tts_start,
                on_end=self._on_tts_end,
                on_error=self._on_tts_error,
                on_progress=self._on_tts_progress
            )
            # Apply saved TTS settings
            self._apply_tts_settings()
        except Exception as e:
            print(f"Failed to initialize TTS: {e}")
            self._tts_available = False

    def _apply_tts_settings(self):
        """Apply TTS settings from config."""
        try:
            from src.config.ai_config import get_ai_config
            config = get_ai_config()
            settings = config.settings

            # Apply speech rate (default 150 WPM - normal pace)
            rate = settings.get("tts_rate", 150)
            self._tts_service.set_rate(rate)

            # Apply volume
            volume = settings.get("tts_volume", 1.0)
            self._tts_service.set_volume(volume)

            # Apply engine preference
            engine_name = settings.get("tts_engine", "system")
            try:
                engine_map = {
                    "vibevoice": TTSEngine.VIBEVOICE,
                    "edge": TTSEngine.EDGE,
                    "chatterbox": TTSEngine.CHATTERBOX,
                    "kokoro": TTSEngine.KOKORO,
                    "system": TTSEngine.SYSTEM,
                }
                engine = engine_map.get(engine_name, TTSEngine.SYSTEM)
                self._tts_service.set_engine(engine)
            except ValueError:
                pass

            # Apply voice: explicit voice setting takes priority, but only
            # if it's valid for the current engine. Otherwise fall back to
            # genre-based voice, then engine default.
            voice = settings.get("tts_voice", "")
            genre = settings.get("tts_genre", "")

            # Validate saved voice against current engine's voice list
            voice_valid = False
            if voice and voice != "default":
                try:
                    available_ids = {v.id for v in self._tts_service.get_voices()}
                    voice_valid = voice in available_ids
                except Exception:
                    voice_valid = True  # Assume valid if we can't check

            if voice == "default":
                # "System Default" — clear any explicit voice
                self._tts_service.set_voice(None)
            elif voice and voice_valid:
                self._tts_service.set_voice(voice)
            elif genre and engine_name:
                try:
                    from src.services.tts_service import get_genre_voice
                    voice_id = get_genre_voice(genre, engine_name)
                    if voice_id and voice_id != "default":
                        self._tts_service.set_voice(voice_id)
                    else:
                        self._tts_service.set_voice(None)
                except Exception:
                    self._tts_service.set_voice(None)
            else:
                # No voice or genre set — use engine default
                self._tts_service.set_voice(None)

            # Apply VibeVoice settings if configured
            vv_path = settings.get("vibevoice_path", "")
            if vv_path:
                self._tts_service.set_vibevoice_path(vv_path)

            vv_model = settings.get("vibevoice_model", "1.5B")
            self._tts_service.set_vibevoice_model(vv_model)

            vv_voice = settings.get("vibevoice_voice", "emma")
            self._tts_service.set_vibevoice_voice(vv_voice)

        except Exception as e:
            print(f"Failed to apply TTS settings: {e}")

    def _on_tts_start(self):
        """Handle TTS start event (called from background thread)."""
        # Use QTimer.singleShot to safely emit from main thread
        QTimer.singleShot(0, self.tts_started.emit)

    def _on_tts_end(self):
        """Handle TTS end event (called from background thread)."""
        # Use QTimer.singleShot to safely emit from main thread
        QTimer.singleShot(0, self.tts_stopped.emit)

    def _on_tts_error(self, error: str):
        """Handle TTS error event (called from background thread)."""
        # Use QTimer.singleShot to safely emit from main thread
        QTimer.singleShot(0, lambda: self.tts_error.emit(error))

    def _on_tts_progress(self, message: str):
        """Handle TTS progress update (for VibeVoice, called from background thread)."""
        # Use QTimer.singleShot to safely emit from main thread
        QTimer.singleShot(0, lambda: self.tts_progress.emit(message))

    def is_tts_available(self) -> bool:
        """Check if TTS is available."""
        return self._tts_available and self._tts_service is not None

    def is_tts_speaking(self) -> bool:
        """Check if TTS is currently speaking."""
        if self._tts_service:
            return self._tts_service.is_speaking
        return False

    def is_tts_paused(self) -> bool:
        """Check if TTS is currently paused."""
        if self._tts_service:
            return self._tts_service.is_paused
        return False

    def pause_speaking(self):
        """Pause TTS playback (can be resumed)."""
        if self._tts_service:
            return self._tts_service.pause()
        return False

    def resume_speaking(self):
        """Resume TTS playback after pause."""
        if self._tts_service:
            return self._tts_service.resume()
        return False

    def speak_text(self, text: str = None):
        """Speak text using TTS.

        Args:
            text: Text to speak. If None, speaks selected text or entire document.

        If playback is already running or paused, this call is refused
        (returns without starting new speech). Use stop_speaking() first
        if you need to interrupt.
        """
        if not self.is_tts_available():
            QMessageBox.warning(
                self,
                "TTS Not Available",
                "Text-to-Speech is not available.\n\n"
                "Install with: pip install pyttsx3 edge-tts"
            )
            return

        # One reading at a time. If audio is actively PLAYING, refuse —
        # the caller must pause or stop first, so we never read over an
        # ongoing reading. If it's PAUSED, a new reading is allowed:
        # abandon the paused one first (stop() releases its thread /
        # audio process) so the old action doesn't linger in memory.
        if self._tts_service.is_speaking:
            if self._tts_service.is_paused:
                self._tts_service.stop()
            else:
                QMessageBox.information(
                    self, "Already Reading",
                    "Audio is currently playing. Pause or stop it "
                    "before starting a new reading.")
                return

        # Re-apply settings so engine/voice changes take effect immediately
        self._apply_tts_settings()

        if text is None:
            # Use selected text or entire document
            cursor = self.textCursor()
            if cursor.hasSelection():
                text = cursor.selectedText()
                # Replace paragraph separators with newlines
                text = text.replace('\u2029', '\n')
            else:
                text = self.toPlainText()

        if not text.strip():
            QMessageBox.information(self, "Nothing to Speak", "No text to read aloud.")
            return

        # Strip Markdown formatting before speaking
        clean_text = strip_markdown(text)

        # Optional: AI enhancement for more natural prosody (adds pauses,
        # expands abbreviations). Controlled by the tts_ai_enhance setting.
        try:
            from src.config.ai_config import get_ai_config
            settings = get_ai_config().settings
            if settings.get("tts_ai_enhance", False):
                from src.services.tts_service import enhance_text_for_speech
                genre = settings.get("tts_genre", "")
                clean_text = enhance_text_for_speech(clean_text, genre)
        except Exception:
            pass

        self._tts_service.speak(clean_text)

    def speak_selection(self):
        """Speak the currently selected text."""
        # Stop any ongoing playback first
        if self._tts_service and self._tts_service.is_speaking:
            self._tts_service.stop()

        cursor = self.textCursor()
        if cursor.hasSelection():
            text = cursor.selectedText().replace('\u2029', '\n')
            if text.strip():
                # Strip Markdown formatting before speaking
                clean_text = strip_markdown(text)
                self._tts_service.speak(clean_text)
            else:
                QMessageBox.information(self, "Nothing Selected", "Please select some text to read aloud.")
        else:
            QMessageBox.information(self, "Nothing Selected", "Please select some text to read aloud.")

    def speak_document(self):
        """Speak the entire document."""
        if self._tts_service and self._tts_service.is_speaking:
            state = "paused" if self._tts_service.is_paused else "playing"
            QMessageBox.information(
                self, "Already Reading",
                f"Audio is currently {state}. "
                f"Stop the current playback before starting a new one.")
            return
        self._apply_tts_settings()

        text = self.toPlainText()
        if text.strip():
            # Strip Markdown formatting before speaking
            clean_text = strip_markdown(text)
            self._tts_service.speak(clean_text)
        else:
            QMessageBox.information(self, "Empty Document", "The document is empty.")

    def speak_from_cursor(self):
        """Speak from cursor position to end of document."""
        if self._tts_service and self._tts_service.is_speaking:
            state = "paused" if self._tts_service.is_paused else "playing"
            QMessageBox.information(
                self, "Already Reading",
                f"Audio is currently {state}. "
                f"Stop the current playback before starting a new one.")
            return
        self._apply_tts_settings()

        cursor = self.textCursor()
        position = cursor.position()
        full_text = self.toPlainText()
        text = full_text[position:]
        if text.strip():
            # Strip Markdown formatting before speaking
            clean_text = strip_markdown(text)
            self._tts_service.speak(clean_text)
        else:
            QMessageBox.information(self, "Nothing to Speak", "No text after cursor position.")

    def stop_speaking(self):
        """Stop TTS playback."""
        if self._tts_service:
            self._tts_service.stop()

    def get_tts_voices(self) -> List:
        """Get available TTS voices."""
        if self._tts_service:
            return self._tts_service.get_voices()
        return []

    def set_tts_voice(self, voice_id: str):
        """Set the TTS voice."""
        if self._tts_service:
            self._tts_service.set_voice(voice_id)

    def set_tts_rate(self, rate: int):
        """Set TTS speech rate."""
        if self._tts_service:
            self._tts_service.set_rate(rate)

    def set_tts_volume(self, volume: float):
        """Set TTS volume (0.0 to 1.0)."""
        if self._tts_service:
            self._tts_service.set_volume(volume)

    def set_tts_engine(self, engine_name: str):
        """Set TTS engine by name."""
        if self._tts_service:
            try:
                engine_map = {
                    "system": TTSEngine.SYSTEM,
                    "edge": TTSEngine.EDGE,
                    "vibevoice": TTSEngine.VIBEVOICE,
                    "chatterbox": TTSEngine.CHATTERBOX,
                    "kokoro": TTSEngine.KOKORO,
                }
                engine = engine_map.get(engine_name, TTSEngine.SYSTEM)
                self._tts_service.set_engine(engine)
            except ValueError as e:
                QMessageBox.warning(self, "Engine Not Available", str(e))

    def save_speech_to_file(self, output_path: str, text: str = None) -> bool:
        """Save speech to an audio file.

        Args:
            output_path: Path to save the audio file
            text: Text to convert. If None, uses selected text or entire document.

        Returns:
            True if successful
        """
        if not self.is_tts_available():
            return False

        if text is None:
            cursor = self.textCursor()
            if cursor.hasSelection():
                text = cursor.selectedText().replace('\u2029', '\n')
            else:
                text = self.toPlainText()

        if not text.strip():
            return False

        return self._tts_service.speak_to_file(text, output_path)

    def show_tts_settings_dialog(self):
        """Show TTS settings dialog."""
        if not self.is_tts_available():
            QMessageBox.warning(
                self,
                "TTS Not Available",
                "Text-to-Speech is not available.\n\n"
                "Install with: pip install pyttsx3 edge-tts"
            )
            return

        dialog = TTSSettingsDialog(self._tts_service, self)
        dialog.exec()

    def show_tts_document_generator(self, text: str = None):
        """Show dialog to generate TTS document.

        Args:
            text: Text to convert. If None, uses entire document.
        """
        if not self.is_tts_available():
            QMessageBox.warning(
                self,
                "TTS Not Available",
                "Text-to-Speech is not available.\n\n"
                "Install with: pip install pyttsx3 edge-tts"
            )
            return

        if text is None:
            text = self.toPlainText()

        if not text.strip():
            QMessageBox.information(self, "No Text", "No text to generate TTS document from.")
            return

        # Strip Markdown formatting before generating TTS document
        clean_text = strip_markdown(text)

        # Get chapter name from parent if available
        chapter_name = "chapter"
        if hasattr(self, 'chapter_name'):
            chapter_name = self.chapter_name
        elif hasattr(self.parent(), 'get_current_chapter_name'):
            chapter_name = self.parent().get_current_chapter_name() or "chapter"

        dialog = TTSDocumentGeneratorDialog(clean_text, chapter_name, self)
        dialog.exec()


class TTSSettingsDialog(QDialog):
    """Dialog for configuring TTS settings."""

    def __init__(self, tts_service, parent=None):
        super().__init__(parent)
        self.tts_service = tts_service
        self.setWindowTitle("Text-to-Speech Settings")
        self.setMinimumSize(400, 350)

        layout = QVBoxLayout(self)

        # Engine selection
        engine_group = QGroupBox("TTS Engine")
        engine_layout = QVBoxLayout(engine_group)

        self.engine_combo = QComboBox()
        engines = tts_service.get_available_engines()
        for engine in engines:
            if engine.value == "system":
                label = "System Voices (Offline)"
            elif engine.value == "vibevoice":
                label = "VibeVoice (High Quality Local Neural)"
            else:
                label = "Edge Neural Voices (Online)"
            self.engine_combo.addItem(label, engine.value)
        self.engine_combo.currentIndexChanged.connect(self._on_engine_changed)
        engine_layout.addWidget(self.engine_combo)

        engine_note = QLabel(
            "System: Uses installed OS voices, works offline\n"
            "Edge: High-quality Microsoft neural voices, requires internet\n"
            "VibeVoice: Best quality local TTS (requires installation)"
        )
        engine_note.setStyleSheet("color: #6b7280; font-size: 10px;")
        engine_note.setWordWrap(True)
        engine_layout.addWidget(engine_note)

        layout.addWidget(engine_group)

        # Voice selection
        voice_group = QGroupBox("Voice")
        voice_layout = QVBoxLayout(voice_group)

        self.voice_combo = QComboBox()
        self._populate_voices()
        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_layout.addWidget(self.voice_combo)

        layout.addWidget(voice_group)

        # Rate control
        rate_group = QGroupBox("Speech Rate")
        rate_layout = QHBoxLayout(rate_group)

        self.rate_slider = QSlider(Qt.Orientation.Horizontal)
        self.rate_slider.setRange(50, 300)
        self.rate_slider.setValue(150)
        self.rate_slider.valueChanged.connect(self._on_rate_changed)
        rate_layout.addWidget(self.rate_slider)

        self.rate_label = QLabel("150 wpm")
        self.rate_label.setMinimumWidth(60)
        rate_layout.addWidget(self.rate_label)

        layout.addWidget(rate_group)

        # Volume control
        volume_group = QGroupBox("Volume")
        volume_layout = QHBoxLayout(volume_group)

        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)
        volume_layout.addWidget(self.volume_slider)

        self.volume_label = QLabel("100%")
        self.volume_label.setMinimumWidth(40)
        volume_layout.addWidget(self.volume_label)

        layout.addWidget(volume_group)

        # Inter-paragraph pause — splits text on blank lines and
        # inserts real silence between chunks. Works with every
        # engine because each engine's per-chunk synth blocks until
        # audio finishes; we just sleep between calls. 0 disables
        # the split and uses the legacy single-shot path. 700 ms is
        # roughly a natural breath between paragraphs.
        from PyQt6.QtWidgets import QSpinBox
        pause_group = QGroupBox("Inter-paragraph pause")
        pause_layout = QHBoxLayout(pause_group)
        self.pause_spin = QSpinBox()
        self.pause_spin.setRange(0, 5000)
        self.pause_spin.setSingleStep(100)
        self.pause_spin.setSuffix(" ms")
        self.pause_spin.setValue(int(
            self.tts_service.get_paragraph_pause_ms()
            if hasattr(self.tts_service, "get_paragraph_pause_ms")
            else 0))
        self.pause_spin.setToolTip(
            "Insert this much silence between paragraphs when "
            "reading aloud. Splits on blank lines and waits for "
            "each paragraph's audio to finish before pausing — "
            "works with every engine. 0 = off (engine reads the "
            "whole text in one go). 700 ms ≈ a natural breath.")
        self.pause_spin.valueChanged.connect(self._on_pause_changed)
        pause_layout.addWidget(self.pause_spin)
        pause_layout.addStretch()
        layout.addWidget(pause_group)

        # Test button
        test_layout = QHBoxLayout()
        test_btn = QPushButton("Test Voice")
        test_btn.clicked.connect(self._test_voice)
        test_layout.addWidget(test_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self.tts_service.stop)
        test_layout.addWidget(stop_btn)

        test_layout.addStretch()
        layout.addLayout(test_layout)

        layout.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _populate_voices(self):
        """Populate voice combo box."""
        self.voice_combo.clear()
        voices = self.tts_service.get_voices()
        for voice in voices:
            self.voice_combo.addItem(f"{voice.name} ({voice.language})", voice.id)

    def _on_engine_changed(self, index):
        """Handle engine selection change."""
        engine_value = self.engine_combo.currentData()
        try:
            engine_map = {
                "system": TTSEngine.SYSTEM,
                "edge": TTSEngine.EDGE,
                "vibevoice": TTSEngine.VIBEVOICE,
                "chatterbox": TTSEngine.CHATTERBOX,
            }
            engine = engine_map.get(engine_value, TTSEngine.EDGE)
            self.tts_service.set_engine(engine)
            self._populate_voices()
        except ValueError as e:
            QMessageBox.warning(self, "Engine Error", str(e))

    def _on_voice_changed(self, index):
        """Handle voice selection change."""
        voice_id = self.voice_combo.currentData()
        if voice_id:
            self.tts_service.set_voice(voice_id)

    def _on_rate_changed(self, value):
        """Handle rate slider change."""
        self.rate_label.setText(f"{value} wpm")
        self.tts_service.set_rate(value)

    def _on_volume_changed(self, value):
        """Handle volume slider change."""
        self.volume_label.setText(f"{value}%")
        self.tts_service.set_volume(value / 100.0)

    def _on_pause_changed(self, value):
        """Handle inter-paragraph pause spinner change. Pushes the
        new value into the TTS service immediately; takes effect
        on the next ``speak()`` call."""
        if hasattr(self.tts_service, "set_paragraph_pause_ms"):
            self.tts_service.set_paragraph_pause_ms(int(value))

    def _test_voice(self):
        """Test the current voice. Uses a multi-paragraph sample so
        the inter-paragraph pause is audible in the test playback."""
        self.tts_service.speak(
            "Hello! This is a test of the text to speech system.\n\n"
            "I can read your writing aloud so you can hear how it "
            "sounds. If you have set a pause between paragraphs, "
            "you should notice a clear gap right about now.\n\n"
            "That gap is configurable in the inter-paragraph pause "
            "setting above."
        )


class TTSDocumentGeneratorDialog(QDialog):
    """Dialog for generating TTS documents with speaker configuration."""

    # Signal emitted when TTS document is generated
    document_generated = pyqtSignal(str)  # Path to generated file

    def __init__(self, text: str, chapter_name: str = "chapter", parent=None):
        super().__init__(parent)
        self.text = text
        self.chapter_name = chapter_name
        self.speaker_configs: List[SpeakerConfig] = []

        self.setWindowTitle("Generate TTS Document")
        self.setMinimumSize(550, 500)

        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Info header
        info_label = QLabel(
            "Generate a TTS-formatted document for text-to-speech synthesis.\n"
            "Configure speakers/voices for narrator and dialogue."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #374151; padding: 8px; background-color: #f3f4f6; border-radius: 4px;")
        layout.addWidget(info_label)

        # Format selection
        format_group = QGroupBox("Output Format")
        format_layout = QVBoxLayout(format_group)

        self.format_combo = QComboBox()
        self.format_combo.addItem("VibeVoice (Speaker N: text)", "vibevoice")
        self.format_combo.addItem("Plain Text", "plain")
        self.format_combo.addItem("SSML (Speech Synthesis Markup)", "ssml")
        format_layout.addWidget(self.format_combo)

        layout.addWidget(format_group)

        # Speaker Configuration
        speakers_group = QGroupBox("Speaker & Voice Configuration")
        speakers_layout = QVBoxLayout(speakers_group)

        # Info about voices
        voice_info = QLabel(
            "VibeVoice supports 7 distinct voices: Carter, Davis, Emma, Frank, Grace, Mike, Samuel.\n"
            "Double-click a speaker to change their name or voice."
        )
        voice_info.setWordWrap(True)
        voice_info.setStyleSheet("color: #6b7280; font-size: 11px; padding: 4px;")
        speakers_layout.addWidget(voice_info)

        # Number of speakers
        num_speakers_layout = QHBoxLayout()
        num_speakers_layout.addWidget(QLabel("Number of Speakers:"))
        self.num_speakers_combo = QComboBox()
        self.num_speakers_combo.addItems(["1 (Narrator only)", "2 (Narrator + 1 voice)", "3", "4 (Maximum)"])
        self.num_speakers_combo.setCurrentIndex(1)  # Default to 2
        self.num_speakers_combo.currentIndexChanged.connect(self._on_num_speakers_changed)
        num_speakers_layout.addWidget(self.num_speakers_combo)
        num_speakers_layout.addStretch()
        speakers_layout.addLayout(num_speakers_layout)

        # Speaker list with better formatting
        self.speaker_list = QListWidget()
        self.speaker_list.setMaximumHeight(160)
        self.speaker_list.setStyleSheet("""
            QListWidget::item {
                padding: 6px;
                border-bottom: 1px solid #e5e7eb;
            }
            QListWidget::item:selected {
                background-color: #e0e7ff;
                color: #3730a3;
            }
        """)
        self.speaker_list.itemDoubleClicked.connect(self._edit_speaker)
        speakers_layout.addWidget(self.speaker_list)

        # Edit speaker button
        edit_btn_layout = QHBoxLayout()
        edit_speaker_btn = QPushButton("Edit Selected Speaker...")
        edit_speaker_btn.clicked.connect(self._edit_speaker)
        edit_btn_layout.addWidget(edit_speaker_btn)
        edit_btn_layout.addStretch()
        speakers_layout.addLayout(edit_btn_layout)

        layout.addWidget(speakers_group)

        # Options
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        from PyQt6.QtWidgets import QCheckBox
        self.dialogue_detection_check = QCheckBox("Auto-detect dialogue (quotes)")
        self.dialogue_detection_check.setChecked(True)
        options_layout.addWidget(self.dialogue_detection_check)

        self.preserve_paragraphs_check = QCheckBox("Preserve paragraph breaks")
        self.preserve_paragraphs_check.setChecked(True)
        options_layout.addWidget(self.preserve_paragraphs_check)

        layout.addWidget(options_group)

        # Output info
        output_group = QGroupBox("Output")
        output_layout = QVBoxLayout(output_group)

        output_dir = get_tts_output_dir() if TTS_AVAILABLE else Path.home() / ".writer_platform" / "tts_output"
        self.output_label = QLabel(f"Output folder: {output_dir}")
        self.output_label.setWordWrap(True)
        self.output_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        output_layout.addWidget(self.output_label)

        safe_name = re.sub(r'[^\w\-_]', '_', self.chapter_name)
        self.filename_label = QLabel(f"Filename: {safe_name}_tts.txt")
        self.filename_label.setStyleSheet("color: #059669; font-weight: bold;")
        output_layout.addWidget(self.filename_label)

        layout.addWidget(output_group)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()

        generate_btn = QPushButton("Generate TTS Document")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                padding: 10px 20px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
        """)
        generate_btn.clicked.connect(self._generate_document)
        button_layout.addWidget(generate_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

        # Initialize speakers
        self._on_num_speakers_changed(1)

    def _on_num_speakers_changed(self, index):
        """Update speaker list when number changes."""
        num_speakers = index + 1

        # Voice display names mapping
        voice_display = {
            "carter": "Carter (Male)",
            "davis": "Davis (Male)",
            "emma": "Emma (Female)",
            "frank": "Frank (Male)",
            "grace": "Grace (Female)",
            "mike": "Mike (Male)",
            "samuel": "Samuel (Male)",
        }

        # Default voice mappings - varied for different speakers
        default_voices = [
            ("Narrator", "emma"),        # Female narrator
            ("Character 1", "carter"),   # Male character
            ("Character 2", "grace"),    # Female character
            ("Character 3", "frank"),    # Male character
        ]

        self.speaker_configs = []
        self.speaker_list.clear()

        for i in range(num_speakers):
            name, voice = default_voices[i] if i < len(default_voices) else (f"Speaker {i+1}", "emma")
            config = SpeakerConfig(
                speaker_id=i + 1,
                name=name,
                voice_id=voice,
                description=""
            )
            self.speaker_configs.append(config)
            voice_name = voice_display.get(voice, voice)
            self.speaker_list.addItem(f"Speaker {i+1}: {name} - {voice_name}")

    def _edit_speaker(self, item=None):
        """Edit the selected speaker configuration."""
        row = self.speaker_list.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select Speaker", "Please select a speaker to edit.")
            return

        config = self.speaker_configs[row]

        # Voice display names mapping
        voice_display = {
            "carter": "Carter (Male)",
            "davis": "Davis (Male)",
            "emma": "Emma (Female)",
            "frank": "Frank (Male)",
            "grace": "Grace (Female)",
            "mike": "Mike (Male)",
            "samuel": "Samuel (Male)",
        }

        # Show edit dialog
        dialog = SpeakerEditDialog(config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Update config
            config.name = dialog.name_edit.text()
            config.voice_id = dialog.voice_combo.currentData()
            self.speaker_configs[row] = config
            voice_name = voice_display.get(config.voice_id, config.voice_id)
            self.speaker_list.item(row).setText(
                f"Speaker {config.speaker_id}: {config.name} - {voice_name}"
            )

    def _generate_document(self):
        """Generate the TTS document."""
        if not TTS_AVAILABLE:
            QMessageBox.warning(self, "TTS Not Available", "TTS services are not available.")
            return

        # Build configuration
        format_value = self.format_combo.currentData()
        tts_format = TTSFormat.VIBEVOICE
        if format_value == "plain":
            tts_format = TTSFormat.PLAIN
        elif format_value == "ssml":
            tts_format = TTSFormat.SSML

        config = TTSDocumentConfig(
            format=tts_format,
            speakers=self.speaker_configs,
            default_speaker=1,
            narrator_speaker=1,
            dialogue_detection=self.dialogue_detection_check.isChecked(),
            preserve_paragraphs=self.preserve_paragraphs_check.isChecked()
        )

        # Generate document
        generator = TTSDocumentGenerator(config)
        output_dir = get_tts_output_dir()

        try:
            filepath, speakers_used = generator.generate_tts_document(
                self.text,
                output_dir,
                self.chapter_name
            )

            # Get speaker names for VibeVoice command
            speaker_names = " ".join(s.name for s in self.speaker_configs)

            QMessageBox.information(
                self,
                "TTS Document Generated",
                f"Document saved to:\n{filepath}\n\n"
                f"Speakers used: {', '.join(speakers_used)}\n\n"
                f"To use with VibeVoice:\n"
                f"python demo/inference_from_file.py \\\n"
                f"  --model_path vibevoice/VibeVoice-1.5B \\\n"
                f"  --txt_path \"{filepath}\" \\\n"
                f"  --speaker_names {speaker_names}"
            )

            self.document_generated.emit(str(filepath))
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Generation Failed", f"Failed to generate TTS document:\n{str(e)}")


class SpeakerEditDialog(QDialog):
    """Dialog for editing a speaker configuration."""

    # VibeVoice voice options with descriptions
    VIBEVOICE_VOICES = [
        ("carter", "Carter", "Male", "Deep, authoritative male voice - good for narrators"),
        ("davis", "Davis", "Male", "Warm, friendly male voice - good for dialogue"),
        ("emma", "Emma", "Female", "Clear, professional female voice - versatile"),
        ("frank", "Frank", "Male", "Mature, steady male voice - good for older characters"),
        ("grace", "Grace", "Female", "Soft, gentle female voice - good for younger characters"),
        ("mike", "Mike", "Male", "Energetic, youthful male voice - good for action"),
        ("samuel", "Samuel", "Male", "Distinguished, formal male voice - good for authority figures"),
    ]

    def __init__(self, config: 'SpeakerConfig', parent=None):
        super().__init__(parent)
        self.config = config

        self.setWindowTitle(f"Edit Speaker {config.speaker_id}")
        self.setMinimumWidth(450)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel(f"Configure Speaker {config.speaker_id}")
        header.setStyleSheet("font-size: 14px; font-weight: bold; padding: 8px;")
        layout.addWidget(header)

        # Name
        from PyQt6.QtWidgets import QFormLayout, QLineEdit
        form_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setText(config.name)
        self.name_edit.setPlaceholderText("e.g., Narrator, Alice, Bob")
        form_layout.addRow("Speaker Name:", self.name_edit)

        layout.addLayout(form_layout)

        # Voice selection group
        voice_group = QGroupBox("VibeVoice Voice Selection")
        voice_layout = QVBoxLayout(voice_group)

        # Voice combo
        self.voice_combo = QComboBox()
        for voice_id, name, gender, desc in self.VIBEVOICE_VOICES:
            self.voice_combo.addItem(f"{name} ({gender})", voice_id)

        # Set current
        for i in range(self.voice_combo.count()):
            if self.voice_combo.itemData(i) == config.voice_id:
                self.voice_combo.setCurrentIndex(i)
                break

        self.voice_combo.currentIndexChanged.connect(self._on_voice_changed)
        voice_layout.addWidget(self.voice_combo)

        # Voice description
        self.voice_desc_label = QLabel()
        self.voice_desc_label.setWordWrap(True)
        self.voice_desc_label.setStyleSheet(
            "color: #6b7280; font-size: 11px; padding: 8px; "
            "background-color: #f3f4f6; border-radius: 4px;"
        )
        voice_layout.addWidget(self.voice_desc_label)
        self._on_voice_changed(self.voice_combo.currentIndex())

        # Preview button
        preview_layout = QHBoxLayout()
        preview_btn = QPushButton("Preview Voice")
        preview_btn.clicked.connect(self._preview_voice)
        preview_layout.addWidget(preview_btn)

        stop_btn = QPushButton("Stop")
        stop_btn.clicked.connect(self._stop_preview)
        preview_layout.addWidget(stop_btn)

        preview_layout.addStretch()
        voice_layout.addLayout(preview_layout)

        layout.addWidget(voice_group)

        # Voice info
        info_label = QLabel(
            "Tip: Choose different voices for narrator vs characters to make dialogue clearer."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #059669; font-size: 11px; padding: 8px;")
        layout.addWidget(info_label)

        layout.addStretch()

        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        layout.addLayout(button_layout)

    def _on_voice_changed(self, index):
        """Update voice description when selection changes."""
        if index >= 0 and index < len(self.VIBEVOICE_VOICES):
            voice_id, name, gender, desc = self.VIBEVOICE_VOICES[index]
            self.voice_desc_label.setText(f"{desc}")

    def _preview_voice(self):
        """Preview the selected voice."""
        if not TTS_AVAILABLE:
            QMessageBox.warning(self, "TTS Not Available", "TTS preview is not available.")
            return

        try:
            tts_service = get_tts_service()
            voice_id = self.voice_combo.currentData()
            speaker_name = self.name_edit.text() or "Speaker"

            # Save current settings
            original_engine = tts_service._current_engine
            original_voice = tts_service._vibevoice_voice

            # Set to VibeVoice with selected voice
            if tts_service.is_vibevoice_available():
                tts_service.set_engine(TTSEngine.VIBEVOICE)
                tts_service.set_vibevoice_voice(voice_id)
                tts_service.speak(
                    f"Hello, I am {speaker_name}. This is how I sound when reading your story."
                )
            else:
                # Fall back to edge-tts for preview
                QMessageBox.information(
                    self,
                    "VibeVoice Not Installed",
                    f"VibeVoice is not installed. Voice '{voice_id}' will be used when generating the TTS document.\n\n"
                    "Install VibeVoice from Settings > Text-to-Speech to enable voice preview."
                )
        except Exception as e:
            QMessageBox.warning(self, "Preview Error", f"Could not preview voice: {e}")

    def _stop_preview(self):
        """Stop voice preview."""
        if TTS_AVAILABLE:
            try:
                tts_service = get_tts_service()
                tts_service.stop()
            except:
                pass
