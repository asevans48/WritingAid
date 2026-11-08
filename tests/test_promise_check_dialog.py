"""The chapter Promise Check dialog builds its model from AI settings
(it used to import a non-existent ``src.config.get_settings``)."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return "OVERALL_SCORE: 8\nSUMMARY: The chapter keeps its promises.\n"


_APP = None


def _dialog():
    global _APP
    from PyQt6.QtWidgets import QApplication
    _APP = QApplication.instance() or QApplication([])
    from src.ui.manuscript_editor import PromiseCheckDialog
    return PromiseCheckDialog(
        chapter_title="The Pier", chapter_content="Mara walked the pier. " * 20,
        promises=[{"title": "The Gull returns", "description": "", "promise_type": "plot"}],
        characters=[{"name": "Mara", "personality": "guarded"}])


def test_runs_with_default_model(monkeypatch):
    import src.ai.task_llm as tl
    llm = FakeLLM()
    monkeypatch.setattr(tl, "build_task_llm_override", lambda task: None)
    monkeypatch.setattr(tl, "build_default_llm", lambda: llm)
    d = _dialog()
    d._run_check()
    out = d.results_text.toPlainText()
    assert "AI module not available" not in out and "get_settings" not in out
    assert llm.prompts and "Mara walked the pier" in llm.prompts[0]
    assert d.run_button.isEnabled()


def test_explains_when_no_model_configured(monkeypatch):
    import src.ai.task_llm as tl
    monkeypatch.setattr(tl, "build_task_llm_override", lambda task: None)
    monkeypatch.setattr(tl, "build_default_llm", lambda: None)
    d = _dialog()
    d._run_check()
    assert "No AI model is configured" in d.results_text.toPlainText()
    assert d.run_button.isEnabled()


def test_plot_task_model_takes_priority(monkeypatch):
    import src.ai.task_llm as tl
    plot, default = FakeLLM(), FakeLLM()
    monkeypatch.setattr(tl, "build_task_llm_override", lambda task: plot)
    monkeypatch.setattr(tl, "build_default_llm", lambda: default)
    _dialog()._run_check()
    assert plot.prompts and not default.prompts


def test_reports_why_the_local_model_failed(monkeypatch):
    import src.ai.task_llm as tl
    monkeypatch.setattr(tl, "build_task_llm_override", lambda task: None)

    def failing():
        tl._last_error = "Couldn't load the local model 'mlx-community/x': boom"
        return None
    monkeypatch.setattr(tl, "build_default_llm", failing)
    d = _dialog()
    d._run_check()
    assert "Couldn't load the local model 'mlx-community/x': boom" in d.results_text.toPlainText()
