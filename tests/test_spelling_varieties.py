"""British and period spellings, accepted when the writer says so."""

import os
import uuid

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.utils import spelling_varieties as sv
from src.utils.spell_checker import SpellChecker

BRITISH = "colour favourite neighbourhood realised organisation centre travelled defence mould grey programme".split()
PERIOD = "shew waggon thou hath betwixt".split()
TYPOS = "colur recieve beutiful organisaton".split()


def _bad(words):
    sc = SpellChecker()
    return [w for w in words if not sc.check_word(w)[0]]


def test_off_by_default_nothing_changes():
    assert _bad(BRITISH) == BRITISH or len(_bad(BRITISH)) >= 8
    assert _bad(TYPOS) == TYPOS


def test_british_spellings_pass_and_typos_do_not():
    sv.set_for_session(True, False)
    assert _bad(BRITISH) == []
    assert _bad(TYPOS) == TYPOS                       # the American twin must be a real word
    assert "waggon" in _bad(PERIOD)                   # period is a separate switch


def test_period_spellings():
    sv.set_for_session(False, True)
    assert "waggon" not in _bad(PERIOD)
    assert "colour" in _bad(BRITISH)


def test_a_checker_follows_a_change_of_settings():
    sc = SpellChecker()
    assert not sc.check_word("colour")[0]
    sv.set_for_session(True, False)
    assert sc.check_word("colour")[0]                 # its cache was dropped
    sv.set_for_session(False, False)
    assert not sc.check_word("colour")[0]


def test_readiness_follows_the_setting(tmp_path):
    from src.ai import readiness as rd
    from src.models.project import Chapter, Manuscript, WriterProject
    p = WriterProject(name="B", manuscript=Manuscript(title="B"))
    p.project_path = str(tmp_path / "b.writerproj")
    ch = Chapter(id=str(uuid.uuid4()), number=1, title="One", folder_root=p.manuscript.folder_root)
    ch.content = "The colour of the harbour was grey. She realised the theatre was empty.\n" * 6
    p.manuscript.chapters.append(ch)
    off = rd.chapter_report(p, ch).results["spelling_grammar"].count
    sv.set_for_session(True, False)
    on = rd.chapter_report(p, ch).results["spelling_grammar"].count      # not the cached result
    assert off > 0 and on == 0


def test_the_settings_page_has_both_switches(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
    app = QApplication.instance() or QApplication([])
    from src.ui.spelling_settings import SpellingOptions
    w = QWidget()
    opts = SpellingOptions(QVBoxLayout(w), {sv.KEY_BRITISH: True})
    assert opts.british.isChecked() and not opts.period.isChecked()
    opts.period.setChecked(True)
    assert opts.values() == {sv.KEY_BRITISH: True, sv.KEY_PERIOD: True}


def test_saving_settings_applies_at_once(monkeypatch):
    import types
    from src.ui import spelling_settings as ss
    monkeypatch.setattr(sv, "_read", lambda: {"british": True, "period": False})
    done = []
    hl = types.SimpleNamespace(rehighlight=lambda: done.append(1))
    mw = types.SimpleNamespace(manuscript_editor=types.SimpleNamespace(
        current_chapter_editor=types.SimpleNamespace(editor=types.SimpleNamespace(
            writing_highlighter=hl))))
    ss.apply_spelling_settings(mw)
    assert sv.current()["british"] and done == [1]
