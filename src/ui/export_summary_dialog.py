"""Dialog for exporting project as a summary with optional AI/ML summarization."""

from typing import Optional
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QRadioButton, QButtonGroup,
    QProgressBar, QTextEdit, QFileDialog, QMessageBox,
    QScrollArea, QWidget, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from src.models.project import WriterProject
from src.export.summary_exporter import (
    SummaryExporter, ProjectSummarizer, SummarizationMethod, ExportResult
)


class ExportWorker(QThread):
    """Background worker for export operation."""

    progress = pyqtSignal(str, int)  # message, percent
    finished = pyqtSignal(object)  # ExportResult

    def __init__(
        self,
        exporter: SummaryExporter,
        output_path: str,
        options: dict
    ):
        super().__init__()
        self.exporter = exporter
        self.output_path = output_path
        self.options = options

    def run(self):
        """Run the export in background."""
        result = self.exporter.export(
            output_path=self.output_path,
            include_manuscript=self.options.get('manuscript', True),
            include_worldbuilding=self.options.get('worldbuilding', True),
            include_characters=self.options.get('characters', True),
            include_plot=self.options.get('plot', True),
            include_promises=self.options.get('promises', True),
            summarize_chapters=self.options.get('summarize_chapters', False),
            progress_callback=self._emit_progress
        )
        self.finished.emit(result)

    def _emit_progress(self, message: str, percent: int):
        """Emit progress signal."""
        self.progress.emit(message, percent)


class ExportSummaryDialog(QDialog):
    """Dialog for configuring and running project summary export."""

    def __init__(self, project: WriterProject, parent=None):
        """Initialize export dialog.

        Args:
            project: The project to export
            parent: Parent widget
        """
        super().__init__(parent)
        self.project = project
        self.export_worker: Optional[ExportWorker] = None
        self.output_path: Optional[str] = None
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI."""
        self.setWindowTitle("Export Project Summary")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        # Header
        header = QLabel(f"<h2>Export: {self.project.name}</h2>")
        layout.addWidget(header)

        desc = QLabel(
            "Export your project as a comprehensive summary. "
            "Optionally use AI or ML to condense content."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #6b7280; margin-bottom: 10px;")
        layout.addWidget(desc)

        # Scroll area for options
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        options_widget = QWidget()
        options_layout = QVBoxLayout(options_widget)

        # Content selection
        content_group = QGroupBox("Content to Include")
        content_layout = QVBoxLayout(content_group)

        self.include_plot = QCheckBox("Plot Structure (events, subplots, themes)")
        self.include_plot.setChecked(True)
        content_layout.addWidget(self.include_plot)

        self.include_promises = QCheckBox("Story Promises (tone, plot, genre, character commitments)")
        self.include_promises.setChecked(True)
        content_layout.addWidget(self.include_promises)

        self.include_characters = QCheckBox("Characters (profiles, relationships)")
        self.include_characters.setChecked(True)
        content_layout.addWidget(self.include_characters)

        self.include_worldbuilding = QCheckBox("Worldbuilding (places, factions, cultures, etc.)")
        self.include_worldbuilding.setChecked(True)
        content_layout.addWidget(self.include_worldbuilding)

        self.include_manuscript = QCheckBox("Manuscript (chapter overviews)")
        self.include_manuscript.setChecked(True)
        content_layout.addWidget(self.include_manuscript)

        options_layout.addWidget(content_group)

        # Summarization method
        summary_group = QGroupBox("Summarization Method")
        summary_layout = QVBoxLayout(summary_group)

        self.summary_button_group = QButtonGroup(self)

        self.no_summary_radio = QRadioButton("None - Export raw data as-is")
        self.no_summary_radio.setChecked(True)
        self.summary_button_group.addButton(self.no_summary_radio, 0)
        summary_layout.addWidget(self.no_summary_radio)

        # AI option
        ai_layout = QHBoxLayout()
        self.ai_summary_radio = QRadioButton("AI Cloud - Use configured AI to summarize content")
        self.summary_button_group.addButton(self.ai_summary_radio, 1)
        ai_layout.addWidget(self.ai_summary_radio)

        self.ai_status_label = QLabel()
        self._update_ai_status()
        ai_layout.addWidget(self.ai_status_label)
        ai_layout.addStretch()
        summary_layout.addLayout(ai_layout)

        # ML option
        ml_layout = QHBoxLayout()
        self.ml_summary_radio = QRadioButton("ML Local - Use local BART model (slower, no API needed)")
        self.summary_button_group.addButton(self.ml_summary_radio, 2)
        ml_layout.addWidget(self.ml_summary_radio)

        self.ml_status_label = QLabel()
        self._update_ml_status()
        ml_layout.addWidget(self.ml_status_label)
        ml_layout.addStretch()
        summary_layout.addLayout(ml_layout)

        # Chapter summarization option
        self.summarize_chapters = QCheckBox("Summarize chapter content (only with AI/ML)")
        self.summarize_chapters.setEnabled(False)
        self.summarize_chapters.setToolTip("When enabled, chapter content will be summarized instead of showing excerpts")
        summary_layout.addWidget(self.summarize_chapters)

        # Connect radio buttons to update chapter option
        self.summary_button_group.buttonClicked.connect(self._on_summary_method_changed)

        options_layout.addWidget(summary_group)

        # Info about summarization
        info_frame = QFrame()
        info_frame.setStyleSheet("""
            QFrame {
                background-color: #f0f9ff;
                border: 1px solid #bae6fd;
                border-radius: 6px;
                padding: 10px;
            }
        """)
        info_layout = QVBoxLayout(info_frame)
        info_label = QLabel(
            "<b>About Summarization:</b><br/>"
            "• <b>None</b>: Full content exported, largest file size<br/>"
            "• <b>AI Cloud</b>: Uses your configured API (OpenAI/Anthropic/etc.) for high-quality summaries<br/>"
            "• <b>ML Local</b>: Uses facebook/bart-large-cnn model locally. "
            "First run downloads ~1.6GB model. No API costs."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet("font-size: 11px;")
        info_layout.addWidget(info_label)
        options_layout.addWidget(info_frame)

        options_layout.addStretch()
        scroll.setWidget(options_widget)
        layout.addWidget(scroll)

        # Progress section
        self.progress_frame = QFrame()
        self.progress_frame.setVisible(False)
        progress_layout = QVBoxLayout(self.progress_frame)

        self.progress_label = QLabel("Preparing export...")
        progress_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        progress_layout.addWidget(self.progress_bar)

        layout.addWidget(self.progress_frame)

        # Result preview
        self.result_frame = QFrame()
        self.result_frame.setVisible(False)
        result_layout = QVBoxLayout(self.result_frame)

        result_header = QLabel("<b>Export Result:</b>")
        result_layout.addWidget(result_header)

        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(150)
        result_layout.addWidget(self.result_text)

        layout.addWidget(self.result_frame)

        # Buttons
        button_layout = QHBoxLayout()

        self.export_btn = QPushButton("Export Summary...")
        self.export_btn.clicked.connect(self._start_export)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                padding: 10px 20px;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
            QPushButton:disabled {
                background-color: #9ca3af;
            }
        """)
        button_layout.addWidget(self.export_btn)

        button_layout.addStretch()

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        button_layout.addWidget(self.close_btn)

        layout.addLayout(button_layout)

    def _update_ai_status(self):
        """Update AI availability status."""
        try:
            from src.config import get_settings
            settings = get_settings()
            if settings.get('ai', {}).get('api_key'):
                self.ai_status_label.setText("✅ Configured")
                self.ai_status_label.setStyleSheet("color: #059669;")
            else:
                self.ai_status_label.setText("⚠️ No API key")
                self.ai_status_label.setStyleSheet("color: #d97706;")
        except:
            self.ai_status_label.setText("⚠️ Not available")
            self.ai_status_label.setStyleSheet("color: #d97706;")

    def _update_ml_status(self):
        """Update ML model availability status."""
        try:
            import transformers
            self.ml_status_label.setText("✅ Available")
            self.ml_status_label.setStyleSheet("color: #059669;")
        except ImportError:
            self.ml_status_label.setText("⚠️ Install: pip install transformers torch")
            self.ml_status_label.setStyleSheet("color: #d97706;")

    def _on_summary_method_changed(self, button):
        """Handle summary method change."""
        is_summarizing = button != self.no_summary_radio
        self.summarize_chapters.setEnabled(is_summarizing)
        if not is_summarizing:
            self.summarize_chapters.setChecked(False)

    def _start_export(self):
        """Start the export process."""
        # Get output file path
        default_name = f"{self.project.name}_Summary.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Summary",
            default_name,
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)"
        )

        if not file_path:
            return

        self.output_path = file_path

        # Determine summarization method
        if self.ai_summary_radio.isChecked():
            method = SummarizationMethod.AI_CLOUD
        elif self.ml_summary_radio.isChecked():
            method = SummarizationMethod.ML_LOCAL
        else:
            method = SummarizationMethod.NONE

        # Create summarizer
        summarizer = ProjectSummarizer(method)

        # Set up LLM client if using AI
        if method == SummarizationMethod.AI_CLOUD:
            try:
                from src.config import get_settings
                from src.ai.llm_client import LLMClient

                settings = get_settings()
                if not settings.get('ai', {}).get('api_key'):
                    QMessageBox.warning(
                        self,
                        "No API Key",
                        "AI summarization requires an API key.\n"
                        "Please configure one in Settings > AI Configuration."
                    )
                    return

                llm = LLMClient(
                    api_key=settings['ai']['api_key'],
                    provider=settings['ai'].get('provider', 'openai'),
                    model=settings['ai'].get('model', 'gpt-4o-mini')
                )
                summarizer.set_llm_client(llm)
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "AI Setup Failed",
                    f"Failed to initialize AI client: {e}\n\n"
                    "Falling back to no summarization."
                )
                summarizer = ProjectSummarizer(SummarizationMethod.NONE)

        # Create exporter
        exporter = SummaryExporter(self.project, summarizer)

        # Gather options
        options = {
            'manuscript': self.include_manuscript.isChecked(),
            'worldbuilding': self.include_worldbuilding.isChecked(),
            'characters': self.include_characters.isChecked(),
            'plot': self.include_plot.isChecked(),
            'promises': self.include_promises.isChecked(),
            'summarize_chapters': self.summarize_chapters.isChecked()
        }

        # Show progress
        self.progress_frame.setVisible(True)
        self.result_frame.setVisible(False)
        self.export_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        # Start export in background
        self.export_worker = ExportWorker(exporter, file_path, options)
        self.export_worker.progress.connect(self._on_progress)
        self.export_worker.finished.connect(self._on_export_finished)
        self.export_worker.start()

    def _on_progress(self, message: str, percent: int):
        """Handle progress update."""
        self.progress_label.setText(message)
        self.progress_bar.setValue(percent)

    def _on_export_finished(self, result: ExportResult):
        """Handle export completion."""
        self.export_btn.setEnabled(True)
        self.progress_frame.setVisible(False)
        self.result_frame.setVisible(True)

        if result.success:
            # Show success info
            lines = [
                f"<b>Export successful!</b><br/>",
                f"<b>File:</b> {result.file_path}<br/>",
                f"<b>Total Words:</b> {result.total_words:,}<br/>",
                f"<b>Method:</b> {result.summarization_method.value}<br/>",
                f"<br/><b>Sections:</b>"
            ]
            for section in result.sections:
                summarized = " (summarized)" if section.summarized else ""
                lines.append(f"• {section.title}: {section.word_count:,} words{summarized}")

            self.result_text.setHtml("<br/>".join(lines))

            QMessageBox.information(
                self,
                "Export Complete",
                f"Project summary exported successfully!\n\n"
                f"File: {result.file_path}\n"
                f"Total Words: {result.total_words:,}"
            )
        else:
            self.result_text.setHtml(
                f"<b style='color: red;'>Export failed!</b><br/>"
                f"<br/>Error: {result.error_message}"
            )

            QMessageBox.critical(
                self,
                "Export Failed",
                f"Failed to export summary:\n\n{result.error_message}"
            )
