"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_critique_history(tmp_path, monkeypatch):
    """Critique runs record history; keep it out of the user's home folder."""
    import src.data.critique_history as ch
    monkeypatch.setattr(ch, "history_path", lambda project: tmp_path / "critique_history.json")
