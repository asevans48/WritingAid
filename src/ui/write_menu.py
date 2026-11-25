"""The Write tab's right-click menu (piece D.1).

A short menu, built from parts; every entry of the old menu is still in it.

* **On a flagged word, its fixes come first:** Replace with, the "Fix all
  N like this" box, Ask, Suggest in context, Rewrite with AI, Ignore, Add
  to dictionary. That section is the editor's own
  (``EnhancedTextEditor.add_flag_section``), reused, not copied. Before this
  piece the Write tab disconnected it, so right-clicking a flag showed none
  of it.
* **"✨ Improve this" is always there,** right after any flag fixes: Rephrase
  with AI, Suggestions (critique and rewrites) and Overly descriptive?, one
  entry until the Improve window (D.2). With a selection it works on the
  selection; without one, on the sentence that was right-clicked, which is
  selected first so the writer sees what it works on.
* **With a selection:** the Synonyms submenu for one word or AI Thesaurus
  for several.
* **Cut, Copy, Paste, Undo, Redo.** Cut and Copy now appear with a
  selection; before, the menu looked for one on the click position, which
  never has one. The same fix makes "Look Up “…”" and "Find Similar
  Content" appear for the selected text.
* **Look Up Context ▸** as before.
* **More ▸:** Add Annotation, View Annotations (when the line has some),
  Heading Style (with a selection) and Text to Speech.

Every action calls the same method as before. Order and grouping only.
"""

from __future__ import annotations

import re
from typing import Any

from PyQt6.QtWidgets import QMenu

IMPROVE = "✨ Improve this"
MORE = "More"


def build(ce: Any, position) -> QMenu:
    """The menu for a right-click at ``position`` in ``ce.editor``
    (``ce``: the ``ChapterEditor``)."""
    editor = ce.editor
    menu = QMenu(editor)
    line_number = editor.cursorForPosition(position).blockNumber() + 1
    text_cursor = editor.textCursor()
    selected = text_cursor.selectedText() if text_cursor.hasSelection() else ""

    # 1. The flagged word's fixes (the editor's own section).
    if hasattr(editor, "add_flag_section"):
        editor.add_flag_section(menu, position)

    # 2. Help with the selection, or with the sentence under the click.
    sentence = None if selected else _sentence_at(editor, position)
    if selected or sentence:
        improve = menu.addMenu(IMPROVE if selected else IMPROVE + " sentence")
        improve.setToolTipsVisible(True)

        def on_target(slot):
            def go(_=False):
                if sentence:
                    _select(editor, *sentence)
                slot()
            return go
        improve.addAction("✨ Rephrase with AI...").triggered.connect(
            on_target(ce._rephrase_selection))
        suggest = improve.addAction("💡 Suggestions (critique + rewrites)...")
        suggest.setToolTip("Critique the highlighted sentences against your characters, world, "
                           "plot and outline, with three rewrites")
        suggest.triggered.connect(on_target(ce._suggest_for_selection))
        expand = improve.addAction("🔍 Overly descriptive? (ways to expand)...")
        expand.setToolTip("Find statements that tell instead of show (words like “too” and "
                          "“almost” are clues) and expand them in your voice")
        expand.triggered.connect(on_target(ce._expand_selection))
    if selected:
        _add_thesaurus(ce, menu, selected.strip())
    if selected or sentence:
        menu.addSeparator()

    # 3. Editing.
    if selected:
        menu.addAction("Cut").triggered.connect(editor.cut)
        menu.addAction("Copy").triggered.connect(editor.copy)
    menu.addAction("Paste").triggered.connect(editor.paste)
    undo = menu.addAction("Undo")
    undo.triggered.connect(editor.undo)
    undo.setEnabled(editor.document().isUndoAvailable())
    redo = menu.addAction("Redo")
    redo.triggered.connect(editor.redo)
    redo.setEnabled(editor.document().isRedoAvailable())
    menu.addSeparator()

    # 4. Look up.
    lookup = menu.addMenu("Look Up Context")
    if selected:
        lookup.addAction(f'Look Up "{selected[:30]}..."').triggered.connect(
            lambda _=False, t=selected: ce._lookup_selected_text(t))
        lookup.addAction("Find Similar Content").triggered.connect(
            lambda _=False, t=selected: ce._find_similar_content(t))
        lookup.addSeparator()
    lookup.addAction("Character Reference").triggered.connect(ce._lookup_character)
    lookup.addAction("Worldbuilding Reference").triggered.connect(ce._lookup_worldbuilding)
    lookup.addAction("Plot Reference").triggered.connect(ce._lookup_plot)
    lookup.addAction("Technology Reference").triggered.connect(ce._lookup_technology)
    lookup.addSeparator()
    lookup.addAction("Advanced Search...").triggered.connect(ce._show_advanced_search)

    # 5. More.
    more = menu.addMenu(MORE)
    more.addAction("📝 Add Annotation").triggered.connect(
        lambda _=False, n=line_number: ce._add_annotation(n))
    notes = [a for a in getattr(ce.chapter, "annotations", None) or []
             if a.line_number == line_number]
    if notes:
        more.addAction(f"📋 View Annotations ({len(notes)})").triggered.connect(
            lambda _=False, n=line_number: ce._on_margin_clicked(n))
    if selected:
        heading = more.addMenu("Heading Style")
        for level in ["Normal", "Heading 1", "Heading 2", "Heading 3"]:
            heading.addAction(level).triggered.connect(
                lambda _=False, l=level: editor.apply_heading(l))
    tts = more.addMenu("🔊 Text to Speech")
    if selected:
        tts.addAction("Read Selection Aloud").triggered.connect(
            lambda _=False, t=selected: ce._tts_speak_selection(t))
        tts.addAction("Generate TTS Doc from Selection...").triggered.connect(
            lambda _=False, t=selected: ce._tts_generate_from_selection(t))
    tts.addAction("Read Entire Chapter").triggered.connect(ce._tts_speak_chapter)
    tts.addAction("Generate TTS Doc for Chapter...").triggered.connect(ce._tts_generate_document)
    tts.addAction("Stop Playback").triggered.connect(ce._tts_stop)
    return menu


def _sentence_at(editor: Any, position):
    """(start, end) in Qt positions of the sentence under ``position``, or
    None (a blank line, or the click is past the text)."""
    from src.ai.passage_critique import expand_to_sentences, py_to_qt_index, qt_to_py_index
    text = editor.toPlainText()
    if not text.strip():
        return None
    at = qt_to_py_index(text, editor.cursorForPosition(position).position())
    at = min(at, len(text) - 1)
    if text[at].isspace() and at > 0 and not text[at - 1].isspace():
        at -= 1                                   # just after a word: that word's sentence
    start, end = expand_to_sentences(text, at, at + 1)
    if end <= start or not text[start:end].strip() or "\n" in text[start:end].strip():
        return None
    return py_to_qt_index(text, start), py_to_qt_index(text, end)


def _select(editor: Any, start: int, end: int) -> None:
    cursor = editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)


def _add_thesaurus(ce: Any, menu: QMenu, selected: str) -> None:
    """Synonyms for one word; AI Thesaurus for several (as before)."""
    from src.utils.thesaurus import get_antonyms, get_synonyms
    word = re.sub(r'^[^\w]+|[^\w]+$', '', selected)
    if word and " " not in word and len(word) <= 30:
        synonyms = get_synonyms(word, max_results=12)
        antonyms = get_antonyms(word, max_results=5)
        shown = word[:15] + "..." if len(word) > 15 else word
        sub = menu.addMenu(f"📖 Synonyms for \"{shown}\"")
        if synonyms:
            for s in synonyms:
                sub.addAction(s).triggered.connect(
                    lambda _=False, s=s: ce._replace_selection_with(s))
            if antonyms:
                sub.addSeparator()
                anti = sub.addMenu("Antonyms")
                for a in antonyms:
                    anti.addAction(a).triggered.connect(
                        lambda _=False, a=a: ce._replace_selection_with(a))
        else:
            sub.addAction("(no synonyms found)").setEnabled(False)
        sub.addSeparator()
        sub.addAction("🤖 AI Suggestions (world-aware)...").triggered.connect(
            ce._world_word_selection)
    else:
        menu.addAction("🤖 AI Thesaurus (world-aware)...").triggered.connect(
            ce._world_word_selection)


def show(ce: Any, position) -> None:
    """The call line for ``ChapterEditor._show_context_menu``."""
    build(ce, position).exec(ce.editor.mapToGlobal(position))
