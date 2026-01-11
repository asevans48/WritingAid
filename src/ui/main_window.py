"""Main application window for Writer Platform."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QMenuBar, QMenu, QFileDialog, QMessageBox,
    QToolBar, QStatusBar, QSplitter, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from pathlib import Path
from typing import Optional

from src.models.project import WriterProject, Manuscript
from src.ui.comprehensive_worldbuilding_widget import ComprehensiveWorldBuildingWidget
from src.ui.characters_widget import CharactersWidget
from src.ui.story_planning_widget import StoryPlanningWidget
from src.ui.manuscript_editor import ManuscriptEditor
from src.ui.image_generator_widget import ImageGeneratorWidget
from src.ui.grader_widget import GraderWidget
from src.ui.agent_manager_widget import AgentManagerWidget
from src.ui.settings_dialog import SettingsDialog
from src.ui.chat_widget import ChatWidget
from src.export.manuscript_exporter import ManuscriptExporter
from src.export.llm_context_exporter import LLMContextExporter
from src.ui.styles import get_modern_style, get_icon
from src.config import get_ai_config


class MainWindow(QMainWindow):
    """Main application window with all features."""

    project_changed = pyqtSignal()

    def __init__(self):
        """Initialize main window."""
        super().__init__()

        self.current_project: Optional[WriterProject] = None
        self.ai_config = get_ai_config()
        self.settings = self.ai_config.get_settings()

        # Apply modern stylesheet
        self.setStyleSheet(get_modern_style())

        self._init_ui()
        self._create_menus()
        self._create_minimal_toolbar()
        self._create_status_bar()

        # Start with new project
        self._new_project()

    def _init_ui(self):
        """Initialize user interface."""
        self.setWindowTitle("Writer Platform")
        self.setMinimumSize(800, 600)  # Reduced from 1200x800 for laptop compatibility

        # Create central widget with splitter for chat
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create splitter for main content and chat
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Create tab widget for main sections with modern styling
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setDocumentMode(True)  # Cleaner look
        self.tab_widget.setMovable(True)  # Allow tab reordering

        # Initialize section widgets
        self.worldbuilding_widget = ComprehensiveWorldBuildingWidget()
        self.characters_widget = CharactersWidget()
        self.story_planning_widget = StoryPlanningWidget()
        self.manuscript_editor = ManuscriptEditor()
        self.image_generator = ImageGeneratorWidget()
        self.grader_widget = GraderWidget()
        self.agent_manager = AgentManagerWidget()

        # Add tabs with icons for visual appeal
        self.tab_widget.addTab(self.manuscript_editor, f"{get_icon('manuscript')} Write")
        self.tab_widget.addTab(self.story_planning_widget, f"{get_icon('story')} Plot")
        self.tab_widget.addTab(self.characters_widget, f"{get_icon('characters')} Characters")
        self.tab_widget.addTab(self.worldbuilding_widget, f"{get_icon('worldbuilding')} World")
        self.tab_widget.addTab(self.image_generator, f"{get_icon('images')} Visuals")
        self.tab_widget.addTab(self.grader_widget, f"{get_icon('grader')} Critique")
        self.tab_widget.addTab(self.agent_manager, f"{get_icon('agents')} Publishing")

        # Create collapsible chat widget
        self.chat_widget = ChatWidget()
        self.chat_widget.setMaximumWidth(400)
        self.chat_widget.setMinimumWidth(300)

        # Add to splitter
        self.main_splitter.addWidget(self.tab_widget)
        self.main_splitter.addWidget(self.chat_widget)

        # Set initial splitter sizes (3:1 ratio)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(self.main_splitter)

        # Connect signals
        self._connect_signals()

    def _create_menus(self):
        """Create application menus."""
        menubar = self.menuBar()

        # File menu
        file_menu = menubar.addMenu("&File")

        new_action = QAction("&New Project", self)
        new_action.setShortcut(QKeySequence.StandardKey.New)
        new_action.triggered.connect(self._new_project)
        file_menu.addAction(new_action)

        open_action = QAction("&Open Project", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self._open_project)
        file_menu.addAction(open_action)

        save_action = QAction("&Save Project", self)
        save_action.setShortcut(QKeySequence.StandardKey.Save)
        save_action.triggered.connect(self._save_project)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save Project &As...", self)
        save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as_action.triggered.connect(self._save_project_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Edit menu
        edit_menu = menubar.addMenu("&Edit")

        settings_action = QAction("&Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._show_settings)
        edit_menu.addAction(settings_action)

        # View menu
        view_menu = menubar.addMenu("&View")

        toggle_chat_action = QAction("Toggle &Chat", self)
        toggle_chat_action.setShortcut(QKeySequence("Ctrl+B"))
        toggle_chat_action.triggered.connect(self._toggle_chat)
        view_menu.addAction(toggle_chat_action)

        # Export menu
        export_menu = menubar.addMenu("E&xport")

        export_kindle_action = QAction("Export for &Kindle", self)
        export_kindle_action.triggered.connect(lambda: self._export_manuscript("kindle"))
        export_menu.addAction(export_kindle_action)

        export_bn_action = QAction("Export for &Barnes && Noble", self)
        export_bn_action.triggered.connect(lambda: self._export_manuscript("barnes_noble"))
        export_menu.addAction(export_bn_action)

        export_publisher_action = QAction("Export &Publisher Ready", self)
        export_publisher_action.triggered.connect(lambda: self._export_manuscript("publisher"))
        export_menu.addAction(export_publisher_action)

        export_docx_action = QAction("Export as &Word Document", self)
        export_docx_action.triggered.connect(lambda: self._export_manuscript("docx"))
        export_menu.addAction(export_docx_action)

        export_menu.addSeparator()

        export_llm_action = QAction("Export for &LLM Context (Markdown)", self)
        export_llm_action.setToolTip("Export worldbuilding, plot, and characters as markdown for AI context")
        export_llm_action.triggered.connect(self._export_llm_context)
        export_menu.addAction(export_llm_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        about_action = QAction("&About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _create_minimal_toolbar(self):
        """Create minimal, modern toolbar."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(toolbar.iconSize() * 0.9)  # Slightly smaller icons
        self.addToolBar(toolbar)

        # Project name label (editable feel)
        self.project_name_label = QLabel("Untitled Project")
        self.project_name_label.setProperty("heading", True)
        self.project_name_label.setStyleSheet("padding: 4px 12px; font-size: 18px; font-weight: 600;")
        toolbar.addWidget(self.project_name_label)

        toolbar.addSeparator()

        # Minimal action buttons with icons
        save_action = QAction(f"{get_icon('save')} Save", self)
        save_action.setToolTip("Save Project (Ctrl+S)")
        save_action.triggered.connect(self._save_project)
        toolbar.addAction(save_action)

        export_action = QAction(f"{get_icon('export')} Export", self)
        export_action.setToolTip("Export manuscript")
        export_action.triggered.connect(lambda: self._export_manuscript("publisher"))
        toolbar.addAction(export_action)

        toolbar.addSeparator()

        # AI toggle
        ai_action = QAction(f"{get_icon('ai')} AI", self)
        ai_action.setToolTip("Toggle AI Assistant (Ctrl+B)")
        ai_action.triggered.connect(self._toggle_chat)
        toolbar.addAction(ai_action)

    def _create_status_bar(self):
        """Create status bar."""
        self.statusBar().showMessage("Ready")

    def _connect_signals(self):
        """Connect signals between widgets."""
        # Connect project changes
        self.worldbuilding_widget.content_changed.connect(self._on_content_changed)
        self.characters_widget.content_changed.connect(self._on_content_changed)
        self.story_planning_widget.content_changed.connect(self._on_content_changed)
        self.manuscript_editor.content_changed.connect(self._on_content_changed)

        # Connect chat to AI assistance
        self.chat_widget.message_sent.connect(self._handle_chat_message)

    def _new_project(self):
        """Create new project."""
        if self.current_project and not self._confirm_unsaved_changes():
            return

        from PyQt6.QtWidgets import QInputDialog

        project_name, ok = QInputDialog.getText(
            self, "New Project", "Enter project name:"
        )

        if ok and project_name:
            self.current_project = WriterProject(
                name=project_name,
                manuscript=Manuscript(title=project_name)
            )
            self._load_project_into_ui()
            self.project_name_label.setText(project_name)
            self.statusBar().showMessage(f"Created new project: {project_name}")

    def _open_project(self):
        """Open existing project."""
        if self.current_project and not self._confirm_unsaved_changes():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Project",
            "",
            "Writer Project Files (*.writerproj);;All Files (*)"
        )

        if file_path:
            try:
                self.current_project = WriterProject.load_project(file_path)
                self._load_project_into_ui()
                self.project_name_label.setText(self.current_project.name)
                self.statusBar().showMessage(f"Opened: {file_path}")
            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Error Opening Project",
                    f"Failed to open project:\n{str(e)}"
                )

    def _save_project(self):
        """Save current project."""
        if not self.current_project:
            return

        if self.current_project.project_path:
            self._save_to_path(self.current_project.project_path)
        else:
            self._save_project_as()

    def _save_project_as(self):
        """Save project to new location."""
        if not self.current_project:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Project As",
            f"{self.current_project.name}.writerproj",
            "Writer Project Files (*.writerproj);;All Files (*)"
        )

        if file_path:
            self._save_to_path(file_path)

    def _save_to_path(self, file_path: str):
        """Save project to specified path."""
        try:
            self._collect_project_data()
            self.current_project.save_project(file_path)
            self.statusBar().showMessage(f"Saved: {file_path}")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Saving Project",
                f"Failed to save project:\n{str(e)}"
            )

    def _load_project_into_ui(self):
        """Load current project data into UI widgets."""
        if not self.current_project:
            return

        # Set project reference on manuscript editor for RAG
        self.manuscript_editor.set_project(self.current_project)

        self.worldbuilding_widget.load_data(self.current_project.worldbuilding)
        self.characters_widget.load_data(self.current_project.characters)
        self.story_planning_widget.load_data(self.current_project.story_planning)
        self.manuscript_editor.load_manuscript(self.current_project.manuscript)
        self.image_generator.load_data(self.current_project.generated_images)
        self.agent_manager.load_data(self.current_project.agent_contacts)

        self.project_changed.emit()

    def _collect_project_data(self):
        """Collect data from UI widgets into project model."""
        if not self.current_project:
            return

        self.current_project.worldbuilding = self.worldbuilding_widget.get_data()
        self.current_project.characters = self.characters_widget.get_data()
        self.current_project.story_planning = self.story_planning_widget.get_data()
        self.current_project.manuscript = self.manuscript_editor.get_manuscript()
        self.current_project.generated_images = self.image_generator.get_data()
        self.current_project.agent_contacts = self.agent_manager.get_data()

    def _confirm_unsaved_changes(self) -> bool:
        """Ask user to confirm discarding unsaved changes."""
        reply = QMessageBox.question(
            self,
            "Unsaved Changes",
            "Do you want to save changes to the current project?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )

        if reply == QMessageBox.StandardButton.Save:
            self._save_project()
            return True
        elif reply == QMessageBox.StandardButton.Discard:
            return True
        else:
            return False

    def _on_content_changed(self):
        """Handle content changes in any widget."""
        # Mark project as modified
        if self.current_project:
            window_title = f"Writer Platform - {self.current_project.name}*"
            self.setWindowTitle(window_title)

    def _toggle_chat(self):
        """Toggle chat widget visibility."""
        if self.chat_widget.isVisible():
            self.chat_widget.hide()
        else:
            self.chat_widget.show()

    def _handle_chat_message(self, message: str):
        """Handle chat message from user."""
        # TODO: Integrate with AI client
        self.chat_widget.add_message("Assistant", "AI integration pending...")

    def _show_settings(self):
        """Show settings dialog."""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec():
            self.settings = dialog.get_settings()
            # Save settings persistently
            if self.ai_config.save_settings(self.settings):
                self.statusBar().showMessage("AI settings saved successfully", 3000)
            else:
                QMessageBox.warning(
                    self,
                    "Save Error",
                    "Failed to save AI settings. Check permissions."
                )

    def _export_manuscript(self, format_type: str):
        """Export manuscript in specified format."""
        if not self.current_project or not self.current_project.manuscript.chapters:
            QMessageBox.warning(
                self,
                "No Content",
                "No manuscript content to export."
            )
            return

        # Collect current manuscript data
        self._collect_project_data()

        # Determine file extension and filter
        extensions = {
            "kindle": ("epub", "EPUB Files (*.epub)"),
            "barnes_noble": ("epub", "EPUB Files (*.epub)"),
            "publisher": ("docx", "Word Documents (*.docx)"),
            "docx": ("docx", "Word Documents (*.docx)")
        }

        ext, file_filter = extensions.get(format_type, ("docx", "Word Documents (*.docx)"))

        # Get output file path
        default_name = f"{self.current_project.manuscript.title}.{ext}"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            f"Export Manuscript - {format_type.replace('_', ' ').title()}",
            default_name,
            file_filter
        )

        if not file_path:
            return

        # Export manuscript
        exporter = ManuscriptExporter(self.current_project.manuscript)

        try:
            success = False
            if format_type == "kindle":
                success = exporter.export_for_kindle(file_path)
            elif format_type == "barnes_noble":
                success = exporter.export_for_barnes_noble(file_path)
            elif format_type == "publisher":
                success = exporter.export_publisher_ready(file_path)
            elif format_type == "docx":
                success = exporter.export_to_docx(file_path)

            if success:
                stats = exporter.get_manuscript_statistics()
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Manuscript exported successfully!\n\n"
                    f"File: {file_path}\n"
                    f"Chapters: {stats['total_chapters']}\n"
                    f"Words: {stats['total_words']:,}\n"
                    f"Estimated Pages: {stats['estimated_pages']}"
                )
            else:
                QMessageBox.critical(
                    self,
                    "Export Failed",
                    "Failed to export manuscript. Check the console for details."
                )

        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"An error occurred during export:\n{str(e)}"
            )

    def _export_llm_context(self):
        """Export worldbuilding, plot, and characters to markdown for LLM context."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "No project loaded to export."
            )
            return

        # Collect current data from all widgets
        self._collect_project_data()

        # Get output file path
        default_name = f"{self.current_project.name}_LLM_Context.md"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export LLM Context",
            default_name,
            "Markdown Files (*.md);;All Files (*)"
        )

        if file_path:
            try:
                # Export to markdown
                markdown_content = LLMContextExporter.export_to_markdown(
                    self.current_project,
                    file_path
                )

                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"LLM context exported successfully to:\n{file_path}\n\n"
                    f"You can now use this markdown file to provide context to LLMs."
                )
                self.statusBar().showMessage(f"Exported LLM context to {file_path}")

            except Exception as e:
                QMessageBox.critical(
                    self,
                    "Export Error",
                    f"An error occurred during export:\n{str(e)}"
                )

    def _show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self,
            "About Writer Platform",
            "Writer Platform v1.0\n\n"
            "A comprehensive platform for writers to organize books, "
            "short stories, and media.\n\n"
            "Features worldbuilding, character development, story planning, "
            "manuscript editing, AI assistance, and more."
        )

    def closeEvent(self, event):
        """Handle window close event."""
        if self.current_project and not self._confirm_unsaved_changes():
            event.ignore()
        else:
            event.accept()
