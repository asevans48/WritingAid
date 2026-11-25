"""P.2a: the missing reports — transitions, pronouns, alliteration, acronyms.

Each is a style kind (``style_checks.KINDS``), off until the writer ticks
it, and reaches the highlights, the Style tab, the Checks menu and the
next-fix queue like the others.
"""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

from src.utils import style_checks as sc
from src.utils import style_reports as sr

NEW = set(sr.NEW_KINDS)
EVERY = set(sc.KINDS)


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    """The editors here would start (and first download) LanguageTool."""
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


def kinds_of(text, kind, document=None):
    return [i for i in sc.analyze_paragraph(text, EVERY, document) if i.kind == kind]


# ── Registration: off until ticked (rule 11) ────────────────────────

def test_the_new_kinds_are_registered_but_off_by_default():
    assert NEW == {"transition", "pronoun", "alliteration", "acronym"}
    assert NEW <= EVERY
    assert not NEW & sc.DEFAULT_KINDS
    assert sc.DEFAULT_KINDS == {"passive", "adverb", "intensifier", "wordy", "cliche",
                                "repeated_start", "echo", "preference", "long_sentence",
                                "hard_sentence", "sticky_sentence"}     # as before P.2a
    text = "She opened it. He came in. She took it. They sat. It rained. NTSB came."
    assert not {i.kind for i in sc.analyze_paragraph(text)} & NEW     # the default kinds


def test_colours_come_from_the_palette():
    from src.ui.styles import COLORS
    for kind in NEW:
        assert sc.KINDS[kind][1] in COLORS.values()


# ── Transitions ─────────────────────────────────────────────────────

CHOPPY = ("The town had one road and one bridge over the river. The bridge had a toll "
          "house at the north end. A man named Pell kept the toll house for thirty years. "
          "Pell wrote every cart and every coin in a ledger. The ledger lived on a shelf "
          "above the stove. Nobody in the town ever asked to read it.")


def test_a_long_paragraph_with_no_transition_is_flagged_once():
    found = kinds_of(CHOPPY, "transition")
    assert len(found) == 1 and found[0].sentence_level and not found[0].suggestions
    assert found[0].start == 0 and found[0].end == len(CHOPPY)


def test_one_linking_word_or_a_short_paragraph_is_enough():
    assert not kinds_of(CHOPPY.replace("Nobody in", "But nobody in"), "transition")
    short = "The town had one road. The bridge had a toll house. Pell kept it."
    assert not kinds_of(short, "transition")
    fragments = "No. Never. Not again. Not ever. Not here. Not now. Gone."
    assert not kinds_of(fragments, "transition")          # fragments are not counted


def test_the_share_of_sentences_with_a_transition():
    assert sr.transition_share("He ran. Then he fell. But he got up.\nShe waited.") == (2, 4)
    assert sr.transition_share("") == (0, 0)
    assert sr.uses_transition("In fact, it was over.") and not sr.uses_transition("It rained.")


# ── Pronouns ────────────────────────────────────────────────────────

RUN = ("Mara opened the door. She looked out at the rain. He came up behind her. "
       "She took the lamp. They stood there a long time. It was Tobin who moved first.")


def test_a_run_of_pronoun_openings_is_flagged_once_on_its_fourth_sentence():
    found = kinds_of(RUN, "pronoun")
    assert [i.text for i in found] == ["They"]
    assert "5 sentences" in found[0].message and not found[0].suggestions


def test_three_are_fine_and_dialogue_is_the_characters_voice():
    assert not kinds_of("Mara left. She ran. He followed. Tobin won.", "pronoun")
    speech = '"I know. I said so. I meant it. You heard me," Ilse said.'
    assert not kinds_of(speech, "pronoun")


def test_the_same_word_each_time_is_left_to_repeated_starts():
    same = "He opened it. He took it out. He read it twice. He put it back."
    assert not kinds_of(same, "pronoun")                         # repeated_start's flag
    assert [i.kind for i in sc.analyze_paragraph(same, {"pronoun"})] == ["pronoun"]


def test_a_sentence_that_leans_on_one_pronoun():
    text = "He told him that he would meet him at his house after he had eaten."
    found = kinds_of(text, "pronoun")
    assert len(found) == 1 and found[0].text.startswith("He told") and "6 times" in found[0].message
    assert not kinds_of("He told Tobin that he would meet him at the house.", "pronoun")


# ── Alliteration ────────────────────────────────────────────────────

def test_opening_sounds():
    assert sr.opening_sound("phone") == sr.opening_sound("fish") == "f"
    assert sr.opening_sound("knee") == sr.opening_sound("night") == "n"
    assert sr.opening_sound("city") == "s" and sr.opening_sound("cat") == "k"
    assert sr.opening_sound("ship") != sr.opening_sound("sip")
    assert sr.opening_sound("apple") == ""


def test_three_words_with_the_same_opening_sound():
    found = kinds_of("She put the plastic plates on the porch.", "alliteration")
    assert [i.text for i in found] == ["put the plastic plates"]
    assert not found[0].suggestions                        # the writer judges


def test_no_alliteration_across_long_gaps_vowels_or_repeats():
    assert not kinds_of("The plates were stacked by the door, and the porch was wet.",
                        "alliteration")
    assert not kinds_of("An old, aching, empty afternoon.", "alliteration")
    assert not kinds_of("Walk, walk, walk.", "alliteration")       # an echo, not alliteration


# ── Acronyms ────────────────────────────────────────────────────────

def test_an_acronym_never_spelled_out_is_flagged_at_its_first_use_only():
    text = "The NTSB team arrived at noon. Later the NTSB took the wreckage away."
    found = kinds_of(text, "acronym")
    assert len(found) == 1 and found[0].start == text.index("NTSB")
    assert "spelled out" in found[0].message and not found[0].suggestions


def test_spelled_out_anywhere_in_the_chapter_is_enough():
    first = "The Air Accidents Investigation Branch sent two inspectors."
    later = "By evening the AAIB had taken over the hangar."
    doc = first + "\n\n" + later
    assert not kinds_of(later, "acronym", document=doc)
    assert kinds_of(later, "acronym")                      # the paragraph alone: not spelled out
    bracket = "They called post traumatic stress (PTS) clinics."
    assert not kinds_of(bracket, "acronym")


def test_only_the_paragraph_with_the_first_use_is_flagged():
    p1, p2 = "Ruiz asked for the CVR at dawn.", "The CVR never came."
    doc = p1 + "\n" + p2
    assert kinds_of(p1, "acronym", document=doc)
    assert not kinds_of(p2, "acronym", document=doc)


def test_used_before_it_is_spelled_out():
    p1 = "The ATSB had asked for a copy of the flight data that afternoon."
    p2 = "Nobody at the Australian Transport Safety Bureau had called back."
    found = kinds_of(p1, "acronym", document=p1 + "\n" + p2)
    assert len(found) == 1 and "before it is spelled out" in found[0].message


def test_two_forms_offer_the_one_used_most():
    text = "The FDR was in the mud. Okafor wanted the F.D.R. sent off, and Ruiz took the FDR."
    found = kinds_of(text, "acronym")
    assert [(i.text, i.suggestions) for i in found] == [("F.D.R.", ["FDR"])]


def test_shouting_emphasis_numerals_and_known_acronyms_are_left_alone():
    for text in ('"STOP!" she shouted.', '"Get BACK from the edge," she said.',
                 "It was HUGE.", "Henry VIII had six wives.", "Chapter XII",
                 "She watched TV with the FBI agent.", "THE END OF IT ALL"):
        assert not kinds_of(text, "acronym"), text


def test_the_document_facts_are_cached_and_have_a_signature():
    doc = "The NTSB came.\nThe NTSB left."
    assert sr.acronym_facts(doc) is sr.acronym_facts(doc)
    assert sr.acronym_signature(doc) == sr.acronym_signature(doc)
    assert sr.acronym_signature(doc) != sr.acronym_signature(doc + "\nThe CVR too.")
    assert sr.acronym_signature("") is None


# ── In the app: highlighter, menu, Style tab, queue ─────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _project(tmp_path, text):
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = text
    p.manuscript.chapters.append(ch)
    return p


DOC = ("The Air Accidents Investigation Branch sent two inspectors from Farnborough.\n"
       "By evening the AAIB had taken over the hangar. The NTSB sent nobody.\n"
       + RUN + "\n")


def _style_kinds_shown(hl, doc):
    out = []
    for n, errs in hl._errors.items():
        out += [(getattr(e, "style_kind", ""), e.word) for e in errs]
    return out


def test_the_editor_draws_them_only_once_ticked_and_acronyms_see_the_chapter(app):
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    ed = EnhancedTextEditor()
    hl = ed.writing_highlighter
    assert not NEW & hl._style_kinds                       # a fresh editor: off
    hl.set_style_mode(CheckMode.REALTIME)
    ed.setPlainText(DOC)
    hl.update_full_text(DOC)
    hl.rehighlight()
    assert not {k for k, _w in _style_kinds_shown(hl, ed.document())} & NEW
    hl.set_style_kinds(set(hl._style_kinds) | NEW)
    shown = _style_kinds_shown(hl, ed.document())
    assert ("acronym", "NTSB") in shown and ("acronym", "AAIB") not in shown
    assert ("pronoun", "They") in shown


def test_the_menu_and_the_style_tab_list_them_unticked(app, tmp_path):
    from src.ui.manuscript_editor import ChapterEditor
    from datetime import datetime
    p = _project(tmp_path, DOC)
    p.created_at = datetime(2026, 3, 1)     # an existing project (a new one ticks two)
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    ed.resize(1100, 700)
    ed.show()
    app.processEvents()
    for kind in NEW:
        act = ed._style_check_actions[kind]
        assert not act.isChecked()
    ed._style_check_actions["acronym"].setChecked(True)
    assert "acronym" in ed.editor.writing_highlighter._style_kinds
    # D.6: the Style tab is retired; its summary line heads the menu.
    sub = ed._style_summary_action.parent()
    sub.aboutToShow.emit()
    assert "transitions in" not in ed._style_summary_action.text()
    ed._style_check_actions["transition"].setChecked(True)
    sub.aboutToShow.emit()
    assert "transitions in" in ed._style_summary_action.text()
    ed.close()
    ed.deleteLater()


def test_the_queue_takes_them_with_a_fix_only_for_two_forms():
    from src.ai import fix_queue
    assert NEW <= set(fix_queue.STYLE_ONLY_KINDS)
    text = "The FDR was in the mud. Okafor wanted the F.D.R. sent off, and Ruiz took the FDR."
    flags = [(0, i) for i in sc.analyze_paragraph(text, EVERY) if i.kind in NEW]
    entries = fix_queue.style_entries(flags + [(0, i) for i in sc.analyze_paragraph(RUN, EVERY)
                                               if i.kind in NEW])
    by_kind = {e.item.kind: e for e in entries}
    assert by_kind["acronym"].item.suggestions == ["FDR"]
    assert by_kind["acronym"].label == "Acronyms" and by_kind["acronym"].stage == "line"
    assert by_kind["pronoun"].item.suggestions == []


def test_an_old_project_opens_and_saves_unchanged(app):
    """Nothing stored changes: an old project shows on Write and saves with
    every chapter file byte-for-byte the same."""
    import shutil
    from test_project_compat import _v1_project_dir
    from src.models.project import WriterProject
    from src.ui.manuscript_editor import ManuscriptEditor
    d, path = _v1_project_dir()
    files = sorted(d.glob("chapters/*/*.md"))
    before = {f: f.read_bytes() for f in files}
    p = WriterProject.load_project(str(path))
    w = ManuscriptEditor()
    w.set_project(p)
    w.load_manuscript(p.manuscript)
    w.open_chapter(p.manuscript.chapters[0].id)
    app.processEvents()
    assert not NEW & w.current_chapter_editor.editor.writing_highlighter._style_kinds
    p.save_project(str(path))
    WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    w.deleteLater()
    shutil.rmtree(d)


# ── The benchmark (Q.2) ─────────────────────────────────────────────

def test_the_benchmark_scores_the_new_kinds_without_moving_the_old_ones():
    import importlib.util
    import json
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("score_checks", root / "scripts" / "score_checks.py")
    s = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s)
    assert NEW <= set(s.STYLE_KINDS)
    data = json.loads((root / "benchmark" / "style" / "marked.json").read_text())
    new_passages = [p for p in data["passages"] if p.get("scores")]
    assert len(new_passages) >= 10
    assert {m["kind"] for p in new_passages for m in p["marks"]} == NEW
    for p in new_passages:
        assert set(p["scores"]) <= NEW
