"""Persistent collapsible chat widget for AI assistance."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QLineEdit,
    QPlainTextEdit, QPushButton, QLabel, QFrame, QComboBox, QToolButton,
    QSizePolicy, QSplitter, QSplitterHandle
)
from PyQt6.QtCore import pyqtSignal, Qt, QSettings
from PyQt6.QtGui import QIcon, QPainter, QColor
from enum import Enum
from typing import List, Dict, Optional
from datetime import datetime
from src.ai.conversation_store import (
    ConversationStore, RatedConversation, ConversationMessage,
    ConversationMetadata, ConversationRating, MessageRole,
    create_conversation_from_messages
)
from src.config import get_ai_config


# Visible-row bounds for the prompt box. The user can grow/shrink
# the prompt area via the −/+ buttons in the chat panel; persisted
# preference is kept across sessions in QSettings.
_INPUT_ROWS_MIN = 1
_INPUT_ROWS_MAX = 16
_INPUT_ROWS_DEFAULT = 2
_INPUT_ROWS_STEP = 2
_INPUT_FONT_PX = 13  # Constant text size — only the height varies now.


class _GripHandle(QSplitterHandle):
    """Splitter handle that paints three centered grip dots.

    Default Qt vertical splitter handles render as a flat coloured
    bar — easy to overlook. Drawing dots in the middle (the same
    convention macOS / GNOME use for resizable elements) tells the
    user at a glance "this is a drag target". Used by the chat
    widget so the prompt-vs-history splitter is discoverable.
    """

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            # Indigo dots that match the hover colour so the
            # affordance feels like one continuous design.
            painter.setBrush(QColor("#6366f1"))
            cx = self.width() // 2
            cy = self.height() // 2
            r = 2  # dot radius
            spacing = 6
            for off in (-spacing, 0, spacing):
                painter.drawEllipse(cx - r + off, cy - r, r * 2, r * 2)
        finally:
            painter.end()


class _GrippedSplitter(QSplitter):
    """QSplitter that uses :class:`_GripHandle` for its handles."""

    def createHandle(self):
        return _GripHandle(self.orientation(), self)


class _ChatInput(QPlainTextEdit):
    """Drop-in replacement for the chat's old QLineEdit prompt box.

    Three departures from QPlainTextEdit:
      1. ``submit_requested`` fires on bare Enter, mirroring the old
         line-edit's ``returnPressed``. Shift+Enter and Ctrl/⌘+Enter
         insert a newline so users can compose multi-line prompts.
      2. ``setText`` / ``text`` aliases keep external callers
         (main_window, manuscript_editor, draft_editor_window) working
         without each having to learn the QPlainTextEdit API.
      3. ``set_visible_rows`` controls how tall the prompt is. The
         field always *can* hold more text than visible — the
         vertical scrollbar handles overflow. The row count just
         decides how many lines the user sees at a glance before
         needing to scroll inside the prompt.
    """
    submit_requested = pyqtSignal()
    rows_changed = pyqtSignal(int)  # Emits new row count for UI sync.

    def __init__(self, parent=None):
        super().__init__(parent)
        # Always show the scrollbar — that's the whole point of the
        # resizable prompt: the user can scroll up to see earlier
        # lines they typed without having to enlarge the field.
        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        # Vertical Expanding so the input fills its splitter pane —
        # the user resizes by dragging the splitter handle, not by
        # us pinning a fixed height. _apply_height now sets only the
        # minimum so we still respect the +/- preset row counts.
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Expanding)
        self.setStyleSheet(
            f"QPlainTextEdit {{"
            f" padding: 8px 12px;"
            f" font-size: {_INPUT_FONT_PX}px;"
            f" border-radius: 8px;"
            f" border: 1px solid #e5e7eb;"
            f" background-color: white;"
            f" }}"
            f"QPlainTextEdit:focus {{ border: 2px solid #6366f1; }}")
        self._rows = _INPUT_ROWS_DEFAULT
        self._apply_height()

    # — line-edit-compat shims —
    def setText(self, text: str) -> None:
        self.setPlainText(text)

    def text(self) -> str:
        return self.toPlainText()

    # — visible-row handling —
    def visible_rows(self) -> int:
        return self._rows

    def set_visible_rows(self, rows: int) -> None:
        rows = max(_INPUT_ROWS_MIN,
                    min(_INPUT_ROWS_MAX, int(rows)))
        if rows == self._rows:
            return
        self._rows = rows
        self._apply_height()
        self.rows_changed.emit(rows)

    def _apply_height(self) -> None:
        """Set a minimum height matching the configured row count.

        The widget itself is now Expanding (the parent splitter
        controls the actual height). We only enforce a minimum so
        the +/- buttons feel responsive: shrinking to 1 row pulls
        the minimum down so the user can drag the splitter tighter,
        and growing to 10 rows pushes the minimum up so the splitter
        snaps to at least that height. Mouse-drag on the splitter
        is the primary resize gesture; +/- are quick presets.
        """
        fm = self.fontMetrics()
        line_h = fm.lineSpacing()
        # Padding (8 top + 8 bottom) + slack for cursor + frame.
        chrome = 8 + 8 + 6
        self.setMinimumHeight(line_h * self._rows + chrome)
        # Drop any old fixed-height constraint so the splitter can
        # actually expand the widget beyond the minimum.
        self.setMaximumHeight(16777215)

    # — keyboard shortcuts —
    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Shift / Ctrl / ⌘+Enter inserts a newline; bare Enter sends.
            if (mods & (Qt.KeyboardModifier.ShiftModifier
                         | Qt.KeyboardModifier.ControlModifier
                         | Qt.KeyboardModifier.MetaModifier)):
                super().keyPressEvent(event)
            else:
                self.submit_requested.emit()
            return
        # Ctrl/⌘ +/- and Ctrl+0 grow / shrink / reset the prompt height.
        if mods & (Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.MetaModifier):
            if key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
                self.set_visible_rows(self._rows + _INPUT_ROWS_STEP)
                return
            if key == Qt.Key.Key_Minus:
                self.set_visible_rows(self._rows - _INPUT_ROWS_STEP)
                return
            if key == Qt.Key.Key_0:
                self.set_visible_rows(_INPUT_ROWS_DEFAULT)
                return
        super().keyPressEvent(event)


class ChatMode(Enum):
    """Available chat assistant modes."""
    GENERAL = "general"
    CHAPTER_FOCUS = "chapter_focus"
    PLOT = "plot"
    WRITER = "writer"
    WORLDBUILDING = "worldbuilding"


class WriterInsertMode(Enum):
    """How to insert AI-generated text in Writer mode."""
    REPLACE_SELECTION = "replace_selection"  # Replace selected text
    INSERT_AT_CURSOR = "insert_at_cursor"    # Insert at cursor position
    APPEND_TO_CHAPTER = "append_to_chapter"  # Append to end of chapter
    REPLACE_CHAPTER = "replace_chapter"      # Replace entire chapter


class WriterOutputMode(Enum):
    """What kind of output Writer mode should produce.

    FULL_TEXT (default) — actual prose for each remaining beat.
    OUTLINE — structured per-beat outline with plot, focal
        characters + tensions, location with worldbuilding hooks
        (folklore, architecture, rituals, factions, mythology),
        sensory examples, subplot / theme landing notes, etc. Used
        when the author wants to plan rather than draft.
    """
    FULL_TEXT = "full_text"
    OUTLINE = "outline"


class WritingPOV(Enum):
    """Narrative point of view options."""
    FIRST_PERSON = "first_person"
    THIRD_PERSON_LIMITED = "third_person_limited"
    THIRD_PERSON_OMNISCIENT = "third_person_omniscient"
    SECOND_PERSON = "second_person"


WRITING_POV_INFO = {
    WritingPOV.FIRST_PERSON: {
        "name": "First Person",
        "description": "I/We - narrator is a character in the story"
    },
    WritingPOV.THIRD_PERSON_LIMITED: {
        "name": "Third Person Limited",
        "description": "He/She/They - follows one character's perspective"
    },
    WritingPOV.THIRD_PERSON_OMNISCIENT: {
        "name": "Third Person Omniscient",
        "description": "He/She/They - all-knowing narrator, access to all thoughts"
    },
    WritingPOV.SECOND_PERSON: {
        "name": "Second Person",
        "description": "You - reader as protagonist (rare)"
    }
}


# Mode descriptions for UI
CHAT_MODE_INFO = {
    ChatMode.GENERAL: {
        "name": "General Assistant",
        "subtitle": "Your creative writing companion",
        "placeholder": "Ask me anything about your project...",
        "description": "General questions, agentic tasks, project-wide assistance"
    },
    ChatMode.CHAPTER_FOCUS: {
        "name": "Chapter Focus",
        "subtitle": "Focused on current chapter",
        "placeholder": "Ask about this chapter...",
        "description": "Discuss, analyze, and improve the current chapter"
    },
    ChatMode.PLOT: {
        "name": "Discuss Plot",
        "subtitle": "Plot, structure, pacing, arcs",
        "placeholder": "Ask about plot, structure, pacing, character arcs...",
        "description": "Discuss the story's arc — plot beats, pacing, "
                       "promises, character arcs — with full manuscript "
                       "and worldbuilding context"
    },
    ChatMode.WRITER: {
        "name": "Writer Mode",
        "subtitle": "AI-assisted writing",
        "placeholder": "Describe what to write or continue...",
        "description": "Write or complete chapters based on your outline and world"
    },
    ChatMode.WORLDBUILDING: {
        "name": "Worldbuilding",
        "subtitle": "Build out cultures, places, factions, mythology",
        "placeholder":
            "Describe a place to flesh out, a faction to design, "
            "a myth to craft, a culture to deepen…",
        "description":
            "Discuss + create worldbuilding elements (factions, "
            "places, cultures, myths, religions, technologies, "
            "flora/fauna, historical events) with the project's "
            "existing world for consistency."
    }
}


class ChatWidget(QWidget):
    """Chat interface for AI assistance.

    Lives inside a collapsible sidebar container in MainWindow —
    the chat itself no longer owns a collapse state.
    """

    message_sent = pyqtSignal(str, str, str)  # message, mode, insert_mode
    mode_changed = pyqtSignal(str)  # Emits mode name when changed
    clear_requested = pyqtSignal()  # Emits when user clicks Clear
    # User clicked the "Preview context" button — main_window builds
    # the context dict + system prompt for the current message+mode
    # and opens the shared context-preview dialog.
    preview_requested = pyqtSignal(str, str)  # message, mode

    def __init__(self):
        """Initialize chat widget."""
        super().__init__()
        self.setObjectName("chatWidget")
        self._current_mode = ChatMode.GENERAL
        self._insert_mode = WriterInsertMode.INSERT_AT_CURSOR
        self._output_mode = WriterOutputMode.FULL_TEXT
        self._has_selection = False  # Track if editor has selection

        # Conversation tracking for training data collection
        self._conversation_store = ConversationStore()
        self._current_conversation: List[Dict[str, str]] = []
        self._system_prompt: Optional[str] = None
        self._last_response_id: Optional[str] = None  # Track last AI response for rating
        self._project_name: Optional[str] = None
        self._ai_config = get_ai_config()

        # Chapter/writing context for style metadata
        self._chapter_context: Dict[str, any] = {
            'tone': None,
            'voice': None,
            'style': None,
            'pacing': None,
            'narrative_pov': None,
            'character_pov': None,
            'chapter_title': None,
            'chapter_number': None
        }

        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header bar — title + Clear button. The chat-widget itself
        # no longer collapses on its own; the surrounding sidebar
        # container (in main_window) owns the show/hide for the
        # whole assistant + outline area.
        self.header_frame = QFrame()
        self.header_frame.setStyleSheet("""
            QFrame {
                background-color: #6366f1;
                border-radius: 6px;
            }
        """)
        header_layout = QHBoxLayout(self.header_frame)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)

        title_label = QLabel("✨ AI Assistant")
        title_label.setStyleSheet(
            "QLabel { background-color: transparent; color: white; "
            " font-size: 13px; font-weight: 600; padding: 2px; }")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        # Clear conversation button
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Clear conversation history")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: rgba(255, 255, 255, 0.7);
                border: 1px solid rgba(255, 255, 255, 0.3);
                border-radius: 4px;
                font-size: 11px;
                padding: 2px 8px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
                color: white;
            }
        """)
        self.clear_btn.clicked.connect(self._clear_conversation)
        header_layout.addWidget(self.clear_btn)

        layout.addWidget(self.header_frame)

        # Content container (collapsible)
        self.content_widget = QWidget()
        content_layout = QVBoxLayout(self.content_widget)
        content_layout.setContentsMargins(0, 4, 0, 0)
        content_layout.setSpacing(8)

        # Mode selector
        mode_layout = QHBoxLayout()
        mode_layout.setSpacing(6)

        mode_label = QLabel("Mode:")
        mode_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        mode_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
            QComboBox::drop-down {
                border: none;
                padding-right: 4px;
            }
        """)
        for mode in ChatMode:
            self.mode_combo.addItem(CHAT_MODE_INFO[mode]["name"], mode.value)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()

        content_layout.addLayout(mode_layout)

        # Subtitle (dynamic based on mode)
        self.subtitle = QLabel(CHAT_MODE_INFO[self._current_mode]["subtitle"])
        self.subtitle.setProperty("muted", True)
        self.subtitle.setStyleSheet("font-size: 11px; color: #a3a3a3;")
        content_layout.addWidget(self.subtitle)

        # Mode description
        self.mode_description = QLabel(CHAT_MODE_INFO[self._current_mode]["description"])
        self.mode_description.setWordWrap(True)
        self.mode_description.setStyleSheet("font-size: 10px; color: #9ca3af; font-style: italic; margin-bottom: 4px;")
        content_layout.addWidget(self.mode_description)

        # Writer mode insert options (only visible in Writer mode)
        self.insert_mode_widget = QWidget()
        insert_layout = QHBoxLayout(self.insert_mode_widget)
        insert_layout.setContentsMargins(0, 4, 0, 4)
        insert_layout.setSpacing(6)

        insert_label = QLabel("Insert:")
        insert_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        insert_layout.addWidget(insert_label)

        self.insert_combo = QComboBox()
        self.insert_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 140px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
        """)
        self.insert_combo.addItem("At Cursor", WriterInsertMode.INSERT_AT_CURSOR.value)
        self.insert_combo.addItem("Append to Chapter", WriterInsertMode.APPEND_TO_CHAPTER.value)
        self.insert_combo.addItem("Replace Chapter", WriterInsertMode.REPLACE_CHAPTER.value)
        self.insert_combo.currentIndexChanged.connect(self._on_insert_mode_changed)
        insert_layout.addWidget(self.insert_combo)

        # Output mode picker — Full Text (prose) vs Outline (structured
        # per-beat plan with worldbuilding / characters / tensions
        # surfaced for the author to flesh out manually). Lives in the
        # same row as the Insert picker so Writer-mode controls stay
        # compact.
        output_label = QLabel("Output:")
        output_label.setStyleSheet(
            "font-size: 11px; color: #6b7280; font-weight: 500; "
            "margin-left: 12px;")
        insert_layout.addWidget(output_label)

        self.output_combo = QComboBox()
        self.output_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 110px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
        """)
        self.output_combo.addItem("Full Text",
                                    WriterOutputMode.FULL_TEXT.value)
        self.output_combo.addItem("Outline",
                                    WriterOutputMode.OUTLINE.value)
        self.output_combo.setToolTip(
            "Full Text drafts prose for each remaining beat.\n"
            "Outline produces a structured per-beat plan: plot + "
            "focal characters + tensions + location worldbuilding + "
            "folklore/myth/faction hooks + sensory examples — "
            "everything you'd want to flesh the beat out yourself.")
        self.output_combo.currentIndexChanged.connect(
            self._on_output_mode_changed)
        insert_layout.addWidget(self.output_combo)

        insert_layout.addStretch()

        content_layout.addWidget(self.insert_mode_widget)
        self.insert_mode_widget.setVisible(False)  # Hidden by default (only in Writer mode)

        # POV options widget (only visible in Writer mode)
        self.pov_widget = QWidget()
        pov_layout = QVBoxLayout(self.pov_widget)
        pov_layout.setContentsMargins(0, 4, 0, 4)
        pov_layout.setSpacing(6)

        # Character POV row
        char_pov_layout = QHBoxLayout()
        char_pov_layout.setSpacing(6)
        char_pov_label = QLabel("Character:")
        char_pov_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        char_pov_layout.addWidget(char_pov_label)

        self.char_pov_combo = QComboBox()
        self.char_pov_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 120px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
        """)
        self.char_pov_combo.addItem("(From chapter)", "")
        char_pov_layout.addWidget(self.char_pov_combo)
        char_pov_layout.addStretch()
        pov_layout.addLayout(char_pov_layout)

        # Writing POV row
        writing_pov_layout = QHBoxLayout()
        writing_pov_layout.setSpacing(6)
        writing_pov_label = QLabel("Narrative:")
        writing_pov_label.setStyleSheet("font-size: 11px; color: #6b7280; font-weight: 500;")
        writing_pov_layout.addWidget(writing_pov_label)

        self.writing_pov_combo = QComboBox()
        self.writing_pov_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 8px;
                font-size: 11px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
                background-color: white;
                min-width: 140px;
            }
            QComboBox:hover {
                border-color: #6366f1;
            }
        """)
        self.writing_pov_combo.addItem("(From chapter)", "")
        for pov in WritingPOV:
            self.writing_pov_combo.addItem(WRITING_POV_INFO[pov]["name"], pov.value)
        writing_pov_layout.addWidget(self.writing_pov_combo)
        writing_pov_layout.addStretch()
        pov_layout.addLayout(writing_pov_layout)

        content_layout.addWidget(self.pov_widget)
        self.pov_widget.setVisible(False)  # Hidden by default (only in Writer mode)

        # Selection indicator (shown when text is selected in Writer mode)
        self.selection_indicator = QLabel("Text selected - will replace selection")
        self.selection_indicator.setStyleSheet(
            "font-size: 10px; color: #059669; font-weight: 500; "
            "background-color: #d1fae5; padding: 4px 8px; border-radius: 4px;"
        )
        content_layout.addWidget(self.selection_indicator)
        self.selection_indicator.setVisible(False)

        # Separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("background-color: #e5e7eb; max-height: 1px;")
        content_layout.addWidget(separator)

        # Chat history with modern styling
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setPlaceholderText("Start a conversation...")
        self.chat_history.setStyleSheet("""
            QTextEdit {
                background-color: #fafafa;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                padding: 12px;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        # The history pane and the input pane are wrapped in a
        # vertical QSplitter — built below — so the user can drag
        # the handle to resize the prompt area with the mouse. The
        # +/- preset buttons just nudge the splitter to a row count.
        # _GrippedSplitter is QSplitter with a handle that paints
        # three centered grip dots — makes the drag target obvious
        # so the user discovers they can resize the prompt area.
        self._chat_splitter = _GrippedSplitter(
            Qt.Orientation.Vertical)
        self._chat_splitter.setChildrenCollapsible(False)
        # Wide, visibly-styled handle so users discover that they
        # can drag-resize the prompt vs the history. With the old
        # 6px handle + 2x12 margin, the actual visible drag target
        # was a thin grey hairline — easy to miss. 10px tall, no
        # horizontal margins (full-width), centered grip lines, and
        # an indigo hover make it impossible to miss.
        self._chat_splitter.setHandleWidth(10)
        self._chat_splitter.setStyleSheet(
            "QSplitter::handle:vertical { "
            "  background: #d1d5db; "
            "  border-top: 1px solid #9ca3af; "
            "  border-bottom: 1px solid #9ca3af; "
            "} "
            "QSplitter::handle:vertical:hover { "
            "  background: #6366f1; "
            "  border-color: #4f46e5; "
            "} "
            "QSplitter::handle:vertical:pressed { "
            "  background: #4f46e5; "
            "}")
        # The splitter sets the SizeVerCursor on its handle by
        # default, so hovering already shows the resize affordance
        # — combined with the wider handle + indigo hover above
        # the drag target is now obvious.
        self._chat_splitter.addWidget(self.chat_history)
        content_layout.addWidget(self._chat_splitter, stretch=1)

        # Prompt-height controls. Lets the user grow the prompt area
        # so they can see (and scroll through) more of a long prompt
        # without it getting clipped to one or two visible lines.
        # Internal scrollbar handles overflow within the prompt box.
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(4)

        size_hint = QLabel("Prompt height:")
        size_hint.setStyleSheet("font-size: 10px; color: #9ca3af;")
        size_row.addWidget(size_hint)

        size_btn_style = (
            "QPushButton { padding: 1px 8px; font-size: 11px;"
            "  border: 1px solid #d1d5db; border-radius: 4px;"
            "  background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6366f1; "
            "  color: #6366f1; }"
            "QPushButton:disabled { color: #d1d5db;"
            "  border-color: #f3f4f6; }")

        self.input_shrink_btn = QPushButton("−")
        self.input_shrink_btn.setStyleSheet(size_btn_style)
        self.input_shrink_btn.setToolTip(
            "Show fewer prompt lines at once (Ctrl+−). "
            "Long prompts still scroll inside the field.")
        self.input_shrink_btn.clicked.connect(
            lambda: self._step_input_rows(-_INPUT_ROWS_STEP))
        size_row.addWidget(self.input_shrink_btn)

        self.input_size_label = QLabel(
            f"{_INPUT_ROWS_DEFAULT} lines")
        self.input_size_label.setStyleSheet(
            "font-size: 10px; color: #6b7280; min-width: 50px;")
        self.input_size_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        size_row.addWidget(self.input_size_label)

        self.input_grow_btn = QPushButton("+")
        self.input_grow_btn.setStyleSheet(size_btn_style)
        self.input_grow_btn.setToolTip(
            "Show more prompt lines at once (Ctrl++). "
            "Useful when composing a long prompt.")
        self.input_grow_btn.clicked.connect(
            lambda: self._step_input_rows(_INPUT_ROWS_STEP))
        size_row.addWidget(self.input_grow_btn)

        self.input_size_reset_btn = QPushButton("Reset")
        self.input_size_reset_btn.setStyleSheet(size_btn_style)
        self.input_size_reset_btn.setToolTip(
            "Reset prompt to default height (Ctrl+0)")
        self.input_size_reset_btn.clicked.connect(
            lambda: self._set_input_rows(_INPUT_ROWS_DEFAULT))
        size_row.addWidget(self.input_size_reset_btn)
        size_row.addStretch()

        content_layout.addLayout(size_row)

        # Input panel — input field + action row in their own QWidget
        # so the splitter has two clean panes. Mouse-drag on the
        # splitter handle resizes the input vs the history.
        input_panel = QWidget()
        input_panel_layout = QVBoxLayout(input_panel)
        input_panel_layout.setContentsMargins(0, 0, 0, 0)
        input_panel_layout.setSpacing(4)

        # Input area — multi-line. Enter sends, Shift/Ctrl+Enter for
        # newline. Resize via mouse-drag on the splitter handle
        # above OR via the +/- presets / Ctrl++/−/0 shortcuts.
        # Long prompts scroll vertically inside the field.
        self.input_field = _ChatInput()
        self.input_field.setPlaceholderText("Ask me anything...")
        self.input_field.submit_requested.connect(self._send_message)
        self.input_field.rows_changed.connect(
            self._on_input_rows_changed)
        # Restore the user's preferred prompt height from prior session.
        self._input_settings = QSettings("WritingAid", "ChatWidget")
        saved_rows = int(self._input_settings.value(
            "inputRows", _INPUT_ROWS_DEFAULT))
        self.input_field.set_visible_rows(saved_rows)
        # set_visible_rows is a no-op when the value matches what was
        # set in the constructor, so push the label state once for the
        # default-restore case.
        self._on_input_rows_changed(self.input_field.visible_rows())
        input_panel_layout.addWidget(self.input_field, stretch=1)

        # Send / preview action row — sits under the input. Send is
        # primary; Preview opens a dialog showing exactly what the
        # AI will receive (system prompt + user-block + RAG-focused
        # selections + history) so the user can sanity-check the
        # context before paying for a model call.
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)
        action_row.addStretch()

        self.preview_btn = QPushButton("👁 Preview")
        self.preview_btn.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 11px; "
            " border: 1px solid #d1d5db; border-radius: 4px; "
            " background: white; color: #374151; }"
            "QPushButton:hover { border-color: #6366f1; "
            " color: #6366f1; }")
        self.preview_btn.setToolTip(
            "Open a popup showing the exact context the AI will "
            "receive when you Send — system prompt, user block, "
            "RAG-selected items for your current input, and "
            "conversation history. Useful for sanity-checking what "
            "the model can actually see.")
        self.preview_btn.clicked.connect(self._on_preview_clicked)
        action_row.addWidget(self.preview_btn)
        input_panel_layout.addLayout(action_row)

        self._chat_splitter.addWidget(input_panel)
        # Default split: history takes 3x what the input takes. The
        # user can drag the handle to bias either way.
        self._chat_splitter.setStretchFactor(0, 3)
        self._chat_splitter.setStretchFactor(1, 1)
        # Persist + restore splitter sizes across sessions.
        saved_sizes = self._input_settings.value(
            "chatSplitterSizes", "")
        try:
            if saved_sizes:
                # QSettings can return a list of strings or a single
                # string depending on the platform — handle both.
                if isinstance(saved_sizes, list):
                    parsed = [int(x) for x in saved_sizes]
                else:
                    parsed = [int(x) for x in
                              str(saved_sizes).split(",") if x]
                if parsed:
                    self._chat_splitter.setSizes(parsed)
        except Exception:
            pass
        # Save sizes whenever the user drags the handle.
        self._chat_splitter.splitterMoved.connect(
            lambda *_: self._save_chat_splitter_sizes())

        # Rating widget (hidden by default, shown after AI responses)
        self.rating_widget = QFrame()
        self.rating_widget.setStyleSheet("""
            QFrame {
                background-color: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 4px;
            }
        """)
        rating_layout = QHBoxLayout(self.rating_widget)
        rating_layout.setContentsMargins(8, 4, 8, 4)
        rating_layout.setSpacing(6)

        rating_label = QLabel("Rate this response:")
        rating_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        rating_layout.addWidget(rating_label)

        self.rating_excellent_btn = QPushButton("⭐ Excellent")
        self.rating_excellent_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.rating_excellent_btn.clicked.connect(lambda: self._rate_response(ConversationRating.EXCELLENT))
        rating_layout.addWidget(self.rating_excellent_btn)

        self.rating_good_btn = QPushButton("👍 Good")
        self.rating_good_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.rating_good_btn.clicked.connect(lambda: self._rate_response(ConversationRating.GOOD))
        rating_layout.addWidget(self.rating_good_btn)

        self.rating_skip_btn = QPushButton("Skip")
        self.rating_skip_btn.setStyleSheet("""
            QPushButton {
                background-color: #6b7280;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4b5563;
            }
        """)
        self.rating_skip_btn.clicked.connect(self._hide_rating_widget)
        rating_layout.addWidget(self.rating_skip_btn)

        rating_layout.addStretch()

        self.rating_widget.setVisible(False)  # Hidden by default
        content_layout.addWidget(self.rating_widget)

        # Send button with modern styling
        # Send and mic button row
        button_row = QHBoxLayout()
        button_row.setSpacing(6)

        send_button = QPushButton("Send")
        send_button.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 16px;
                font-weight: 500;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:pressed {
                background-color: #4338ca;
            }
        """)
        send_button.clicked.connect(self._send_message)
        button_row.addWidget(send_button)

        self.mic_button = QPushButton("🎤")
        self.mic_button.setToolTip("Voice input (Ctrl+Shift+V)")
        self.mic_button.setFixedSize(38, 38)
        self.mic_button.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
                font-size: 16px;
            }
            QPushButton:hover { background-color: #e5e7eb; }
        """)
        button_row.addWidget(self.mic_button)

        content_layout.addLayout(button_row)

        layout.addWidget(self.content_widget)

    def is_collapsed(self) -> bool:
        """Always-expanded shim — sidebar handles the collapse now.

        Retained so older call sites that asked the chat whether
        it was collapsed don't break; the sidebar container owns
        that state in the new layout.
        """
        return False

    def set_collapsed(self, collapsed: bool):
        """Set the collapsed state."""
        if collapsed != self._collapsed:
            self._toggle_collapse()

    def _on_mode_changed(self, index: int):
        """Handle mode selection change."""
        mode_value = self.mode_combo.itemData(index)
        self._current_mode = ChatMode(mode_value)

        # Update UI elements for new mode
        mode_info = CHAT_MODE_INFO[self._current_mode]
        self.subtitle.setText(mode_info["subtitle"])
        self.mode_description.setText(mode_info["description"])
        self.input_field.setPlaceholderText(mode_info["placeholder"])

        # Show/hide writer mode options
        is_writer_mode = self._current_mode == ChatMode.WRITER
        self.insert_mode_widget.setVisible(is_writer_mode and not self._has_selection)
        self.pov_widget.setVisible(is_writer_mode)
        self.selection_indicator.setVisible(is_writer_mode and self._has_selection)

        # Clear chat history when switching modes
        self.chat_history.clear()

        # Emit mode changed signal
        self.mode_changed.emit(mode_value)

    def _on_insert_mode_changed(self, index: int):
        """Handle insert mode selection change."""
        insert_value = self.insert_combo.itemData(index)
        self._insert_mode = WriterInsertMode(insert_value)

    def _on_output_mode_changed(self, index: int):
        """Handle output mode selection change (Full Text / Outline)."""
        output_value = self.output_combo.itemData(index)
        self._output_mode = WriterOutputMode(output_value)

    def update_selection_state(self, has_selection: bool):
        """Update UI based on whether editor has text selected.

        Args:
            has_selection: True if text is selected in the editor
        """
        self._has_selection = has_selection

        # Only relevant in Writer mode
        if self._current_mode == ChatMode.WRITER:
            self.insert_mode_widget.setVisible(not has_selection)
            self.selection_indicator.setVisible(has_selection)

    def get_insert_mode(self) -> str:
        """Get the current insert mode for Writer mode.

        Returns:
            Insert mode value, or 'replace_selection' if text is selected
        """
        if self._has_selection:
            return WriterInsertMode.REPLACE_SELECTION.value
        return self._insert_mode.value

    def get_output_mode(self) -> str:
        """Get the current Writer-mode output type (Full Text / Outline)."""
        return self._output_mode.value

    def get_current_mode(self) -> str:
        """Get the current chat mode value."""
        return self._current_mode.value

    def set_mode(self, mode: str):
        """Set the chat mode programmatically."""
        for i in range(self.mode_combo.count()):
            if self.mode_combo.itemData(i) == mode:
                self.mode_combo.setCurrentIndex(i)
                break

    def set_output_mode(self, output_mode: str):
        """Set the writer-output mode (Full Text / Outline)
        programmatically. Drives the combo box so the visible UI
        stays in sync — needed by the per-beat ✨ AI flow which
        forces the chat into Writer + Outline so the AI's
        phase=\"beat\" JSON routes through the outline JSON parser.
        """
        if not hasattr(self, "output_combo"):
            return
        for i in range(self.output_combo.count()):
            if self.output_combo.itemData(i) == output_mode:
                self.output_combo.setCurrentIndex(i)
                break

    def _send_message(self):
        """Send user message."""
        message = self.input_field.text().strip()
        if message:
            self.add_message("You", message)
            self.input_field.clear()
            insert_mode = self.get_insert_mode() if self._current_mode == ChatMode.WRITER else ""
            self.message_sent.emit(message, self._current_mode.value, insert_mode)

    def _on_preview_clicked(self):
        """Ask the host to show the context-preview dialog.

        The host (main_window) listens for ``preview_requested``,
        builds the chat-context dict + system prompt for the
        current message+mode, and opens the shared dialog. We pass
        the current input text (or empty string if not typed yet —
        the dialog can show a placeholder + warn the user that RAG
        won't fire without a real question).
        """
        message = self.input_field.text().strip()
        self.preview_requested.emit(
            message, self._current_mode.value)

    # — prompt-height helpers —
    def _step_input_rows(self, delta: int) -> None:
        """Grow / shrink the prompt by ``delta`` visible lines."""
        self._set_input_rows(self.input_field.visible_rows() + delta)

    def _set_input_rows(self, rows: int) -> None:
        """Apply a specific visible-row count to the prompt."""
        self.input_field.set_visible_rows(rows)

    def _on_input_rows_changed(self, rows: int) -> None:
        """Sync the row label, button enabled state, and saved pref.

        Also nudges the splitter so the input pane gets enough
        room for the requested row count — the user sees the
        +/- buttons resize the input even when the splitter
        currently gives the pane more or less space than the
        chosen row count would.
        """
        self.input_size_label.setText(
            f"{rows} line{'' if rows == 1 else 's'}")
        # Disable the at-bound buttons so the user sees they're capped.
        self.input_shrink_btn.setEnabled(rows > _INPUT_ROWS_MIN)
        self.input_grow_btn.setEnabled(rows < _INPUT_ROWS_MAX)
        try:
            self._input_settings.setValue("inputRows", rows)
        except Exception:
            pass
        # Sync splitter so the +/- preset actually changes the
        # visible height — the splitter would otherwise hold the
        # input pane at whatever the user dragged it to. Only
        # apply when we have a splitter (constructor ordering).
        if hasattr(self, '_chat_splitter'):
            try:
                fm = self.input_field.fontMetrics()
                line_h = fm.lineSpacing()
                desired_input = line_h * rows + 22 + 36  # input + button row
                sizes = self._chat_splitter.sizes()
                total = sum(sizes) or 400
                # Don't shrink the history below ~120 px even if the
                # user picked a giant row count — they can drag the
                # splitter for finer control if they really want.
                history_h = max(120, total - desired_input)
                self._chat_splitter.setSizes(
                    [history_h, total - history_h])
                self._save_chat_splitter_sizes()
            except Exception:
                pass

    def _save_chat_splitter_sizes(self) -> None:
        """Persist the current splitter sizes so they survive
        across sessions."""
        if not hasattr(self, '_chat_splitter'):
            return
        try:
            sizes = self._chat_splitter.sizes()
            self._input_settings.setValue(
                "chatSplitterSizes",
                ",".join(str(s) for s in sizes))
        except Exception:
            pass

    def add_message(self, sender: str, message: str, system_prompt: Optional[str] = None, original_response: Optional[str] = None):
        """Add message to chat history with modern bubble styling.

        Args:
            sender: "You" for user, "Assistant" for AI
            message: The message content (may be cleaned for display)
            system_prompt: Optional system prompt (for AI responses)
            original_response: Optional original AI response WITH tool calls (for training data)
        """
        is_user = sender == "You"

        # Track message for training data collection
        if is_user:
            # User message
            self._current_conversation.append({
                "role": "user",
                "content": message
            })
        else:
            # AI response - also track system prompt if provided
            if system_prompt:
                # Add system message at start if not already present
                if not self._current_conversation or self._current_conversation[0].get("role") != "system":
                    self._current_conversation.insert(0, {
                        "role": "system",
                        "content": system_prompt
                    })

            # CRITICAL: Save the ORIGINAL response with tool calls for training
            # If original_response is provided, use it; otherwise use the display message
            # This preserves creation blocks like <create_character>...</create_character>
            training_content = original_response if original_response else message

            self._current_conversation.append({
                "role": "assistant",
                "content": training_content
            })

        # Different styling for user vs AI
        if is_user:
            bubble_style = "background-color: #6366f1; color: white; border-radius: 12px 12px 4px 12px; padding: 8px 12px; margin: 4px 0 4px 40px; display: inline-block;"
            formatted = f'<div style="text-align: right;"><span style="{bubble_style}">{message}</span></div>'
        else:
            # Convert markdown to HTML for AI responses
            html_message = self._markdown_to_html(message)
            bubble_style = "background-color: white; color: #1a1a1a; border: 1px solid #e5e7eb; border-radius: 12px 12px 12px 4px; padding: 8px 12px; margin: 4px 40px 4px 0; display: inline-block;"
            formatted = f'<div style="text-align: left;"><span style="{bubble_style}"><strong style="color: #6366f1;">AI:</strong> {html_message}</span></div>'

            # Check if training is enabled to show rating widget
            settings = self._ai_config.get_settings()
            enable_training = settings.get("enable_conversation_collection", False)

            if enable_training:
                # Show rating widget for user to rate this response
                self.rating_widget.setVisible(True)

        self.chat_history.append(formatted)

    def _markdown_to_html(self, text: str) -> str:
        """Convert markdown in AI responses to HTML for display."""
        import re

        lines = text.split('\n')
        html_lines = []
        in_list = False
        in_code_block = False

        for line in lines:
            stripped = line.strip()

            # Code blocks (```)
            if stripped.startswith('```'):
                if in_code_block:
                    html_lines.append('</pre>')
                    in_code_block = False
                else:
                    if in_list:
                        html_lines.append('</ul>')
                        in_list = False
                    html_lines.append(
                        '<pre style="background-color: #f3f4f6; padding: 8px; '
                        'border-radius: 4px; font-family: monospace; font-size: 12px; '
                        'white-space: pre-wrap; margin: 4px 0;">')
                    in_code_block = True
                continue

            if in_code_block:
                # Escape HTML inside code blocks
                escaped = stripped.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                html_lines.append(escaped)
                continue

            # Headers
            if stripped.startswith('### '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                html_lines.append(
                    f'<div style="color: #4f46e5; font-weight: bold; font-size: 12px; '
                    f'margin-top: 10px; margin-bottom: 2px;">{stripped[4:]}</div>')
                continue
            if stripped.startswith('## '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                html_lines.append(
                    f'<div style="color: #4f46e5; font-weight: bold; font-size: 13px; '
                    f'margin-top: 12px; margin-bottom: 2px;">{stripped[3:]}</div>')
                continue
            if stripped.startswith('# '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                html_lines.append(
                    f'<div style="color: #312e81; font-weight: bold; font-size: 14px; '
                    f'margin-top: 14px; margin-bottom: 4px;">{stripped[2:]}</div>')
                continue

            # List items (- or *)
            if stripped.startswith('- ') or stripped.startswith('* '):
                if not in_list:
                    html_lines.append('<ul style="margin: 4px 0 4px 16px; padding: 0;">')
                    in_list = True
                item_text = stripped[2:]
                item_text = self._inline_markdown(item_text)
                html_lines.append(f'<li style="margin: 2px 0;">{item_text}</li>')
                continue

            # Numbered list items
            if re.match(r'^\d+\.\s', stripped):
                if not in_list:
                    html_lines.append('<ul style="margin: 4px 0 4px 16px; padding: 0;">')
                    in_list = True
                item_text = re.sub(r'^\d+\.\s', '', stripped)
                item_text = self._inline_markdown(item_text)
                html_lines.append(f'<li style="margin: 2px 0;">{item_text}</li>')
                continue

            # Close list if we hit a non-list line
            if in_list:
                html_lines.append('</ul>')
                in_list = False

            # Empty lines become breaks
            if not stripped:
                html_lines.append('<br>')
                continue

            # Regular paragraph with inline formatting
            p = self._inline_markdown(stripped)
            html_lines.append(f'<div style="margin: 3px 0; line-height: 1.5;">{p}</div>')

        if in_list:
            html_lines.append('</ul>')
        if in_code_block:
            html_lines.append('</pre>')

        return '\n'.join(html_lines)

    def _inline_markdown(self, text: str) -> str:
        """Convert inline markdown (bold, italic, code) to HTML."""
        import re
        # Bold
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        # Italic
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        # Inline code
        text = re.sub(
            r'`([^`]+)`',
            r'<code style="background-color: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-family: monospace; font-size: 12px;">\1</code>',
            text
        )
        return text

    def set_characters(self, characters: list):
        """Populate character POV dropdown from project characters.

        Args:
            characters: List of character objects with 'name' attribute
        """
        current_selection = self.char_pov_combo.currentData()
        self.char_pov_combo.clear()
        self.char_pov_combo.addItem("(From chapter)", "")

        for char in characters:
            name = getattr(char, 'name', str(char))
            self.char_pov_combo.addItem(name, name)

        # Restore selection if still valid
        if current_selection:
            for i in range(self.char_pov_combo.count()):
                if self.char_pov_combo.itemData(i) == current_selection:
                    self.char_pov_combo.setCurrentIndex(i)
                    break

    def get_character_pov(self) -> str:
        """Get the selected character POV.

        Returns:
            Character name or empty string if using chapter default
        """
        return self.char_pov_combo.currentData() or ""

    def get_writing_pov(self) -> str:
        """Get the selected writing POV.

        Returns:
            Writing POV value or empty string if using chapter default
        """
        return self.writing_pov_combo.currentData() or ""

    def get_writer_settings(self) -> dict:
        """Get all Writer mode settings.

        Returns:
            Dict with insert_mode, character_pov, writing_pov
        """
        return {
            "insert_mode": self.get_insert_mode(),
            "character_pov": self.get_character_pov(),
            "writing_pov": self.get_writing_pov()
        }

    def set_project_name(self, project_name: str):
        """Set the current project name for training data metadata.

        Args:
            project_name: Name of the current project
        """
        self._project_name = project_name

    def set_chapter_context(self, chapter_planning=None, chapter_title: str = None, chapter_number: int = None):
        """Set chapter context for style/voice metadata in training data.

        Args:
            chapter_planning: ChapterPlanning object with tone, voice, style, pacing
            chapter_title: Current chapter title
            chapter_number: Current chapter number
        """
        # Reset context
        self._chapter_context = {
            'tone': None,
            'voice': None,
            'style': None,
            'pacing': None,
            'narrative_pov': None,
            'character_pov': None,
            'chapter_title': chapter_title,
            'chapter_number': chapter_number
        }

        # Extract from chapter planning if provided
        if chapter_planning:
            if hasattr(chapter_planning, 'tone') and chapter_planning.tone:
                self._chapter_context['tone'] = chapter_planning.tone
            if hasattr(chapter_planning, 'voice') and chapter_planning.voice:
                self._chapter_context['voice'] = chapter_planning.voice
            if hasattr(chapter_planning, 'style') and chapter_planning.style:
                self._chapter_context['style'] = chapter_planning.style
            if hasattr(chapter_planning, 'pacing') and chapter_planning.pacing:
                self._chapter_context['pacing'] = chapter_planning.pacing
            if hasattr(chapter_planning, 'pov_character') and chapter_planning.pov_character:
                self._chapter_context['character_pov'] = chapter_planning.pov_character

    def _build_context_tags(self) -> List[str]:
        """Build list of context tags for training data categorization.

        Returns:
            List of tags describing this conversation context
        """
        tags = []

        # Add mode tag
        tags.append(f"mode:{self._current_mode.value}")

        # Add style tags if present
        if self._chapter_context.get('tone'):
            tags.append(f"tone:{self._chapter_context['tone'][:20]}")  # Truncate long values
        if self._chapter_context.get('voice'):
            tags.append(f"voice:{self._chapter_context['voice'][:20]}")
        if self._chapter_context.get('pacing'):
            tags.append(f"pacing:{self._chapter_context['pacing'][:20]}")

        # Add POV tags
        if self._chapter_context.get('narrative_pov'):
            tags.append(f"pov:{self._chapter_context['narrative_pov']}")
        if self._chapter_context.get('character_pov'):
            tags.append(f"character:{self._chapter_context['character_pov']}")

        # Add chapter tag if applicable
        if self._chapter_context.get('chapter_number'):
            tags.append(f"chapter:{self._chapter_context['chapter_number']}")

        return tags

    def _hide_rating_widget(self):
        """Hide the rating widget (skip rating)."""
        self.rating_widget.setVisible(False)
        # Clear current conversation without saving
        self._current_conversation = []

    def _rate_response(self, rating: ConversationRating):
        """Rate the current AI response and save to training data.

        Args:
            rating: The rating to assign (EXCELLENT or GOOD typically)
        """
        if not self._current_conversation:
            print("No conversation to rate")
            return

        # Hide rating widget
        self.rating_widget.setVisible(False)

        # Create metadata for this conversation
        settings = self._ai_config.get_settings()

        # Get current writer settings (POV)
        writer_settings = self.get_writer_settings()

        # Build comprehensive metadata including style/voice parameters
        metadata = ConversationMetadata(
            project_name=self._project_name or "Unknown Project",
            task_type=self._current_mode.value,  # general, chapter_focus, writer
            provider=settings.get("default_llm", "claude"),
            model_name=self._ai_config.get_model(settings.get("default_llm", "claude")),
            temperature=settings.get("temperature", 0.7),
            max_tokens=settings.get("max_tokens", 2000),

            # Style parameters (critical for learning author's voice)
            tone=self._chapter_context.get('tone'),
            voice=self._chapter_context.get('voice'),
            writing_style=self._chapter_context.get('style'),
            pacing=self._chapter_context.get('pacing'),

            # POV parameters (for narrative consistency)
            narrative_pov=self._chapter_context.get('narrative_pov') or writer_settings.get('writing_pov'),
            character_pov=self._chapter_context.get('character_pov') or writer_settings.get('character_pov'),

            # Chapter context
            chapter_title=self._chapter_context.get('chapter_title'),
            chapter_number=self._chapter_context.get('chapter_number'),

            # Add task-specific tags
            tags=self._build_context_tags()
        )

        # Create conversation from tracked messages
        conversation = create_conversation_from_messages(
            messages=self._current_conversation,
            metadata=metadata
        )

        # Rate it
        conversation.rating = rating
        conversation.rated_at = datetime.now()

        # Save to store
        try:
            conv_id = self._conversation_store.add_conversation(conversation)
            print(f"Saved rated conversation {conv_id} with rating: {rating.value}")

            # Show feedback to user
            self.chat_history.append(
                f'<div style="text-align: center; color: #10b981; font-size: 11px; margin: 4px 0;">'
                f'✓ Response rated as {rating.value.title()} and saved for training</div>'
            )

        except Exception as e:
            print(f"Failed to save conversation: {e}")
            self.chat_history.append(
                f'<div style="text-align: center; color: #ef4444; font-size: 11px; margin: 4px 0;">'
                f'Failed to save rating: {str(e)}</div>'
            )

        # ALSO mirror to the unified learning database tagged with the
        # chat mode so the Training Studio can combine rephrase, chat
        # writing assistance, and general chat data freely.
        try:
            self._log_chat_to_learning_db(rating)
        except Exception as e:
            print(f"[Chat] Could not mirror to learning DB: {e}")

        # Clear current conversation for next exchange
        self._current_conversation = []

    def _log_chat_to_learning_db(self, rating):
        """Mirror the just-rated chat turn into the unified learning DB.

        The chat already has its own ConversationStore for fully detailed
        replay. The learning DB stores the same prompt/response pair in
        the simple shape the Training Studio expects, so the user can
        combine chat data with rephrase data when fine-tuning.

        Gated by ``enable_chat_data_collection`` in OS settings.
        """
        from src.config.creativeos_config import get_creativeos_config
        if not get_creativeos_config().get(
                "enable_chat_data_collection", False):
            return

        # Find the most recent (user, assistant) pair in the conversation
        msgs = [m for m in self._current_conversation
                if m.get("role") in ("user", "assistant")]
        if len(msgs) < 2:
            return
        # Walk backwards for the last assistant message and the user
        # message immediately preceding it
        assistant_msg = None
        user_msg = None
        for i in range(len(msgs) - 1, -1, -1):
            if msgs[i]["role"] == "assistant" and assistant_msg is None:
                assistant_msg = msgs[i]
            elif msgs[i]["role"] == "user" and assistant_msg is not None:
                user_msg = msgs[i]
                break
        if not user_msg or not assistant_msg:
            return

        from src.data.rephrase_database import get_rephrase_database
        db = get_rephrase_database()
        # Map ConversationRating → our unified rating vocabulary
        rating_map = {
            "excellent": "excellent", "good": "good",
            "neutral": "neutral", "poor": "poor", "bad": "bad",
        }
        unified = rating_map.get(rating.value, "neutral")

        mode_name = self._current_mode.value if self._current_mode else "general"
        genre = self._chapter_context.get("genre", "") if self._chapter_context else ""
        db.log_chat(
            prompt=user_msg.get("content", ""),
            response=assistant_msg.get("content", ""),
            mode=mode_name,
            rating=unified,
            accepted=True,
            genre=genre,
            project_path=self._project_name or "",
        )

    def clear_conversation(self):
        """Clear the current conversation tracking (start fresh)."""
        self._current_conversation = []
        self.rating_widget.setVisible(False)

    def _clear_conversation(self):
        """Handle Clear button click — wipe display and notify MainWindow."""
        self.chat_history.clear()
        self._current_conversation = []
        self.rating_widget.setVisible(False)
        self.clear_requested.emit()
