"""P.2b: the last missing reports — homonyms, sensory detail, sentence
structure and vague words (diction).

Each is a style kind (``style_checks.KINDS``), off in existing projects until
the writer ticks it; a new project ticks only those that meet four in five
on the marked benchmark (decision 3): Homonyms.
"""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace as N

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))     # test_project_compat

from src.utils import homonyms as hm
from src.utils import style_checks as sc
from src.utils import style_reports_more as more

ROOT = Path(__file__).resolve().parent.parent
MORE = set(more.MORE_KINDS)
EVERY = set(sc.KINDS)


@pytest.fixture(autouse=True)
def _no_languagetool(monkeypatch):
    import src.utils.proofing as pf
    monkeypatch.setattr(pf.LanguageToolEngine, "ensure_started", lambda self: False)


def kinds_of(text, kind, kinds=None):
    return [i for i in sc.analyze_paragraph(text, kinds or EVERY) if i.kind == kind]


# ── Registration: off until ticked (rule 11) ────────────────────────

def test_the_four_kinds_are_registered_but_off_by_default():
    assert MORE == {"homonym", "sensory", "sentence_structure", "vague"}
    assert MORE <= EVERY and not MORE & sc.DEFAULT_KINDS
    assert sc.DEFAULT_KINDS == {"passive", "adverb", "intensifier", "wordy", "cliche",
                                "repeated_start", "echo", "preference", "long_sentence",
                                "hard_sentence", "sticky_sentence"}     # as before P.2a
    text = "She took a sneak peak. It was kind of nice, all sorts of things."
    assert not {i.kind for i in sc.analyze_paragraph(text)} & MORE


def test_colours_come_from_the_palette():
    from src.ui.styles import COLORS
    for kind in MORE:
        assert sc.KINDS[kind][1] in COLORS.values()


# ── Homonyms ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, word, right", [
    ("She took a sneak peak at the file.", "peak", "peek"),
    ("The photographs peaked her curiosity.", "peaked", "piqued"),
    ("He gave the mare free reign.", "reign", "rein"),
    ("The storm wrecked havoc on the coast.", "wrecked", "wreaked"),
    ("They poured over the maps all night.", "poured", "pored"),
    ("For a moment she couldn't breath.", "breath", "breathe"),
    ("He took a deep breathe and went in.", "breathe", "breath"),
    ("She walked passed the guards.", "passed", "past"),
    ("Don't loose your temper.", "loose", "lose"),
    ("The dog broke lose and ran.", "lose", "loose"),
    ("It had a strange affect on him.", "affect", "effect"),
    ("Please bare with me.", "bare", "bear"),
    ("He slammed on the breaks.", "breaks", "brakes"),
    ("Weather or not it rains, we go.", "Weather", "Whether"),
    ("I wandered if she knew.", "wandered", "wondered"),
    ("The rope was pulled taught.", "taught", "taut"),
    ("The men were lead into the yard.", "lead", "led"),
    ("Thunder and lightening filled the night.", "lightening", "lightning"),
    ("He waited with baited breath.", "baited", "bated"),
    ("She fell pray to his charm.", "pray", "prey"),
])
def test_a_sound_alike_the_sentence_does_not_want_is_flagged_with_its_twin(text, word, right):
    found = kinds_of(text, "homonym")
    assert [(i.text, i.suggestions) for i in found] == [(word, [right])]
    assert right in found[0].message and not found[0].sentence_level


def test_the_right_uses_are_left_alone():
    right = ("From the peak of the ridge they could see the valley. Rain poured over the "
             "gutter, and the horse shook its reins loose. He could not bear it. The trees "
             "were bare and the bear had gone. They passed the gate at dusk, and the past felt "
             "far away. She had been taught by nuns and kept the line taut. The lead pipe was "
             "heavy. The board met on Tuesday and she was bored. We'll wait here. The weight "
             "of it hurt. A whole loaf sat by the hole in the wall. Its effect on him was "
             "plain. The plain stretched west. The plane landed. She took a breath and began "
             "to breathe slowly. He wondered about it while he wandered through the town. "
             "Whether or not the weather held, they would sail. Free Reign Stables were shut. "
             "His loose collar flapped. Try not to lose it. The brake failed on the hill; "
             "they took a break. Peace and quiet at last, and a piece of cake.")
    assert not [i.text for i in sc.analyze_document(right, {"homonym"})]


def test_the_grammar_checks_own_confusions_are_left_to_them():
    assert not kinds_of("Their going home. Its a shame. He is taller then me.", "homonym")


def test_case_is_kept_in_the_suggestion():
    assert hm.find("Sneak PEAK!")[0][3] == "PEEK"
    assert kinds_of("Free reign, he said.", "homonym")[0].suggestions == ["rein"]


def test_fix_all_is_never_offered_for_a_homonym():
    """Decision 9: the right form depends on the sentence."""
    from src.ui import fix_all
    from src.utils.editor_flags import ErrorType
    homonym = N(error_type=ErrorType.STYLE, word="wrecked", suggestions=["wreaked"],
                rule_id="", style_kind="homonym", start=0, end=7)
    assert fix_all.is_confusable(homonym) and not fix_all.can_fix_everywhere(homonym)
    acronym = N(error_type=ErrorType.STYLE, word="F.D.R.", suggestions=["FDR"], rule_id="",
                style_kind="acronym", start=0, end=6)
    assert fix_all.can_fix_everywhere(acronym)          # other style kinds keep it


# ── Sensory detail ──────────────────────────────────────────────────

TOLD = ("Mara was angry with her brother, and she had been angry with him for most of the "
        "year. He had promised to help with the farm after their father died, and he had not "
        "kept the promise. She understood why he had gone. He had a family of his own now and "
        "a job in the city that paid well. But understanding it did not make it easier to "
        "forgive, and she knew that when he arrived on Sunday they would argue again about "
        "the same old grievances, and nothing would change.")


def test_a_long_stretch_with_no_sense_at_all_is_flagged_once():
    found = kinds_of(TOLD, "sensory")
    assert len(found) == 1 and found[0].sentence_level and not found[0].suggestions
    assert found[0].start == 0 and found[0].end == len(TOLD)


def test_one_sense_a_short_paragraph_or_mostly_dialogue_is_enough():
    assert not kinds_of(TOLD.replace("on Sunday", "on Sunday in the rain, smelling of"
                                                  " diesel,"), "sensory")
    assert not kinds_of("She was angry. He had gone. Nothing would change.", "sensory")
    talk = " ".join(f'"{s}"' for s in TOLD.split(". "))
    assert not kinds_of(talk, "sensory")


def test_the_balance_of_senses():
    assert more.senses_in("She heard the bell and saw the red door. It smelled of bread.") \
        == {"sight": 2, "sound": 2, "touch": 0, "smell": 1, "taste": 0}
    assert more.sense_balance("She heard the bell and saw the red door.") == \
        "sight 50%, sound 50%, touch 0%, smell 0%, taste 0%"
    assert more.sense_balance("Nothing here.") == ""


# ── Sentence structure ──────────────────────────────────────────────

EVEN = ("Tobin carried the crates up from the boat. He stacked them by the shed door. The "
        "rain had started again by then. Mara came out to help with the last. They worked "
        "without saying very much at all.")


def test_a_run_of_sentences_of_the_same_length_is_flagged():
    found = kinds_of(EVEN, "sentence_structure")
    assert len(found) == 1 and "5 sentences" in found[0].message and found[0].sentence_level
    varied = ("The ferry was late. By the time it came in, slewing against the tide with its "
              "lamps still lit from the night crossing, half the queue had given up and gone "
              "home. Tobin stayed. He had nowhere better to be.")
    assert not kinds_of(varied, "sentence_structure")


def test_a_run_of_the_same_opening_is_flagged():
    ing = ("Turning from the window, Ilse picked up the letter. Tearing it open, she read the "
           "first line twice. Folding it again, she put it away. Then she went back.")
    found = kinds_of(ing, "sentence_structure")
    assert len(found) == 1 and "-ing" in found[0].message
    assert more.opening_kind("When he came in, she left.") == "clause"
    assert more.opening_kind("In the hall, a clock ticked.") == "prep"
    assert more.opening_kind("Slowly she turned.") == "ly"
    assert more.opening_kind("Nothing moved, at all.") == ""
    assert more.opening_kind("The door opened.") == ""
    two = "Turning, she ran. Grabbing the keys, he followed. They stopped."
    assert not kinds_of(two, "sentence_structure")


def test_same_first_words_are_left_to_repeated_starts():
    text = "As he ran, it rained. As he fell, it rained. As he rose, it stopped."
    assert kinds_of(text, "sentence_structure", {"sentence_structure"})
    assert not kinds_of(text, "sentence_structure", {"sentence_structure", "repeated_start"})


# ── Vague words ─────────────────────────────────────────────────────

def test_vague_words_in_narration_are_flagged():
    text = ("The kitchen was kind of a mess. There was stuff on every surface, all sorts of "
            "things, and it smelled of coffee or something. The worst aspect was the cold.")
    assert [i.text for i in kinds_of(text, "vague")] == [
        "kind of", "stuff", "all sorts of things", "or something", "aspect"]
    assert not any(i.suggestions for i in kinds_of(text, "vague"))


def test_vague_words_in_speech_or_set_phrases_are_not():
    assert not kinds_of('"It\'s just stuff," she said. "Kind of nice, really."', "vague")
    assert not kinds_of("That was kind of you. What kind of man was he? A sort of hum.", "vague")
    assert not kinds_of("They drove south to Nice.", "vague")


# ── On realistic prose ──────────────────────────────────────────────

MODERN = [
    ("I hadn't been back to the house since the funeral. The key was where Dad always left "
     "it, under the cracked pot by the step, and the door stuck the way it always had. Inside, "
     "the hall smelled of damp coats. I stood there longer than I meant to, listening to the "
     "fridge hum in the kitchen, before I made myself go through."),
    ("Okafor read the report twice before she called Ruiz. The lab had found traces of "
     "kerosene on the victim's coat, which nobody had expected, and a partial print on the "
     "lighter. \"So it wasn't an accident,\" Ruiz said. \"It never looked like one.\" Okafor "
     "pulled the photographs across the desk and laid them out in a row."),
    ("The convoy left at dawn. By the second checkpoint the sun was up and the road shimmered; "
     "Daniels drove with one hand and kept the other on the radio. Nobody talked. When the lead "
     "truck slowed, every head in the cab turned to the ditch."),
]


def test_no_flags_on_modern_prose_or_the_clean_benchmark():
    for text in MODERN:
        assert not [(i.kind, i.text) for i in sc.analyze_document(text, MORE)], text
    words, found = 0, {}
    for path in sorted((ROOT / "benchmark" / "clean").glob("*.txt")):
        t = path.read_text(encoding="utf-8")
        words += len(t.split())
        for i in sc.analyze_document(t, MORE):
            found[i.kind] = found.get(i.kind, 0) + 1
    assert not found.get("homonym") and not found.get("vague")
    assert not found.get("sentence_structure")
    assert 1000 * found.get("sensory", 0) / words <= 1.0       # two told paragraphs


# ── In the app: highlighter, menu, queue, new projects ──────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


DOC = "She took a sneak peak at the file. The room smelled of bread.\n" + EVEN + "\n" + TOLD + "\n"


def _style_kinds_shown(hl):
    return [(getattr(e, "style_kind", ""), e.word) for errs in hl._errors.values() for e in errs]


def test_the_editor_draws_them_only_once_ticked(app):
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    ed = EnhancedTextEditor()
    hl = ed.writing_highlighter
    assert not MORE & hl._style_kinds
    hl.set_style_mode(CheckMode.REALTIME)
    ed.setPlainText(DOC)
    hl.rehighlight()
    assert not {k for k, _w in _style_kinds_shown(hl)} & MORE
    hl.set_style_kinds(set(hl._style_kinds) | MORE)
    shown = {k for k, _w in _style_kinds_shown(hl)}
    assert {"homonym", "sentence_structure", "sensory"} <= shown
    ed.deleteLater()


def _project(tmp_path, text):
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    ch = Chapter(id="c1", number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = text
    p.manuscript.chapters.append(ch)
    return p


def test_the_menu_lists_them_unticked_and_shows_the_senses(app, tmp_path):
    from datetime import datetime
    from src.ui.manuscript_editor import ChapterEditor
    p = _project(tmp_path, DOC)
    p.created_at = datetime(2026, 3, 1)               # an existing project
    ed = ChapterEditor(p.manuscript.chapters[0], project=p)
    ed.resize(1100, 700)
    ed.show()
    app.processEvents()
    for kind in MORE:
        assert not ed._style_check_actions[kind].isChecked()
    sub = ed._style_summary_action.parent()
    sub.aboutToShow.emit()
    assert "senses" not in ed._style_summary_action.text()
    assert ed._style_check_actions["homonym"].text().endswith("(1)")    # counted while off
    ed._style_check_actions["sensory"].setChecked(True)
    assert "sensory" in ed.editor.writing_highlighter._style_kinds
    sub.aboutToShow.emit()
    assert "senses: sight" in ed._style_summary_action.text()
    ed.close()
    ed.deleteLater()


def test_a_new_project_ticks_homonyms_only():
    from src.data import check_switches
    from src.models.project import Manuscript, WriterProject
    fresh = WriterProject(name="Fresh", manuscript=Manuscript(title="Fresh"))
    kinds = check_switches.default_kinds(fresh)
    assert "homonym" in kinds and not {"sensory", "sentence_structure", "vague"} & kinds
    old = WriterProject(name="Old", manuscript=Manuscript(title="Old"))
    from datetime import datetime
    old.created_at = datetime(2026, 3, 1)
    assert not MORE & check_switches.default_kinds(old)


def test_the_queue_takes_them_with_a_fix_only_for_homonyms():
    from src.ai import fix_queue
    assert MORE <= set(fix_queue.STYLE_ONLY_KINDS)
    flags = [(0, i) for t in DOC.split("\n") for i in sc.analyze_paragraph(t, EVERY)
             if i.kind in MORE]
    by_kind = {e.item.kind: e for e in fix_queue.style_entries(flags)}
    assert by_kind["homonym"].item.suggestions == ["peek"]
    assert by_kind["homonym"].label == "Homonyms" and by_kind["homonym"].stage == "line"
    assert by_kind["sensory"].item.suggestions == []
    assert by_kind["sentence_structure"].item.suggestions == []


def test_an_old_project_opens_and_saves_unchanged(app):
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
    assert not MORE & w.current_chapter_editor.editor.writing_highlighter._style_kinds
    p.save_project(str(path))
    WriterProject.load_project(str(path))
    assert {f: f.read_bytes() for f in files} == before
    w.deleteLater()
    shutil.rmtree(d)


# ── The benchmark (Q.2) ─────────────────────────────────────────────

def test_the_benchmark_scores_the_four_kinds():
    import importlib.util
    spec = importlib.util.spec_from_file_location("score_checks", ROOT / "scripts" / "score_checks.py")
    s = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(s)
    assert MORE <= set(s.STYLE_KINDS)
    data = json.loads((ROOT / "benchmark" / "style" / "marked.json").read_text())
    ours = [p for p in data["passages"] if p.get("scores") and set(p["scores"]) == MORE]
    assert len(ours) >= 14
    assert {m["kind"] for p in ours for m in p["marks"]} == MORE
    for kind in MORE:                     # each has a right flag and a deliberate choice
        marks = [m["flag"] for p in ours for m in p["marks"] if m["kind"] == kind]
        assert True in marks and False in marks
