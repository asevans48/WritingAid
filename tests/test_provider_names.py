"""R.1: one list of model providers.

Before the 24 copied provider maps were replaced, each one was evaluated for
every name below and the results recorded here. ``provider_for_name`` must
return exactly the same for every name at every site.
"""

import ast
import pathlib

import pytest

from src.ai.llm_client import LLMProvider
from src.ai.provider_names import PROVIDERS_BY_NAME, provider_for_name

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Recorded from the old maps. The lookup was exact, so case, spaces and the
# local kinds all fell through to the site's default.
_RECORDED = {
    "claude": "CLAUDE", "chatgpt": "CHATGPT", "openai": "CHATGPT",
    "gemini": "GEMINI", "server": "SERVER",
    "huggingface": None, "huggingface_local": None, "mlx_local": None,
    "local": None, "Claude": None, "CHATGPT": None, "Server": None,
    " claude": None, "claude ": None, "": None, None: None,
    "unknown": None, "anthropic": None,
}

# Every site that had a map, and what an unknown name gave there.
_SITES_DEFAULT_CLAUDE = [
    "src/ai/agent_suite.py", "src/ai/field_synthesizer.py",
    "src/ai/model_builder_agent.py", "src/data/corpus_adapters.py",
    "src/services/tts_service.py", "src/ui/characters_widget.py (2)",
    "src/ui/export_audio_dialog.py", "src/ui/main_window.py (7)",
    "src/ui/manuscript_editor.py", "src/ui/plot/plot_manager.py",
    "src/ui/rephrase_dialog.py (3)", "src/ui/training_tool_window.py (2)",
    "src/ui/world_word_dialog.py",
]
_SITES_DEFAULT_NONE = ["src/ai/task_llm.py"]


def _expected(name, default):
    got = _RECORDED[name]
    return getattr(LLMProvider, got) if got else default


@pytest.mark.parametrize("name", list(_RECORDED))
def test_matches_old_maps_that_defaulted_to_claude(name):
    assert provider_for_name(name) is _expected(name, LLMProvider.CLAUDE)


@pytest.mark.parametrize("name", list(_RECORDED))
def test_matches_old_map_that_defaulted_to_none(name):
    assert provider_for_name(name, None) is _expected(name, None)


def test_stored_names_unchanged():
    assert set(PROVIDERS_BY_NAME) == {
        "claude", "chatgpt", "openai", "gemini", "server"}


def _provider_map_literals():
    """Dict literals in src/ that map names to LLMProvider.SERVER."""
    found = []
    for path in sorted((ROOT / "src").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        if rel == "src/ai/provider_names.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Dict) and any(
                    isinstance(v, ast.Attribute) and v.attr == "SERVER"
                    and isinstance(v.value, ast.Name)
                    and v.value.id == "LLMProvider"
                    for v in node.values):
                found.append(rel)
    return found


def test_no_copied_maps_left():
    # The two image/video maps name LLMProvider.OPENAI, which does not exist,
    # so they raise when reached. Replacing them would change behaviour, so
    # they are left for a separate fix (see R.1 Outcome).
    assert sorted(_provider_map_literals()) == [
        "src/ai/image_generation_agent.py",
        "src/ai/video_generation_agent.py",
    ]
