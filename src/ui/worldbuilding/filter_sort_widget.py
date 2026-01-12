"""Reusable filter and sort widget for worldbuilding lists."""

from typing import List, Callable, Any, Optional
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QComboBox, QLabel
)
from PyQt6.QtCore import pyqtSignal, Qt


class FilterSortWidget(QWidget):
    """Widget providing filter and sort controls for lists."""

    filter_changed = pyqtSignal()  # Emitted when filter/sort changes

    def __init__(self, sort_options: List[str] = None, filter_placeholder: str = "Search...",
                 parent=None):
        """Initialize filter/sort widget.

        Args:
            sort_options: List of sort option labels (e.g., ["Name", "Type", "Date"])
            filter_placeholder: Placeholder text for search box
            parent: Parent widget
        """
        super().__init__(parent)
        self.sort_options = sort_options or ["Name"]
        self._init_ui(filter_placeholder)

    def _init_ui(self, filter_placeholder: str):
        """Initialize UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(8)

        # Search/filter box
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(filter_placeholder)
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        self.filter_edit.setMinimumWidth(150)
        self.filter_edit.setMaximumWidth(250)
        layout.addWidget(self.filter_edit)

        # Sort controls
        sort_label = QLabel("Sort:")
        sort_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(self.sort_options)
        self.sort_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.sort_combo.setMinimumWidth(100)
        layout.addWidget(self.sort_combo)

        # Sort direction
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(["A-Z", "Z-A"])
        self.direction_combo.currentIndexChanged.connect(self._on_filter_changed)
        self.direction_combo.setMinimumWidth(60)
        layout.addWidget(self.direction_combo)

        layout.addStretch()

    def _on_filter_changed(self):
        """Handle filter/sort change."""
        self.filter_changed.emit()

    def get_filter_text(self) -> str:
        """Get current filter text."""
        return self.filter_edit.text().strip().lower()

    def get_sort_key(self) -> str:
        """Get current sort key."""
        return self.sort_combo.currentText()

    def is_ascending(self) -> bool:
        """Check if sort is ascending."""
        return self.direction_combo.currentIndex() == 0

    def set_filter_options(self, filter_combo_options: List[str]):
        """Add a filter-by-type dropdown.

        Args:
            filter_combo_options: List of filter options (first should be "All")
        """
        if not hasattr(self, 'type_filter_combo'):
            # Insert type filter before sort label
            type_label = QLabel("Filter:")
            type_label.setStyleSheet("color: #6b7280; font-size: 11px;")

            self.type_filter_combo = QComboBox()
            self.type_filter_combo.currentIndexChanged.connect(self._on_filter_changed)
            self.type_filter_combo.setMinimumWidth(100)

            # Insert after search box
            layout = self.layout()
            layout.insertWidget(1, type_label)
            layout.insertWidget(2, self.type_filter_combo)

        self.type_filter_combo.clear()
        self.type_filter_combo.addItems(filter_combo_options)

    def get_type_filter(self) -> str:
        """Get current type filter value."""
        if hasattr(self, 'type_filter_combo'):
            return self.type_filter_combo.currentText()
        return "All"

    def filter_and_sort(self, items: List[Any],
                        get_text: Callable[[Any], str],
                        get_sort_value: Callable[[Any, str], Any],
                        get_type: Callable[[Any], str] = None) -> List[Any]:
        """Filter and sort items.

        Args:
            items: List of items to filter/sort
            get_text: Function to get searchable text from item
            get_sort_value: Function to get sort value from item and sort key
            get_type: Optional function to get type from item for type filtering

        Returns:
            Filtered and sorted list
        """
        filter_text = self.get_filter_text()
        sort_key = self.get_sort_key()
        ascending = self.is_ascending()
        type_filter = self.get_type_filter()

        # Filter by text
        filtered = items
        if filter_text:
            filtered = [item for item in filtered if filter_text in get_text(item).lower()]

        # Filter by type if enabled
        if get_type and type_filter and type_filter != "All":
            filtered = [item for item in filtered if get_type(item) == type_filter]

        # Sort
        try:
            sorted_items = sorted(
                filtered,
                key=lambda x: get_sort_value(x, sort_key) or "",
                reverse=not ascending
            )
        except TypeError:
            # Fall back if sort values aren't comparable
            sorted_items = filtered

        return sorted_items
