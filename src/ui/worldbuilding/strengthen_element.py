"""Strengthen a single worldbuilding element using manuscript + RAG context.

Provides a button and worker that can be added to any element editor dialog.
Searches the manuscript for mentions, finds correlated concepts, and uses
the RAG system (including encyclopedia) to enrich thin fields.
"""

import re
from typing import Optional
from PyQt6.QtWidgets import QPushButton, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal


class StrengthenElementWorker(QThread):
    """Background worker to strengthen a single element."""

    finished = pyqtSignal(str)  # report
    error = pyqtSignal(str)

    def __init__(self, element, element_type: str, project):
        super().__init__()
        self.element = element
        self.element_type = element_type
        self.project = project

    def run(self):
        try:
            name = getattr(self.element, 'name', '')
            if not name:
                self.finished.emit("Element has no name.")
                return

            report_parts = []

            # --- Gather manuscript context ---
            chapter_texts = self._get_chapter_texts()
            all_sents = []
            for ch_title, ch_text in chapter_texts.items():
                sents = self._find_sentences(name, ch_text)
                for s in sents:
                    all_sents.append(f"[{ch_title}] {s}")

            if all_sents:
                report_parts.append(
                    f"Found {len(all_sents)} mention(s) across "
                    f"{sum(1 for _, t in chapter_texts.items() if name.lower() in t.lower())} chapter(s)"
                )
            manuscript_context = " ... ".join(all_sents[:8])[:1200]

            # --- Find correlated concepts ---
            all_text = "\n\n".join(chapter_texts.values())
            correlated = self._find_nearby_terms(name, all_text)
            if correlated:
                report_parts.append(f"Related concepts: {', '.join(correlated[:10])}")

            # --- Get encyclopedia/RAG reference ---
            encyclopedia_ref = ""
            try:
                from src.config.ai_config import get_ai_config
                kb_enabled = get_ai_config().get_settings().get("enable_knowledge_base", True)
                if kb_enabled:
                    from src.ai.enhanced_rag import EnhancedRAGSystem
                    from src.ai.semantic_search import SearchMethod
                    rag = EnhancedRAGSystem(project=self.project)
                    rag.rebuild_index()
                    rag_result = rag.get_context_for_ai(
                        f"{self.element_type} {name}", max_tokens=600,
                        method=SearchMethod.HYBRID
                    )
                    if rag_result:
                        useful = [l.strip() for l in rag_result.split('\n')
                                  if l.strip() and not l.startswith('RELEVANT')
                                  and l.strip() != '---'
                                  and not (l.strip().startswith('[') and ']' in l)]
                        encyclopedia_ref = " ".join(useful[:4])[:500]
            except Exception:
                pass

            # --- Synthesize proper descriptions for each field ---
            from src.ai.field_synthesizer import synthesize_field, get_llm_client
            llm = get_llm_client()

            enrichable = self._get_enrichable_fields()
            enriched_fields = []

            for field in enrichable:
                if not hasattr(self.element, field):
                    continue
                current = getattr(self.element, field, '') or ''

                # Skip if already has synthesized content
                if current and len(current) > 200:
                    continue

                synthesized = synthesize_field(
                    element_name=name,
                    element_type=self.element_type,
                    field_name=field,
                    manuscript_evidence=manuscript_context,
                    encyclopedia_reference=encyclopedia_ref,
                    existing_content=current,
                    llm_client=llm
                )

                if synthesized and synthesized != current:
                    try:
                        setattr(self.element, field, synthesized)
                        enriched_fields.append(field)
                    except (AttributeError, TypeError, ValueError):
                        pass

            # Add correlated concepts to notes
            if correlated:
                notes = getattr(self.element, 'notes', '') or ''
                terms_str = ", ".join(correlated[:10])
                addition = f"Related concepts: {terms_str}"
                if addition not in notes:
                    try:
                        new_notes = f"{notes}\n\n{addition}" if notes else addition
                        setattr(self.element, 'notes', new_notes)
                        enriched_fields.append('notes')
                    except (AttributeError, TypeError, ValueError):
                        pass

            if enriched_fields:
                report_parts.append(f"Enriched fields: {', '.join(enriched_fields)}")

            if report_parts:
                self.finished.emit("\n".join(report_parts))
            else:
                self.finished.emit("No additional context found for this element.")

        except Exception as e:
            self.error.emit(str(e))

    def _get_enrichable_fields(self) -> list:
        """Get the list of fields to try enriching for this element type."""
        fields_map = {
            "character": ["personality", "backstory", "physical_description",
                          "speaking_style", "motivations"],
            "faction": ["description", "notes"],
            "place": ["description", "atmosphere", "cultural_significance"],
            "culture": ["description", "social_structure"],
            "technology": ["description", "limitations"],
            "myth": ["description"],
            "magic_system": ["description", "rules", "limitations"],
            "flora": ["description"],
            "fauna": ["description", "behavior"],
        }
        return fields_map.get(self.element_type, ["description", "notes"])

    def _get_primary_field(self) -> str:
        """Get the primary text field for RAG enrichment."""
        primary_map = {
            "character": "backstory",
            "faction": "description",
            "place": "description",
            "culture": "description",
            "technology": "description",
            "myth": "description",
            "magic_system": "description",
            "flora": "description",
            "fauna": "description",
        }
        return primary_map.get(self.element_type, "description")

    def _get_chapter_texts(self) -> dict:
        if not self.project or not hasattr(self.project, 'manuscript'):
            return {}
        from pathlib import Path
        project_dir = None
        if hasattr(self.project, 'project_path') and self.project.project_path:
            project_dir = Path(self.project.project_path).parent
        result = {}
        for ch in self.project.manuscript.chapters:
            content = getattr(ch, 'content', '')
            if not content and project_dir:
                try:
                    ch.load_content_from_file(project_dir)
                    content = getattr(ch, 'content', '')
                except Exception:
                    pass
            if content:
                title = getattr(ch, 'title', f"Ch {getattr(ch, 'number', '?')}")
                result[title] = content
        return result

    def _find_sentences(self, name: str, text: str) -> list:
        sents = re.split(r'(?<=[.!?])\s+', text)
        matches = []
        name_lower = name.lower()
        for s in sents:
            if name_lower in s.lower() and 20 < len(s.strip()) < 500:
                matches.append(s.strip())
                if len(matches) >= 5:
                    break
        return matches

    def _find_nearby_terms(self, name: str, text: str) -> list:
        """Find terms that co-occur with this element in nearby sentences."""
        from collections import Counter

        sents = re.split(r'(?<=[.!?])\s+', text)
        name_lower = name.lower()

        stopwords = {
            "the", "and", "but", "was", "were", "had", "have", "has", "been",
            "they", "them", "their", "she", "her", "his", "him", "its",
            "this", "that", "with", "from", "into", "could", "would",
            "said", "like", "back", "over", "down", "some", "what",
            "when", "where", "which", "about", "after", "before",
            "through", "still", "every", "never", "something", "nothing",
        }

        nearby = Counter()
        for i, sent in enumerate(sents):
            if name_lower not in sent.lower():
                continue
            window = []
            if i > 0:
                window.append(sents[i - 1])
            window.append(sent)
            if i < len(sents) - 1:
                window.append(sents[i + 1])

            for s in window:
                terms = re.findall(r'\b([a-z][\w-]*(?:\s+[a-z][\w-]*){0,2})\b', s.lower())
                for term in terms:
                    term = term.strip()
                    if len(term) < 5 or term == name_lower:
                        continue
                    if all(w in stopwords for w in term.split()):
                        continue
                    nearby[term] += 1

        return [t for t, c in nearby.most_common(15) if c >= 2 and len(t) > 4]


def _find_project(widget):
    """Walk the parent chain to find a project reference."""
    parent = widget
    while parent:
        if hasattr(parent, '_project') and parent._project:
            return parent._project
        if hasattr(parent, 'project') and parent.project:
            return parent.project
        if hasattr(parent, 'current_project') and parent.current_project:
            return parent.current_project
        parent = parent.parent() if hasattr(parent, 'parent') and callable(parent.parent) else None
    return None


def add_strengthen_button(dialog, element, element_type: str, project=None,
                          button_box=None, reload_callback=None):
    """Add a 'Strengthen with AI' button to an element editor dialog.

    Args:
        dialog: The QDialog editor
        element: The element being edited
        element_type: Type string (faction, place, character, etc.)
        project: WriterProject instance (if None, walks parent chain to find it)
        button_box: Optional QDialogButtonBox to add the button to
        reload_callback: Optional callable to refresh the dialog after enrichment
    """
    btn = QPushButton("🤖 Strengthen")
    btn.setToolTip(
        "Use AI to enrich this element from your manuscript, "
        "correlated concepts, and the encyclopedia"
    )
    btn.setStyleSheet("font-weight: bold;")

    def _on_click():
        # Resolve project at click time (may not be available at button creation)
        resolved_project = project or _find_project(dialog)
        if not resolved_project:
            QMessageBox.information(dialog, "No Project", "Open a project first.")
            return

        btn.setEnabled(False)
        btn.setText("🤖 Analyzing...")

        worker = StrengthenElementWorker(element, element_type, resolved_project)

        def _on_done(report):
            btn.setEnabled(True)
            btn.setText("🤖 Strengthen")
            if reload_callback:
                reload_callback()
            QMessageBox.information(dialog, "Element Strengthened", report)

        def _on_error(msg):
            btn.setEnabled(True)
            btn.setText("🤖 Strengthen")
            QMessageBox.warning(dialog, "Error", msg)

        worker.finished.connect(_on_done)
        worker.error.connect(_on_error)
        # Store worker on dialog to prevent garbage collection
        dialog._strengthen_worker = worker
        worker.start()

    btn.clicked.connect(_on_click)

    if button_box:
        button_box.addButton(btn, button_box.ButtonRole.ActionRole)
    else:
        # Find the layout and add before the last widget (usually the button box)
        layout = dialog.layout()
        if layout and layout.count() > 0:
            layout.insertWidget(layout.count() - 1, btn)

    return btn
