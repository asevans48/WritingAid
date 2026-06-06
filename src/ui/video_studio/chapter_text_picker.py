"""Chapter-text picker dialog used by the Video Studio.

The user clicks "Pull from chapter" in the scene editor; this
dialog shows the prose of the scene's anchored chapter (when set),
lets them select a portion of text, and returns the selection so
the scene's narration text gets pre-filled. Saves the writer from
copy-pasting from one tab to another and ensures narration is
grounded in the actual chapter prose.

When the scene has no chapter anchor, the user picks a chapter
from a dropdown first.

When a scene and LLM provider are supplied, the dialog asks the
model to *auto-highlight* the passage in the prose it thinks the
scene depicts. The user can accept the highlight or re-select to
override. On accept, the dialog runs a second short LLM pass to
turn the selected prose into a 2-3 sentence action summary, which
the caller can use to fill out the scene's description.
"""

from __future__ import annotations

import re
from typing import Any, Callable, List, Optional

from PyQt6.QtGui import (
    QColor, QFont, QTextCharFormat, QTextCursor,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)


# A single light-yellow highlight format the editor reuses for both
# the AI's initial guess and any subsequent re-highlight requests.
_HIGHLIGHT_BG = QColor("#fef08a")
_HIGHLIGHT_TEXT = QColor("#1f2937")


class ChapterTextPickerDialog(QDialog):
    """Show the chapter prose, return the user's text selection.

    ``selected_text()`` returns the prose payload after Accept;
    ``selected_text_summary()`` returns the LLM's 2-3 sentence
    action summary when a provider was supplied (empty string
    otherwise). When the user picks **Use entire chapter**, the
    full chapter text is returned — common for long-form narration.
    """

    def __init__(
        self,
        chapters: List[Any],
        initial_chapter_id: Optional[str] = None,
        scene: Optional[Any] = None,
        llm_provider: Optional[Callable[[], Any]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._chapters = list(chapters)
        self._initial_chapter_id = initial_chapter_id
        # Optional scene + LLM enable the auto-highlight + summary
        # path. When either is None, the dialog runs in legacy
        # manual-pick mode without any AI calls.
        self._scene = scene
        self._llm_provider = llm_provider
        self._selected_text = ""
        self._selected_text_summary = ""
        self._selected_chapter_id: Optional[str] = None
        # The most recent AI suggestion so we can show the user what
        # was picked + let them accept it directly without
        # re-selecting in the text editor.
        self._ai_highlight_text = ""
        self.setWindowTitle("Pull narration text from chapter")
        self.setModal(True)
        self.resize(840, 660)
        self._build_ui()
        self._load_initial_chapter()

    # ------------------------------------------------------------------
    # Public results
    # ------------------------------------------------------------------
    def selected_text(self) -> str:
        return self._selected_text

    def selected_text_summary(self) -> str:
        """Action summary of the selected prose (2-3 sentences).

        Populated when an LLM provider was supplied AND the user
        accepted a selection. Empty when no LLM was available or
        the summary call failed — the caller should fall back to
        the existing scene description in that case.
        """
        return self._selected_text_summary

    def selected_chapter_id(self) -> Optional[str]:
        return self._selected_chapter_id

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Pick a chapter, then highlight the passage you want "
            "as narration. Click <b>Use selection</b> to copy just "
            "the highlighted text, or <b>Use entire chapter</b> "
            "for the whole prose."))

        # Chapter dropdown
        row = QHBoxLayout()
        row.addWidget(QLabel("Chapter:"))
        self._chapter_combo = QComboBox()
        for ch in self._chapters:
            num = getattr(ch, "number", 0)
            title = getattr(ch, "title", "") or "(untitled)"
            label = f"Ch. {num}: {title}" if num else title
            wc = len((getattr(ch, "content", "") or "").split())
            label += f"  ·  {wc:,} words"
            self._chapter_combo.addItem(label, getattr(ch, "id", ""))
        self._chapter_combo.currentIndexChanged.connect(
            self._on_chapter_changed)
        row.addWidget(self._chapter_combo, stretch=1)

        # AI assist button. Only meaningful when both a scene and
        # an LLM provider were supplied; hidden otherwise so we
        # don't tease a feature the caller didn't enable.
        self._ai_highlight_btn = QPushButton("AI: find scene")
        self._ai_highlight_btn.setToolTip(
            "Ask the LLM to highlight the passage that matches "
            "this scene. Re-highlight by selecting text yourself "
            "if the AI picks wrong.")
        self._ai_highlight_btn.clicked.connect(
            self._run_ai_highlight)
        ai_available = (
            self._scene is not None and self._llm_provider is not None)
        self._ai_highlight_btn.setVisible(ai_available)
        row.addWidget(self._ai_highlight_btn)
        layout.addLayout(row)

        # Word-count + selection-length banner
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #4b5563;")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # The chapter prose. Read-only with selection enabled.
        # We use a QTextEdit so we can paint highlights via the
        # underlying QTextDocument when the AI suggests a range.
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        font = QFont("Georgia", 12)
        self._text.setFont(font)
        self._text.cursorPositionChanged.connect(
            self._on_selection_changed)
        layout.addWidget(self._text, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        self._use_selection_btn = QPushButton("Use selection")
        self._use_selection_btn.clicked.connect(self._on_use_selection)
        self._use_selection_btn.setEnabled(False)
        btn_row.addWidget(self._use_selection_btn)
        self._use_ai_btn = QPushButton("Use AI highlight")
        self._use_ai_btn.setToolTip(
            "Use the prose the AI auto-highlighted (skip the "
            "manual selection step).")
        self._use_ai_btn.clicked.connect(self._on_use_ai_highlight)
        self._use_ai_btn.setEnabled(False)
        self._use_ai_btn.setVisible(ai_available)
        btn_row.addWidget(self._use_ai_btn)
        self._use_all_btn = QPushButton("Use entire chapter")
        self._use_all_btn.clicked.connect(self._on_use_all)
        btn_row.addWidget(self._use_all_btn)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Chapter switch / load
    # ------------------------------------------------------------------
    def _load_initial_chapter(self) -> None:
        # Pre-select the anchored chapter if we have one in scope.
        if self._initial_chapter_id:
            for i in range(self._chapter_combo.count()):
                if (self._chapter_combo.itemData(i)
                        == self._initial_chapter_id):
                    self._chapter_combo.setCurrentIndex(i)
                    break
        self._on_chapter_changed(self._chapter_combo.currentIndex())

    def _on_chapter_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._chapters):
            self._text.clear()
            return
        ch = self._chapters[index]
        content = getattr(ch, "content", "") or ""
        self._text.setPlainText(content)
        self._clear_ai_highlight_state()
        wc = len(content.split())
        if self._scene is not None and self._llm_provider is not None:
            self._status_label.setText(
                f"Chapter has {wc:,} words. Click "
                f"<b>AI: find scene</b> to auto-highlight the "
                f"passage, or select text yourself.")
            self._status_label.setTextFormat(
                self._status_label.textFormat())
            # Kick off the AI highlight automatically — saves the
            # user a click on the common path. If they want manual
            # only, they ignore it and select.
            self._run_ai_highlight()
        else:
            self._status_label.setText(
                f"Chapter has {wc:,} words. Select text and click "
                f"'Use selection', or click 'Use entire chapter'.")
        self._use_selection_btn.setEnabled(False)

    def _clear_ai_highlight_state(self) -> None:
        """Drop the previous chapter's highlight + cached suggestion."""
        self._ai_highlight_text = ""
        self._use_ai_btn.setEnabled(False)
        # Clear any extra selections so a previously highlighted
        # passage doesn't bleed into the new chapter.
        self._text.setExtraSelections([])

    # ------------------------------------------------------------------
    # Selection tracking
    # ------------------------------------------------------------------
    def _on_selection_changed(self) -> None:
        cursor = self._text.textCursor()
        has_sel = cursor.hasSelection()
        self._use_selection_btn.setEnabled(has_sel)
        if has_sel:
            sel = self._cursor_text(cursor)
            wc = len(sel.split())
            self._status_label.setText(
                f"<b>Manual selection: {wc:,} word(s)</b> — "
                f"ready to use. (Re-highlighting overrides the "
                f"AI's pick.)")

    @staticmethod
    def _cursor_text(cursor: QTextCursor) -> str:
        sel = cursor.selectedText()
        # Qt uses U+2029 paragraph separator inside the editor;
        # normalize to plain newlines for downstream consumption.
        return sel.replace(" ", "\n").replace(" ", "\n")

    # ------------------------------------------------------------------
    # AI highlight + summary
    # ------------------------------------------------------------------
    def _run_ai_highlight(self) -> None:
        """Call the LLM to pick a passage and paint it in the editor.

        Defensive: any failure (no LLM configured, parse error,
        passage not found in prose) degrades silently to manual
        selection — the dialog never blocks on the AI.
        """
        if self._scene is None or self._llm_provider is None:
            return
        content = self._text.toPlainText()
        if not content.strip():
            return
        try:
            llm = self._llm_provider()
        except Exception:
            llm = None
        if llm is None:
            self._status_label.setText(
                "<i>No LLM configured — select text manually.</i>")
            return
        self._ai_highlight_btn.setEnabled(False)
        self._status_label.setText(
            "<i>AI is locating the scene in the chapter…</i>")
        # Force the status repaint before the (potentially several-
        # second) LLM call so the user sees the in-flight state.
        QApplication.processEvents()
        try:
            picked = _ask_llm_to_find_passage(
                llm=llm, scene=self._scene, prose=content)
        except Exception as e:
            print(f"[picker] auto-highlight failed: {e}")
            picked = ""
        finally:
            self._ai_highlight_btn.setEnabled(True)
        if not picked:
            self._status_label.setText(
                "<i>AI couldn't lock onto a passage. Select text "
                "manually.</i>")
            return
        # Locate the passage in the prose so we can paint it. Try
        # exact first, then a relaxed (whitespace-collapsed) match
        # since LLMs sometimes drop or rearrange spaces.
        start, end = _locate_passage(picked, content)
        if start < 0:
            self._status_label.setText(
                "<i>AI suggested a passage that isn't in the prose. "
                "Select text manually.</i>")
            return
        self._ai_highlight_text = content[start:end]
        self._apply_highlight(start, end)
        self._use_ai_btn.setEnabled(True)
        wc = len(self._ai_highlight_text.split())
        self._status_label.setText(
            f"<b>AI highlighted {wc:,} word(s).</b> Click "
            f"<b>Use AI highlight</b> to accept, or select different "
            f"text to override.")

    def _apply_highlight(self, start: int, end: int) -> None:
        """Paint a range as the AI's suggestion using QTextEdit's
        extraSelections — non-destructive (doesn't modify the
        text or the user's caret)."""
        cursor = QTextCursor(self._text.document())
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setBackground(_HIGHLIGHT_BG)
        fmt.setForeground(_HIGHLIGHT_TEXT)
        extra = QTextEdit.ExtraSelection()
        extra.cursor = cursor
        extra.format = fmt
        self._text.setExtraSelections([extra])
        # Scroll the highlight into view so the user sees what
        # the AI picked without hunting for it.
        self._text.setTextCursor(cursor)
        # Move the cursor back to the start so the highlight isn't
        # immediately turned into a "live" selection that overrides
        # the extraSelection.
        deselected = QTextCursor(self._text.document())
        deselected.setPosition(start)
        self._text.setTextCursor(deselected)
        self._text.ensureCursorVisible()

    def _maybe_summarize(self, text: str) -> str:
        """Run the action-summary pass on the selected text.

        Returns "" on any failure or when no LLM is available, so
        callers can fall back to existing scene metadata cleanly.
        """
        if not text or not text.strip():
            return ""
        if self._llm_provider is None:
            return ""
        try:
            llm = self._llm_provider()
        except Exception:
            llm = None
        if llm is None:
            return ""
        try:
            return _ask_llm_for_action_summary(llm, text)
        except Exception as e:
            print(f"[picker] action-summary failed: {e}")
            return ""

    # ------------------------------------------------------------------
    # Accept handlers
    # ------------------------------------------------------------------
    def _on_use_selection(self) -> None:
        cursor = self._text.textCursor()
        if not cursor.hasSelection():
            return
        sel = self._cursor_text(cursor)
        self._finalize_with_text(sel)

    def _on_use_ai_highlight(self) -> None:
        if not self._ai_highlight_text:
            return
        self._finalize_with_text(self._ai_highlight_text)

    def _on_use_all(self) -> None:
        self._finalize_with_text(self._text.toPlainText())

    def _finalize_with_text(self, text: str) -> None:
        """Common tail for all three accept buttons: stash the chosen
        text, run the summary pass if possible, and accept."""
        if not text or not text.strip():
            return
        self._selected_text = text
        self._selected_chapter_id = (
            self._chapter_combo.currentData())
        # Status update for the brief moment between accept and
        # dialog dismissal — useful when the LLM call adds latency.
        self._status_label.setText(
            "<i>Summarizing selected prose as scene action…</i>")
        QApplication.processEvents()
        self._selected_text_summary = self._maybe_summarize(text)
        self.accept()


# ---------------------------------------------------------------------
# LLM helpers — kept module-level so the dialog stays UI-focused and
# the LLM logic is easy to test independently.
# ---------------------------------------------------------------------
def _ask_llm_to_find_passage(
    llm: Any, scene: Any, prose: str,
) -> str:
    """Ask the LLM to return the exact prose passage that depicts
    the given scene. Returns the raw passage string or empty when
    the model declines / errors.
    """
    scene_name = (getattr(scene, "name", "") or "").strip()
    scene_desc = (getattr(scene, "description", "") or "").strip()
    scene_prompt = (getattr(scene, "prompt", "") or "").strip()
    char_refs = list(getattr(scene, "character_refs", []) or [])
    # Cap prose to ~6000 chars head + ~2500 chars tail. Long chapters
    # would otherwise blow the model's context; we lose nothing by
    # trimming the middle since scenes typically land near beats the
    # writer described in the scene metadata.
    prose_trim = _head_tail_trim(prose, head_chars=6000,
                                 tail_chars=2500)
    system_prompt = (
        "You are a story editor pinpointing which passage of the "
        "chapter prose a particular scene depicts. You return ONLY "
        "the exact prose — copied character-for-character so it can "
        "be located by string search in the chapter. Pick a passage "
        "between 60 and 350 words long. Do not paraphrase, "
        "summarize, or rewrite. Do not include commentary, "
        "explanations, or quote markers. If multiple passages could "
        "match, pick the one that best fits the scene's prompt + "
        "character_refs combination. If the scene clearly doesn't "
        "appear in this chapter, output exactly: NONE")
    user_prompt = f"""
Scene name: {scene_name or "(unnamed)"}
Scene description: {scene_desc or "(none)"}
Scene visual prompt: {scene_prompt or "(none)"}
Scene character refs: {", ".join(char_refs) if char_refs else "(none)"}

CHAPTER PROSE:
{prose_trim}

Return the exact prose passage that depicts this scene, or NONE if
the scene isn't in this chapter.
""".strip()
    try:
        raw = llm.generate_text(
            user_prompt, system_prompt,
            max_tokens=800, temperature=0.0)
    except Exception as e:
        print(f"[picker] passage-find LLM call failed: {e}")
        return ""
    if not raw:
        return ""
    out = raw.strip()
    # Strip code fences the model may have wrapped output in.
    out = re.sub(r"^```[a-zA-Z]*\n?", "", out)
    out = re.sub(r"\n?```$", "", out).strip()
    if out.upper() == "NONE" or out.upper().startswith("NONE\n"):
        return ""
    return out


def _ask_llm_for_action_summary(llm: Any, prose: str) -> str:
    """Turn a prose passage into 2-3 sentences of scene action."""
    if not prose.strip():
        return ""
    # Action summaries don't need to read the whole 8 KB passage —
    # the opening and closing carry the load.
    capped = _head_tail_trim(prose, head_chars=3500, tail_chars=1500)
    system_prompt = (
        "You write 2-3 sentence scene-action summaries for a "
        "video storyboard. Focus on what HAPPENS visually: who "
        "does what, where, and the immediate consequence. Skip "
        "interior thoughts unless they directly motivate visible "
        "action. Write in present tense, third person. Output ONLY "
        "the summary — no labels, no quotes, no commentary.")
    user_prompt = (
        f"Prose passage:\n{capped}\n\nSummarize as scene action.")
    try:
        raw = llm.generate_text(
            user_prompt, system_prompt,
            max_tokens=300, temperature=0.5)
    except Exception as e:
        print(f"[picker] summary LLM call failed: {e}")
        return ""
    if not raw:
        return ""
    # Strip leading "Summary:" / "Scene action:" labels models
    # sometimes add despite the instruction.
    out = re.sub(
        r"^\s*(scene action|summary|description)\s*[:\-—]\s*",
        "", raw.strip(), flags=re.IGNORECASE)
    out = re.sub(r"^```[a-zA-Z]*\n?", "", out)
    out = re.sub(r"\n?```$", "", out).strip()
    return out


def _head_tail_trim(
    s: str, head_chars: int, tail_chars: int,
) -> str:
    """Keep the head + tail, replace the middle with an ellipsis
    notice. Used to fit long chapters into a single LLM call without
    losing the structural opening + closing."""
    if len(s) <= head_chars + tail_chars + 100:
        return s
    head = s[:head_chars].rstrip()
    tail = s[-tail_chars:].lstrip()
    omitted_chars = len(s) - head_chars - tail_chars
    omitted_words = omitted_chars // 6  # rough chars-per-word average
    return (
        f"{head}\n\n"
        f"[...middle of chapter omitted: ~{omitted_words} words...]\n\n"
        f"{tail}")


def _locate_passage(needle: str, haystack: str) -> tuple:
    """Find ``needle`` inside ``haystack``. Tries:
      1. Direct ``str.find`` (exact match)
      2. Whitespace-normalized comparison (collapses runs of
         whitespace so LLMs that re-flowed the text still match)
      3. First-N-words anchor (matches against the first 8 words of
         the needle, useful when the LLM truncated the tail)

    Returns ``(start, end)`` indices into the original haystack, or
    ``(-1, -1)`` when nothing aligns.
    """
    if not needle or not haystack:
        return (-1, -1)
    # 1. Exact match
    idx = haystack.find(needle)
    if idx >= 0:
        return (idx, idx + len(needle))
    # 2. Whitespace-normalized match — build a map back to original
    # offsets so we can return positions in the original haystack.
    norm_needle = re.sub(r"\s+", " ", needle).strip()
    # Walk haystack collecting (norm_idx → orig_idx) so we can
    # translate a hit in the normalized string back to the original.
    norm_chars: List[str] = []
    norm_to_orig: List[int] = []
    in_ws = False
    for i, ch in enumerate(haystack):
        if ch.isspace():
            if not in_ws and norm_chars and norm_chars[-1] != " ":
                norm_chars.append(" ")
                norm_to_orig.append(i)
            in_ws = True
        else:
            norm_chars.append(ch)
            norm_to_orig.append(i)
            in_ws = False
    norm_haystack = "".join(norm_chars)
    norm_idx = norm_haystack.find(norm_needle)
    if norm_idx >= 0:
        end_norm = norm_idx + len(norm_needle) - 1
        if end_norm < len(norm_to_orig):
            start_orig = norm_to_orig[norm_idx]
            end_orig = norm_to_orig[end_norm] + 1
            return (start_orig, end_orig)
    # 3. Anchor on a progressively shorter prefix. LLMs sometimes
    # hallucinate a tail or alter end punctuation; trying 8 → 5 → 3
    # words lets us still land on the head of the passage and span
    # roughly the right amount of prose. We stop at 3 words because
    # shorter anchors hit too many false positives.
    words = norm_needle.split()
    for n in (8, 6, 5, 4, 3):
        if len(words) < n:
            continue
        anchor = " ".join(words[:n])
        anchor_idx = norm_haystack.find(anchor)
        if anchor_idx >= 0:
            start_orig = norm_to_orig[anchor_idx]
            # Span the same byte count as the original needle so
            # we capture roughly the right amount of prose.
            end_orig = min(len(haystack),
                           start_orig + len(needle))
            return (start_orig, end_orig)
    return (-1, -1)
