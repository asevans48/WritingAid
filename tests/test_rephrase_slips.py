"""Two old Rephrase slips, fixed.

(a) Each rating row is stamped with the style of the option that was
    rated, not always the first option's (the old code asked a
    ``results_list`` that does not exist, so the row was always 0).
(b) "Auto-detect from text" is in the character-voice list (it was added,
    then cleared away when the project's characters were filled in), and
    choosing it runs speaker detection.

Both in the old window and in the Improve window's hosted Rephrase tab.
Fake models, a scratch HOME and its temporary ratings database (conftest);
no real model, no LanguageTool."""

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).parent))

from test_improve_rephrase import (  # noqa: F401  (fixtures)
    OPTIONS, _window, app, chapter, collect, fake_rephrase, fire, project,
    rephrase_rows, result,
)


def _old(project):
    from src.ui.rephrase_dialog import RephraseDialog
    return RephraseDialog(OPTIONS[0][0], project, None,
                          chapter_content="Mara said it. " + OPTIONS[0][0])


def _style(i):
    return f"{OPTIONS[i][1]}/neutral"


# ── (a) the rated option's style ───────────────────────────────────────

def test_old_window_rows_carry_the_rated_options_style(app, project, fake_rephrase, collect):
    d = _old(project)
    d._on_generation_complete(result())
    d.options_list.setCurrentRow(1)
    d.rate_good_btn.click()
    fire(d)
    d.options_list.setCurrentRow(2)
    d.rate_bad_btn.click()
    d.options_list.setCurrentRow(0)        # leaving saves the waiting rating: option 3's
    rows = collect()
    assert [(r["rating"], r["style"], r["output_text"]) for r in rows] == [
        ("good", _style(1), OPTIONS[1][0]), ("bad", _style(2), OPTIONS[2][0])]
    d.options_list.setCurrentRow(2)
    d.rate_excellent_btn.click()
    d.preview_edit.setPlainText(OPTIONS[2][0] + " Edited.")
    d._use_selected()                      # accepted, edited; then the unedited option
    rows = collect()
    assert [(r["rating"], r["accepted"], r["style"]) for r in rows] == [
        ("excellent", 1, _style(2) + " | edited"), ("neutral", 0, _style(2))]
    d.deleteLater()


def test_hosted_tab_rows_carry_the_rated_options_style(app, project, chapter, fake_rephrase,
                                                       collect):
    win = _window(project, chapter)
    d = win.tab_objects["rephrase"].dlg
    d._on_generation_complete(result())
    rows = rephrase_rows(win)
    win.version_list.setCurrentRow(rows[1])
    win.rate_buttons["good"].click()
    fire(d)
    win.version_list.setCurrentRow(rows[2])
    win.rate_buttons["poor"].click()
    win.version_list.setCurrentRow(rows[0])   # leaving saves the waiting rating: option 3's
    saved = collect()
    assert [(r["rating"], r["style"], r["output_text"]) for r in saved] == [
        ("good", _style(1), OPTIONS[1][0]), ("poor", _style(2), OPTIONS[2][0])]
    win.version_list.setCurrentRow(rows[2])
    win._accept()                             # rated Poor: rejected, then accepted
    saved = collect()
    assert saved and {r["style"] for r in saved} == {_style(2)}


def test_a_rating_with_no_option_loaded_keeps_the_old_first_option_stamp(
        app, project, fake_rephrase, collect):
    d = _old(project)
    d.result = result()                       # options, none loaded in the preview
    d._log_to_rephrase_db("a source", "an output", rating="good")
    assert [r["style"] for r in collect()] == [_style(0)]
    d.deleteLater()


# ── (b) Auto-detect from text ──────────────────────────────────────────

def _auto(d):
    from PyQt6.QtCore import Qt
    items = [d.char_list.item(i) for i in range(d.char_list.count())]
    return [i for i in items if i.data(Qt.ItemDataRole.UserRole) == "__auto__"]


def _check_auto(d, monkeypatch):
    from PyQt6.QtCore import Qt
    auto = _auto(d)
    assert len(auto) == 1 and d.char_list.item(0) is auto[0]
    assert auto[0].text() == "Auto-detect from text"
    assert auto[0].flags() & Qt.ItemFlag.ItemIsSelectable
    assert d.char_list.item(1).text() == "Mara (protagonist)"   # characters still listed
    ran = []
    monkeypatch.setattr(type(d), "_detect_speaker_for_rephrase",
                        lambda self: ran.append(1) or "Speaker: Mara")
    auto[0].setSelected(True)
    assert d._get_selected_characters_context() == "Speaker: Mara" and ran == [1]
    d._populate_character_list()                  # a refill keeps it, once
    assert len(_auto(d)) == 1 and d.char_list.count() == 2


def test_old_window_lists_auto_detect_and_it_runs(app, project, fake_rephrase, monkeypatch):
    d = _old(project)
    _check_auto(d, monkeypatch)
    d.deleteLater()


def test_hosted_tab_lists_auto_detect_and_the_summary_says_so(app, project, chapter,
                                                              fake_rephrase, monkeypatch):
    win = _window(project, chapter)
    tab = win.tab_objects["rephrase"]
    d = tab.dlg
    assert tab.options.isAncestorOf(d.char_list)
    _check_auto(d, monkeypatch)
    d.char_list.item(0).setSelected(True)
    assert "Voice: auto-detect" in tab.summary.text()
    win.reject()


def test_with_no_project_auto_detect_is_still_there(app, fake_rephrase):
    from src.ui.rephrase_dialog import RephraseDialog
    d = RephraseDialog("Some text.", None, None)
    assert len(_auto(d)) == 1 and d.char_list.count() == 1
    d.deleteLater()
