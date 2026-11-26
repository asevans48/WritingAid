"""LanguageTool's Java server is stopped when the process ends (no orphans)."""

import atexit

from src.utils import proofing


class _FakeTool:
    def __init__(self):
        self.closed = False
        self.disabled_rules = set()

    def close(self):
        self.closed = True


def test_a_started_server_is_closed_at_exit(monkeypatch):
    import src.utils.lt_ngrams as ng
    registered = []
    monkeypatch.setattr(atexit, "register", lambda fn, *a, **k: registered.append(fn))
    monkeypatch.setattr(proofing.LanguageToolEngine, "prerequisites", staticmethod(lambda: (True, "")))
    tool = _FakeTool()
    monkeypatch.setattr(ng, "start_language_tool", lambda lang: (tool, False))
    engine = proofing.LanguageToolEngine()
    assert engine.ensure_started()
    assert len(registered) == 1
    engine.close()                       # a restart closes and starts again …
    assert engine.ensure_started()
    assert len(registered) == 1          # … without a second exit hook
    registered[0]()                      # the process ends
    assert tool.closed and engine.status == "idle"
