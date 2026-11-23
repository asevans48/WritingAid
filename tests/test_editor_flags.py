"""R.6: the editor's rules for which flags to show, without Qt."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent

import pytest  # noqa: E402


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

TEXT = ("# Chapter One\n\n"
        "\"Dont go,\" she said quickly. \"Its fine. Really really fine.\"\n\n"
        "Tommorow the Vethari came. Vethari were tall. Its a beutiful day and he dont care. "
        "The ball was thrown by him very very quickly at the end of the day. "
        "He walked and walked and walked and walked. He walked home and walked home.\n")


def _editor_and_state(qapp, text):
    from src.ui.enhanced_text_editor import CheckMode, EnhancedTextEditor
    from src.utils.editor_flags import FlagState
    from src.utils.style_checks import KINDS
    ed = EnhancedTextEditor()
    hl = ed.writing_highlighter
    for setter in (hl.set_spell_mode, hl.set_grammar_mode, hl.set_overuse_mode, hl.set_style_mode):
        setter(CheckMode.REALTIME)
    hl.set_style_kinds(set(KINDS))
    ed.setPlainText(text)
    ed.overuse_detector.update_cache(text)
    hl.update_full_text(text)
    hl.rehighlight()
    return ed, FlagState.from_highlighter(hl)


def _editor_flags(ed):
    doc = ed.document()
    out = []
    for n, errors in sorted(ed.writing_highlighter._errors.items()):
        pos = doc.findBlockByNumber(n).position()
        out += [(pos, e.error_type, e.start, e.end, e.word, e.reason) for e in errors]
    return out


def _state_flags(state, text):
    return [(pos, e.error_type, e.start, e.end, e.word, e.reason)
            for pos, e in state.flags_for_text(text)]


def test_the_engine_sees_exactly_what_the_editor_shows(qapp):
    texts = [TEXT] + [json.loads(f.read_text())["text"]
                      for f in sorted((ROOT / "benchmark" / "seeded").glob("*.json"))[:3]]
    for text in texts:
        ed, state = _editor_and_state(qapp, text)
        editor = _editor_flags(ed)
        assert editor, "the sample should raise flags"
        assert _state_flags(state, text) == editor
        families = {f[1].value for f in editor}
        assert {"spelling", "style"} <= families


def test_settings_carry_over(qapp):
    ed, _ = _editor_and_state(qapp, TEXT)
    hl = ed.writing_highlighter
    hl.phase = "drafting"
    hl.ignore_error(0, 0, "beutiful")
    hl.rehighlight()
    from src.utils.editor_flags import FlagState
    state = FlagState.from_highlighter(hl)
    flags = _state_flags(state, TEXT)
    assert flags == _editor_flags(ed)
    assert all(f[1].value in ("spelling", "grammar") for f in flags)     # drafting
    assert not any(f[4] == "beutiful" for f in flags)                    # ignored


def test_old_imports_are_the_same_objects():
    import src.ui.enhanced_text_editor as ete
    import src.utils.editor_flags as ef
    for name in ("CheckMode", "ErrorType", "WritingError", "issue_weight"):
        assert getattr(ete, name) is getattr(ef, name)
    assert issubclass(ete.WritingHighlighter, ef.FlagRules)


def test_no_qt_and_any_thread():
    code = (
        "import sys\n"
        "from src.utils.editor_flags import FlagState, flags_for_paragraph, CheckMode\n"
        "from src.utils.spell_checker import SpellChecker\n"
        "from src.utils.overuse import OveruseDetector\n"
        "s = FlagState(SpellChecker(), overuse_detector=OveruseDetector())\n"
        "s._style_mode = CheckMode.REALTIME\n"
        f"flags = s.flags_for_text({TEXT!r})\n"
        "assert any(e.word == 'beutiful' for _, e in flags), flags\n"
        "assert flags_for_paragraph('Its a beutiful day.', s)\n"
        "qt = sorted(m for m in sys.modules if m.startswith('PyQt'))\n"
        "assert not qt, qt\n"
        "print('ok')\n")
    env = dict(os.environ, HOME=os.environ.get("HOME", ""))
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                       env=env, timeout=120)
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-2000:]


def test_runs_on_a_worker_thread():
    from src.utils.editor_flags import CheckMode, FlagState
    from src.utils.overuse import OveruseDetector
    from src.utils.spell_checker import SpellChecker
    state = FlagState(SpellChecker(), overuse_detector=OveruseDetector())
    state._style_mode = CheckMode.REALTIME
    out, errors = [], []

    def work():
        try:
            out.extend(state.flags_for_text(TEXT))
        except Exception as e:      # pragma: no cover
            errors.append(e)
    t = threading.Thread(target=work)
    t.start()
    t.join(60)
    assert not errors and out
