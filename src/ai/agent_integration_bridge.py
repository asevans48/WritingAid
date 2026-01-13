"""Integration bridge between AI agents and manual UI tools.

This module provides seamless integration between the conversational AI agents
and the existing manual worldbuilding tools, allowing users to:
- Create elements through conversation and have them appear in manual editors
- Use AI suggestions as starting points for manual refinement
- Get AI recommendations while working in manual tools
- Switch between AI and manual workflows seamlessly
"""

from typing import Optional, Dict, Any, TYPE_CHECKING
from PyQt6.QtWidgets import QPushButton, QMessageBox, QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox
from PyQt6.QtCore import pyqtSignal, QObject
import uuid

if TYPE_CHECKING:
    from src.models.project import WriterProject, Character
    from src.models.worldbuilding_objects import Faction, Place
    from src.ai.agent_suite import AgentSuite
    from src.ai.chapter_analysis_agent import ChapterAnalysis


class AIAssistButton(QPushButton):
    """Custom button that triggers AI assistance for a specific context."""

    def __init__(self, context_type: str, parent=None):
        """Initialize AI assist button.

        Args:
            context_type: Type of assistance (character, faction, place, chapter, etc.)
            parent: Parent widget
        """
        super().__init__("✨ AI Assist", parent)
        self.context_type = context_type
        self.setToolTip(f"Get AI suggestions for this {context_type}")
        self.setStyleSheet("""
            QPushButton {
                background-color: #6366f1;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #4f46e5;
            }
        """)


class AISuggestionDialog(QDialog):
    """Dialog showing AI suggestions with option to apply."""

    def __init__(self, suggestion_text: str, element_type: str, parent=None):
        """Initialize suggestion dialog.

        Args:
            suggestion_text: The AI's suggestion text
            element_type: Type of element (character, faction, etc.)
            parent: Parent widget
        """
        super().__init__(parent)
        self.setWindowTitle(f"AI Suggestions - {element_type.title()}")
        self.resize(600, 400)

        layout = QVBoxLayout(self)

        # Suggestion display
        self.suggestion_text = QTextEdit()
        self.suggestion_text.setReadOnly(True)
        self.suggestion_text.setPlainText(suggestion_text)
        layout.addWidget(self.suggestion_text)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("Apply as Starting Point")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class AgentIntegrationBridge(QObject):
    """Bridge between AI agents and manual UI tools.

    This class provides methods to:
    - Apply AI suggestions to manual form fields
    - Trigger AI assistance from manual tools
    - Create elements from AI conversations
    - Enhance manual tools with AI capabilities
    """

    element_created = pyqtSignal(str, str)  # element_type, element_id

    def __init__(self, project: 'WriterProject', agent_suite: 'AgentSuite'):
        """Initialize integration bridge.

        Args:
            project: WriterProject to modify
            agent_suite: AgentSuite for AI operations
        """
        super().__init__()
        self.project = project
        self.agent_suite = agent_suite

    def create_character_from_ai(self, user_description: str) -> Optional['Character']:
        """Create character from AI conversation and add to project.

        Args:
            user_description: User's description of the character

        Returns:
            Created Character object, or None if failed
        """
        from src.models.project import Character

        try:
            # Get world context
            world_context = self._get_world_context()

            # Use agent to generate character data
            character_data = self.agent_suite.worldbuilding_agent.help_create_character(
                user_description=user_description,
                world_context=world_context
            )

            # Create character object
            character = Character(
                id=str(uuid.uuid4()),
                name=character_data.get('name', 'Unnamed Character'),
                character_type=character_data.get('character_type', 'Supporting'),
                personality=character_data.get('personality', ''),
                backstory='',  # User fills in after
                notes=character_data.get('notes', '')
            )

            # Add to project
            self.project.characters.append(character)

            # Emit signal
            self.element_created.emit('character', character.id)

            return character

        except Exception as e:
            print(f"Error creating character from AI: {e}")
            return None

    def create_faction_from_ai(self, user_description: str) -> Optional['Faction']:
        """Create faction from AI conversation and add to project.

        Args:
            user_description: User's description of the faction

        Returns:
            Created Faction object, or None if failed
        """
        from src.models.worldbuilding_objects import Faction, FactionType

        try:
            world_context = self._get_world_context()

            faction_data = self.agent_suite.worldbuilding_agent.help_create_faction(
                user_description=user_description,
                world_context=world_context
            )

            # Parse faction type from description
            faction_type = FactionType.OTHER
            type_str = faction_data.get('faction_type', '').lower()
            for ftype in FactionType:
                if ftype.value.lower() in type_str:
                    faction_type = ftype
                    break

            faction = Faction(
                id=str(uuid.uuid4()),
                name=faction_data.get('name', 'Unnamed Faction'),
                faction_type=faction_type,
                description=faction_data.get('description', ''),
                goals=faction_data.get('goals', ''),
                structure=faction_data.get('structure', ''),
                values=faction_data.get('values', '')
            )

            # Add to project
            if not hasattr(self.project.worldbuilding, 'factions'):
                self.project.worldbuilding.factions = []
            self.project.worldbuilding.factions.append(faction)

            self.element_created.emit('faction', faction.id)

            return faction

        except Exception as e:
            print(f"Error creating faction from AI: {e}")
            return None

    def create_place_from_ai(self, user_description: str) -> Optional['Place']:
        """Create place from AI conversation and add to project.

        Args:
            user_description: User's description of the place

        Returns:
            Created Place object, or None if failed
        """
        from src.models.worldbuilding_objects import Place, PlaceType

        try:
            world_context = self._get_world_context()

            # Get available planets
            planets = [p.name for p in getattr(self.project.worldbuilding, 'planets', [])]

            place_data = self.agent_suite.worldbuilding_agent.help_create_place(
                user_description=user_description,
                world_context=world_context,
                available_planets=planets
            )

            # Parse place type
            place_type = PlaceType.CITY
            type_str = place_data.get('place_type', '').lower()
            for ptype in PlaceType:
                if ptype.value.lower() in type_str:
                    place_type = ptype
                    break

            place = Place(
                id=str(uuid.uuid4()),
                name=place_data.get('name', 'Unnamed Place'),
                place_type=place_type,
                planet=place_data.get('planet', ''),
                description=place_data.get('description', ''),
                key_features=place_data.get('key_features', []),
                atmosphere=place_data.get('atmosphere', ''),
                story_relevance=place_data.get('story_relevance', ''),
                notes=place_data.get('notes', '')
            )

            # Add to project
            self.project.worldbuilding.places.append(place)

            self.element_created.emit('place', place.id)

            return place

        except Exception as e:
            print(f"Error creating place from AI: {e}")
            return None

    def apply_character_suggestions(
        self,
        character_widget,
        suggestion_text: str
    ) -> bool:
        """Apply AI suggestions to character form fields.

        Args:
            character_widget: CharacterWidget instance
            suggestion_text: AI suggestion text to parse and apply

        Returns:
            True if successfully applied
        """
        try:
            # Parse suggestions (simplified - could be more sophisticated)
            lines = suggestion_text.split('\n')

            for line in lines:
                if line.startswith('- Name:') or line.startswith('Name:'):
                    name = line.split(':', 1)[1].strip()
                    if name and '[' not in name:  # Avoid placeholders
                        character_widget.name_edit.setText(name)

                elif line.startswith('- Type:') or line.startswith('Type:'):
                    char_type = line.split(':', 1)[1].strip()
                    # Set combo box if valid type
                    index = character_widget.type_combo.findText(char_type, Qt.MatchFlag.MatchContains)
                    if index >= 0:
                        character_widget.type_combo.setCurrentIndex(index)

                elif line.startswith('- Personality:') or line.startswith('Personality:'):
                    personality = line.split(':', 1)[1].strip()
                    character_widget.personality_edit.setPlainText(personality)

            # Add full suggestion to notes
            current_notes = character_widget.notes_edit.toPlainText()
            separator = "\n\n---\nAI Suggestions:\n" if current_notes else "AI Suggestions:\n"
            character_widget.notes_edit.setPlainText(
                current_notes + separator + suggestion_text
            )

            return True

        except Exception as e:
            print(f"Error applying character suggestions: {e}")
            return False

    def get_ai_suggestions_for_form(
        self,
        element_type: str,
        current_data: Dict[str, Any],
        parent_widget
    ) -> Optional[str]:
        """Get AI suggestions for partially filled form.

        Args:
            element_type: Type of element (character, faction, place)
            current_data: Current form data
            parent_widget: Parent widget for dialog

        Returns:
            Suggestion text, or None if cancelled
        """
        from PyQt6.QtWidgets import QInputDialog

        # Ask user what they want help with
        prompt, ok = QInputDialog.getText(
            parent_widget,
            f"AI Assistance - {element_type.title()}",
            f"What would you like help with for this {element_type}?\n"
            f"(e.g., 'suggest personality traits', 'develop backstory', 'add conflict')"
        )

        if not ok or not prompt:
            return None

        # Build context from current data
        context = self._build_element_context(element_type, current_data)

        # Get world context
        world_context = self._get_world_context()

        # Get recommendations
        agent_response = self.agent_suite.worldbuilding_agent.get_recommendations(
            category=element_type,
            context=world_context + "\n\n" + context,
            question=prompt,
            existing_elements=None
        )

        # Show suggestions in dialog
        dialog = AISuggestionDialog(
            suggestion_text=agent_response.content,
            element_type=element_type,
            parent=parent_widget
        )

        if dialog.exec() == QDialog.DialogCode.Accepted:
            return agent_response.content
        else:
            return None

    def analyze_chapter_with_ui(
        self,
        chapter_text: str,
        chapter_title: str,
        parent_widget,
        detailed: bool = False
    ) -> Optional['ChapterAnalysis']:
        """Analyze chapter and show results in UI.

        Args:
            chapter_text: Full chapter text
            chapter_title: Chapter title
            parent_widget: Parent widget for dialogs
            detailed: Whether to do detailed analysis

        Returns:
            ChapterAnalysis object, or None if cancelled
        """
        from PyQt6.QtWidgets import QProgressDialog
        from PyQt6.QtCore import Qt

        # Show progress dialog
        progress = QProgressDialog(
            f"Analyzing chapter: {chapter_title}",
            "Cancel",
            0, 0,  # Indeterminate
            parent_widget
        )
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()

        try:
            # Perform analysis
            analysis = self.agent_suite.analyze_chapter_full(
                chapter_text=chapter_text,
                chapter_title=chapter_title,
                detailed=detailed
            )

            progress.close()

            # Show results
            self._show_chapter_analysis_dialog(analysis, chapter_title, parent_widget)

            return analysis

        except Exception as e:
            progress.close()
            QMessageBox.critical(
                parent_widget,
                "Analysis Error",
                f"Failed to analyze chapter:\n{str(e)}"
            )
            return None

    def _show_chapter_analysis_dialog(
        self,
        analysis: 'ChapterAnalysis',
        chapter_title: str,
        parent_widget
    ):
        """Show chapter analysis results in dialog."""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QLabel, QDialogButtonBox

        dialog = QDialog(parent_widget)
        dialog.setWindowTitle(f"Chapter Analysis - {chapter_title}")
        dialog.resize(700, 600)

        layout = QVBoxLayout(dialog)

        # Cost info
        cost_label = QLabel(f"Analysis Cost: ${analysis.estimated_cost:.4f}")
        cost_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(cost_label)

        # Analysis display
        analysis_text = QTextEdit()
        analysis_text.setReadOnly(True)

        # Format analysis
        formatted = f"""**OVERALL ASSESSMENT**
{analysis.overall_assessment}

**STRENGTHS**
"""
        for i, strength in enumerate(analysis.strengths, 1):
            formatted += f"{i}. {strength}\n"

        formatted += f"\n**AREAS FOR IMPROVEMENT**\n"
        for i, area in enumerate(analysis.areas_for_improvement, 1):
            formatted += f"{i}. {area}\n"

        formatted += f"\n**PACING NOTES**\n{analysis.pacing_notes}\n"
        formatted += f"\n**CHARACTER CONSISTENCY**\n{analysis.character_consistency_notes}\n"

        if analysis.line_item_suggestions:
            formatted += f"\n**LINE-ITEM SUGGESTIONS ({len(analysis.line_item_suggestions)})**\n\n"
            for i, suggestion in enumerate(analysis.line_item_suggestions, 1):
                formatted += f"{i}. Paragraph {suggestion.paragraph_number}\n"
                formatted += f"   Type: {suggestion.suggestion_type.value.replace('_', ' ').title()}\n"
                formatted += f"   Quote: \"{suggestion.original_text[:100]}...\"\n"
                formatted += f"   Suggestion: {suggestion.suggestion}\n"
                formatted += f"   Why: {suggestion.explanation}\n"
                formatted += f"   Priority: {suggestion.priority.upper()}\n\n"

        analysis_text.setPlainText(formatted)
        layout.addWidget(analysis_text)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)

        dialog.exec()

    def _get_world_context(self) -> str:
        """Get relevant world context from project."""
        if not self.project:
            return ""

        wb = self.project.worldbuilding
        parts = []

        if wb.mythology:
            parts.append(f"Mythology: {wb.mythology[:200]}")
        if wb.history:
            parts.append(f"History: {wb.history[:200]}")

        return "\n".join(parts)

    def _build_element_context(self, element_type: str, current_data: Dict[str, Any]) -> str:
        """Build context string from current form data."""
        if element_type == "character":
            return f"""
Current Character Data:
Name: {current_data.get('name', 'Not set')}
Type: {current_data.get('type', 'Not set')}
Personality: {current_data.get('personality', 'Not set')}
Backstory: {current_data.get('backstory', 'Not set')}
            """.strip()

        elif element_type == "faction":
            return f"""
Current Faction Data:
Name: {current_data.get('name', 'Not set')}
Type: {current_data.get('type', 'Not set')}
Description: {current_data.get('description', 'Not set')}
            """.strip()

        elif element_type == "place":
            return f"""
Current Place Data:
Name: {current_data.get('name', 'Not set')}
Type: {current_data.get('type', 'Not set')}
Description: {current_data.get('description', 'Not set')}
            """.strip()

        return ""


# Utility functions for adding AI assist buttons to existing widgets

def add_ai_assist_to_character_widget(character_widget, bridge: AgentIntegrationBridge):
    """Add AI assist button to character widget.

    Args:
        character_widget: CharacterWidget instance
        bridge: AgentIntegrationBridge instance
    """
    # Add AI assist button to personality section
    personality_group = None
    for child in character_widget.findChildren(QWidget):
        if isinstance(child, QWidget) and child.objectName() == "personality_group":
            personality_group = child
            break

    if personality_group:
        assist_btn = AIAssistButton("character", character_widget)
        assist_btn.clicked.connect(lambda: _handle_character_ai_assist(character_widget, bridge))
        # Add button to layout


def _handle_character_ai_assist(character_widget, bridge: AgentIntegrationBridge):
    """Handle AI assist button click for character widget."""
    current_data = {
        'name': character_widget.name_edit.text(),
        'type': character_widget.type_combo.currentText(),
        'personality': character_widget.personality_edit.toPlainText(),
        'backstory': character_widget.backstory_edit.toPlainText()
    }

    suggestions = bridge.get_ai_suggestions_for_form(
        element_type='character',
        current_data=current_data,
        parent_widget=character_widget
    )

    if suggestions:
        bridge.apply_character_suggestions(character_widget, suggestions)
