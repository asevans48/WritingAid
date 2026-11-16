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
