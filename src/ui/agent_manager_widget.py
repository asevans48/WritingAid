"""Agent management widget for literary agents and publishing."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QGroupBox,
    QFormLayout, QMessageBox, QInputDialog
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import List
import uuid

from src.models.project import AgentContact


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
        layout = QVBoxLayout(self)

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
        self.notes_edit.setPlaceholderText("Notes about this agent or agency...")
        self.notes_edit.textChanged.connect(self.content_changed.emit)
        notes_layout.addWidget(self.notes_edit)

        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # Send email button
        email_button = QPushButton("Compose Email to Agent")
        email_button.clicked.connect(self._compose_email)
        layout.addWidget(email_button)

    def _load_agent(self):
        """Load agent data."""
        self.name_edit.setText(self.agent.name)
        self.agency_edit.setText(self.agent.agency)
        self.email_edit.setText(self.agent.email)
        self.phone_edit.setText(self.agent.phone)
        self.notes_edit.setPlainText(self.agent.notes)

    def _compose_email(self):
        """Compose email to agent."""
        # TODO: Integrate email functionality
        QMessageBox.information(
            self,
            "Email",
            f"Email composition to {self.agent.email} will be implemented soon."
        )

    def save_to_model(self):
        """Save widget data to agent model."""
        self.agent.name = self.name_edit.text()
        self.agent.agency = self.agency_edit.text()
        self.agent.email = self.email_edit.text()
        self.agent.phone = self.phone_edit.text()
        self.agent.notes = self.notes_edit.toPlainText()


class AgentManagerWidget(QWidget):
    """Widget for managing literary agents and publishing contacts."""

    content_changed = pyqtSignal()

    def __init__(self):
        """Initialize agent manager widget."""
        super().__init__()
        self.agents: List[AgentContact] = []
        self.current_agent_widget = None
        self._init_ui()

    def _init_ui(self):
        """Initialize user interface."""
        layout = QVBoxLayout(self)

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

        # Buttons
        button_layout = QHBoxLayout()

        add_button = QPushButton("Add")
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
        self.details_scroll.setWidget(QLabel("Add or select an agent/publisher"))

        content_layout.addWidget(self.details_scroll, stretch=1)

        layout.addLayout(content_layout)

        # Publishing actions
        publishing_group = QGroupBox("Publishing Actions")
        publishing_layout = QVBoxLayout()

        publish_kindle_button = QPushButton("Publish to Kindle Direct Publishing")
        publish_kindle_button.clicked.connect(lambda: self._publish_to_platform("Kindle"))
        publishing_layout.addWidget(publish_kindle_button)

        publish_bn_button = QPushButton("Publish to Barnes & Noble Press")
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
        if not current_item:
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

            self.details_scroll.setWidget(QLabel("Add or select an agent/publisher"))
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
        agent = next((a for a in self.agents if a.id == agent_id), None)

        if agent:
            self.current_agent_widget = AgentContactWidget(agent)
            self.current_agent_widget.content_changed.connect(self.content_changed.emit)
            self.details_scroll.setWidget(self.current_agent_widget)

    def _publish_to_platform(self, platform: str):
        """Publish manuscript to platform."""
        # TODO: Implement publishing integration
        QMessageBox.information(
            self,
            f"Publish to {platform}",
            f"Direct publishing to {platform} will be implemented soon.\n\n"
            "This will require API integration and formatting your manuscript "
            "according to platform requirements."
        )

    def load_data(self, agents: List[AgentContact]):
        """Load agent contacts."""
        self.agents = agents
        self.agent_list.clear()

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
