"""Worldbuilding JSON importer for importing elements from external files."""

import json
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from dataclasses import dataclass

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QTextEdit, QGroupBox, QCheckBox, QScrollArea,
    QWidget, QDialogButtonBox, QMessageBox, QTreeWidget, QTreeWidgetItem
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from src.models.worldbuilding_objects import (
    CompleteWorldBuilding, Faction, Planet, Star, StarSystem, HistoricalEvent,
    EnhancedCharacter, Army, Economy, Good, PowerHierarchy,
    PoliticalSystem, Myth, WorldMap, MilitaryBranch, Place, Culture,
    Flora, Fauna, Technology, ClimatePreset
)


# Mapping of JSON keys to model classes and display names
WORLDBUILDING_SECTIONS = {
    "factions": ("Factions", Faction),
    "planets": ("Planets", Planet),
    "stars": ("Stars", Star),
    "star_systems": ("Star Systems", StarSystem),
    "historical_events": ("Historical Events", HistoricalEvent),
    "characters": ("Characters", EnhancedCharacter),
    "armies": ("Armies", Army),
    "economies": ("Economies", Economy),
    "goods": ("Goods", Good),
    "power_hierarchies": ("Power Hierarchies", PowerHierarchy),
    "political_systems": ("Political Systems", PoliticalSystem),
    "myths": ("Myths", Myth),
    "places": ("Places", Place),
    "cultures": ("Cultures", Culture),
    "flora": ("Flora", Flora),
    "fauna": ("Fauna", Fauna),
    "technologies": ("Technologies", Technology),
    "climate_presets": ("Climate Presets", ClimatePreset),
    "maps": ("Maps", WorldMap),
}


@dataclass
class ImportResult:
    """Result of an import operation."""
    success: bool
    imported_counts: Dict[str, int]
    errors: List[str]
    warnings: List[str]


class WorldbuildingImporter:
    """Handles importing worldbuilding elements from JSON files."""

    # Nested keys that can be extracted from parent objects to their own sections
    NESTED_EXTRACTIONS = {
        "factions": {
            "militaries": "armies",
            "armies": "armies",
            "characters": "characters",
            "economies": "economies",
        },
        "planets": {
            "characters": "characters",
        }
    }

    @staticmethod
    def get_model_fields(model_class) -> Set[str]:
        """Get the set of valid field names for a Pydantic model.

        Args:
            model_class: The Pydantic model class

        Returns:
            Set of valid field names
        """
        return set(model_class.model_fields.keys())

    @staticmethod
    def filter_item_keys(item: Dict, model_class) -> Dict:
        """Filter item dictionary to only include valid model fields.

        Args:
            item: Dictionary with item data
            model_class: The Pydantic model class

        Returns:
            Filtered dictionary with only valid keys
        """
        valid_fields = WorldbuildingImporter.get_model_fields(model_class)
        return {k: v for k, v in item.items() if k in valid_fields}

    @staticmethod
    def parse_json_file(file_path: str) -> Tuple[Optional[Dict], Optional[str]]:
        """Parse a JSON file and return its contents.

        Args:
            file_path: Path to the JSON file

        Returns:
            Tuple of (parsed_data, error_message)
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data, None
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {str(e)}"
        except FileNotFoundError:
            return None, f"File not found: {file_path}"
        except Exception as e:
            return None, f"Error reading file: {str(e)}"

    @staticmethod
    def extract_nested_sections(data: Dict) -> Tuple[Dict, List[str]]:
        """Extract nested sections from parent objects (e.g., militaries from factions).

        Args:
            data: Parsed JSON data

        Returns:
            Tuple of (modified_data, info_messages)
        """
        info_messages = []
        modified_data = dict(data)  # Shallow copy

        for parent_section, nested_mappings in WorldbuildingImporter.NESTED_EXTRACTIONS.items():
            if parent_section not in data:
                continue

            parent_items = data[parent_section]
            if not isinstance(parent_items, list):
                continue

            for nested_key, target_section in nested_mappings.items():
                extracted_items = []

                for parent_item in parent_items:
                    if not isinstance(parent_item, dict):
                        continue

                    nested_data = parent_item.get(nested_key)
                    if not nested_data:
                        continue

                    # Handle both list and single item
                    if isinstance(nested_data, list):
                        for nested_item in nested_data:
                            if isinstance(nested_item, dict):
                                # Ensure faction_id is set for armies
                                if target_section == "armies" and "faction_id" not in nested_item:
                                    nested_item["faction_id"] = parent_item.get("id", "")
                                # Ensure id is set
                                if "id" not in nested_item:
                                    nested_item["id"] = str(uuid.uuid4())
                                extracted_items.append(nested_item)
                    elif isinstance(nested_data, dict):
                        if target_section == "armies" and "faction_id" not in nested_data:
                            nested_data["faction_id"] = parent_item.get("id", "")
                        if "id" not in nested_data:
                            nested_data["id"] = str(uuid.uuid4())
                        extracted_items.append(nested_data)

                if extracted_items:
                    # Add to existing section or create new one
                    if target_section not in modified_data:
                        modified_data[target_section] = []
                    elif not isinstance(modified_data[target_section], list):
                        modified_data[target_section] = []

                    modified_data[target_section].extend(extracted_items)
                    info_messages.append(
                        f"Extracted {len(extracted_items)} {target_section} from {parent_section}.{nested_key}"
                    )

        return modified_data, info_messages

    @staticmethod
    def detect_sections(data: Dict) -> Dict[str, List]:
        """Detect which worldbuilding sections are present in the data.

        Args:
            data: Parsed JSON data

        Returns:
            Dictionary mapping section names to their data lists
        """
        # First extract nested sections
        expanded_data, _ = WorldbuildingImporter.extract_nested_sections(data)

        detected = {}

        for key, (display_name, model_class) in WORLDBUILDING_SECTIONS.items():
            if key in expanded_data and isinstance(expanded_data[key], list) and len(expanded_data[key]) > 0:
                detected[key] = expanded_data[key]

        return detected

    @staticmethod
    def validate_section(section_key: str, items: List[Dict]) -> Tuple[List, List[str]]:
        """Validate items in a section and parse them into model objects.

        Args:
            section_key: The section key (e.g., "factions", "characters")
            items: List of dictionaries to parse

        Returns:
            Tuple of (valid_objects, error_messages)
        """
        if section_key not in WORLDBUILDING_SECTIONS:
            return [], [f"Unknown section: {section_key}"]

        display_name, model_class = WORLDBUILDING_SECTIONS[section_key]
        valid_objects = []
        errors = []

        for i, item in enumerate(items):
            try:
                # Filter to only valid keys for this model
                filtered_item = WorldbuildingImporter.filter_item_keys(item, model_class)
                obj = model_class(**filtered_item)
                valid_objects.append(obj)
            except Exception as e:
                errors.append(f"{display_name} #{i+1}: {str(e)}")

        return valid_objects, errors

    @staticmethod
    def import_to_worldbuilding(
        worldbuilding: CompleteWorldBuilding,
        data: Dict,
        sections_to_import: List[str],
        merge_duplicates: bool = False
    ) -> ImportResult:
        """Import data into a worldbuilding object.

        Args:
            worldbuilding: Target worldbuilding object
            data: Parsed JSON data
            sections_to_import: List of section keys to import
            merge_duplicates: If True, skip items with duplicate IDs

        Returns:
            ImportResult with counts and any errors
        """
        imported_counts = {}
        errors = []
        warnings = []

        # First extract nested sections from the data
        expanded_data, extraction_info = WorldbuildingImporter.extract_nested_sections(data)
        warnings.extend(extraction_info)

        for section_key in sections_to_import:
            if section_key not in expanded_data:
                continue

            items = expanded_data[section_key]
            valid_objects, section_errors = WorldbuildingImporter.validate_section(
                section_key, items
            )
            errors.extend(section_errors)

            if not valid_objects:
                continue

            # Get the target list
            target_list = getattr(worldbuilding, section_key, None)
            if target_list is None:
                errors.append(f"Cannot find target list for {section_key}")
                continue

            # Track existing IDs for duplicate detection
            existing_ids = {getattr(obj, 'id', None) for obj in target_list}

            added_count = 0
            for obj in valid_objects:
                obj_id = getattr(obj, 'id', None)
                if obj_id in existing_ids:
                    if merge_duplicates:
                        warnings.append(f"Skipped duplicate: {section_key} ID {obj_id}")
                        continue
                    else:
                        # Generate new ID to avoid conflict
                        if hasattr(obj, 'id'):
                            obj.id = str(uuid.uuid4())
                        warnings.append(f"Renamed duplicate ID in {section_key}")

                target_list.append(obj)
                added_count += 1

            imported_counts[section_key] = added_count

        success = len(errors) == 0 or sum(imported_counts.values()) > 0
        return ImportResult(
            success=success,
            imported_counts=imported_counts,
            errors=errors,
            warnings=warnings
        )


class ImportPreviewDialog(QDialog):
    """Dialog for previewing and selecting items to import."""

    def __init__(self, file_path: str, target_section: Optional[str] = None, parent=None):
        """Initialize import preview dialog.

        Args:
            file_path: Path to the JSON file to import
            target_section: If specified, only show this section (e.g., "factions")
            parent: Parent widget
        """
        super().__init__(parent)
        self.file_path = file_path
        self.target_section = target_section
        self.data = None
        self.expanded_data = None
        self.extraction_info = []
        self.detected_sections = {}
        self.section_checkboxes = {}

        self.setWindowTitle("Import Worldbuilding Data")
        self.resize(600, 500)
        self._init_ui()
        self._load_file()

    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)

        # File info
        file_group = QGroupBox("Source File")
        file_layout = QVBoxLayout(file_group)

        self.file_label = QLabel(f"File: {Path(self.file_path).name}")
        self.file_label.setStyleSheet("font-weight: 600;")
        file_layout.addWidget(self.file_label)

        self.status_label = QLabel("Loading...")
        file_layout.addWidget(self.status_label)

        layout.addWidget(file_group)

        # Detected sections
        sections_group = QGroupBox("Detected Sections")
        sections_layout = QVBoxLayout(sections_group)

        self.sections_tree = QTreeWidget()
        self.sections_tree.setHeaderLabels(["Section", "Items", "Import"])
        self.sections_tree.setColumnWidth(0, 200)
        self.sections_tree.setColumnWidth(1, 80)
        sections_layout.addWidget(self.sections_tree)

        # Select all / none buttons
        select_layout = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        select_layout.addWidget(select_all_btn)

        select_none_btn = QPushButton("Select None")
        select_none_btn.clicked.connect(self._select_none)
        select_layout.addWidget(select_none_btn)

        select_layout.addStretch()
        sections_layout.addLayout(select_layout)

        layout.addWidget(sections_group)

        # Options
        options_group = QGroupBox("Import Options")
        options_layout = QVBoxLayout(options_group)

        self.skip_duplicates_check = QCheckBox("Skip items with duplicate IDs")
        self.skip_duplicates_check.setChecked(True)
        options_layout.addWidget(self.skip_duplicates_check)

        layout.addWidget(options_group)

        # Preview area
        preview_group = QGroupBox("Preview (First 3 items per section)")
        preview_layout = QVBoxLayout(preview_group)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setMaximumHeight(150)
        self.preview_text.setFont(QFont("Consolas", 9))
        preview_layout.addWidget(self.preview_text)

        layout.addWidget(preview_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setText("Import Selected")
        self.ok_button.setEnabled(False)
        layout.addWidget(buttons)

    def _load_file(self):
        """Load and parse the JSON file."""
        self.data, error = WorldbuildingImporter.parse_json_file(self.file_path)

        if error:
            self.status_label.setText(f"❌ Error: {error}")
            self.status_label.setStyleSheet("color: red;")
            return

        # Extract nested sections (e.g., militaries from factions)
        self.expanded_data, self.extraction_info = WorldbuildingImporter.extract_nested_sections(self.data)

        self.detected_sections = WorldbuildingImporter.detect_sections(self.data)

        if not self.detected_sections:
            self.status_label.setText("❌ No valid worldbuilding sections found")
            self.status_label.setStyleSheet("color: red;")
            return

        # Filter to target section if specified
        if self.target_section and self.target_section in self.detected_sections:
            self.detected_sections = {
                self.target_section: self.detected_sections[self.target_section]
            }
        elif self.target_section and self.target_section not in self.detected_sections:
            display_name = WORLDBUILDING_SECTIONS.get(self.target_section, (self.target_section,))[0]
            self.status_label.setText(f"❌ No {display_name} found in file")
            self.status_label.setStyleSheet("color: red;")
            return

        total_items = sum(len(items) for items in self.detected_sections.values())
        status_text = f"✓ Found {len(self.detected_sections)} section(s) with {total_items} total items"

        # Show extraction info if any nested sections were found
        if self.extraction_info:
            status_text += f"\n  (+ {', '.join(self.extraction_info)})"

        self.status_label.setText(status_text)
        self.status_label.setStyleSheet("color: green;")

        self._populate_sections_tree()
        self._update_preview()
        self.ok_button.setEnabled(True)

    def _populate_sections_tree(self):
        """Populate the sections tree with detected sections."""
        self.sections_tree.clear()
        self.section_checkboxes.clear()

        for section_key, items in self.detected_sections.items():
            display_name = WORLDBUILDING_SECTIONS.get(section_key, (section_key,))[0]

            item = QTreeWidgetItem([display_name, str(len(items)), ""])
            item.setData(0, Qt.ItemDataRole.UserRole, section_key)
            item.setCheckState(2, Qt.CheckState.Checked)

            # Add sample items as children
            for i, obj in enumerate(items[:5]):
                name = obj.get('name', obj.get('title', f'Item {i+1}'))
                child = QTreeWidgetItem([f"  • {name}", "", ""])
                item.addChild(child)

            if len(items) > 5:
                child = QTreeWidgetItem([f"  ... and {len(items) - 5} more", "", ""])
                child.setForeground(0, Qt.GlobalColor.gray)
                item.addChild(child)

            self.sections_tree.addTopLevelItem(item)
            item.setExpanded(True)

    def _update_preview(self):
        """Update the preview text area."""
        preview_lines = []

        for section_key, items in self.detected_sections.items():
            display_name = WORLDBUILDING_SECTIONS.get(section_key, (section_key,))[0]
            preview_lines.append(f"=== {display_name} ({len(items)} items) ===")

            for item in items[:3]:
                name = item.get('name', item.get('title', 'Unnamed'))
                item_id = item.get('id', 'no-id')[:8]
                preview_lines.append(f"  • {name} (ID: {item_id}...)")

            if len(items) > 3:
                preview_lines.append(f"  ... and {len(items) - 3} more")
            preview_lines.append("")

        self.preview_text.setText("\n".join(preview_lines))

    def _select_all(self):
        """Select all sections."""
        for i in range(self.sections_tree.topLevelItemCount()):
            item = self.sections_tree.topLevelItem(i)
            item.setCheckState(2, Qt.CheckState.Checked)

    def _select_none(self):
        """Deselect all sections."""
        for i in range(self.sections_tree.topLevelItemCount()):
            item = self.sections_tree.topLevelItem(i)
            item.setCheckState(2, Qt.CheckState.Unchecked)

    def get_selected_sections(self) -> List[str]:
        """Get list of selected section keys."""
        selected = []
        for i in range(self.sections_tree.topLevelItemCount()):
            item = self.sections_tree.topLevelItem(i)
            if item.checkState(2) == Qt.CheckState.Checked:
                section_key = item.data(0, Qt.ItemDataRole.UserRole)
                selected.append(section_key)
        return selected

    def get_skip_duplicates(self) -> bool:
        """Get whether to skip duplicates."""
        return self.skip_duplicates_check.isChecked()

    def get_data(self) -> Optional[Dict]:
        """Get the parsed data (with extracted nested sections)."""
        return getattr(self, 'expanded_data', self.data)


def show_import_dialog(
    parent,
    worldbuilding: CompleteWorldBuilding,
    target_section: Optional[str] = None
) -> Optional[ImportResult]:
    """Show the import dialog and perform import if confirmed.

    Args:
        parent: Parent widget
        worldbuilding: Target worldbuilding object
        target_section: If specified, only import this section

    Returns:
        ImportResult if import was performed, None if cancelled
    """
    # Open file dialog
    section_name = ""
    if target_section:
        section_name = WORLDBUILDING_SECTIONS.get(target_section, (target_section,))[0]

    title = f"Import {section_name}" if section_name else "Import Worldbuilding Data"

    file_path, _ = QFileDialog.getOpenFileName(
        parent,
        title,
        "",
        "JSON Files (*.json);;All Files (*)"
    )

    if not file_path:
        return None

    # Show preview dialog
    preview_dialog = ImportPreviewDialog(file_path, target_section, parent)

    if preview_dialog.exec() != QDialog.DialogCode.Accepted:
        return None

    data = preview_dialog.get_data()
    if not data:
        return None

    selected_sections = preview_dialog.get_selected_sections()
    if not selected_sections:
        QMessageBox.warning(parent, "No Selection", "No sections selected for import.")
        return None

    skip_duplicates = preview_dialog.get_skip_duplicates()

    # Perform import
    result = WorldbuildingImporter.import_to_worldbuilding(
        worldbuilding,
        data,
        selected_sections,
        merge_duplicates=skip_duplicates
    )

    # Show result
    if result.success:
        counts_str = ", ".join(
            f"{WORLDBUILDING_SECTIONS.get(k, (k,))[0]}: {v}"
            for k, v in result.imported_counts.items()
            if v > 0
        )

        message = f"Successfully imported:\n{counts_str}"

        if result.warnings:
            message += f"\n\nWarnings:\n" + "\n".join(result.warnings[:5])
            if len(result.warnings) > 5:
                message += f"\n... and {len(result.warnings) - 5} more warnings"

        QMessageBox.information(parent, "Import Complete", message)
    else:
        error_str = "\n".join(result.errors[:10])
        if len(result.errors) > 10:
            error_str += f"\n... and {len(result.errors) - 10} more errors"

        QMessageBox.warning(parent, "Import Errors", f"Import had errors:\n{error_str}")

    return result
