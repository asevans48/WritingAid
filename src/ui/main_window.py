"""Main application window for Writer Platform."""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QMenuBar, QMenu, QFileDialog, QMessageBox,
    QToolBar, QStatusBar, QSplitter, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QPoint
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
from src.ui.attributions_tab import AttributionsTab
from src.ui.window_manager import WindowManager
from src.ui.secondary_window import SecondaryWindow
from src.ui.import_guide_dialog import ImportGuideDialog
from src.ui.json_import_dialog import JSONImportDialog
from src.export.manuscript_exporter import ManuscriptExporter
from src.export.llm_context_exporter import LLMContextExporter
from src.ui.export_summary_dialog import ExportSummaryDialog
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

        # Register with window manager
        self.window_manager = WindowManager()
        self.window_manager.set_main_window(self)

        # Apply modern stylesheet
        self.setStyleSheet(get_modern_style())

        self._init_ui()
        self._create_menus()
        self._create_minimal_toolbar()
        self._create_status_bar()

        # Try to load last project, or prompt for new one
        self._startup_load_project()

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

        # Enable context menu on tab bar for multi-window support
        self.tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tab_widget.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

        # Initialize section widgets
        self.worldbuilding_widget = ComprehensiveWorldBuildingWidget()
        self.characters_widget = CharactersWidget()
        self.story_planning_widget = StoryPlanningWidget()
        self.manuscript_editor = ManuscriptEditor()
        self.image_generator = ImageGeneratorWidget()
        self.grader_widget = GraderWidget()
        self.agent_manager = AgentManagerWidget()
        self.attributions_tab = AttributionsTab()

        # Connect attributions tab jump signal
        self.attributions_tab.jump_to_annotation.connect(self._jump_to_annotation)

        # Add tabs with icons for visual appeal
        self.tab_widget.addTab(self.manuscript_editor, f"{get_icon('manuscript')} Write")
        self.tab_widget.addTab(self.story_planning_widget, f"{get_icon('story')} Plot")
        self.tab_widget.addTab(self.characters_widget, f"{get_icon('characters')} Characters")
        self.tab_widget.addTab(self.worldbuilding_widget, f"{get_icon('worldbuilding')} World")
        self.tab_widget.addTab(self.attributions_tab, "📚 Attributions")
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

        view_menu.addSeparator()

        # Multi-window mode toggle
        self.multi_window_action = QAction("&Multi-Window Mode", self)
        self.multi_window_action.setCheckable(True)
        self.multi_window_action.setChecked(False)
        self.multi_window_action.setToolTip("Enable to detach tabs into separate windows")
        self.multi_window_action.triggered.connect(self._toggle_multi_window_mode)
        view_menu.addAction(self.multi_window_action)

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

        export_summary_action = QAction("Export Project &Summary...", self)
        export_summary_action.setToolTip("Export comprehensive project summary with optional AI/ML summarization")
        export_summary_action.triggered.connect(self._export_project_summary)
        export_menu.addAction(export_summary_action)

        # Help menu
        help_menu = menubar.addMenu("&Help")

        import_guide_action = QAction("&Import Guide (AI Prompts)", self)
        import_guide_action.setToolTip("Prompts to help build your project with ChatGPT, Claude, or other AI assistants")
        import_guide_action.triggered.connect(self._show_import_guide)
        help_menu.addAction(import_guide_action)

        import_json_action = QAction("Import &JSON Data...", self)
        import_json_action.setToolTip("Import AI-generated JSON data into your project")
        import_json_action.triggered.connect(self._show_json_import)
        help_menu.addAction(import_json_action)

        help_menu.addSeparator()

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

        # Connect annotation changes to update attributions tab
        self.manuscript_editor.annotations_changed.connect(self._on_annotations_changed)

        # Auto-save when switching chapters
        self.manuscript_editor.chapter_switched.connect(self._auto_save_project)

        # Connect chat to AI assistance
        self.chat_widget.message_sent.connect(self._handle_chat_message)

    def _startup_load_project(self):
        """Load last project on startup, or prompt for new one."""
        from pathlib import Path

        last_path = self.ai_config.get_last_project_path()

        if last_path and Path(last_path).exists():
            try:
                self.current_project = WriterProject.load_project(last_path)
                self._load_project_into_ui()
                self.project_name_label.setText(self.current_project.name)
                self.statusBar().showMessage(f"Loaded: {last_path}")
                return
            except Exception as e:
                # Failed to load, will prompt for new project
                QMessageBox.warning(
                    self,
                    "Could Not Load Project",
                    f"Failed to load last project:\n{last_path}\n\nError: {str(e)}\n\nPlease create a new project."
                )

        # No last project or failed to load - prompt for new one
        self._new_project()

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
                # Remember this project for next startup
                self.ai_config.set_last_project_path(file_path)
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
            # Remember this project for next startup
            self.ai_config.set_last_project_path(file_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error Saving Project",
                f"Failed to save project:\n{str(e)}"
            )

    def _auto_save_project(self):
        """Auto-save project (e.g., when switching chapters).

        Silently saves without showing status messages to avoid interrupting workflow.
        """
        if not self.current_project:
            return

        if self.current_project.project_path:
            try:
                self._collect_project_data()
                self.current_project.save_project(self.current_project.project_path)
                # Update window title to remove unsaved indicator
                self.setWindowTitle(f"Writer Platform - {self.current_project.name}")
            except Exception as e:
                # Log error but don't interrupt user
                print(f"Auto-save failed: {e}")

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
        self.attributions_tab.set_manuscript(self.current_project.manuscript)

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

    def _on_annotations_changed(self):
        """Handle annotation changes - update attributions tab."""
        if self.current_project:
            self.attributions_tab.set_manuscript(self.current_project.manuscript)
            self._on_content_changed()

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

    def _export_project_summary(self):
        """Export project as a comprehensive summary with optional AI/ML summarization."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "No project loaded to export."
            )
            return

        # Show export dialog
        dialog = ExportSummaryDialog(self.current_project, self)
        dialog.exec()

    def _show_import_guide(self):
        """Show the import guide dialog with AI prompts."""
        dialog = ImportGuideDialog(self)
        dialog.exec()

    def _show_json_import(self):
        """Show the JSON import dialog."""
        if not self.current_project:
            QMessageBox.warning(
                self,
                "No Project",
                "Please create or open a project before importing data."
            )
            return

        dialog = JSONImportDialog(self, self.current_project)
        dialog.data_imported.connect(self._on_json_imported)
        dialog.exec()

    def _on_json_imported(self, imported_data: dict):
        """Handle successful JSON import."""
        # Refresh all widgets to show imported data
        self._load_project_into_ui()
        self.statusBar().showMessage("Data imported successfully", 5000)

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

    def _jump_to_annotation(self, chapter_id: str, annotation_id: str):
        """Jump to specific annotation in manuscript editor."""
        # Switch to Write tab
        self.tab_widget.setCurrentWidget(self.manuscript_editor)

        # Find and select the chapter in manuscript editor
        for i in range(self.manuscript_editor.chapter_list.count()):
            item = self.manuscript_editor.chapter_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == chapter_id:
                self.manuscript_editor.chapter_list.setCurrentItem(item)

                # Wait for chapter to load, then jump to annotation
                if self.manuscript_editor.current_chapter_editor:
                    # Find the annotation to get its line number
                    annotation = next(
                        (a for a in self.manuscript_editor.current_chapter_editor.chapter.annotations
                         if a.id == annotation_id),
                        None
                    )
                    if annotation:
                        self.manuscript_editor.current_chapter_editor._jump_to_line(annotation.line_number)
                break

    def _toggle_multi_window_mode(self, checked: bool):
        """Toggle multi-window mode on/off."""
        self.window_manager.set_multi_window_mode(checked)

        if not checked:
            # Merge all tabs back to main window
            self._merge_all_secondary_windows()
            self.statusBar().showMessage("Multi-window mode disabled", 3000)
        else:
            self.statusBar().showMessage(
                "Multi-window mode enabled - Right-click tabs to create new windows",
                5000
            )

    def _merge_all_secondary_windows(self):
        """Merge all secondary windows back to main window."""
        for window in self.window_manager.get_secondary_windows():
            window.close()  # closeEvent will merge tabs back

    def _show_tab_context_menu(self, pos: QPoint):
        """Show context menu for tab operations."""
        tab_bar = self.tab_widget.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index == -1:
            return

        menu = QMenu(self)

        # Only show Create New Window if multi-window mode is enabled
        if self.window_manager.is_multi_window_mode():
            # Don't allow detaching the last tab
            if self.tab_widget.count() > 1:
                detach_action = menu.addAction("Create New Window")
                detach_action.triggered.connect(lambda: self._detach_tab_to_new_window(tab_index))

        if not menu.isEmpty():
            menu.exec(tab_bar.mapToGlobal(pos))

    def _detach_tab_to_new_window(self, tab_index: int):
        """Detach a tab to a new secondary window."""
        if tab_index < 0 or tab_index >= self.tab_widget.count():
            return

        # Don't allow detaching the last tab
        if self.tab_widget.count() <= 1:
            QMessageBox.warning(
                self,
                "Cannot Detach",
                "Cannot detach the last tab from the main window."
            )
            return

        # Get widget and label
        widget = self.tab_widget.widget(tab_index)
        label = self.tab_widget.tabText(tab_index)

        # Remove from main window
        widget.setParent(None)
        self.tab_widget.removeTab(tab_index)

        # Create new secondary window
        project_name = self.current_project.name if self.current_project else "Writer Platform"
        new_window = SecondaryWindow(project_name, self)
        new_window.add_tab(widget, label)
        new_window.tab_merge_requested.connect(self._handle_tab_merge)
        new_window.show()

        self.statusBar().showMessage(f"Created new window with '{label}' tab", 3000)

    def _handle_tab_merge(self, widget: QWidget, label: str):
        """Handle merging a tab back from a secondary window."""
        self.tab_widget.addTab(widget, label)
        self.statusBar().showMessage(f"Merged '{label}' tab back to main window", 3000)

    def closeEvent(self, event):
        """Handle window close event."""
        if self.current_project and not self._confirm_unsaved_changes():
            event.ignore()
        else:
            # Close all secondary windows
            self.window_manager.close_all_secondary_windows()
            event.accept()
