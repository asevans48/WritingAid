"""Agent management widget for literary agents and publishing."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QGroupBox,
    QFormLayout, QMessageBox, QInputDialog, QScrollArea
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import List
import uuid

from src.models.project import AgentContact
from src.ui import notify, ui_kit  # D.9: messages that need no click; D.8: one look


class AgentContactWidget(QWidget):
    """Widget for editing agent contact details."""

    content_changed = pyqtSignal()

    def __init__(self, agent: AgentContact):
        """Initialize agent contact widget."""
        super().__init__()
        self.agent = agent
        self._init_ui()
        self._load_agent()

    def _init_ui(self):
        """Initialize user interface."""
        # Main layout with scroll area
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area for all content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Content widget inside scroll area
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)

        # Contact info
        info_group = QGroupBox("Contact Information")
        info_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self.content_changed.emit)
        info_layout.addRow("Name:", self.name_edit)

        self.agency_edit = QLineEdit()
        self.agency_edit.textChanged.connect(self.content_changed.emit)
        info_layout.addRow("Agency:", self.agency_edit)

        self.email_edit = QLineEdit()
        self.email_edit.textChanged.connect(self.content_changed.emit)
        info_layout.addRow("Email:", self.email_edit)

        self.phone_edit = QLineEdit()
        self.phone_edit.textChanged.connect(self.content_changed.emit)
        info_layout.addRow("Phone:", self.phone_edit)

        info_group.setLayout(info_layout)
        layout.addWidget(info_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText(
            "Notes about this agent or agency... A line such as “Represents: gothic "
            "and literary horror” is used in your query letter.")
        self.notes_edit.textChanged.connect(self.content_changed.emit)
        notes_layout.addWidget(self.notes_edit)

        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # Send email button
        email_button = QPushButton("Compose Email to Agent")
        email_button.setToolTip("Opens a draft in your mail program: your query letter, "
                                "addressed to this agent. Nothing is sent.")
        email_button.clicked.connect(self._compose_email)
        layout.addWidget(email_button)

        # Set content widget to scroll area and add to main layout
        scroll_area.setWidget(content_widget)
        main_layout.addWidget(scroll_area)

    def _load_agent(self):
        """Load agent data."""
        self.name_edit.setText(self.agent.name)
        self.agency_edit.setText(self.agent.agency)
        self.email_edit.setText(self.agent.email)
        self.phone_edit.setText(self.agent.phone)
        self.notes_edit.setPlainText(self.agent.notes)

    manager = None          # the Publishing tab, for the project's query letter (9.3 addendum)

    def _compose_email(self):
        """A draft in the writer's mail program with the query letter
        addressed to this agent. Nothing is sent (9.3 addendum)."""
        self.save_to_model()
        from src.ui import query_email
        query_email.compose(self, self.agent, self.manager)

    def save_to_model(self):
        """Save widget data to agent model."""
        self.agent.name = self.name_edit.text()
        self.agent.agency = self.agency_edit.text()
        self.agent.email = self.email_edit.text()
        self.agent.phone = self.phone_edit.text()
        self.agent.notes = self.notes_edit.toPlainText()


class _FitLayout(QVBoxLayout):
    """The page's layout. A scroll area gives a page whose layout has
    height-for-width (word-wrapped labels) its full preferred height; this
    one asks only for its minimum, so the page fills the window as it did
    before and scrolls only when it truly can't fit (the package open on a
    small screen)."""

    def hasHeightForWidth(self) -> bool:
        return False


class AgentManagerWidget(QWidget):
    """Widget for managing literary agents and publishing contacts."""

    content_changed = pyqtSignal()

    PACKAGE = "__submission_package__"      # the list's first entry (9.3), never an agent

    def __init__(self):
        """Initialize agent manager widget."""
        super().__init__()
        self.agents: List[AgentContact] = []
        self.current_agent_widget = None
        self.project = None
        self.package_view = None             # made when first opened (9.3)
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        # The page scrolls when it outgrows the window (the submission
        # package needs room, 9.3); with nothing open it looks as before.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        page = QWidget()
        layout = _FitLayout(page)
        outer.addWidget(ui_kit.scrollable(page))

        # Header
        header = QLabel("Agent Management & Publishing")
        header.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        layout.addWidget(header)

        # Content layout
        content_layout = QHBoxLayout()

        # Left panel - agent list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        list_label = QLabel("Agents & Publishers")
        list_label.setStyleSheet("font-size: 14px; font-weight: bold; padding: 5px;")
        left_layout.addWidget(list_label)

        self.agent_list = QListWidget()
        self.agent_list.currentItemChanged.connect(self._on_agent_selected)
        left_layout.addWidget(self.agent_list)
        self._add_package_item()

        # Buttons
        button_layout = QHBoxLayout()

        add_button = ui_kit.main_button("Add")
        add_button.clicked.connect(self._add_agent)
        button_layout.addWidget(add_button)

        remove_button = QPushButton("Remove")
        remove_button.clicked.connect(self._remove_agent)
        button_layout.addWidget(remove_button)

        left_layout.addLayout(button_layout)

        left_panel.setMaximumWidth(250)
        content_layout.addWidget(left_panel)

        # Right panel - agent details
        from PyQt6.QtWidgets import QScrollArea

        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setWidget(ui_kit.empty_state("Add or select an agent/publisher"))

        content_layout.addWidget(self.details_scroll, stretch=1)

        layout.addLayout(content_layout)

        # Publishing actions
        publishing_group = QGroupBox("Publishing Actions")
        publishing_layout = QVBoxLayout()

        # The publishing route, per manuscript (piece 1.1).
        from src.ui.publishing_route import RouteForm
        self.route_form = RouteForm()
        # Beside it, the writer's name, pen name, phone, email and address
        # for the standard manuscript title page (9.2 addendum), stored as
        # typed. Side by side so the tab still fits a 600-pixel screen.
        from src.ui.writer_contact_form import ContactForm
        self.contact_form = ContactForm()
        self.contact_form.changed.connect(self.content_changed.emit)
        route_row = QHBoxLayout()
        route_row.addWidget(self.route_form, 1, Qt.AlignmentFlag.AlignTop)
        route_row.addWidget(self.contact_form, 1, Qt.AlignmentFlag.AlignTop)
        publishing_layout.addLayout(route_row)

        publish_kindle_button = QPushButton("Publish to Kindle Direct Publishing")
        publish_kindle_button.clicked.connect(lambda: self._publish_to_platform("Kindle"))
        publishing_layout.addWidget(publish_kindle_button)

        publish_bn_button = QPushButton("Publish to Barnes && Noble Press")   # "&&" shows one "&"
        publish_bn_button.clicked.connect(lambda: self._publish_to_platform("Barnes & Noble"))
        publishing_layout.addWidget(publish_bn_button)

        publishing_group.setLayout(publishing_layout)
        layout.addWidget(publishing_group)

    def _add_agent(self):
        """Add new agent contact."""
        name, ok = QInputDialog.getText(
            self,
            "New Agent/Publisher",
            "Enter name:"
        )

        if ok and name:
            agent = AgentContact(
                id=str(uuid.uuid4()),
                name=name
            )
            self.agents.append(agent)

            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, agent.id)
            self.agent_list.addItem(item)

            self.agent_list.setCurrentItem(item)
            self.content_changed.emit()

    def _remove_agent(self):
        """Remove selected agent."""
        current_item = self.agent_list.currentItem()
        if not current_item or current_item.data(Qt.ItemDataRole.UserRole) == self.PACKAGE:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete '{current_item.text()}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            agent_id = current_item.data(Qt.ItemDataRole.UserRole)
            self.agents = [a for a in self.agents if a.id != agent_id]

            row = self.agent_list.row(current_item)
            self.agent_list.takeItem(row)

            self.details_scroll.setWidget(ui_kit.empty_state("Add or select an agent/publisher"))
            self.content_changed.emit()

    def _on_agent_selected(self, current, previous):
        """Handle agent selection change."""
        if not current:
            return

        # Save previous agent
        if self.current_agent_widget:
            self.current_agent_widget.save_to_model()

        # Load selected agent
        agent_id = current.data(Qt.ItemDataRole.UserRole)
        from src.ui import submission_package_view as spv
        if spv.show_in(self, agent_id == self.PACKAGE):
            return
        agent = next((a for a in self.agents if a.id == agent_id), None)

        if agent:
            self.current_agent_widget = AgentContactWidget(agent)
            self.current_agent_widget.manager = self
            self.current_agent_widget.content_changed.connect(self.content_changed.emit)
            self.details_scroll.setWidget(self.current_agent_widget)

    def _publish_to_platform(self, platform: str):
        """Publish manuscript to platform."""
        # TODO: Implement publishing integration
        notify.empty(
            self,
            f"Publish to {platform}",
            f"Direct publishing to {platform} will be implemented soon.\n\n"
            "This will require API integration and formatting your manuscript "
            "according to platform requirements."
        )

    def set_project(self, project) -> None:
        """The project whose manuscripts' publishing routes are shown."""
        self.route_form.set_project(project)
        self.contact_form.set_project(project)
        self.project = project
        if self.package_view is not None:
            self.package_view.set_project(project)

    def _add_package_item(self):
        """The list's first entry opens the submission package (9.3)."""
        item = QListWidgetItem("📦 Submission package")
        item.setData(Qt.ItemDataRole.UserRole, self.PACKAGE)
        item.setToolTip("Synopsis, query letter, blurb, and readers and comparable titles")
        self.agent_list.addItem(item)

    def load_data(self, agents: List[AgentContact]):
        """Load agent contacts."""
        self.agents = agents
        self.agent_list.clear()
        self._add_package_item()
        if self.package_view is not None and self.details_scroll.widget() is self.package_view:
            self.agent_list.blockSignals(True)          # still showing: keep it chosen
            self.agent_list.setCurrentRow(0)
            self.agent_list.blockSignals(False)

        for agent in agents:
            item = QListWidgetItem(agent.name)
            item.setData(Qt.ItemDataRole.UserRole, agent.id)
            self.agent_list.addItem(item)

    def get_data(self) -> List[AgentContact]:
        """Get agent contacts data."""
        # Save current agent
        if self.current_agent_widget:
            self.current_agent_widget.save_to_model()

        return self.agents
