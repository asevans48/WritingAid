"""Culture builder widget with rituals, language, music, art, and traditions."""

from typing import List, Optional
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget,
    QLabel, QLineEdit, QTextEdit, QFormLayout, QComboBox, QGroupBox,
    QDialog, QDialogButtonBox, QListWidgetItem, QCheckBox, QScrollArea,
    QTabWidget, QSplitter, QMessageBox, QStackedWidget
)
from PyQt6.QtCore import pyqtSignal, Qt

from src.models.worldbuilding_objects import (
    Culture, Ritual, Language, MusicStyle, ArtForm, Tradition, Cuisine, Faction, Planet
)
from src.ui.worldbuilding.filter_sort_widget import FilterSortWidget


class RitualEditor(QDialog):
    """Dialog for editing a ritual."""

    def __init__(self, ritual: Optional[Ritual] = None, parent=None):
        super().__init__(parent)
        self.ritual = ritual or Ritual(id="", name="")
        self._init_ui()
        if ritual:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("Edit Ritual")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the ritual")
        form.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "ceremony", "rite_of_passage", "festival", "mourning",
            "religious", "seasonal", "initiation", "blessing", "other"
        ])
        form.addRow("Type:", self.type_combo)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Describe the ritual...")
        form.addRow("Description:", self.description_edit)

        self.significance_edit = QTextEdit()
        self.significance_edit.setMaximumHeight(60)
        self.significance_edit.setPlaceholderText("Cultural/spiritual meaning...")
        form.addRow("Significance:", self.significance_edit)

        self.frequency_edit = QLineEdit()
        self.frequency_edit.setPlaceholderText("e.g., annually, at birth, weekly")
        form.addRow("Frequency:", self.frequency_edit)

        self.participants_edit = QLineEdit()
        self.participants_edit.setPlaceholderText("Who participates")
        form.addRow("Participants:", self.participants_edit)

        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Where it takes place")
        form.addRow("Location:", self.location_edit)

        self.duration_edit = QLineEdit()
        self.duration_edit.setPlaceholderText("How long it lasts")
        form.addRow("Duration:", self.duration_edit)

        self.required_items_edit = QTextEdit()
        self.required_items_edit.setMaximumHeight(60)
        self.required_items_edit.setPlaceholderText("Required items (one per line)")
        form.addRow("Required Items:", self.required_items_edit)

        self.origin_edit = QTextEdit()
        self.origin_edit.setMaximumHeight(60)
        self.origin_edit.setPlaceholderText("Origin story of this ritual")
        form.addRow("Origin Story:", self.origin_edit)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self.name_edit.setText(self.ritual.name)
        idx = self.type_combo.findText(self.ritual.ritual_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.description_edit.setPlainText(self.ritual.description)
        self.significance_edit.setPlainText(self.ritual.significance)
        self.frequency_edit.setText(self.ritual.frequency)
        self.participants_edit.setText(self.ritual.participants)
        self.location_edit.setText(self.ritual.location)
        self.duration_edit.setText(self.ritual.duration)
        self.required_items_edit.setPlainText("\n".join(self.ritual.required_items))
        self.origin_edit.setPlainText(self.ritual.origin_story)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if not self.ritual.id:
            self.ritual.id = name.lower().replace(" ", "-").replace("'", "")
        self.ritual.name = name
        self.ritual.ritual_type = self.type_combo.currentText()
        self.ritual.description = self.description_edit.toPlainText().strip()
        self.ritual.significance = self.significance_edit.toPlainText().strip()
        self.ritual.frequency = self.frequency_edit.text().strip()
        self.ritual.participants = self.participants_edit.text().strip()
        self.ritual.location = self.location_edit.text().strip()
        self.ritual.duration = self.duration_edit.text().strip()
        items_text = self.required_items_edit.toPlainText().strip()
        self.ritual.required_items = [i.strip() for i in items_text.split("\n") if i.strip()]
        self.ritual.origin_story = self.origin_edit.toPlainText().strip()
        self.accept()

    def get_ritual(self) -> Ritual:
        return self.ritual


class LanguageEditor(QDialog):
    """Dialog for editing a language."""

    def __init__(self, language: Optional[Language] = None, parent=None):
        super().__init__(parent)
        self.language = language or Language(id="", name="")
        self._init_ui()
        if language:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("Edit Language")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the language")
        form.addRow("Name:*", self.name_edit)

        self.family_edit = QLineEdit()
        self.family_edit.setPlaceholderText("e.g., Romance, Sino-Tibetan")
        form.addRow("Language Family:", self.family_edit)

        self.writing_edit = QLineEdit()
        self.writing_edit.setPlaceholderText("e.g., Alphabetic, Logographic, None (oral)")
        form.addRow("Writing System:", self.writing_edit)

        self.status_combo = QComboBox()
        self.status_combo.addItems(["living", "endangered", "extinct", "constructed"])
        form.addRow("Status:", self.status_combo)

        self.speakers_edit = QLineEdit()
        self.speakers_edit.setPlaceholderText("e.g., ~1 million, extinct")
        form.addRow("Speakers:", self.speakers_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Describe the language...")
        form.addRow("Description:", self.description_edit)

        self.phonetics_edit = QTextEdit()
        self.phonetics_edit.setMaximumHeight(60)
        self.phonetics_edit.setPlaceholderText("Sound characteristics...")
        form.addRow("Phonetics:", self.phonetics_edit)

        self.grammar_edit = QTextEdit()
        self.grammar_edit.setMaximumHeight(60)
        self.grammar_edit.setPlaceholderText("Notable grammar features...")
        form.addRow("Grammar Notes:", self.grammar_edit)

        self.sample_words_edit = QTextEdit()
        self.sample_words_edit.setMaximumHeight(80)
        self.sample_words_edit.setPlaceholderText("word = translation (one per line)")
        form.addRow("Sample Words:", self.sample_words_edit)

        self.sample_phrases_edit = QTextEdit()
        self.sample_phrases_edit.setMaximumHeight(80)
        self.sample_phrases_edit.setPlaceholderText("phrase = translation (one per line)")
        form.addRow("Sample Phrases:", self.sample_phrases_edit)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self.name_edit.setText(self.language.name)
        self.family_edit.setText(self.language.language_family)
        self.writing_edit.setText(self.language.writing_system)
        idx = self.status_combo.findText(self.language.status)
        if idx >= 0:
            self.status_combo.setCurrentIndex(idx)
        self.speakers_edit.setText(self.language.speakers_count)
        self.description_edit.setPlainText(self.language.description)
        self.phonetics_edit.setPlainText(self.language.phonetics)
        self.grammar_edit.setPlainText(self.language.grammar_notes)
        words = [f"{k} = {v}" for k, v in self.language.sample_words.items()]
        self.sample_words_edit.setPlainText("\n".join(words))
        phrases = [f"{k} = {v}" for k, v in self.language.sample_phrases.items()]
        self.sample_phrases_edit.setPlainText("\n".join(phrases))

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if not self.language.id:
            self.language.id = name.lower().replace(" ", "-").replace("'", "")
        self.language.name = name
        self.language.language_family = self.family_edit.text().strip()
        self.language.writing_system = self.writing_edit.text().strip()
        self.language.status = self.status_combo.currentText()
        self.language.speakers_count = self.speakers_edit.text().strip()
        self.language.description = self.description_edit.toPlainText().strip()
        self.language.phonetics = self.phonetics_edit.toPlainText().strip()
        self.language.grammar_notes = self.grammar_edit.toPlainText().strip()

        # Parse sample words
        self.language.sample_words = {}
        for line in self.sample_words_edit.toPlainText().strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                self.language.sample_words[k.strip()] = v.strip()

        # Parse sample phrases
        self.language.sample_phrases = {}
        for line in self.sample_phrases_edit.toPlainText().strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                self.language.sample_phrases[k.strip()] = v.strip()

        self.accept()

    def get_language(self) -> Language:
        return self.language


class MusicStyleEditor(QDialog):
    """Dialog for editing a music style."""

    def __init__(self, music_style: Optional[MusicStyle] = None, parent=None):
        super().__init__(parent)
        self.music_style = music_style or MusicStyle(id="", name="")
        self._init_ui()
        if music_style:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("Edit Music Style")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the music style")
        form.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "traditional", "sacred", "folk", "courtly", "popular", "ceremonial", "military", "other"
        ])
        form.addRow("Type:", self.type_combo)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Describe the music style...")
        form.addRow("Description:", self.description_edit)

        self.instruments_edit = QTextEdit()
        self.instruments_edit.setMaximumHeight(60)
        self.instruments_edit.setPlaceholderText("Instruments used (one per line)")
        form.addRow("Instruments:", self.instruments_edit)

        self.vocal_edit = QLineEdit()
        self.vocal_edit.setPlaceholderText("e.g., chanting, polyphonic, solo")
        form.addRow("Vocal Style:", self.vocal_edit)

        self.rhythm_edit = QLineEdit()
        self.rhythm_edit.setPlaceholderText("Characteristic rhythms")
        form.addRow("Rhythm Pattern:", self.rhythm_edit)

        self.occasions_edit = QTextEdit()
        self.occasions_edit.setMaximumHeight(60)
        self.occasions_edit.setPlaceholderText("When played (one per line)")
        form.addRow("Occasions:", self.occasions_edit)

        self.compositions_edit = QTextEdit()
        self.compositions_edit.setMaximumHeight(60)
        self.compositions_edit.setPlaceholderText("Famous compositions (one per line)")
        form.addRow("Famous Compositions:", self.compositions_edit)

        self.performers_edit = QTextEdit()
        self.performers_edit.setMaximumHeight(60)
        self.performers_edit.setPlaceholderText("Famous performers (one per line)")
        form.addRow("Famous Performers:", self.performers_edit)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self.name_edit.setText(self.music_style.name)
        idx = self.type_combo.findText(self.music_style.music_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.description_edit.setPlainText(self.music_style.description)
        self.instruments_edit.setPlainText("\n".join(self.music_style.instruments))
        self.vocal_edit.setText(self.music_style.vocal_style)
        self.rhythm_edit.setText(self.music_style.rhythm_pattern)
        self.occasions_edit.setPlainText("\n".join(self.music_style.occasions))
        self.compositions_edit.setPlainText("\n".join(self.music_style.famous_compositions))
        self.performers_edit.setPlainText("\n".join(self.music_style.famous_performers))

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if not self.music_style.id:
            self.music_style.id = name.lower().replace(" ", "-").replace("'", "")
        self.music_style.name = name
        self.music_style.music_type = self.type_combo.currentText()
        self.music_style.description = self.description_edit.toPlainText().strip()
        self.music_style.instruments = [i.strip() for i in self.instruments_edit.toPlainText().split("\n") if i.strip()]
        self.music_style.vocal_style = self.vocal_edit.text().strip()
        self.music_style.rhythm_pattern = self.rhythm_edit.text().strip()
        self.music_style.occasions = [o.strip() for o in self.occasions_edit.toPlainText().split("\n") if o.strip()]
        self.music_style.famous_compositions = [c.strip() for c in self.compositions_edit.toPlainText().split("\n") if c.strip()]
        self.music_style.famous_performers = [p.strip() for p in self.performers_edit.toPlainText().split("\n") if p.strip()]
        self.accept()

    def get_music_style(self) -> MusicStyle:
        return self.music_style


class ArtFormEditor(QDialog):
    """Dialog for editing an art form."""

    def __init__(self, art_form: Optional[ArtForm] = None, parent=None):
        super().__init__(parent)
        self.art_form = art_form or ArtForm(id="", name="")
        self._init_ui()
        if art_form:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("Edit Art Form")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the art form")
        form.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "visual", "performance", "textile", "sculpture", "architecture", "literary", "craft", "other"
        ])
        form.addRow("Type:", self.type_combo)

        self.medium_edit = QLineEdit()
        self.medium_edit.setPlaceholderText("e.g., oil paint, stone, dance")
        form.addRow("Medium:", self.medium_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Describe the art form...")
        form.addRow("Description:", self.description_edit)

        self.style_edit = QTextEdit()
        self.style_edit.setMaximumHeight(60)
        self.style_edit.setPlaceholderText("Defining visual/aesthetic features...")
        form.addRow("Style Characteristics:", self.style_edit)

        self.subjects_edit = QTextEdit()
        self.subjects_edit.setMaximumHeight(60)
        self.subjects_edit.setPlaceholderText("Common subjects (one per line)")
        form.addRow("Common Subjects:", self.subjects_edit)

        self.works_edit = QTextEdit()
        self.works_edit.setMaximumHeight(60)
        self.works_edit.setPlaceholderText("Famous works (one per line)")
        form.addRow("Famous Works:", self.works_edit)

        self.artists_edit = QTextEdit()
        self.artists_edit.setMaximumHeight(60)
        self.artists_edit.setPlaceholderText("Famous artists (one per line)")
        form.addRow("Famous Artists:", self.artists_edit)

        self.significance_edit = QTextEdit()
        self.significance_edit.setMaximumHeight(60)
        self.significance_edit.setPlaceholderText("Cultural significance...")
        form.addRow("Cultural Significance:", self.significance_edit)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self.name_edit.setText(self.art_form.name)
        idx = self.type_combo.findText(self.art_form.art_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.medium_edit.setText(self.art_form.medium)
        self.description_edit.setPlainText(self.art_form.description)
        self.style_edit.setPlainText(self.art_form.style_characteristics)
        self.subjects_edit.setPlainText("\n".join(self.art_form.common_subjects))
        self.works_edit.setPlainText("\n".join(self.art_form.famous_works))
        self.artists_edit.setPlainText("\n".join(self.art_form.famous_artists))
        self.significance_edit.setPlainText(self.art_form.cultural_significance)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if not self.art_form.id:
            self.art_form.id = name.lower().replace(" ", "-").replace("'", "")
        self.art_form.name = name
        self.art_form.art_type = self.type_combo.currentText()
        self.art_form.medium = self.medium_edit.text().strip()
        self.art_form.description = self.description_edit.toPlainText().strip()
        self.art_form.style_characteristics = self.style_edit.toPlainText().strip()
        self.art_form.common_subjects = [s.strip() for s in self.subjects_edit.toPlainText().split("\n") if s.strip()]
        self.art_form.famous_works = [w.strip() for w in self.works_edit.toPlainText().split("\n") if w.strip()]
        self.art_form.famous_artists = [a.strip() for a in self.artists_edit.toPlainText().split("\n") if a.strip()]
        self.art_form.cultural_significance = self.significance_edit.toPlainText().strip()
        self.accept()

    def get_art_form(self) -> ArtForm:
        return self.art_form


class TraditionEditor(QDialog):
    """Dialog for editing a tradition."""

    def __init__(self, tradition: Optional[Tradition] = None, parent=None):
        super().__init__(parent)
        self.tradition = tradition or Tradition(id="", name="")
        self._init_ui()
        if tradition:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("Edit Tradition")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the tradition")
        form.addRow("Name:*", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItems([
            "social", "familial", "religious", "seasonal", "culinary", "dress", "greeting", "other"
        ])
        form.addRow("Type:", self.type_combo)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Describe the tradition...")
        form.addRow("Description:", self.description_edit)

        self.origin_edit = QTextEdit()
        self.origin_edit.setMaximumHeight(60)
        self.origin_edit.setPlaceholderText("How it started...")
        form.addRow("Origin:", self.origin_edit)

        self.significance_edit = QTextEdit()
        self.significance_edit.setMaximumHeight(60)
        self.significance_edit.setPlaceholderText("Why it matters...")
        form.addRow("Significance:", self.significance_edit)

        self.practice_edit = QTextEdit()
        self.practice_edit.setMaximumHeight(60)
        self.practice_edit.setPlaceholderText("How it's observed...")
        form.addRow("Practice:", self.practice_edit)

        self.variations_edit = QTextEdit()
        self.variations_edit.setMaximumHeight(60)
        self.variations_edit.setPlaceholderText("Regional/group variations...")
        form.addRow("Variations:", self.variations_edit)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self.name_edit.setText(self.tradition.name)
        idx = self.type_combo.findText(self.tradition.tradition_type)
        if idx >= 0:
            self.type_combo.setCurrentIndex(idx)
        self.description_edit.setPlainText(self.tradition.description)
        self.origin_edit.setPlainText(self.tradition.origin)
        self.significance_edit.setPlainText(self.tradition.significance)
        self.practice_edit.setPlainText(self.tradition.practice)
        self.variations_edit.setPlainText(self.tradition.variations)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if not self.tradition.id:
            self.tradition.id = name.lower().replace(" ", "-").replace("'", "")
        self.tradition.name = name
        self.tradition.tradition_type = self.type_combo.currentText()
        self.tradition.description = self.description_edit.toPlainText().strip()
        self.tradition.origin = self.origin_edit.toPlainText().strip()
        self.tradition.significance = self.significance_edit.toPlainText().strip()
        self.tradition.practice = self.practice_edit.toPlainText().strip()
        self.tradition.variations = self.variations_edit.toPlainText().strip()
        self.accept()

    def get_tradition(self) -> Tradition:
        return self.tradition


class CuisineEditor(QDialog):
    """Dialog for editing cuisine."""

    def __init__(self, cuisine: Optional[Cuisine] = None, parent=None):
        super().__init__(parent)
        self.cuisine = cuisine or Cuisine(id="", name="")
        self._init_ui()
        if cuisine:
            self._load_data()

    def _init_ui(self):
        self.setWindowTitle("Edit Cuisine")
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)

        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form = QFormLayout(scroll_content)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Name of the cuisine")
        form.addRow("Name:*", self.name_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Describe the cuisine...")
        form.addRow("Description:", self.description_edit)

        self.staples_edit = QTextEdit()
        self.staples_edit.setMaximumHeight(60)
        self.staples_edit.setPlaceholderText("Staple foods (one per line)")
        form.addRow("Staple Foods:", self.staples_edit)

        self.dishes_edit = QTextEdit()
        self.dishes_edit.setMaximumHeight(60)
        self.dishes_edit.setPlaceholderText("Signature dishes (one per line)")
        form.addRow("Signature Dishes:", self.dishes_edit)

        self.methods_edit = QTextEdit()
        self.methods_edit.setMaximumHeight(60)
        self.methods_edit.setPlaceholderText("Cooking methods (one per line)")
        form.addRow("Cooking Methods:", self.methods_edit)

        self.customs_edit = QTextEdit()
        self.customs_edit.setMaximumHeight(60)
        self.customs_edit.setPlaceholderText("How meals are served/eaten...")
        form.addRow("Dining Customs:", self.customs_edit)

        self.taboos_edit = QTextEdit()
        self.taboos_edit.setMaximumHeight(60)
        self.taboos_edit.setPlaceholderText("Foods not eaten (one per line)")
        form.addRow("Taboos:", self.taboos_edit)

        self.beverages_edit = QTextEdit()
        self.beverages_edit.setMaximumHeight(60)
        self.beverages_edit.setPlaceholderText("Traditional drinks (one per line)")
        form.addRow("Beverages:", self.beverages_edit)

        self.festivals_edit = QTextEdit()
        self.festivals_edit.setMaximumHeight(60)
        self.festivals_edit.setPlaceholderText("Special occasion foods...")
        form.addRow("Festival Food:", self.festivals_edit)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_data(self):
        self.name_edit.setText(self.cuisine.name)
        self.description_edit.setPlainText(self.cuisine.description)
        self.staples_edit.setPlainText("\n".join(self.cuisine.staple_foods))
        self.dishes_edit.setPlainText("\n".join(self.cuisine.signature_dishes))
        self.methods_edit.setPlainText("\n".join(self.cuisine.cooking_methods))
        self.customs_edit.setPlainText(self.cuisine.dining_customs)
        self.taboos_edit.setPlainText("\n".join(self.cuisine.taboos))
        self.beverages_edit.setPlainText("\n".join(self.cuisine.beverages))
        self.festivals_edit.setPlainText(self.cuisine.festivals_food)

    def _save(self):
        name = self.name_edit.text().strip()
        if not name:
            return
        if not self.cuisine.id:
            self.cuisine.id = name.lower().replace(" ", "-").replace("'", "")
        self.cuisine.name = name
        self.cuisine.description = self.description_edit.toPlainText().strip()
        self.cuisine.staple_foods = [s.strip() for s in self.staples_edit.toPlainText().split("\n") if s.strip()]
        self.cuisine.signature_dishes = [d.strip() for d in self.dishes_edit.toPlainText().split("\n") if d.strip()]
        self.cuisine.cooking_methods = [m.strip() for m in self.methods_edit.toPlainText().split("\n") if m.strip()]
        self.cuisine.dining_customs = self.customs_edit.toPlainText().strip()
        self.cuisine.taboos = [t.strip() for t in self.taboos_edit.toPlainText().split("\n") if t.strip()]
        self.cuisine.beverages = [b.strip() for b in self.beverages_edit.toPlainText().split("\n") if b.strip()]
        self.cuisine.festivals_food = self.festivals_edit.toPlainText().strip()
        self.accept()

    def get_cuisine(self) -> Cuisine:
        return self.cuisine


class CultureElementList(QWidget):
    """Generic list widget for culture sub-elements."""

    content_changed = pyqtSignal()

    def __init__(self, element_name: str, editor_class, parent=None):
        super().__init__(parent)
        self.element_name = element_name
        self.editor_class = editor_class
        self.elements = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        toolbar = QHBoxLayout()
        self.add_btn = QPushButton(f"+ Add {self.element_name}")
        self.add_btn.clicked.connect(self._add_element)
        toolbar.addWidget(self.add_btn)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._edit_element)
        self.edit_btn.setEnabled(False)
        toolbar.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_element)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._edit_element)
        layout.addWidget(self.list_widget)

    def _on_selection_changed(self):
        has_selection = bool(self.list_widget.selectedItems())
        self.edit_btn.setEnabled(has_selection)
        self.remove_btn.setEnabled(has_selection)

    def _add_element(self):
        editor = self.editor_class(parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            element = self._get_element_from_editor(editor)
            self.elements.append(element)
            self._update_list()
            self.content_changed.emit()

    def _edit_element(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        idx = self.list_widget.row(items[0])
        element = self.elements[idx]
        editor = self.editor_class(element, parent=self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._update_list()
            self.content_changed.emit()

    def _remove_element(self):
        items = self.list_widget.selectedItems()
        if not items:
            return
        idx = self.list_widget.row(items[0])
        self.elements.pop(idx)
        self._update_list()
        self.content_changed.emit()

    def _update_list(self):
        self.list_widget.clear()
        for element in self.elements:
            self.list_widget.addItem(element.name)

    def _get_element_from_editor(self, editor):
        """Override in subclass to get element from editor."""
        raise NotImplementedError

    def load_elements(self, elements):
        self.elements = list(elements)
        self._update_list()

    def get_elements(self):
        return self.elements


class RitualList(CultureElementList):
    def __init__(self, parent=None):
        super().__init__("Ritual", RitualEditor, parent)

    def _get_element_from_editor(self, editor):
        return editor.get_ritual()


class LanguageList(CultureElementList):
    def __init__(self, parent=None):
        super().__init__("Language", LanguageEditor, parent)

    def _get_element_from_editor(self, editor):
        return editor.get_language()


class MusicStyleList(CultureElementList):
    def __init__(self, parent=None):
        super().__init__("Music Style", MusicStyleEditor, parent)

    def _get_element_from_editor(self, editor):
        return editor.get_music_style()


class ArtFormList(CultureElementList):
    def __init__(self, parent=None):
        super().__init__("Art Form", ArtFormEditor, parent)

    def _get_element_from_editor(self, editor):
        return editor.get_art_form()


class TraditionList(CultureElementList):
    def __init__(self, parent=None):
        super().__init__("Tradition", TraditionEditor, parent)

    def _get_element_from_editor(self, editor):
        return editor.get_tradition()


class CuisineList(CultureElementList):
    def __init__(self, parent=None):
        super().__init__("Cuisine", CuisineEditor, parent)

    def _get_element_from_editor(self, editor):
        return editor.get_cuisine()


class CultureEditor(QWidget):
    """Editor widget for a single culture with all its sub-elements."""

    content_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.culture: Optional[Culture] = None
        self.available_factions: List[Faction] = []
        self.available_planets: List[str] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)

        # Basic info group
        basic_group = QGroupBox("Basic Information")
        basic_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Culture name")
        self.name_edit.textChanged.connect(self._on_content_changed)
        basic_layout.addRow("Name:*", self.name_edit)

        self.description_edit = QTextEdit()
        self.description_edit.setMaximumHeight(80)
        self.description_edit.setPlaceholderText("Describe this culture...")
        self.description_edit.textChanged.connect(self._on_content_changed)
        basic_layout.addRow("Description:", self.description_edit)

        basic_group.setLayout(basic_layout)
        scroll_layout.addWidget(basic_group)

        # Values group
        values_group = QGroupBox("Values & Beliefs")
        values_layout = QFormLayout()

        self.core_values_edit = QTextEdit()
        self.core_values_edit.setMaximumHeight(60)
        self.core_values_edit.setPlaceholderText("Core values (one per line): honor, community, knowledge...")
        self.core_values_edit.textChanged.connect(self._on_content_changed)
        values_layout.addRow("Core Values:", self.core_values_edit)

        self.taboos_edit = QTextEdit()
        self.taboos_edit.setMaximumHeight(60)
        self.taboos_edit.setPlaceholderText("Cultural taboos (one per line)")
        self.taboos_edit.textChanged.connect(self._on_content_changed)
        values_layout.addRow("Taboos:", self.taboos_edit)

        values_group.setLayout(values_layout)
        scroll_layout.addWidget(values_group)

        # Social structure group
        social_group = QGroupBox("Social Structure")
        social_layout = QFormLayout()

        self.social_structure_edit = QTextEdit()
        self.social_structure_edit.setMaximumHeight(60)
        self.social_structure_edit.setPlaceholderText("How society is organized...")
        self.social_structure_edit.textChanged.connect(self._on_content_changed)
        social_layout.addRow("Social Structure:", self.social_structure_edit)

        self.family_structure_edit = QLineEdit()
        self.family_structure_edit.setPlaceholderText("Nuclear, extended, clan-based, etc.")
        self.family_structure_edit.textChanged.connect(self._on_content_changed)
        social_layout.addRow("Family Structure:", self.family_structure_edit)

        self.gender_roles_edit = QTextEdit()
        self.gender_roles_edit.setMaximumHeight(60)
        self.gender_roles_edit.setPlaceholderText("Cultural expectations around gender...")
        self.gender_roles_edit.textChanged.connect(self._on_content_changed)
        social_layout.addRow("Gender Roles:", self.gender_roles_edit)

        self.coming_of_age_edit = QTextEdit()
        self.coming_of_age_edit.setMaximumHeight(60)
        self.coming_of_age_edit.setPlaceholderText("How adulthood is marked...")
        self.coming_of_age_edit.textChanged.connect(self._on_content_changed)
        social_layout.addRow("Coming of Age:", self.coming_of_age_edit)

        social_group.setLayout(social_layout)
        scroll_layout.addWidget(social_group)

        # Associations group
        assoc_group = QGroupBox("Associations")
        assoc_layout = QVBoxLayout()

        faction_label = QLabel("Associated Factions:")
        faction_label.setStyleSheet("font-weight: bold;")
        assoc_layout.addWidget(faction_label)

        self.faction_checkboxes = {}
        self.factions_container = QWidget()
        self.factions_layout = QVBoxLayout(self.factions_container)
        self.factions_layout.setContentsMargins(0, 0, 0, 0)
        assoc_layout.addWidget(self.factions_container)

        planet_label = QLabel("Associated Planets:")
        planet_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        assoc_layout.addWidget(planet_label)

        self.planet_checkboxes = {}
        self.planets_container = QWidget()
        self.planets_layout = QVBoxLayout(self.planets_container)
        self.planets_layout.setContentsMargins(0, 0, 0, 0)
        assoc_layout.addWidget(self.planets_container)

        self.origin_edit = QLineEdit()
        self.origin_edit.setPlaceholderText("Where culture originated")
        self.origin_edit.textChanged.connect(self._on_content_changed)
        origin_row = QHBoxLayout()
        origin_row.addWidget(QLabel("Origin Location:"))
        origin_row.addWidget(self.origin_edit)
        assoc_layout.addLayout(origin_row)

        assoc_group.setLayout(assoc_layout)
        scroll_layout.addWidget(assoc_group)

        # Cultural elements tabs
        elements_group = QGroupBox("Cultural Elements")
        elements_layout = QVBoxLayout()

        self.elements_tabs = QTabWidget()

        self.rituals_list = RitualList()
        self.rituals_list.content_changed.connect(self._on_content_changed)
        self.elements_tabs.addTab(self.rituals_list, "Rituals")

        self.languages_list = LanguageList()
        self.languages_list.content_changed.connect(self._on_content_changed)
        self.elements_tabs.addTab(self.languages_list, "Languages")

        self.music_list = MusicStyleList()
        self.music_list.content_changed.connect(self._on_content_changed)
        self.elements_tabs.addTab(self.music_list, "Music")

        self.art_list = ArtFormList()
        self.art_list.content_changed.connect(self._on_content_changed)
        self.elements_tabs.addTab(self.art_list, "Art")

        self.traditions_list = TraditionList()
        self.traditions_list.content_changed.connect(self._on_content_changed)
        self.elements_tabs.addTab(self.traditions_list, "Traditions")

        self.cuisine_list = CuisineList()
        self.cuisine_list.content_changed.connect(self._on_content_changed)
        self.elements_tabs.addTab(self.cuisine_list, "Cuisine")

        elements_layout.addWidget(self.elements_tabs)
        elements_group.setLayout(elements_layout)
        scroll_layout.addWidget(elements_group)

        # Notes
        notes_group = QGroupBox("Notes")
        notes_layout = QVBoxLayout()
        self.notes_edit = QTextEdit()
        self.notes_edit.setMaximumHeight(80)
        self.notes_edit.setPlaceholderText("Additional notes...")
        self.notes_edit.textChanged.connect(self._on_content_changed)
        notes_layout.addWidget(self.notes_edit)
        notes_group.setLayout(notes_layout)
        scroll_layout.addWidget(notes_group)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, 1)  # Give scroll area stretch to fill available space

    def set_available_factions(self, factions: List[Faction]):
        """Set available factions for association."""
        self.available_factions = factions
        self._rebuild_faction_checkboxes()

    def set_available_planets(self, planets: List[str]):
        """Set available planets for association."""
        self.available_planets = planets
        self._rebuild_planet_checkboxes()

    def _rebuild_faction_checkboxes(self):
        """Rebuild faction checkboxes."""
        # Clear existing
        for checkbox in self.faction_checkboxes.values():
            checkbox.deleteLater()
        self.faction_checkboxes.clear()

        # Add new checkboxes
        selected_ids = []
        if self.culture:
            selected_ids = self.culture.associated_factions

        for faction in self.available_factions:
            checkbox = QCheckBox(f"{faction.name} ({faction.faction_type.value})")
            checkbox.setProperty("faction_id", faction.id)
            checkbox.setChecked(faction.id in selected_ids)
            checkbox.stateChanged.connect(self._on_content_changed)
            self.faction_checkboxes[faction.id] = checkbox
            self.factions_layout.addWidget(checkbox)

        if not self.available_factions:
            label = QLabel("No factions available")
            label.setStyleSheet("color: #6b7280; font-style: italic;")
            self.factions_layout.addWidget(label)

    def _rebuild_planet_checkboxes(self):
        """Rebuild planet checkboxes."""
        # Clear existing
        for checkbox in self.planet_checkboxes.values():
            checkbox.deleteLater()
        self.planet_checkboxes.clear()

        # Add new checkboxes
        selected_planets = []
        if self.culture:
            selected_planets = self.culture.associated_planets

        for planet_name in self.available_planets:
            checkbox = QCheckBox(planet_name)
            checkbox.setProperty("planet_name", planet_name)
            checkbox.setChecked(planet_name in selected_planets)
            checkbox.stateChanged.connect(self._on_content_changed)
            self.planet_checkboxes[planet_name] = checkbox
            self.planets_layout.addWidget(checkbox)

        if not self.available_planets:
            label = QLabel("No planets available")
            label.setStyleSheet("color: #6b7280; font-style: italic;")
            self.planets_layout.addWidget(label)

    def load_culture(self, culture: Culture):
        """Load culture data into editor."""
        self.culture = culture

        self.name_edit.setText(culture.name)
        self.description_edit.setPlainText(culture.description)
        self.core_values_edit.setPlainText("\n".join(culture.core_values))
        self.taboos_edit.setPlainText("\n".join(culture.taboos))
        self.social_structure_edit.setPlainText(culture.social_structure)
        self.family_structure_edit.setText(culture.family_structure)
        self.gender_roles_edit.setPlainText(culture.gender_roles)
        self.coming_of_age_edit.setPlainText(culture.coming_of_age)
        self.origin_edit.setText(culture.origin_location or "")
        self.notes_edit.setPlainText(culture.notes)

        # Load sub-elements
        self.rituals_list.load_elements(culture.rituals)
        self.languages_list.load_elements(culture.languages)
        self.music_list.load_elements(culture.music_styles)
        self.art_list.load_elements(culture.art_forms)
        self.traditions_list.load_elements(culture.traditions)
        self.cuisine_list.load_elements(culture.cuisines)

        # Rebuild checkboxes with current selections
        self._rebuild_faction_checkboxes()
        self._rebuild_planet_checkboxes()

    def save_to_culture(self):
        """Save editor data back to culture object."""
        if not self.culture:
            return

        self.culture.name = self.name_edit.text().strip()
        self.culture.description = self.description_edit.toPlainText().strip()

        values_text = self.core_values_edit.toPlainText().strip()
        self.culture.core_values = [v.strip() for v in values_text.split("\n") if v.strip()]

        taboos_text = self.taboos_edit.toPlainText().strip()
        self.culture.taboos = [t.strip() for t in taboos_text.split("\n") if t.strip()]

        self.culture.social_structure = self.social_structure_edit.toPlainText().strip()
        self.culture.family_structure = self.family_structure_edit.text().strip()
        self.culture.gender_roles = self.gender_roles_edit.toPlainText().strip()
        self.culture.coming_of_age = self.coming_of_age_edit.toPlainText().strip()
        self.culture.origin_location = self.origin_edit.text().strip() or None
        self.culture.notes = self.notes_edit.toPlainText().strip()

        # Save faction associations
        self.culture.associated_factions = [
            faction_id for faction_id, checkbox in self.faction_checkboxes.items()
            if checkbox.isChecked()
        ]

        # Save planet associations
        self.culture.associated_planets = [
            planet_name for planet_name, checkbox in self.planet_checkboxes.items()
            if checkbox.isChecked()
        ]

        # Save sub-elements
        self.culture.rituals = self.rituals_list.get_elements()
        self.culture.languages = self.languages_list.get_elements()
        self.culture.music_styles = self.music_list.get_elements()
        self.culture.art_forms = self.art_list.get_elements()
        self.culture.traditions = self.traditions_list.get_elements()
        self.culture.cuisines = self.cuisine_list.get_elements()

    def _on_content_changed(self):
        """Handle content changes."""
        if self.culture:
            self.save_to_culture()
            self.content_changed.emit()

    def clear(self):
        """Clear the editor."""
        self.culture = None
        self.name_edit.clear()
        self.description_edit.clear()
        self.core_values_edit.clear()
        self.taboos_edit.clear()
        self.social_structure_edit.clear()
        self.family_structure_edit.clear()
        self.gender_roles_edit.clear()
        self.coming_of_age_edit.clear()
        self.origin_edit.clear()
        self.notes_edit.clear()
        self.rituals_list.load_elements([])
        self.languages_list.load_elements([])
        self.music_list.load_elements([])
        self.art_list.load_elements([])
        self.traditions_list.load_elements([])
        self.cuisine_list.load_elements([])


class CultureBuilderWidget(QWidget):
    """Widget for building and managing cultures."""

    content_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.cultures: List[Culture] = []
        self.available_factions: List[Faction] = []
        self.available_planets: List[str] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QHBoxLayout()
        title = QLabel("🎭 Cultures")
        title.setStyleSheet("font-size: 16px; font-weight: 600; color: #1a1a1a;")
        header.addWidget(title)

        header.addStretch()

        subtitle = QLabel("Build rich cultural systems with rituals, language, music, art, and traditions")
        subtitle.setStyleSheet("font-size: 12px; color: #6b7280;")
        header.addWidget(subtitle)

        layout.addLayout(header)

        # Help text
        help_text = QLabel(
            "Create cultures and associate them with factions and planets. "
            "Each culture can have rituals, languages, music styles, art forms, traditions, and cuisine."
        )
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #6b7280; font-size: 11px; margin-bottom: 8px;")
        layout.addWidget(help_text)

        # Splitter for list and editor
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Left panel - culture list
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Toolbar
        toolbar = QHBoxLayout()

        self.add_btn = QPushButton("➕ Add Culture")
        self.add_btn.clicked.connect(self._add_culture)
        toolbar.addWidget(self.add_btn)

        self.remove_btn = QPushButton("🗑️ Remove")
        self.remove_btn.clicked.connect(self._remove_culture)
        self.remove_btn.setEnabled(False)
        toolbar.addWidget(self.remove_btn)

        toolbar.addStretch()

        import_btn = QPushButton("📥 Import")
        import_btn.clicked.connect(self._import_cultures)
        toolbar.addWidget(import_btn)

        left_layout.addLayout(toolbar)

        # Filter/Sort controls
        self.filter_sort = FilterSortWidget(
            sort_options=["Name"],
            filter_placeholder="Search cultures..."
        )
        self.filter_sort.filter_changed.connect(self._update_list)
        left_layout.addWidget(self.filter_sort)

        # Culture list
        self.culture_list = QListWidget()
        self.culture_list.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self.culture_list)

        splitter.addWidget(left_panel)

        # Right panel - editor
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        # Stacked widget for editor/placeholder
        self.stack = QStackedWidget()

        # Placeholder
        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_label = QLabel("Select a culture to edit or create a new one")
        placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_label.setStyleSheet("color: #6b7280; font-size: 14px;")
        placeholder_layout.addWidget(placeholder_label)
        self.stack.addWidget(placeholder)

        # Editor
        self.editor = CultureEditor()
        self.editor.content_changed.connect(self._on_editor_changed)
        self.stack.addWidget(self.editor)

        right_layout.addWidget(self.stack)
        splitter.addWidget(right_panel)

        splitter.setSizes([250, 550])
        layout.addWidget(splitter, 1)  # Give splitter stretch factor of 1 to take remaining space

    def set_available_factions(self, factions: List[Faction]):
        """Set available factions for culture association."""
        self.available_factions = factions
        self.editor.set_available_factions(factions)

        # Clean up references to deleted factions
        faction_ids = {f.id for f in factions}
        for culture in self.cultures:
            culture.associated_factions = [
                fid for fid in culture.associated_factions if fid in faction_ids
            ]

    def set_available_planets(self, planets: List[str]):
        """Set available planets for culture association."""
        self.available_planets = planets
        self.editor.set_available_planets(planets)

        # Clean up references to deleted planets
        for culture in self.cultures:
            culture.associated_planets = [
                p for p in culture.associated_planets if p in planets
            ]

    def load_cultures(self, cultures: List[Culture]):
        """Load cultures into widget."""
        self.cultures = cultures
        self._update_list()

    def get_cultures(self) -> List[Culture]:
        """Get all cultures."""
        return self.cultures

    def _import_cultures(self):
        """Import cultures from JSON file."""
        from src.ui.worldbuilding.worldbuilding_importer import show_import_dialog
        from src.models.worldbuilding_objects import CompleteWorldBuilding

        temp_wb = CompleteWorldBuilding(cultures=self.cultures)
        result = show_import_dialog(self, temp_wb, target_section="cultures")
        if result and result.imported_counts.get("cultures", 0) > 0:
            self.cultures = temp_wb.cultures
            self._update_list()
            self.content_changed.emit()

    def _update_list(self):
        """Update culture list display."""
        self.culture_list.clear()

        # Filter and sort functions
        def get_searchable_text(culture):
            faction_names = [f.name for f in self.available_factions if f.id in culture.associated_factions]
            planets = " ".join(culture.associated_planets) if culture.associated_planets else ""
            return f"{culture.name} {' '.join(faction_names)} {planets} {culture.description or ''}"

        def get_sort_value(culture, key):
            if key == "Name":
                return culture.name.lower()
            return culture.name.lower()

        filtered_cultures = self.filter_sort.filter_and_sort(
            self.cultures, get_searchable_text, get_sort_value
        )

        for culture in filtered_cultures:
            # Get faction names for display
            faction_names = []
            for faction_id in culture.associated_factions:
                faction = next((f for f in self.available_factions if f.id == faction_id), None)
                if faction:
                    faction_names.append(faction.name)

            # Create display text
            factions_text = f" • {', '.join(faction_names)}" if faction_names else ""
            item_text = f"{culture.name}{factions_text}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, culture.id)
            self.culture_list.addItem(item)

    def _update_current_list_item(self):
        """Update the currently selected list item."""
        items = self.culture_list.selectedItems()
        if not items:
            return

        culture_id = items[0].data(Qt.ItemDataRole.UserRole)
        culture = next((c for c in self.cultures if c.id == culture_id), None)
        if not culture:
            return

        # Get faction names for display
        faction_names = []
        for faction_id in culture.associated_factions:
            faction = next((f for f in self.available_factions if f.id == faction_id), None)
            if faction:
                faction_names.append(faction.name)

        factions_text = f" • {', '.join(faction_names)}" if faction_names else ""
        items[0].setText(f"{culture.name}{factions_text}")

    def _on_selection_changed(self):
        """Handle selection change."""
        items = self.culture_list.selectedItems()
        has_selection = bool(items)
        self.remove_btn.setEnabled(has_selection)

        if has_selection:
            culture_id = items[0].data(Qt.ItemDataRole.UserRole)
            culture = next((c for c in self.cultures if c.id == culture_id), None)
            if culture:
                self.editor.set_available_factions(self.available_factions)
                self.editor.set_available_planets(self.available_planets)
                self.editor.load_culture(culture)
                self.stack.setCurrentIndex(1)
        else:
            self.editor.clear()
            self.stack.setCurrentIndex(0)

    def _add_culture(self):
        """Add a new culture."""
        import uuid
        culture = Culture(
            id=str(uuid.uuid4())[:8],
            name="New Culture"
        )
        self.cultures.append(culture)
        self._update_list()

        # Select the new culture
        self.culture_list.setCurrentRow(len(self.cultures) - 1)
        self.content_changed.emit()

    def _remove_culture(self):
        """Remove selected culture."""
        items = self.culture_list.selectedItems()
        if not items:
            return

        culture_id = items[0].data(Qt.ItemDataRole.UserRole)
        culture = next((c for c in self.cultures if c.id == culture_id), None)
        if not culture:
            return

        # Confirm deletion
        reply = QMessageBox.question(
            self,
            "Remove Culture",
            f"Are you sure you want to remove '{culture.name}'?\n\nThis will delete all associated rituals, languages, music, art, traditions, and cuisine.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        current_row = self.culture_list.row(items[0])
        self.cultures = [c for c in self.cultures if c.id != culture_id]
        self.culture_list.takeItem(current_row)

        # Select next available
        if self.culture_list.count() > 0:
            next_row = min(current_row, self.culture_list.count() - 1)
            self.culture_list.setCurrentRow(next_row)
        else:
            self.editor.clear()
            self.stack.setCurrentIndex(0)

        self.content_changed.emit()

    def _on_editor_changed(self):
        """Handle editor content changes."""
        self._update_current_list_item()
        self.content_changed.emit()
