"""Shared test fixtures."""

import pytest


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
