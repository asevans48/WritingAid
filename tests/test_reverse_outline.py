"""7.1: a reverse outline without a model, in the Critique."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import reverse_outline as ro

# Three scenes, counted by hand:
#   1: 9 + 6 = 15 words, 4 of them in quotes (Mara 1 line, Tobin 1 line)
#   2: 5 words, no dialogue
#   3: 9 words, 4 in quotes (Tobin 1 line, one unclear line)
TEXT = ("Rain fell on the harbor. “Go now,” Mara said.\n"
        "“Not yet,” said Tobin, and waited.\n"
        "\n"
        "***\n"
        "\n"
        "Morning came cold and grey.\n"
        "\n"
        "\n"
        "Tobin walked out. “Hello,” Tobin said.\n"
        "“Who is there?”")


def test_scenes_split_at_breaks_and_double_blank_lines():
    spans = ro.split_scenes(TEXT)
    parts = [TEXT[s:e].strip() for s, e in spans]
    assert len(parts) == 3
    assert parts[0].startswith("Rain fell") and parts[1] == "Morning came cold and grey."
    assert parts[2].startswith("Tobin walked out")


def test_counts_against_a_hand_count():
    scenes = ro.outline(TEXT, ["Mara", "Tobin"])
    assert [s.words for s in scenes] == [15, 5, 9]
    assert [s.dialogue_words for s in scenes] == [4, 0, 4]
    assert scenes[0].speakers == [("Mara", 1), ("Tobin", 1)]
    assert scenes[1].speakers == [] and scenes[1].dialogue_share == 0
    assert scenes[2].speakers == [("Tobin", 1)] and scenes[2].unattributed == 1
    assert TEXT[scenes[1].start:].startswith("Morning came")       # where it starts
    assert scenes[2].opening.startswith("Tobin walked out.")


def test_no_breaks_is_one_scene():
    assert len(ro.outline("One paragraph.\nAnother line.", [])) == 1


def test_describe_reads_plainly():
    s = ro.outline(TEXT, ["Mara", "Tobin"])
    assert ro.describe(s[1]) == "5 words · no dialogue"
    assert ro.describe(s[2]) == "9 words · 44% dialogue: Tobin (1), unclear (1)"


def test_cached_by_text():
    a = ro.outline(TEXT, ["Mara"])
    assert ro.outline(TEXT, ["Mara"]) is a
    assert ro.outline(TEXT + " More.", ["Mara"]) is not a


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_the_critique_shows_it_closed_then_open_with_links(app):
    from types import SimpleNamespace as NS
    from PyQt6.QtCore import QUrl
    from src.ui.readiness_issues import ChapterIssues
    view = ChapterIssues()
    view.outline_names = lambda: ["Mara", "Tobin"]
    ch = NS(chapter_id="c1", number=1, title="One", words=27, text_hash="", is_opening=False,
            results={}, stage="", scope=None)
    view.show_chapter(ch, None, TEXT, {})
    page = view.toPlainText()
    assert "Scene outline (3 scenes) ▸" in page and "Morning came" not in page
    toggle = next(i for i, (k, _) in enumerate(view._links) if k == "outline")
    view._on_link(QUrl(f"issue:{toggle}"))
    page = view.toPlainText()
    assert "Scene outline (3 scenes) ▾" in page and "“Morning came cold and grey.…”" in page
    got = []
    view.show_requested.connect(lambda cid, text, at: got.append((cid, text, at)))
    shows = [i for i, (k, _) in enumerate(view._links) if k == "show"]
    view._on_link(QUrl(f"issue:{shows[1]}"))
    assert got == [("c1", "Morning came cold and grey.", TEXT.index("Morning"))]


def test_not_shown_on_the_whole_manuscript_row(app):
    from types import SimpleNamespace as NS
    from src.ai import readiness as rd
    from src.ui.readiness_issues import ChapterIssues
    view = ChapterIssues()
    ch = NS(chapter_id=rd.BOOK_ROW, number=0, title="Whole manuscript", words=0, text_hash="",
            is_opening=False, results={}, stage="", scope=None)
    view.show_chapter(ch, None, None, {})
    assert "Scene outline" not in view.toPlainText()
