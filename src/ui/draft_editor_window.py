"""Secondary/side-by-side editor for manuscript drafts.

Provides two classes:
  * DraftEditorPanel — reusable QWidget that holds the draft picker,
    chapter list, and text editor. Can be embedded anywhere.
  * DraftEditorWindow — standalone QMainWindow that wraps the panel for
    use as a pop-out window.

Saving the panel signals the host (or the window's parent) to persist
the project.
"""

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QKeySequence, QShortcut, QAction, QTextCursor
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QComboBox, QPushButton, QLabel,
    QTextEdit, QMessageBox, QStatusBar, QMenu,
)

from src.models.project import ManuscriptDraft, Chapter, WriterProject


class DraftEditorPanel(QWidget):
    """Embeddable editor panel for a single manuscript draft or Main.

    Emits ``draft_saved`` when the user saves changes so the host can
    persist the project to disk.
    """

    # Sentinel value used in the draft combo to represent the main manuscript
    MAIN_SOURCE_ID = "__main__"

    draft_saved = pyqtSignal(str)  # draft_id (or MAIN_SOURCE_ID)
    dirty_changed = pyqtSignal(bool)

    def __init__(self, project: WriterProject, initial_draft_id: str = "",
                 parent=None, show_close_button: bool = False,
                 compact: bool = False):
        super().__init__(parent)
        self.project = project
        # _current_source is either a ManuscriptDraft or the main Manuscript.
        # Both expose `.chapters` so chapter ops are uniform.
        self._current_source = None
        self._current_chapter: Optional[Chapter] = None
        self._dirty = False
        self._show_close_button = show_close_button
        # Compact mode: used when embedded in split view on narrow screens.
        # Replaces the chapter LIST with a chapter COMBO to reclaim width.
        self._compact = compact
        self._init_ui()
        self._populate_drafts()
        # Explicitly select and load the initial source. Default is Main
        # (index 0); optionally jump to a specific draft id.
        if self.draft_combo.count() > 0:
            target_idx = 0
            if initial_draft_id:
                for i in range(self.draft_combo.count()):
                    if self.draft_combo.itemData(i) == initial_draft_id:
                        target_idx = i
                        break
            self.draft_combo.blockSignals(True)
            self.draft_combo.setCurrentIndex(target_idx)
            self.draft_combo.blockSignals(False)
            self._on_draft_changed(target_idx)

    # Backwards-compat alias — some host code may still reference this
    @property
    def _current_draft(self):
        """The current source as a ManuscriptDraft (None if Main is active)."""
        if isinstance(self._current_source, ManuscriptDraft):
            return self._current_source
        return None

    @property
    def _is_main_active(self) -> bool:
        return self._current_source is not None and not isinstance(
            self._current_source, ManuscriptDraft)

    # ── UI ───────────────────────────────────────────────────

    def _init_ui(self):
        if self._compact:
            self._init_ui_compact()
        else:
            self._init_ui_full()
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self._save_current)
        # Install a right-click context menu that targets THIS panel's
        # editor (not the main editor), so actions like Cut/Paste/Read
        # Aloud act on the content the user is actually right-clicking on.
        self._install_context_menu()

    def _init_ui_compact(self):
        """Narrow layout for side-by-side embedding on laptop screens.

        Everything lives on a single toolbar row:
          [Draft ▾] [Ch N ▾] [▲] [▼] [💾] [🗙]
        The chapter LIST is replaced with a chapter COMBO to reclaim the
        ~260 px the list would otherwise consume.
        """
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        bar = QHBoxLayout()
        bar.setSpacing(4)

        self.draft_combo = QComboBox()
        self.draft_combo.setMinimumContentsLength(14)
        self.draft_combo.setToolTip("Draft")
        self.draft_combo.currentIndexChanged.connect(self._on_draft_changed)
        bar.addWidget(self.draft_combo, 1)

        self.chapter_combo = QComboBox()
        self.chapter_combo.setMinimumContentsLength(14)
        self.chapter_combo.setToolTip("Chapter")
        self.chapter_combo.currentIndexChanged.connect(self._on_chapter_combo_changed)
        bar.addWidget(self.chapter_combo, 1)

        btn_css = "font-size: 11px; padding: 2px 6px;"

        self.move_up_btn = QPushButton("▲")
        self.move_up_btn.setToolTip("Move selected chapter up in the draft order")
        self.move_up_btn.setStyleSheet(btn_css)
        self.move_up_btn.setMaximumWidth(28)
        self.move_up_btn.clicked.connect(self._move_chapter_up)
        bar.addWidget(self.move_up_btn)

        self.move_down_btn = QPushButton("▼")
        self.move_down_btn.setToolTip("Move selected chapter down in the draft order")
        self.move_down_btn.setStyleSheet(btn_css)
        self.move_down_btn.setMaximumWidth(28)
        self.move_down_btn.clicked.connect(self._move_chapter_down)
        bar.addWidget(self.move_down_btn)

        self.save_btn = QPushButton("💾")
        self.save_btn.setToolTip("Save draft edits (Ctrl+S)")
        self.save_btn.setStyleSheet(btn_css)
        self.save_btn.setMaximumWidth(30)
        self.save_btn.clicked.connect(self._save_current)
        bar.addWidget(self.save_btn)

        if self._show_close_button:
            self.close_btn = QPushButton("🗙")
            self.close_btn.setToolTip("Close this side-by-side panel")
            self.close_btn.setMaximumWidth(30)
            self.close_btn.setStyleSheet("""
                QPushButton {
                    font-size: 11px;
                    padding: 2px 6px;
                    background-color: #fee2e2;
                    border: 1px solid #fca5a5;
                    border-radius: 4px;
                }
                QPushButton:hover { background-color: #fecaca; }
            """)
            self.close_btn.clicked.connect(self._on_close_clicked)
            bar.addWidget(self.close_btn)

        outer.addLayout(bar)

        # Chapter title + word count on a single compact line
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        self.chapter_title_label = QLabel("Select a chapter")
        self.chapter_title_label.setStyleSheet(
            "font-weight: 600; font-size: 12px; color: #374151;")
        meta_row.addWidget(self.chapter_title_label)
        meta_row.addStretch()
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        meta_row.addWidget(self.status_label)
        outer.addLayout(meta_row)

        # The editor takes all remaining space
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Pick a draft and a chapter to start editing.")
        self.editor.textChanged.connect(self._on_text_changed)
        outer.addWidget(self.editor, stretch=1)

        # Compact mode doesn't have a chapter list widget; create a
        # stub attribute so the rest of the class can safely poll it.
        self.chapter_list = None
        # Hidden info label (referenced by full-layout code paths)
        self.draft_info_label = QLabel("")
        self.draft_info_label.hide()
        self.draft_info_label.setParent(self)

    def _init_ui_full(self):
        """Fuller layout for the standalone pop-out window."""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel("Draft:"))
        self.draft_combo = QComboBox()
        self.draft_combo.setMinimumWidth(200)
        self.draft_combo.currentIndexChanged.connect(self._on_draft_changed)
        top_bar.addWidget(self.draft_combo)

        self.draft_info_label = QLabel("")
        self.draft_info_label.setStyleSheet("color: #6b7280; font-style: italic;")
        top_bar.addWidget(self.draft_info_label)
        top_bar.addStretch()

        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setToolTip("Save draft edits (Ctrl+S)")
        self.save_btn.clicked.connect(self._save_current)
        top_bar.addWidget(self.save_btn)

        if self._show_close_button:
            self.close_btn = QPushButton("🗙 Close")
            self.close_btn.setToolTip("Close this side-by-side panel")
            self.close_btn.setStyleSheet("""
                QPushButton {
                    font-size: 11px;
                    padding: 3px 10px;
                    background-color: #fee2e2;
                    border: 1px solid #fca5a5;
                    border-radius: 4px;
                }
                QPushButton:hover { background-color: #fecaca; }
            """)
            self.close_btn.clicked.connect(self._on_close_clicked)
            top_bar.addWidget(self.close_btn)

        outer.addLayout(top_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        chapter_panel = QWidget()
        ch_layout = QVBoxLayout(chapter_panel)
        ch_layout.setContentsMargins(0, 0, 0, 0)
        ch_layout.addWidget(QLabel("Chapters:"))
        self.chapter_list = QListWidget()
        self.chapter_list.currentItemChanged.connect(self._on_chapter_changed)
        ch_layout.addWidget(self.chapter_list)

        move_row = QHBoxLayout()
        move_row.setSpacing(4)
        self.move_up_btn = QPushButton("▲ Up")
        self.move_up_btn.setToolTip("Move selected chapter up in the draft order")
        self.move_up_btn.setStyleSheet("font-size: 11px; padding: 3px 6px;")
        self.move_up_btn.clicked.connect(self._move_chapter_up)
        move_row.addWidget(self.move_up_btn)

        self.move_down_btn = QPushButton("▼ Down")
        self.move_down_btn.setToolTip("Move selected chapter down in the draft order")
        self.move_down_btn.setStyleSheet("font-size: 11px; padding: 3px 6px;")
        self.move_down_btn.clicked.connect(self._move_chapter_down)
        move_row.addWidget(self.move_down_btn)
        move_row.addStretch()
        ch_layout.addLayout(move_row)

        chapter_panel.setMaximumWidth(260)
        splitter.addWidget(chapter_panel)

        editor_panel = QWidget()
        ed_layout = QVBoxLayout(editor_panel)
        ed_layout.setContentsMargins(0, 0, 0, 0)
        self.chapter_title_label = QLabel("Select a chapter to edit")
        self.chapter_title_label.setStyleSheet(
            "font-weight: bold; font-size: 13px; padding: 4px;")
        ed_layout.addWidget(self.chapter_title_label)

        self.editor = QTextEdit()
        self.editor.setPlaceholderText(
            "Pick a draft and a chapter. Edits are kept in memory until "
            "you click Save — and are persisted when the project saves.")
        self.editor.textChanged.connect(self._on_text_changed)
        ed_layout.addWidget(self.editor)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("font-size: 11px; color: #6b7280;")
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        ed_layout.addLayout(status_row)

        splitter.addWidget(editor_panel)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=1)
        # No chapter_combo in full layout
        self.chapter_combo = None

    # ── Drafts ───────────────────────────────────────────────

    def _populate_drafts(self):
        self.draft_combo.blockSignals(True)
        try:
            self.draft_combo.clear()
            main_count = len(self.project.manuscript.chapters) if \
                self.project and self.project.manuscript else 0
            self.draft_combo.addItem(
                f"📖 Main Manuscript  ({main_count} chapters)",
                self.MAIN_SOURCE_ID)
            for d in self.project.drafts:
                label = f"📝 {d.name}  ({len(d.chapters)} chapters)"
                self.draft_combo.addItem(label, d.id)
        finally:
            self.draft_combo.blockSignals(False)

    def refresh_drafts(self):
        """Re-populate the draft combo (call after drafts are added/removed).

        Preserves the current selection (Main or a specific draft) if it
        still exists. If the previously selected draft was deleted, falls
        back to Main.
        """
        # Figure out what's currently selected by combo data (survives
        # draft deletions because we read the stored data id)
        current_id = self.MAIN_SOURCE_ID
        if self._current_source and not self._is_main_active:
            current_id = self._current_source.id

        self._populate_drafts()
        if self.draft_combo.count() == 0:
            return
        target_idx = 0
        for i in range(self.draft_combo.count()):
            if self.draft_combo.itemData(i) == current_id:
                target_idx = i
                break
        self.draft_combo.blockSignals(True)
        self.draft_combo.setCurrentIndex(target_idx)
        self.draft_combo.blockSignals(False)
        self._on_draft_changed(target_idx)

    def refresh_chapters(self):
        """Reload the chapter picker from the current source.

        Call this when the active source's chapter list is modified
        externally (e.g. the primary editor added, removed, or moved a
        chapter in Main). Tries to keep the same chapter selected; if
        that chapter no longer exists, loads the first one or clears.
        """
        self._refresh_chapter_list()

    def _on_draft_changed(self, index: int):
        self._flush_editor_to_chapter()
        source_id = self.draft_combo.itemData(index)
        if source_id == self.MAIN_SOURCE_ID:
            self._current_source = (self.project.manuscript
                                    if self.project else None)
        else:
            self._current_source = (self.project.get_draft(source_id)
                                    if source_id else None)
        self._current_chapter = None

        # Disable chapter moves when editing Main from the side panel —
        # reordering Main should happen in the primary editor (main
        # writing view) to keep everything in sync.
        main_active = self._is_main_active
        if hasattr(self, 'move_up_btn'):
            self.move_up_btn.setEnabled(not main_active)
            self.move_down_btn.setEnabled(not main_active)

        self._refresh_chapter_list()
        if not self._compact:
            self._refresh_editor(None)
        if self._current_draft:
            self.draft_info_label.setText(self._current_draft.description or "")
        else:
            self.draft_info_label.setText(
                "(main manuscript — chapter moves are disabled here)"
                if main_active else "")

    def _source_chapters(self):
        """Return the chapters list of the current source (or [])."""
        if self._current_source is None:
            return []
        return getattr(self._current_source, 'chapters', []) or []

    def _refresh_chapter_list(self):
        """Repopulate either the chapter list (full) or combo (compact)."""
        if self._compact:
            self._refresh_chapter_combo()
            return
        self.chapter_list.blockSignals(True)
        try:
            self.chapter_list.clear()
            ordered = sorted(self._source_chapters(),
                             key=lambda c: getattr(c, 'number', 0))
            for ch in ordered:
                num = getattr(ch, 'number', 0)
                title = getattr(ch, 'title', 'Untitled')
                item = QListWidgetItem(f"{num}. {title}")
                item.setData(Qt.ItemDataRole.UserRole, ch.id)
                self.chapter_list.addItem(item)
        finally:
            self.chapter_list.blockSignals(False)

    def _refresh_chapter_combo(self):
        """Compact-mode chapter picker (combo replaces the list)."""
        current_id = self._current_chapter.id if self._current_chapter else None
        ordered = sorted(self._source_chapters(),
                         key=lambda c: getattr(c, 'number', 0))
        self.chapter_combo.blockSignals(True)
        try:
            self.chapter_combo.clear()
            for ch in ordered:
                num = getattr(ch, 'number', 0)
                title = getattr(ch, 'title', 'Untitled')
                self.chapter_combo.addItem(f"{num}. {title}", ch.id)
        finally:
            self.chapter_combo.blockSignals(False)
        # Try to restore the previous chapter selection; otherwise load the
        # first chapter; if the source is empty, clear the editor.
        if self.chapter_combo.count() > 0:
            target = 0
            if current_id:
                for i in range(self.chapter_combo.count()):
                    if self.chapter_combo.itemData(i) == current_id:
                        target = i
                        break
            self.chapter_combo.blockSignals(True)
            self.chapter_combo.setCurrentIndex(target)
            self.chapter_combo.blockSignals(False)
            self._on_chapter_combo_changed(target)
        else:
            self._refresh_editor(None)

    def _on_chapter_combo_changed(self, index: int):
        """Handle chapter combo selection change (compact mode)."""
        self._flush_editor_to_chapter()
        chapters = self._source_chapters()
        if not chapters or index < 0:
            self._refresh_editor(None)
            return
        chapter_id = self.chapter_combo.itemData(index)
        ch = next((c for c in chapters if c.id == chapter_id), None)
        self._refresh_editor(ch)

    # ── Chapter editor ───────────────────────────────────────

    def _move_chapter_up(self):
        """Move the selected chapter one slot earlier in the draft order."""
        self._move_chapter(-1)

    def _move_chapter_down(self):
        """Move the selected chapter one slot later in the draft order."""
        self._move_chapter(1)

    def _move_chapter(self, offset: int):
        """Reorder the currently selected chapter within the active source."""
        if not self._current_source or offset == 0:
            return
        # Don't reorder the main manuscript from the side panel — the
        # primary editor is the source of truth for that.
        if self._is_main_active:
            return

        # Get the selected chapter id from whichever picker is active
        chapter_id = None
        if self._compact:
            if self.chapter_combo.currentIndex() >= 0:
                chapter_id = self.chapter_combo.currentData()
        else:
            row = self.chapter_list.currentRow()
            if row >= 0:
                item = self.chapter_list.item(row)
                if item:
                    chapter_id = item.data(Qt.ItemDataRole.UserRole)
        if not chapter_id:
            return

        self._flush_editor_to_chapter()

        ordered = sorted(self._source_chapters(),
                         key=lambda c: getattr(c, 'number', 0))
        idx = next((i for i, c in enumerate(ordered) if c.id == chapter_id), -1)
        if idx < 0:
            return
        new_idx = idx + offset
        if new_idx < 0 or new_idx >= len(ordered):
            return

        ordered[idx], ordered[new_idx] = ordered[new_idx], ordered[idx]
        for i, ch in enumerate(ordered, start=1):
            ch.number = i

        self._current_source.chapters = ordered
        if hasattr(self._current_source, 'updated_at'):
            self._current_source.updated_at = datetime.now()
        self._set_dirty(True)

        self._refresh_chapter_list()
        if self._compact:
            for i in range(self.chapter_combo.count()):
                if self.chapter_combo.itemData(i) == chapter_id:
                    self.chapter_combo.setCurrentIndex(i)
                    break
        else:
            for i in range(self.chapter_list.count()):
                if self.chapter_list.item(i).data(Qt.ItemDataRole.UserRole) == chapter_id:
                    self.chapter_list.setCurrentRow(i)
                    break

    def _on_chapter_changed(self, current, previous):
        self._flush_editor_to_chapter()
        chapters = self._source_chapters()
        if not current or not chapters:
            self._refresh_editor(None)
            return
        chapter_id = current.data(Qt.ItemDataRole.UserRole)
        ch = next((c for c in chapters if c.id == chapter_id), None)
        self._refresh_editor(ch)

    def _refresh_editor(self, chapter: Optional[Chapter]):
        """Load chapter content into the editor, rendering markdown visually.

        Qt's QTextEdit renders markdown (bold, italic, headings, lists,
        blockquotes) when loaded via setMarkdown(). We save back via
        toMarkdown() to preserve the source syntax.
        """
        self._current_chapter = chapter
        self.editor.blockSignals(True)
        try:
            if chapter is None:
                self.editor.clear()
                self.chapter_title_label.setText("Select a chapter to edit")
                self.editor.setEnabled(False)
            else:
                text = chapter.content or ""
                if text.strip():
                    # Render markdown syntax as styled rich text
                    self.editor.setMarkdown(text)
                else:
                    self.editor.clear()
                num = getattr(chapter, 'number', 0)
                title = getattr(chapter, 'title', 'Untitled')
                self.chapter_title_label.setText(f"Ch {num}: {title}")
                self.editor.setEnabled(True)
        finally:
            self.editor.blockSignals(False)
        # Cache the loaded markdown so we can detect real edits later
        self._loaded_content = chapter.content if chapter else ""
        self._set_dirty(False)
        self._update_status()

    def _on_text_changed(self):
        self._set_dirty(True)
        self._update_status()

    # ── Right-click context menu ─────────────────────────────

    def _install_context_menu(self):
        """Attach a custom context menu that targets THIS panel's editor.

        Qt normally bubbles right-clicks to the parent, and in split view
        that could hit the main writing editor's context menu on the wrong
        content. By installing a CustomContextMenu on our own editor we
        make sure every action runs against THIS panel's document/cursor.
        """
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos: QPoint):
        """Build and show the right-click menu for the panel's editor.

        Every action uses self.editor (not any other editor in the app)
        so there's no chance of an accidental action firing on the main
        writing window.
        """
        ed = self.editor  # local ref — guarantees we target this panel
        menu = QMenu(ed)
        cursor = ed.textCursor()
        has_selection = cursor.hasSelection()

        # --- Undo / Redo ---
        undo = QAction("Undo", menu)
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        undo.setEnabled(ed.document().isUndoAvailable())
        undo.triggered.connect(ed.undo)
        menu.addAction(undo)

        redo = QAction("Redo", menu)
        redo.setShortcut(QKeySequence.StandardKey.Redo)
        redo.setEnabled(ed.document().isRedoAvailable())
        redo.triggered.connect(ed.redo)
        menu.addAction(redo)

        menu.addSeparator()

        # --- Cut / Copy / Paste / Select All ---
        cut = QAction("Cut", menu)
        cut.setShortcut(QKeySequence.StandardKey.Cut)
        cut.setEnabled(has_selection)
        cut.triggered.connect(ed.cut)
        menu.addAction(cut)

        copy = QAction("Copy", menu)
        copy.setShortcut(QKeySequence.StandardKey.Copy)
        copy.setEnabled(has_selection)
        copy.triggered.connect(ed.copy)
        menu.addAction(copy)

        paste = QAction("Paste", menu)
        paste.setShortcut(QKeySequence.StandardKey.Paste)
        paste.triggered.connect(ed.paste)
        menu.addAction(paste)

        select_all = QAction("Select All", menu)
        select_all.setShortcut(QKeySequence.StandardKey.SelectAll)
        select_all.triggered.connect(ed.selectAll)
        menu.addAction(select_all)

        menu.addSeparator()

        # --- Markdown formatting (wraps selection) ---
        fmt_menu = menu.addMenu("Format")
        fmt_menu.setEnabled(has_selection or not ed.document().isEmpty())

        bold = QAction("Bold", fmt_menu)
        bold.triggered.connect(lambda: self._wrap_selection("**", "**"))
        fmt_menu.addAction(bold)

        italic = QAction("Italic", fmt_menu)
        italic.triggered.connect(lambda: self._wrap_selection("*", "*"))
        fmt_menu.addAction(italic)

        code = QAction("Inline Code", fmt_menu)
        code.triggered.connect(lambda: self._wrap_selection("`", "`"))
        fmt_menu.addAction(code)

        fmt_menu.addSeparator()

        for level, prefix in [("Heading 1", "# "), ("Heading 2", "## "),
                              ("Heading 3", "### ")]:
            a = QAction(level, fmt_menu)
            a.triggered.connect(lambda checked=False, p=prefix:
                                self._apply_line_prefix(p))
            fmt_menu.addAction(a)

        menu.addSeparator()

        # --- AI / Lookup features ---
        # Every action below reads the selection from THIS panel's editor
        # (captured via the local `cursor` / `ed`) so nothing can fire on
        # the main writing editor by accident.
        selected_text = cursor.selectedText().strip() if has_selection else ""

        if selected_text:
            # Offline synonyms submenu for single words (WordNet)
            import re as _re
            clean_word = _re.sub(r'^[^\w]+|[^\w]+$', '', selected_text)
            is_single_word = (clean_word and ' ' not in clean_word
                              and len(clean_word) <= 30)

            if is_single_word:
                try:
                    from src.utils.thesaurus import get_synonyms, get_antonyms
                    synonyms = get_synonyms(clean_word, max_results=12)
                    antonyms = get_antonyms(clean_word, max_results=5)
                except Exception:
                    synonyms, antonyms = [], []

                display_word = (clean_word[:15] + "…"
                                if len(clean_word) > 15 else clean_word)
                thes_menu = menu.addMenu(f"📖 Synonyms for \"{display_word}\"")
                if synonyms:
                    for syn in synonyms:
                        a = thes_menu.addAction(syn)
                        a.triggered.connect(
                            lambda checked=False, s=syn: self._replace_selection_with(s))
                    if antonyms:
                        thes_menu.addSeparator()
                        ant_menu = thes_menu.addMenu("Antonyms")
                        for ant in antonyms:
                            a = ant_menu.addAction(ant)
                            a.triggered.connect(
                                lambda checked=False, x=ant: self._replace_selection_with(x))
                else:
                    no_a = thes_menu.addAction("(no synonyms found)")
                    no_a.setEnabled(False)
                thes_menu.addSeparator()
                ai_thes = thes_menu.addAction("🤖 AI Suggestions (world-aware)…")
                ai_thes.triggered.connect(self._world_word_selection)
            else:
                # Multi-word selection — AI thesaurus only
                ai_thes = menu.addAction("🤖 AI Thesaurus (world-aware)…")
                ai_thes.triggered.connect(self._world_word_selection)

            rephrase_act = menu.addAction("✨ Rephrase with AI…")
            rephrase_act.triggered.connect(self._rephrase_selection)

            menu.addSeparator()

        # --- Draft actions ---
        save_act = QAction("💾 Save Draft", menu)
        save_act.setShortcut(QKeySequence.StandardKey.Save)
        save_act.triggered.connect(self._save_current)
        menu.addAction(save_act)

        # Show at the right-click point in editor viewport coords
        menu.exec(ed.viewport().mapToGlobal(pos))

    def _wrap_selection(self, left: str, right: str):
        """Wrap the current selection (in this panel's editor) with markers."""
        ed = self.editor
        cursor = ed.textCursor()
        if not cursor.hasSelection():
            # No selection — insert a placeholder between the markers
            cursor.insertText(f"{left}{right}")
            return
        selected = cursor.selectedText()
        cursor.insertText(f"{left}{selected}{right}")

    def _apply_line_prefix(self, prefix: str):
        """Prefix the current line in this panel's editor (for headings)."""
        ed = self.editor
        cursor = ed.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.insertText(prefix)

    def _replace_selection_with(self, replacement: str):
        """Replace this panel's selection with the given text.

        Preserves the original case pattern (lowercase → lowercase,
        Title → Title, UPPER → UPPER) so a synonym pick doesn't
        accidentally change sentence capitalization.
        """
        ed = self.editor
        cursor = ed.textCursor()
        if not cursor.hasSelection():
            return
        original = cursor.selectedText()
        if original and original[0].isupper():
            if original.isupper():
                replacement = replacement.upper()
            elif len(original) > 1 and original[1:].islower():
                replacement = replacement[:1].upper() + replacement[1:]
        cursor.insertText(replacement)

    def _rephrase_selection(self):
        """Open the Rephrase dialog with this panel's selection + context."""
        ed = self.editor
        cursor = ed.textCursor()
        selected = cursor.selectedText()
        if not selected or len(selected.strip()) < 3:
            QMessageBox.information(
                self, "No Selection",
                "Select some text in this panel to rephrase.")
            return

        doc_text = ed.toPlainText()
        s = cursor.selectionStart()
        e = cursor.selectionEnd()
        ctx_before = doc_text[max(0, s - 500):s]
        ctx_after = doc_text[e:e + 500]

        try:
            from src.ui.rephrase_dialog import RephraseDialog
            from PyQt6.QtWidgets import QDialog as _QDialog
            dialog = RephraseDialog(
                selected, self.project, self,
                surrounding_context=(ctx_before, ctx_after),
                chapter_content=doc_text,
                chapter=self._current_chapter)
            if dialog.exec() == _QDialog.DialogCode.Accepted:
                replacement = dialog.get_selected_text()
                if replacement:
                    # Apply to THIS panel's cursor — not any other editor
                    cursor.insertText(replacement)
                    self._set_dirty(True)
        except Exception as ex:
            QMessageBox.warning(self, "Rephrase Error", str(ex))

    def _world_word_selection(self):
        """Open the world-aware thesaurus dialog for this panel's selection."""
        ed = self.editor
        cursor = ed.textCursor()
        selected = cursor.selectedText()
        if not selected or not selected.strip():
            QMessageBox.information(
                self, "No Selection",
                "Select a word or phrase in this panel first.")
            return

        doc_text = ed.toPlainText()
        s = cursor.selectionStart()
        e = cursor.selectionEnd()
        ctx_before = doc_text[max(0, s - 300):s]
        ctx_after = doc_text[e:e + 300]

        try:
            from src.ui.world_word_dialog import WorldWordDialog
            from PyQt6.QtWidgets import QDialog as _QDialog
            dialog = WorldWordDialog(
                selected.strip(), self.project, self,
                surrounding_context=(ctx_before, ctx_after),
                chapter_content=doc_text,
                chapter=self._current_chapter)
            if dialog.exec() == _QDialog.DialogCode.Accepted:
                replacement = dialog.get_replacement()
                if replacement:
                    self._replace_selection_with(replacement)
                    self._set_dirty(True)
        except Exception as ex:
            QMessageBox.warning(self, "AI Thesaurus Error", str(ex))

    def _flush_editor_to_chapter(self):
        """Write editor markdown back to the chapter, guarding against overwrites.

        Safety rule: NEVER blank out a chapter that had content. The side
        panel is primarily for navigation and short edits; a widget that
        shows empty text while the model holds real content is almost
        certainly a state-mismatch bug (stale widget, draft swap race),
        not a user intent to delete the entire chapter.

        Users who want to wipe a chapter should do so in the primary
        editor, which has a more explicit flow (revisions, backups, undo).
        """
        if not (self._current_chapter and self._dirty):
            return

        new_text = self.editor.toMarkdown().rstrip('\n')
        existing = (self._current_chapter.content or "").strip()

        # Defense: never overwrite non-empty chapter content with empty text.
        if not new_text.strip() and existing:
            print(f"[Draft] Refusing to blank out '{self._current_chapter.title}' — "
                  f"editor empty but chapter has {len(existing)} chars. "
                  f"Draft data preserved.")
            self._set_dirty(False)
            return

        self._current_chapter.content = new_text
        self._current_chapter.word_count = len(new_text.split())
        self._set_dirty(False)

    def _save_current(self):
        if not self._current_source:
            return
        self._flush_editor_to_chapter()
        if hasattr(self._current_source, 'updated_at'):
            self._current_source.updated_at = datetime.now()
        if self._is_main_active:
            name = "Main Manuscript"
            emit_id = self.MAIN_SOURCE_ID
        else:
            name = self._current_source.name
            emit_id = self._current_source.id
        self.draft_saved.emit(emit_id)
        self.status_label.setText(
            f"Saved '{name}' — {datetime.now().strftime('%H:%M:%S')}")

    def _set_dirty(self, dirty: bool):
        if dirty != self._dirty:
            self._dirty = dirty
            self.dirty_changed.emit(dirty)

    def is_dirty(self) -> bool:
        return self._dirty

    def _update_status(self):
        if self._current_chapter:
            wc = len((self.editor.toPlainText() or "").split())
            mark = " ●" if self._dirty else ""
            self.status_label.setText(f"{wc} words{mark}")
        else:
            self.status_label.setText("Ready")

    # ── Embedded-close support ───────────────────────────────

    close_requested = pyqtSignal()

    def _on_close_clicked(self):
        if self._dirty:
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save this draft before closing the panel?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if reply == QMessageBox.StandardButton.Save:
                self._save_current()
            elif reply == QMessageBox.StandardButton.Cancel:
                return
        self.close_requested.emit()


class DraftEditorWindow(QMainWindow):
    """Standalone pop-out window wrapping a DraftEditorPanel."""

    draft_saved = pyqtSignal(str)

    def __init__(self, project: WriterProject, initial_draft_id: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Draft Editor")
        self.resize(900, 650)
        self.panel = DraftEditorPanel(project, initial_draft_id, self)
        self.panel.draft_saved.connect(self.draft_saved.emit)
        self.setCentralWidget(self.panel)
        self.setStatusBar(QStatusBar())

    def closeEvent(self, event):
        if self.panel.is_dirty():
            reply = QMessageBox.question(
                self, "Unsaved Changes",
                "Save changes to this draft before closing?",
                QMessageBox.StandardButton.Save |
                QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if reply == QMessageBox.StandardButton.Save:
                self.panel._save_current()
            elif reply == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        super().closeEvent(event)
