"""1.3–1.6: the line, copyedit, structure and scene checks."""

import os
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import readiness as rd
from src.models.project import Chapter, Character, Manuscript, WriterProject

# Written to trip the line checks: adverbs, passive, clichés, filler, echoes.
TRIPS = ("She ran quickly and quietly and very slowly down the road. The door was opened by "
         "him. It was all of a sudden over at the end of the day. He just really actually "
         "basically knew. The door, the door, the door was old. The ball was thrown by her. "
         "He spoke softly, gently, warmly and sadly. In order to leave, he left. The cake was "
         "eaten by them. Needless to say, it was what it was, as luck would have it.\n") * 6
# Plain, varied prose.
CLEAN = ("Rain came in off the river before dawn. Mara pulled her coat tight and walked "
         "the length of the wharf, counting the boats.\n\n"
         "Three had sailed. The fourth sat low, its hull dark with weed, a lantern swinging "
         "from the mast though no one stood on deck.\n\n"
         "She stopped. Somewhere below, a pump clanked twice and fell silent.\n\n"
         "\"Anyone there?\" she called. Nobody answered, and the gulls went on with their "
         "quarrel over a fish head on the stones.\n") * 4


def _project(tmp_path, *texts, genre="literary"):
    p = WriterProject(name="Book", manuscript=Manuscript(title="Book"))
    p.project_path = str(tmp_path / "book.writerproj")
    p.prose_profile.genre = genre
    p.characters.append(Character(id="m", name="Mara", character_type="protagonist"))
    for i, t in enumerate(texts):
        ch = Chapter(id=str(uuid.uuid4()), number=i + 1, title=f"Chapter {i + 1}",
                     folder_root=p.manuscript.folder_root)
        ch.content = t
        p.manuscript.chapters.append(ch)
    return p


LINE = ("echoes", "filler", "passive", "adverbs", "cliches")


def test_line_checks_trip_and_clean_prose_passes(tmp_path):
    p = _project(tmp_path, TRIPS, CLEAN)
    book = rd.book_report(p)
    tripped, clean = book.chapters[0].results, book.chapters[1].results
    for name in LINE:
        assert tripped[name].status != rd.Status.READY, name
        assert clean[name].status == rd.Status.READY, (name, clean[name].count)
    assert tripped["repetition"].status == rd.Status.NEEDS_MODEL      # shown, not counted
    assert "repetition" in book.left_out and "repetition" not in book.counted
    assert all(i.kind == "adverb" for i in tripped["adverbs"].items)
    assert tripped["adverbs"].items[0].text.lower().endswith("ly")


def test_line_checks_count_what_the_editor_shows(tmp_path, qapp):
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    from src.utils.style_checks import KINDS
    p = _project(tmp_path, TRIPS)
    ed = EnhancedTextEditor()
    ed.set_project_vocabulary(p)
    hl = ed.writing_highlighter
    hl.set_style_mode(CheckMode.REALTIME)
    hl.set_style_kinds(set(KINDS))
    ed.setPlainText(TRIPS)
    hl.rehighlight()
    shown = sum(1 for errs in hl._errors.values() for e in errs
                if getattr(e, "style_kind", "") == "passive")
    r = rd.chapter_report(p, p.manuscript.chapters[0])
    assert r.results["passive"].count == shown > 0


def test_kept_kinds_and_ignored_flags_are_respected(tmp_path):
    from src.models.project import StyleRule
    p = _project(tmp_path, TRIPS)
    before = rd.chapter_report(p, p.manuscript.chapters[0], use_cache=False)
    assert before.results["adverbs"].count > 0
    p.style_sheet.append(StyleRule(id="k", text="Adverbs are my style", kind="keep",
                                   subject="adverb", status="active"))
    after = rd.chapter_report(p, p.manuscript.chapters[0], use_cache=False)
    assert after.results["adverbs"].count == 0                 # the writer keeps them


def test_sentence_variety_is_a_score(tmp_path):
    flat = "The cat sat on the mat. " * 30 + "\n"
    p = _project(tmp_path, flat, CLEAN)
    book = rd.book_report(p)
    var = book.chapters[0].results["sentence_variety"]
    assert var.status == rd.Status.PROBLEM and var.measure < 20
    assert rd.REGISTRY["sentence_variety"].display == "measure"
    short = _project(tmp_path, "Too short. Two sentences.")
    assert "sentence_variety" not in rd.chapter_report(short, short.manuscript.chapters[0]).results


# ── Copyedit ─────────────────────────────────────────────────────────────

def test_consistency_across_chapters(tmp_path):
    a = CLEAN + "\nHer grey coat was wet. The grey sky. A grey gull.\n"
    b = CLEAN + "\nHis gray hat.\n"
    p = _project(tmp_path, a, b)
    book = rd.book_report(p)
    first, second = (c.results["consistency"] for c in book.chapters)
    assert second.count == 1 and second.items[0].text == "gray"
    assert second.items[0].suggestions == ["grey"] and "grey" in second.items[0].reason
    assert first.count == 0
    # It depends on every chapter: changing the other chapter re-checks it.
    p.manuscript.chapters[0].content = a.replace("grey", "gray")
    again = rd.book_report(p)
    assert again.chapters[0].results["consistency"].count == 0 or \
        again.chapters[1].results["consistency"].count == 0


def test_names_ending_in_s_are_not_misspellings(tmp_path):
    from src.utils.consistency_checks import ConsistencyChecker
    text = "Dorcas came in. Dorcas's coat was wet. The Dorcas' hats. Paris was far.\n" * 3
    groups = ConsistencyChecker([("c", "One", text)], ["Dorcas", "Paris"],
                                is_known_word=lambda w: False).run()
    assert not [g for g in groups if g.kind == "name"]


def test_style_sheet_breaks(tmp_path):
    from src.models.project import StyleRule
    p = _project(tmp_path, CLEAN + "\nShe said okay.\n")
    assert "style_sheet" not in rd.chapter_report(p, p.manuscript.chapters[0]).results
    p.style_sheet.append(StyleRule(id="r", text="OK, not okay", kind="prefer",
                                   subject="okay", replacement="OK", status="active"))
    r = rd.chapter_report(p, p.manuscript.chapters[0], use_cache=False).results["style_sheet"]
    assert r.count == 1 and r.items[0].text == "okay" and r.items[0].suggestions == ["OK"]


# ── Structure ────────────────────────────────────────────────────────────

def test_pacing_says_which_genre_it_used(tmp_path):
    p = _project(tmp_path, CLEAN, genre="thriller")
    pacing = rd.chapter_report(p, p.manuscript.chapters[0]).results["pacing"]
    assert "Thriller" in pacing.message and pacing.status in rd.Status.VERDICTS
    none = _project(tmp_path, CLEAN, genre="")
    msg = rd.chapter_report(none, none.manuscript.chapters[0]).results["pacing"].message
    assert "no genre is set" in msg


def test_lengths_are_information_only(tmp_path):
    p = _project(tmp_path, CLEAN, CLEAN)
    book = rd.book_report(p)
    ch = book.chapters[0].results["chapter_length"]
    assert ch.status == rd.Status.INFO and ch.measure == len(CLEAN.split())
    ms = book.book_results["manuscript_length"]
    assert ms.status == rd.Status.INFO and "Typical for" in ms.message
    assert "chapter_length" not in book.counted and "manuscript_length" not in book.counted


def test_subplots_and_promises(tmp_path):
    from src.models.project import StoryPromise, Subplot, SubplotNote
    p = _project(tmp_path, CLEAN, CLEAN)
    assert "subplots" not in rd.book_report(p).book_results      # no subplots: doesn't apply
    sp = p.story_planning
    sp.subplots += [Subplot(id="s1", title="The smuggling ring", description=""),
                    Subplot(id="s2", title="Mara's brother", description="")]
    r = rd.book_report(p).book_results["subplots"]
    assert r.status == rd.Status.INFO and "links a subplot" in r.message   # nothing linked yet
    p.manuscript.chapters[0].planning.subplot_notes.append(
        SubplotNote(id="n", title="ring", content="", subplot_id="s1"))
    r = rd.book_report(p).book_results["subplots"]
    assert r.count == 1 and r.items[0].text == "Mara's brother"
    assert "promises" not in rd.book_report(p).book_results
    sp.promises.append(StoryPromise(id="p", promise_type="plot", title="Who sank the boat?"))
    pr = rd.book_report(p).book_results["promises"]
    assert pr.status == rd.Status.NEEDS_MODEL


# ── Scene ────────────────────────────────────────────────────────────────

def test_dialogue_problems(tmp_path):
    talk = ('"Go," Mara hissed angrily. "Mara, listen, Mara," Mara expostulated.\n\n' * 3) + CLEAN
    p = _project(tmp_path, talk)
    r = rd.chapter_report(p, p.manuscript.chapters[0]).results["dialogue_problems"]
    kinds = {i.kind for i in r.items}
    assert {"bookism", "tag_adverb"} & kinds and r.count > 0
    quiet = _project(tmp_path, "No one spoke. The boats rocked. " * 20)
    assert "dialogue_problems" not in rd.chapter_report(
        quiet, quiet.manuscript.chapters[0]).results                 # no dialogue


def test_dialogue_fit_needs_known_voices(tmp_path):
    p = _project(tmp_path, CLEAN)
    assert "dialogue_fit" not in rd.chapter_report(p, p.manuscript.chapters[0]).results


def test_continuity(tmp_path):
    p = _project(tmp_path, CLEAN)
    book = rd.book_report(p)
    assert book.chapters[0].results["continuity"].status == rd.Status.NEEDS_MODEL
    assert "continuity_novellas" not in book.book_results           # no novellas
    sp = p.create_subproject("Novella")
    ch = Chapter(id="n1", number=1, title="N1", folder_root=sp.manuscript.folder_root)
    ch.content = CLEAN
    sp.manuscript.chapters.append(ch)
    main = rd.book_report(p, None)
    nov = rd.book_report(p, sp.id)
    assert main.book_results["continuity_novellas"].status == rd.Status.NEEDS_MODEL
    assert "continuity_novellas" not in nov.book_results            # shown once, on the main


def test_book_checks_are_cached_on_every_chapter(tmp_path, monkeypatch):
    p = _project(tmp_path, CLEAN, CLEAN)
    calls = []
    spec = rd.checks_for() and rd.REGISTRY["manuscript_length"]
    real = spec.fn
    monkeypatch.setattr(spec, "fn", lambda ctx: calls.append(1) or real(ctx))
    rd.book_report(p)
    rd.book_report(p)
    assert len(calls) == 1
    p.manuscript.chapters[1].content = CLEAN + "More.\n"
    rd.book_report(p)
    assert len(calls) == 2


def test_whole_manuscript_row_on_the_scorecard(qapp, tmp_path, monkeypatch):
    import src.ui.scorecard_widget as sw
    from src.ui.grader_widget import GraderWidget
    from src.models.project import Subplot, SubplotNote
    monkeypatch.setattr(sw, "_settings", lambda: type("S", (), {
        "value": lambda self, k, d=None: d, "setValue": lambda self, k, v: None})())
    p = _project(tmp_path, CLEAN, CLEAN)
    p.story_planning.subplots += [Subplot(id="s1", title="Ring", description=""), Subplot(id="s2", title="Brother", description="")]
    p.manuscript.chapters[0].planning.subplot_notes.append(
        SubplotNote(id="n", title="r", content="", subplot_id="s1"))
    g = GraderWidget()
    g.set_project(p)
    sc = g.scorecard
    sc.refresh()
    from src.ui import background
    for _ in range(100):
        background.wait_all(5000)
        qapp.processEvents()
        if sc._task is None:
            break
    last = sc.table.rowCount() - 1
    assert sc.table.verticalHeaderItem(last).text() == "Whole manuscript"
    col = next(c for c, n in enumerate(sc._column_checks) if n == ["manuscript_length"])
    assert sc.table.item(last, col).text() == f"{2 * len(CLEAN.split()):,}"   # words, no colour
    sc._select_row(last, None)
    text = sc.issues.toPlainText()
    assert "Whole manuscript" in text and "Brother" in text and "Run Critique" not in text


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])
