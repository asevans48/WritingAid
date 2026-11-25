"""Shared test fixtures."""

import os
import pwd
from pathlib import Path

import pytest


def _share_dictionary_data() -> None:
    """Tests run with HOME set to a scratch folder, which hides the WordNet
    data installed in the user's real ``~/nltk_data``. That data is a
    read-only dictionary, not the writer's work, so let the tests find it.
    Without it the WordNet tests fail for a reason unrelated to the code."""
    if os.environ.get("NLTK_DATA"):
        return
    try:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:
        return
    data = real_home / "nltk_data"
    if data.is_dir() and Path.home() != real_home:
        os.environ["NLTK_DATA"] = str(data)
        try:
            import nltk
            if str(data) not in nltk.data.path:
                nltk.data.path.insert(0, str(data))
        except Exception:
            pass


_share_dictionary_data()


def _share_languagetool_program() -> None:
    """The same for LanguageTool: with a scratch HOME, a test that starts it
    would download it again (about 260 MB) into the scratch folder. Point
    language_tool_python at the copy already installed in the real
    ``~/.cache`` (a program, not the writer's work)."""
    if os.environ.get("LTP_PATH"):
        return
    try:
        real_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:
        return
    installed = real_home / ".cache" / "language_tool_python"
    if installed.is_dir() and any(installed.glob("LanguageTool-*")) \
            and Path.home() != real_home:
        os.environ["LTP_PATH"] = str(installed)


_share_languagetool_program()


@pytest.fixture(autouse=True)
def _isolated_critique_history(tmp_path, monkeypatch):
    """Critique runs record history; keep it out of the user's home folder."""
    import src.data.critique_history as ch
    monkeypatch.setattr(ch, "history_path", lambda project: tmp_path / "critique_history.json")


@pytest.fixture(autouse=True)
def _isolated_rephrase_database(tmp_path, monkeypatch):
    """Ratings and logged rewrites go to a throwaway database, never the
    user's real one (data collection may be switched on)."""
    import src.data.rephrase_database as rd
    monkeypatch.setattr(rd, "_instance", rd.RephraseDatabase(tmp_path / "rephrase_test.db"))


@pytest.fixture(autouse=True)
def _no_personal_avoid_list(monkeypatch):
    """The writer's own avoided phrases live in their settings; tests use none."""
    import src.ai.rewrite_quality as rq
    monkeypatch.setattr(rq, "avoid_phrases", lambda: [])


@pytest.fixture(autouse=True)
def _no_model_for_background_review(monkeypatch):
    """Editors review light repeats with the configured model in the
    background; tests never load the writer's real model."""
    import src.ai.word_suggest as ws
    monkeypatch.setattr(ws, "get_llm", lambda: None)


@pytest.fixture(autouse=True)
def _isolated_companion_state(tmp_path, monkeypatch):
    """The writing companion remembers sessions; keep that out of the
    user's home folder."""
    import src.data.companion_state as cs
    monkeypatch.setattr(cs, "state_path", lambda project: tmp_path / "companion_state.json")


@pytest.fixture(autouse=True)
def _isolated_window_geometry(tmp_path, monkeypatch):
    """Window positions (ui_kit.remember_geometry) go to a throwaway file,
    never the writer's real settings."""
    try:
        from PyQt6.QtCore import QSettings
        import src.ui.ui_kit as kit
    except Exception:
        return
    path = str(tmp_path / "window_geometry.ini")
    monkeypatch.setattr(kit, "_settings", lambda: QSettings(path, QSettings.Format.IniFormat))


@pytest.fixture(autouse=True)
def _american_spelling_by_default():
    """The British / period spelling settings start off in every test (and
    never read the writer's real settings)."""
    from src.utils import spelling_varieties as sv
    sv.set_for_session(False, False)
    yield
    sv.set_for_session(False, False)


@pytest.fixture(autouse=True)
def _fresh_model_verdicts():
    """The flag and repetition judges remember verdicts in memory; one
    test's "intended word" must not leak into the next."""
    try:
        from src.ai import flag_judge, repetition_judge
    except Exception:
        yield
        return
    flag_judge._CACHE.clear()
    repetition_judge._CACHE.clear()
    from src.utils import proof_store
    proof_store.clear()                 # a model's stored corrections
    yield
    flag_judge._CACHE.clear()
    repetition_judge._CACHE.clear()


@pytest.fixture(autouse=True)
def _isolated_critique_resume(tmp_path, monkeypatch):
    """A stopped critique's finished reports: beside a saved project (a
    temporary folder in tests); an unsaved one's go to a temporary folder."""
    import src.data.critique_resume as cr
    original = cr.resume_path

    def path(project):
        if getattr(project, "project_path", ""):
            return original(project)
        return tmp_path / "critique_resume" / "unsaved.json"
    monkeypatch.setattr(cr, "resume_path", path)


@pytest.fixture(autouse=True)
def _isolated_readiness_file(tmp_path, monkeypatch):
    """The readiness file (route, and later readiness results) sits beside a
    saved project, which tests keep in temporary folders; an unsaved one
    would go to the home folder, so send it to a temporary one."""
    import src.data.readiness_state as rs
    original = rs.readiness_path

    def path(project):
        if getattr(project, "project_path", ""):
            return original(project)
        return tmp_path / "readiness" / "unsaved.json"
    monkeypatch.setattr(rs, "readiness_path", path)


@pytest.fixture(autouse=True)
def _isolated_genre_baseline(tmp_path, monkeypatch):
    """The genre baseline (P.3) is read from the home folder; tests start
    with none, in a temporary folder, so checks keep their fixed figures."""
    import src.ai.genre_baseline as gb
    monkeypatch.setattr(gb, "baseline_path", lambda: tmp_path / "genre_baseline.json")
    gb._LOADED.update(key=None, data={})
    import src.data.conlit_loader as cl        # and no CONLIT unless a test puts one there
    monkeypatch.setattr(cl, "_CONLIT_PATH_HINT_FILE", tmp_path / "conlit_path.txt")
    monkeypatch.setattr(cl, "_DEFAULT_LOCAL_CONLIT_DIR", tmp_path / "conlit")
    monkeypatch.setattr(cl, "_CONLIT_CACHE_FILE", tmp_path / "conlit_stats.json")
