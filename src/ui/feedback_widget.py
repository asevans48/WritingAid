"""Feedback Widget - Collect and analyze reader/editor feedback for chapters."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QLabel, QFrame, QScrollArea, QLineEdit, QComboBox,
    QSizePolicy, QMessageBox, QProgressBar
)
from PyQt6.QtCore import pyqtSignal, Qt, QTimer
from PyQt6.QtGui import QFont, QTextCursor
from typing import Optional, Callable, List
import threading
import uuid
import copy

from src.ui.styles import SYSTEM_FONT


# Common feedback source presets
FEEDBACK_SOURCES = [
    "Beta Reader",
    "Editor",
    "Workshop",
    "Self",
    "Critique Partner",
    "Agent",
    "Other",
]


class FeedbackWidget(QWidget):
    """Widget for collecting and analyzing feedback on chapter writing."""

    feedback_changed = pyqtSignal()
    _ai_response_ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ai_handler: Optional[Callable] = None
        self._chapter_content_provider: Optional[Callable] = None
        self._feedback_data: list = []  # List of entry dicts
        self._entry_widgets: list = []
        self._is_processing = False
        self._current_callback: Optional[Callable] = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        title = QLabel("Feedback")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        header.addWidget(title)
        header.addStretch()

        self.add_feedback_btn = QPushButton("+ Feedback")
        self.add_feedback_btn.setFixedHeight(24)
        self.add_feedback_btn.setStyleSheet("font-size: 11px; padding: 2px 8px;")
        self.add_feedback_btn.clicked.connect(self._add_feedback_entry)
        header.addWidget(self.add_feedback_btn)
        layout.addLayout(header)

        # Scrollable area for feedback entries
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.container = QWidget()
        self.entries_layout = QVBoxLayout(self.container)
        self.entries_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.entries_layout.setSpacing(3)
        self.entries_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self.container)
        layout.addWidget(self.scroll)

        # AI analysis section (collapsible)
        analysis_frame = QFrame()
        analysis_frame.setStyleSheet("""
            QFrame#analysisFrame {
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background: #f9fafb;
            }
        """)
        analysis_frame.setObjectName("analysisFrame")
        analysis_layout = QVBoxLayout(analysis_frame)
        analysis_layout.setContentsMargins(6, 4, 6, 6)
        analysis_layout.setSpacing(4)

        analysis_header = QHBoxLayout()
        self.analysis_toggle = QPushButton("\u25bc Analysis")
        self.analysis_toggle.setStyleSheet(
            "border: none; font-weight: 600; font-size: 11px; color: #4f46e5; text-align: left; padding: 0;"
        )
        self.analysis_toggle.clicked.connect(self._toggle_analysis)
        analysis_header.addWidget(self.analysis_toggle)
        analysis_header.addStretch()

        self.analyze_btn = QPushButton("Analyze")
        self.analyze_btn.setFixedHeight(24)
        self.analyze_btn.setToolTip("Compare chapter against feedback using AI")
        self.analyze_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                font-size: 11px;
                padding: 2px 10px;
                border-radius: 3px;
            }
            QPushButton:hover { background-color: #4f46e5; }
            QPushButton:disabled { background-color: #9ca3af; }
        """)
        self.analyze_btn.clicked.connect(self._run_analysis)
        analysis_header.addWidget(self.analyze_btn)
        analysis_layout.addLayout(analysis_header)

        self.analysis_content = QWidget()
        analysis_content_layout = QVBoxLayout(self.analysis_content)
        analysis_content_layout.setContentsMargins(0, 0, 0, 0)
        analysis_content_layout.setSpacing(2)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setVisible(False)
        analysis_content_layout.addWidget(self.progress_bar)

        self.analysis_display = QTextEdit()
        self.analysis_display.setReadOnly(True)
        self.analysis_display.setPlaceholderText(
            "Click \"Analyze\" to compare your chapter against the collected feedback. "
            "The analysis will highlight which feedback points have been addressed "
            "and offer gentle suggestions — your creative vision always comes first."
        )
        self.analysis_display.setFont(QFont(SYSTEM_FONT, 10))
        self.analysis_display.setMinimumHeight(60)
        self.analysis_display.setMaximumHeight(200)
        self.analysis_display.setStyleSheet("border: none; background: transparent;")
        analysis_content_layout.addWidget(self.analysis_display)

        analysis_layout.addWidget(self.analysis_content)
        layout.addWidget(analysis_frame)

        self._analysis_visible = True

    # --- Public API ---

    def set_ai_handler(self, handler: Callable):
        self._ai_handler = handler

    def set_chapter_content_provider(self, provider: Callable):
        self._chapter_content_provider = provider

    def set_feedback_data(self, data: list):
        """Load feedback entries from data (list of dicts)."""
        self._feedback_data = data if isinstance(data, list) else []
        # Ensure backwards compat fields
        for entry in self._feedback_data:
            entry.setdefault('title', '')
            entry.setdefault('content', '')
            entry.setdefault('source', '')
            entry.setdefault('collapsed', False)
        self._refresh_entries()

    def get_feedback_data(self) -> list:
        """Return feedback data, saving in-progress edits."""
        self._save_current_entries()
        return copy.deepcopy(self._feedback_data)

    # --- Entry management ---

    def _add_feedback_entry(self):
        entry = {
            'id': uuid.uuid4().hex[:8],
            'title': '',
            'content': '',
            'source': '',
            'collapsed': False,
        }
        self._feedback_data.append(entry)
        self._add_entry_widget(entry, len(self._entry_widgets), focus_title=True)
        self.feedback_changed.emit()

    def _remove_entry(self, index: int):
        if 0 <= index < len(self._feedback_data):
            self._feedback_data.pop(index)
            self._refresh_entries()
            self.feedback_changed.emit()

    def _toggle_entry_collapsed(self, index: int):
        if 0 <= index < len(self._feedback_data):
            self._feedback_data[index]['collapsed'] = not self._feedback_data[index].get('collapsed', False)
            if index < len(self._entry_widgets):
                w = self._entry_widgets[index]
                collapsed = self._feedback_data[index]['collapsed']
                w['body_widget'].setVisible(not collapsed)
                w['toggle_btn'].setText("\u25b6" if collapsed else "\u25bc")

    def _save_current_entries(self):
        for i, w in enumerate(self._entry_widgets):
            if i < len(self._feedback_data):
                self._feedback_data[i]['title'] = w['title_edit'].text()
                self._feedback_data[i]['content'] = w['editor'].toPlainText()
                self._feedback_data[i]['source'] = w['source_combo'].currentText()

    def _refresh_entries(self):
        for w in self._entry_widgets:
            w['frame'].deleteLater()
        self._entry_widgets.clear()
        for i, entry in enumerate(self._feedback_data):
            self._add_entry_widget(entry, i)

    def _add_entry_widget(self, entry: dict, index: int, focus_title: bool = False):
        collapsed = entry.get('collapsed', False)
        title = entry.get('title', '')
        source = entry.get('source', '')

        # Prevent macOS from stealing window focus when new widgets appear
        wa_no_activate = Qt.WidgetAttribute.WA_ShowWithoutActivating

        frame = QFrame()
        frame.setAttribute(wa_no_activate)
        frame.setStyleSheet("""
            QFrame#fbCard {
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background: #fefefe;
            }
        """)
        frame.setObjectName("fbCard")
        frame_layout = QVBoxLayout(frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setAttribute(wa_no_activate)
        header.setStyleSheet("background: #fef3c7; border-top-left-radius: 4px; border-top-right-radius: 4px;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(6, 3, 4, 3)
        header_layout.setSpacing(4)

        toggle_btn = QPushButton("\u25b6" if collapsed else "\u25bc")
        toggle_btn.setFixedSize(18, 18)
        toggle_btn.setAttribute(wa_no_activate)
        toggle_btn.setStyleSheet("border: none; font-size: 9px; color: #92400e; padding: 0;")
        toggle_btn.clicked.connect(lambda _, idx=index: self._toggle_entry_collapsed(idx))
        header_layout.addWidget(toggle_btn)

        title_edit = QLineEdit(title)
        title_edit.setAttribute(wa_no_activate)
        title_edit.setPlaceholderText("Feedback title...")
        title_edit.setStyleSheet(
            "font-weight: 600; font-size: 11px; color: #92400e; background: transparent;"
            "border: none; padding: 0px 2px;"
        )
        title_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header_layout.addWidget(title_edit)

        del_btn = QPushButton("\u00d7")
        del_btn.setFixedSize(20, 18)
        del_btn.setToolTip("Remove feedback")
        del_btn.setAttribute(wa_no_activate)
        del_btn.setStyleSheet("border: none; font-size: 13px; font-weight: bold; color: #92400e; padding: 0;")
        del_btn.clicked.connect(lambda _, idx=index: self._remove_entry(idx))
        header_layout.addWidget(del_btn)

        frame_layout.addWidget(header)

        # Body
        body_widget = QWidget()
        body_widget.setAttribute(wa_no_activate)
        body_layout = QVBoxLayout(body_widget)
        body_layout.setContentsMargins(6, 4, 6, 6)
        body_layout.setSpacing(3)

        # Source selector
        source_row = QHBoxLayout()
        source_row.setSpacing(4)
        source_label = QLabel("Source:")
        source_label.setStyleSheet("font-size: 10px; color: #6b7280;")
        source_row.addWidget(source_label)
        source_combo = QComboBox()
        source_combo.setAttribute(wa_no_activate)
        source_combo.setEditable(True)
        source_combo.addItems(FEEDBACK_SOURCES)
        if source and source in FEEDBACK_SOURCES:
            source_combo.setCurrentText(source)
        elif source:
            source_combo.setCurrentText(source)
        else:
            source_combo.setCurrentIndex(-1)
            source_combo.lineEdit().setPlaceholderText("Select or type...")
        source_combo.setStyleSheet("font-size: 10px;")
        source_combo.setFixedHeight(22)
        source_row.addWidget(source_combo)
        source_row.addStretch()
        body_layout.addLayout(source_row)

        editor = QTextEdit()
        editor.setAttribute(wa_no_activate)
        editor.setPlainText(entry.get('content', ''))
        editor.setPlaceholderText("Paste or type feedback here...")
        editor.setFont(QFont(SYSTEM_FONT, 10))
        editor.setMinimumHeight(50)
        editor.setMaximumHeight(140)
        editor.setStyleSheet("border: 1px solid #e5e7eb; border-radius: 3px; background: white;")
        body_layout.addWidget(editor)

        body_widget.setVisible(not collapsed)
        frame_layout.addWidget(body_widget)

        # Add to layout first, then connect signals
        self.entries_layout.addWidget(frame)
        title_edit.textChanged.connect(lambda: self.feedback_changed.emit())
        editor.textChanged.connect(lambda: self.feedback_changed.emit())
        source_combo.currentTextChanged.connect(lambda: self.feedback_changed.emit())

        self._entry_widgets.append({
            'frame': frame,
            'editor': editor,
            'title_edit': title_edit,
            'source_combo': source_combo,
            'toggle_btn': toggle_btn,
            'body_widget': body_widget,
        })

        if focus_title:
            QTimer.singleShot(0, lambda: (title_edit.setFocus(), title_edit.selectAll()))

    # --- Analysis ---

    def _toggle_analysis(self):
        self._analysis_visible = not self._analysis_visible
        self.analysis_content.setVisible(self._analysis_visible)
        self.analysis_toggle.setText(
            "\u25bc Analysis" if self._analysis_visible else "\u25b6 Analysis"
        )

    def _run_analysis(self):
        if not self._ai_handler:
            QMessageBox.warning(self, "AI Not Available", "No AI model configured.")
            return

        self._save_current_entries()
        feedback_items = [e for e in self._feedback_data if e.get('content', '').strip()]
        if not feedback_items:
            QMessageBox.information(self, "No Feedback", "Add some feedback entries first.")
            return

        chapter_content = ""
        if self._chapter_content_provider:
            chapter_content = self._chapter_content_provider()
        if not chapter_content.strip():
            QMessageBox.information(self, "No Content", "Write some chapter content first.")
            return

        # Build feedback summary
        feedback_parts = []
        for entry in feedback_items:
            label = entry.get('title', '') or 'Untitled'
            source = entry.get('source', '')
            if source:
                label = f"{label} ({source})"
            feedback_parts.append(f"- {label}: {entry['content'].strip()}")
        feedback_text = "\n".join(feedback_parts)

        prompt = f"""You are a thoughtful writing assistant. A writer has collected feedback on their chapter and would like a gentle analysis.

IMPORTANT: This is the writer's creative work. Your role is to be helpful, not prescriptive. Frame everything as observations and possibilities, never demands.

CHAPTER CONTENT:
{chapter_content[:4000]}

COLLECTED FEEDBACK:
{feedback_text}

Please provide a brief, supportive analysis:
1. **Feedback addressed**: Which feedback points seem to already be reflected in the current draft? Acknowledge the writer's work.
2. **Worth considering**: Any feedback that might strengthen the chapter if the writer chooses to explore it? Frame as gentle suggestions, not requirements.
3. **Creative tensions**: Any feedback that might conflict with the writer's apparent intent? Note where the writer may want to trust their own vision.

Keep your response concise and respectful of the writer's craft. Use a warm, collegial tone."""

        self._set_processing(True)
        self.analysis_display.setPlainText("Analyzing...")

        def on_response(result):
            self._set_processing(False)
            if result:
                html = self._markdown_to_html(result)
                self.analysis_display.setHtml(html)
            else:
                self.analysis_display.setPlainText("Analysis could not be completed. Check your AI configuration.")

        self._current_callback = on_response
        try:
            self._ai_response_ready.disconnect(self._handle_ai_response)
        except:
            pass
        self._ai_response_ready.connect(self._handle_ai_response)

        def run():
            try:
                result = self._ai_handler(prompt, "Auto")
                self._ai_response_ready.emit(result)
            except Exception as e:
                print(f"Feedback analysis error: {e}")
                self._ai_response_ready.emit(None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    def _handle_ai_response(self, result):
        try:
            self._ai_response_ready.disconnect(self._handle_ai_response)
        except:
            pass
        if self._current_callback:
            self._current_callback(result)
            self._current_callback = None

    def _set_processing(self, active: bool):
        self._is_processing = active
        self.progress_bar.setVisible(active)
        self.analyze_btn.setEnabled(not active)
        self.add_feedback_btn.setEnabled(not active)

    def _markdown_to_html(self, text: str) -> str:
        """Simple markdown to HTML for analysis display."""
        import re
        import html as html_mod
        lines = text.strip().split('\n')
        html_lines = []
        in_list = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('**') and stripped.endswith('**'):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                inner = html_mod.escape(stripped[2:-2])
                html_lines.append(f'<div style="font-weight:bold;color:#4f46e5;margin-top:8px;">{inner}</div>')
                continue
            if stripped.startswith('## '):
                if in_list:
                    html_lines.append('</ul>')
                    in_list = False
                inner = html_mod.escape(stripped[3:])
                html_lines.append(f'<div style="font-weight:bold;color:#4f46e5;margin-top:8px;">{inner}</div>')
                continue
            if stripped.startswith('- ') or stripped.startswith('* '):
                if not in_list:
                    html_lines.append('<ul style="margin:4px 0 4px 16px;padding:0;">')
                    in_list = True
                item = self._inline_md(stripped[2:])
                html_lines.append(f'<li style="margin:2px 0;">{item}</li>')
                continue
            if re.match(r'^\d+\.\s', stripped):
                if not in_list:
                    html_lines.append('<ul style="margin:4px 0 4px 16px;padding:0;">')
                    in_list = True
                item = re.sub(r'^\d+\.\s', '', stripped)
                item = self._inline_md(item)
                html_lines.append(f'<li style="margin:2px 0;">{item}</li>')
                continue
            if in_list:
                html_lines.append('</ul>')
                in_list = False
            if not stripped:
                html_lines.append('<br>')
                continue
            html_lines.append(f'<div style="margin:3px 0;line-height:1.4;">{self._inline_md(stripped)}</div>')
        if in_list:
            html_lines.append('</ul>')
        return '\n'.join(html_lines)

    @staticmethod
    def _inline_md(text: str) -> str:
        import re
        import html as html_mod
        text = html_mod.escape(text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        return text
