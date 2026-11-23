"""R.3: the checkers run without the editor, and what the writer built up is
still honoured after they moved out of the editor file."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

TEXT = ("She could of gone home. The door was opened by Mara. It was very, very cold. "
        "The cold wind and the cold rain made the cold night colder. Vethari glimmered.")


def test_a_chapter_can_be_checked_from_a_plain_script_with_no_window():
    script = f"""
import json, sys
sys.path.insert(0, {str(ROOT)!r})
from src.utils.spell_checker import SpellChecker
from src.utils.overuse import OveruseDetector
from src.utils.writing_stats import ProWritingAnalyzer
from src.utils.grammar_checker import GrammarChecker
text = {TEXT!r}
spell = SpellChecker()
misspelled = [w for w in ("vethari", "cold") if not spell.check_word(w)[0]]
over = OveruseDetector()
over.update_cache(text)
stats = ProWritingAnalyzer().analyze(text)
grammar = GrammarChecker().check_text(text)
print(json.dumps({{"qt": any(m.startswith("PyQt6") for m in sys.modules),
                  "misspelled": misspelled, "overused": over.analyze_text(text).get("cold", 0),
                  "sentences": stats.sentence_count, "grammar": [g[2] for g in grammar]}}))
"""
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                         cwd=str(ROOT), env=env, timeout=120)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["qt"] is False                     # no window, no Qt
    assert result["misspelled"] == ["vethari"]
    assert result["overused"] >= 4
    assert result["sentences"] == 5
    assert "could of" in result["grammar"]


def test_old_import_paths_give_the_same_classes():
    import src.ui.enhanced_text_editor as ete
    from src.utils import grammar_checker, overuse, spell_checker, writing_stats
    assert ete.SpellChecker is spell_checker.SpellChecker
    assert ete.OveruseDetector is overuse.OveruseDetector
    assert ete.ProWritingAnalyzer is writing_stats.ProWritingAnalyzer
    assert ete.WritingStats is writing_stats.WritingStats
    assert ete.GrammarChecker is grammar_checker.GrammarChecker
    assert ete._apos is spell_checker._apos


@pytest.fixture
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_saved_project_words_names_and_allowed_words_are_still_honoured(app, tmp_path, monkeypatch):
    """Data safety: a project with its own dictionary words, character
    names and an allowed word in its style sheet, saved and reopened, is
    checked the same way after the move."""
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)
    from src.ai import style_sheet
    from src.models.project import Chapter, Character, WriterProject
    from src.ui.enhanced_text_editor import EnhancedTextEditor, ErrorType

    path = tmp_path / "book.writerproj"
    p = WriterProject(name="Book")
    p.project_path = str(path)
    p.characters = [Character(id="m", name="Mara Quillon", character_type="protagonist")]
    p.dictionary.words.append("Vethari")
    style_sheet.add(p, "allow glimmerkin")
    p.manuscript.chapters.append(Chapter(id="c1", number=1, title="One", content="x"))
    p.save_project(str(path))

    project = WriterProject.load_project(str(path))
    assert "Vethari" in project.dictionary.words                    # stored where it was
    assert "glimmerkin" in style_sheet.allowed_words(project)

    ed = EnhancedTextEditor()
    ed.setPlainText("Vethari and Quillon met a glimmerkin and a zorbleflax.")
    ed.set_project_vocabulary(project)
    spell = ed.spell_checker
    assert spell.check_word("vethari")[0] is True                   # project dictionary
    assert spell.check_word("quillon")[0] is True                   # character name
    assert spell.check_word("zorbleflax")[0] is False               # still checked
    ed.writing_highlighter.rehighlight()
    app.processEvents()
    flagged = {e.word.lower() for errs in ed.writing_highlighter._errors.values() for e in errs
               if e.error_type == ErrorType.SPELLING}
    assert "glimmerkin" not in flagged                              # allowed in the style sheet
    assert "zorbleflax" in flagged


def test_ignored_words_and_rules_are_still_honoured():
    from src.utils.grammar_checker import GrammarChecker
    from src.utils.overuse import OveruseDetector
    from src.utils.proofing import builtin_grammar

    g = GrammarChecker()
    text = "She could of gone home."
    assert any(i[2] == "could of" for i in g.check_text(text))
    rule = next(i.rule_id for i in builtin_grammar(text) if i.text == "could of")
    g.ignore_rule(rule)
    assert not any(i[2] == "could of" for i in g.check_text(text))

    over = OveruseDetector()
    over.update_cache(TEXT)
    over.ignore_word("cold")
    assert over.is_ignored("cold")
    assert over.is_overused("cold", TEXT)[0] is False
