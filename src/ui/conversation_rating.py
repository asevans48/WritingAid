"""Conversation rating widget for collecting fine-tuning data."""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel,
    QDialog, QTextEdit, QCheckBox, QGroupBox, QFormLayout,
    QComboBox
)
from PyQt6.QtCore import pyqtSignal, Qt
from typing import Optional, List


class StarRatingWidget(QWidget):
    """A 5-star rating widget."""

    rating_changed = pyqtSignal(int)  # Emits 1-5

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rating = 0
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._stars = []
        for i in range(5):
            star = QPushButton("☆")
            star.setFlat(True)
            star.setFixedSize(24, 24)
            star.setStyleSheet("""
                QPushButton {
                    font-size: 16px;
                    border: none;
                    background: transparent;
                    color: #d1d5db;
                }
                QPushButton:hover {
                    color: #fbbf24;
                }
            """)
            star.clicked.connect(lambda checked, idx=i: self._set_rating(idx + 1))
            self._stars.append(star)
            layout.addWidget(star)

        layout.addStretch()

    def _set_rating(self, rating: int):
        self._rating = rating
        self._update_display()
        self.rating_changed.emit(rating)

    def _update_display(self):
        for i, star in enumerate(self._stars):
            if i < self._rating:
                star.setText("★")
                star.setStyleSheet("""
                    QPushButton {
                        font-size: 16px;
                        border: none;
                        background: transparent;
                        color: #fbbf24;
                    }
                    QPushButton:hover {
                        color: #f59e0b;
                    }
                """)
            else:
                star.setText("☆")
                star.setStyleSheet("""
                    QPushButton {
                        font-size: 16px;
                        border: none;
                        background: transparent;
                        color: #d1d5db;
                    }
                    QPushButton:hover {
                        color: #fbbf24;
                    }
                """)

    def get_rating(self) -> int:
        return self._rating

    def set_rating(self, rating: int):
        self._rating = max(0, min(5, rating))
        self._update_display()


class QuickRatingBar(QWidget):
    """Compact rating bar for inline use in chat."""

    rating_submitted = pyqtSignal(str, str, list, list)  # rating, notes, positive, negative

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Rating label
        label = QLabel("Rate this response:")
        label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(label)

        # Star rating
        self.star_rating = StarRatingWidget()
        layout.addWidget(self.star_rating)

        # Quick buttons
        self.excellent_btn = QPushButton("Excellent")
        self.excellent_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #059669;
            }
        """)
        self.excellent_btn.clicked.connect(lambda: self._quick_rate("excellent"))
        layout.addWidget(self.excellent_btn)

        self.good_btn = QPushButton("Good")
        self.good_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        self.good_btn.clicked.connect(lambda: self._quick_rate("good"))
        layout.addWidget(self.good_btn)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.setStyleSheet("""
            QPushButton {
                background-color: #e5e7eb;
                color: #6b7280;
                border: none;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #d1d5db;
            }
        """)
        self.skip_btn.clicked.connect(lambda: self._quick_rate("neutral"))
        layout.addWidget(self.skip_btn)

        # Details button
        self.details_btn = QPushButton("Details...")
        self.details_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #6b7280;
                border: 1px solid #e5e7eb;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #f3f4f6;
            }
        """)
        self.details_btn.clicked.connect(self._show_details_dialog)
        layout.addWidget(self.details_btn)

        layout.addStretch()

    def _quick_rate(self, rating: str):
        self.rating_submitted.emit(rating, "", [], [])
        self.hide()

    def _show_details_dialog(self):
        dialog = DetailedRatingDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            rating, notes, positive, negative = dialog.get_rating()
            self.rating_submitted.emit(rating, notes, positive, negative)
            self.hide()


class DetailedRatingDialog(QDialog):
    """Detailed rating dialog with notes and aspect selection."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rate Conversation")
        self.setMinimumSize(450, 500)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # Header
        header = QLabel("How was this AI response?")
        header.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(header)

        # Rating
        rating_group = QGroupBox("Overall Rating")
        rating_layout = QVBoxLayout()

        self.rating_combo = QComboBox()
        self.rating_combo.addItems([
            "Excellent - Perfect for training",
            "Good - Useful with minor issues",
            "Neutral - Mediocre",
            "Poor - Problematic",
            "Bad - Should not be used"
        ])
        self.rating_combo.setCurrentIndex(1)  # Default to Good
        rating_layout.addWidget(self.rating_combo)

        rating_group.setLayout(rating_layout)
        layout.addWidget(rating_group)

        # Positive aspects
        positive_group = QGroupBox("What worked well? (select all that apply)")
        positive_layout = QVBoxLayout()

        self._positive_checks = {}
        positive_aspects = [
            ("voice", "Matched character voice"),
            ("creative", "Creative and original ideas"),
            ("consistent", "Consistent with story/world"),
            ("helpful", "Helpful and actionable"),
            ("detailed", "Good level of detail"),
            ("engaging", "Engaging writing style")
        ]

        for key, label in positive_aspects:
            check = QCheckBox(label)
            self._positive_checks[key] = check
            positive_layout.addWidget(check)

        positive_group.setLayout(positive_layout)
        layout.addWidget(positive_group)

        # Negative aspects
        negative_group = QGroupBox("What could be improved?")
        negative_layout = QVBoxLayout()

        self._negative_checks = {}
        negative_aspects = [
            ("verbose", "Too verbose/wordy"),
            ("generic", "Too generic/bland"),
            ("inconsistent", "Inconsistent with story"),
            ("repetitive", "Repetitive patterns"),
            ("off_topic", "Off topic or missed the point"),
            ("too_short", "Too brief/incomplete")
        ]

        for key, label in negative_aspects:
            check = QCheckBox(label)
            self._negative_checks[key] = check
            negative_layout.addWidget(check)

        negative_group.setLayout(negative_layout)
        layout.addWidget(negative_group)

        # Notes
        notes_group = QGroupBox("Additional Notes (optional)")
        notes_layout = QVBoxLayout()

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Any additional feedback about this response...")
        self.notes_edit.setMaximumHeight(80)
        notes_layout.addWidget(self.notes_edit)

        notes_group.setLayout(notes_layout)
        layout.addWidget(notes_group)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save Rating")
        save_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
        """)
        save_btn.clicked.connect(self.accept)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def get_rating(self):
        """Get the rating data."""
        rating_map = {
            0: "excellent",
            1: "good",
            2: "neutral",
            3: "poor",
            4: "bad"
        }
        rating = rating_map.get(self.rating_combo.currentIndex(), "neutral")

        notes = self.notes_edit.toPlainText()

        positive = [key for key, check in self._positive_checks.items() if check.isChecked()]
        negative = [key for key, check in self._negative_checks.items() if check.isChecked()]

        return rating, notes, positive, negative


def create_rating_callback(conversation_store, conversation_id: str):
    """Create a callback function for rating a specific conversation.

    Args:
        conversation_store: The ConversationStore instance
        conversation_id: ID of conversation to rate

    Returns:
        Callback function that handles the rating
    """
    from src.ai.conversation_store import ConversationRating

    def callback(rating_str: str, notes: str, positive: List[str], negative: List[str]):
        rating_map = {
            "excellent": ConversationRating.EXCELLENT,
            "good": ConversationRating.GOOD,
            "neutral": ConversationRating.NEUTRAL,
            "poor": ConversationRating.POOR,
            "bad": ConversationRating.BAD
        }
        rating = rating_map.get(rating_str, ConversationRating.NEUTRAL)

        conversation_store.rate_conversation(
            conversation_id,
            rating,
            notes,
            positive,
            negative
        )

    return callback
