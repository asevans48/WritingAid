"""Shared local-model layer: Gemma 4 quant catalog, one loader, one copy in
memory, sizing, torchvision guard."""

import gc
import sys
import threading
import time
from types import SimpleNamespace as NS

import pytest

from src.ai import mlx_utils as mu

IDS = {
    ("26", "4bit"): "mlx-community/gemma-4-26b-a4b-it-4bit",
    ("26", "8bit"): "mlx-community/gemma-4-26b-a4b-it-8bit",
    ("31", "4bit"): "mlx-community/gemma-4-31b-it-4bit",
    ("31", "8bit"): "mlx-community/gemma-4-31b-it-8bit",
}


class FakeModel:
    pass


@pytest.fixture
def loader(monkeypatch):
    """A fresh slot with a counting fake loader."""
    calls = []

    def fake(model_id):
        calls.append(model_id)
        return FakeModel(), f"tok:{model_id}"
    monkeypatch.setattr(mu, "_load_with_fallback", fake)
    monkeypatch.setattr(mu, "check_model_fits", lambda m: "")
    mu.get_mlx_cache().unload()
    mu._live_models.clear()
    yield calls
    mu.get_mlx_cache().unload()
    mu._live_models.clear()


# ── Catalog + selection ───────────────────────────────────────────

@pytest.mark.parametrize("model_id", IDS.values())
def test_catalog_lists_gemma4_quants(model_id):
    from src.ui.model_picker_widget import MLX_MODELS
    assert model_id in {m.model_id for m in MLX_MODELS}


@pytest.mark.parametrize("model_id", IDS.values())
def test_every_task_can_select_gemma4_quants(model_id, monkeypatch):
    """Task pickers enumerate the catalog; specs parse and resolve."""
    from src.config.creativeos_config import parse_task_model_spec, format_task_model_spec, TASK_MODEL_KEYS
    from src.data import model_registry as reg
    entries = {e.id: e for e in reg.list_models(framework="mlx")}
    assert model_id in entries and entries[model_id].size_b >= 20
    spec = format_task_model_spec("mlx", model_id=model_id)
    assert parse_task_model_spec(spec) == {"kind": "mlx", "model_id": model_id}
    assert {"model_for_rephrase", "model_for_worldbuilding", "model_for_general",
            "model_for_critique", "model_for_plot", "model_for_character"} <= set(TASK_MODEL_KEYS)


def test_picker_offers_gemma4_quants():
    from src.ui.per_task_model_picker import build_task_picker_options
    specs = {spec for _, spec, sep in build_task_picker_options() if not sep}
    for model_id in IDS.values():
        assert any(s and s.endswith(model_id) for s in specs), model_id


def test_old_settings_values_still_parse():
    from src.config.creativeos_config import parse_task_model_spec
    assert parse_task_model_spec("") == {"kind": ""}
    assert parse_task_model_spec("my-trained") == {"kind": "trained", "name": "my-trained"}
    assert parse_task_model_spec("cloud:claude")["provider"] == "claude"


# ── Sizing ────────────────────────────────────────────────────────

@pytest.mark.parametrize("model_id,quant,billions,low,high", [
    (IDS[("26", "4bit")], "4bit", 26, 14, 17),
    (IDS[("26", "8bit")], "8bit", 26, 26, 30),
    (IDS[("31", "4bit")], "4bit", 31, 17, 20),
    (IDS[("31", "8bit")], "8bit", 31, 32, 36),
    ("google/gemma-4-31b-it", "", 31, 60, 64),
])
def test_sizes(model_id, quant, billions, low, high):
    assert mu.quantization_of(model_id) == quant
    assert mu.parameter_billions(model_id) == billions
    assert low <= mu.estimate_weights_gb(model_id) <= high


def test_ram_estimate_is_quantization_aware():
    from src.ai.model_cache import _estimated_ram_gb
    e = lambda i, s: NS(size_b=s, id=i, base_model=i, path="", is_adapter=False)
    four = _estimated_ram_gb(e(IDS[("26", "4bit")], 26))
    eight = _estimated_ram_gb(e(IDS[("26", "8bit")], 26))
    assert 16 <= four <= 20 and 30 <= eight <= 36
    assert _estimated_ram_gb(e("google/gemma-3-4b-it", 4)) == pytest.approx(8.9, abs=0.2)


def test_oversized_model_is_refused_with_alternative(monkeypatch):
    monkeypatch.setattr(mu, "total_ram_gb", lambda: 32.0)
    monkeypatch.setattr(mu, "allow_oversized_models", lambda: False)
    with pytest.raises(mu.ModelTooLargeError) as e:
        mu.check_model_fits(IDS[("31", "8bit")])
    assert IDS[("31", "4bit")] in str(e.value)
    monkeypatch.setattr(mu, "allow_oversized_models", lambda: True)
    assert "needs about" in mu.check_model_fits(IDS[("31", "8bit")])


def test_tight_fit_warns_and_small_fit_is_silent(monkeypatch):
    monkeypatch.setattr(mu, "total_ram_gb", lambda: 32.0)
    assert "needs about" in mu.check_model_fits(IDS[("26", "8bit")])   # loads, with a warning
    assert mu.check_model_fits(IDS[("26", "4bit")]) == ""


# ── One loader, one copy ──────────────────────────────────────────

def test_same_model_is_loaded_once(loader):
    a = mu.load_mlx_model("m/a-4bit")
    b = mu.load_mlx_model("m/a-4bit")
    assert a[0] is b[0] and loader == ["m/a-4bit"]


def test_old_model_released_before_new_one_loads(loader, monkeypatch):
    seen = {}
    real = mu._load_with_fallback

    def spy(mid):
        seen[mid] = mu.get_mlx_cache().is_loaded()
        return real(mid)
    monkeypatch.setattr(mu, "_load_with_fallback", spy)
    mu.load_mlx_model("m/a")
    mu.load_mlx_model("m/b")
    assert seen == {"m/a": False, "m/b": False}          # slot empty during each load
    assert mu.get_mlx_cache().is_loaded("m/b")


def test_concurrent_requests_share_one_load(loader, monkeypatch):
    real = mu._load_with_fallback

    def slow(mid):
        time.sleep(0.05)
        return real(mid)
    monkeypatch.setattr(mu, "_load_with_fallback", slow)
    results = []
    ts = [threading.Thread(target=lambda: results.append(mu.load_mlx_model("m/a"))) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(loader) == 1 and all(r[0] is results[0][0] for r in results)


def test_hub_reuses_model_already_in_memory_without_taking_the_slot(loader):
    from src.ai.model_cache import _load_mlx
    chat_model, _ = mu.load_mlx_model("m/a")
    tok, model = _load_mlx("m/a")
    assert model is chat_model and loader == ["m/a"]
    other = mu.load_mlx_model("m/b", use_slot=False)
    assert mu.get_mlx_cache().is_loaded("m/a")           # Hub load didn't evict the chat's
    assert other[0] is not chat_model


def test_live_copy_held_by_a_client_is_reused(loader):
    held, _ = mu.load_mlx_model("m/a")
    mu.load_mlx_model("m/b")                              # slot moves on; client still holds a
    again, _ = mu.load_mlx_model("m/a")
    assert again is held and loader == ["m/a", "m/b"]


def test_released_model_is_actually_freed(loader):
    import weakref
    m, _ = mu.load_mlx_model("m/a")
    ref = weakref.ref(m)
    del m
    mu.get_mlx_cache().unload()
    gc.collect()
    assert ref() is None
    mu.load_mlx_model("m/a")
    assert loader == ["m/a", "m/a"]                       # genuinely reloaded


def test_generation_is_serialised():
    active, peak = [0], [0]

    def work():
        with mu.MLX_GENERATE_LOCK:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            time.sleep(0.01)
            active[0] -= 1
    ts = [threading.Thread(target=work) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert peak[0] == 1


# ── Loader fallbacks + clients ────────────────────────────────────

def _fake_mlx(monkeypatch, lm_error=None):
    import types
    lm = types.ModuleType("mlx_lm")

    def load(mid):
        if lm_error:
            raise lm_error
        return "lm-model", "lm-tok"
    lm.load = load
    vlm = types.ModuleType("mlx_vlm")
    vlm.load = lambda mid: ("vlm-model", "vlm-tok")
    monkeypatch.setitem(sys.modules, "mlx_lm", lm)
    monkeypatch.setitem(sys.modules, "mlx_vlm", vlm)


@pytest.mark.parametrize("msg", ["Model type gemma4 not supported",
                                 "Could not import module 'Gemma4Config'. Are this..."])
def test_falls_back_to_vlm(monkeypatch, msg):
    _fake_mlx(monkeypatch, RuntimeError(msg))
    assert mu._load_with_fallback("m/x") == ("vlm-model", "vlm-tok")


def test_prefers_mlx_lm_and_reports_real_failures(monkeypatch):
    _fake_mlx(monkeypatch)
    assert mu._load_with_fallback("m/x") == ("lm-model", "lm-tok")
    _fake_mlx(monkeypatch, RuntimeError("disk on fire"))
    with pytest.raises(RuntimeError, match="disk on fire"):
        mu._load_with_fallback("m/x")


def test_llm_client_and_rephrase_use_shared_loader(loader):
    from src.ai.llm_client import HuggingFaceConfig, LLMClient, LLMProvider
    c1 = LLMClient(provider=LLMProvider.MLX_LOCAL,
                   hf_config=HuggingFaceConfig(model_id="m/a-4bit", use_local=True))
    c2 = LLMClient(provider=LLMProvider.MLX_LOCAL,
                   hf_config=HuggingFaceConfig(model_id="m/a-4bit", use_local=True))
    assert c1._mlx_model is c2._mlx_model and loader == ["m/a-4bit"]
    assert c1.has_loaded_local_model()


def test_free_ram_really_clears_the_slot(loader):
    from src.ai.llm_client import HuggingFaceConfig, LLMClient, LLMProvider, unload_all_local_clients
    c = LLMClient(provider=LLMProvider.MLX_LOCAL,
                  hf_config=HuggingFaceConfig(model_id="m/a-4bit", use_local=True))
    assert unload_all_local_clients(clear_cuda=False) >= 1
    assert not mu.get_mlx_cache().is_loaded() and not c.has_loaded_local_model()


def test_hf_clients_share_one_pipeline(monkeypatch):
    import src.ai.llm_client as lc
    lc._HF_SHARED.clear()
    cfg = lc.HuggingFaceConfig(model_id="org/m", use_local=True)
    pipe = object()
    lc._HF_SHARED[lc._hf_cache_key(cfg)] = (pipe, "tok")
    c = lc.LLMClient(provider=lc.LLMProvider.HUGGINGFACE_LOCAL, hf_config=cfg)
    assert c._hf_pipeline is pipe and c._hf_tokenizer == "tok"
    lc.release_shared_hf_models()
    assert not lc._HF_SHARED


def test_rephrase_id_tables_cover_gemma4():
    from src.ai.rephrasing_agent import RephrasingAgent
    a = RephrasingAgent(use_python_libraries=True)
    assert a._convert_to_mlx_model_id("google/gemma-4-31b-it") == IDS[("31", "4bit")]
    assert a._convert_to_mlx_model_id(IDS[("31", "8bit")]) == IDS[("31", "8bit")]   # untouched
    assert a._convert_to_pytorch_model_id(IDS[("26", "8bit")]) == "google/gemma-4-26b-a4b-it"


# ── torchvision guard ─────────────────────────────────────────────

@pytest.mark.parametrize("tv,th,bad", [("0.27.1", "2.12.0", False), ("0.24.1", "2.12.0", True),
                                       ("0.20.0", "2.5.1", False)])
def test_version_mismatch_detection(monkeypatch, tv, th, bad):
    import importlib.metadata as md
    monkeypatch.setattr(md, "version", lambda p: {"torchvision": tv, "torch": th}[p])
    assert mu.torch_torchvision_mismatch() is bad


def test_guard_marks_broken_torchvision_absent(monkeypatch):
    import importlib.util
    import types
    monkeypatch.setattr(mu, "_torchvision_checked", False)
    saved = sys.modules.get("torchvision", "missing")

    class Boom(types.ModuleType):
        def __getattr__(self, n):
            raise RuntimeError("operator torchvision::nms does not exist")
    monkeypatch.delitem(sys.modules, "torchvision", raising=False)
    import builtins
    real_import = builtins.__import__

    def imp(name, *a, **k):
        if name == "torchvision":
            raise RuntimeError("operator torchvision::nms does not exist")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", imp)
    try:
        assert mu.ensure_torchvision_usable() is False
        assert sys.modules["torchvision"] is None
        assert importlib.util.find_spec("torchvision") is None
    finally:
        monkeypatch.setattr(builtins, "__import__", real_import)
        if saved == "missing":
            sys.modules.pop("torchvision", None)
        else:
            sys.modules["torchvision"] = saved


def test_startup_guard_blocks_mismatched_torchvision_without_importing_it():
    import subprocess
    code = (
        "import importlib.metadata as m, sys\n"
        "v = m.version\n"
        "m.version = lambda n: {'torch': '2.12.0', 'torchvision': '0.24.1'}.get(n) or v(n)\n"
        "import src.ai\n"
        "assert sys.modules['torchvision'] is None\n"
        "assert 'torch' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_cloud_sdks_load_only_for_the_chosen_provider():
    import subprocess
    code = (
        "import sys\n"
        "import src.ai.llm_client as c\n"
        "assert not {'anthropic', 'openai', 'google.genai'} & set(sys.modules)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


# ── Room for large models (Metal aborts the process when it runs out) ─

@pytest.fixture
def large_models(loader, monkeypatch):
    monkeypatch.setattr(mu, "estimate_weights_gb", lambda m: 15.0)
    monkeypatch.setattr(mu, "total_ram_gb", lambda: 32.0)
    return loader


def mlx_client(model_id):
    from src.ai import llm_client as lc
    client = lc.LLMClient.__new__(lc.LLMClient)
    client.provider = lc.LLMProvider.MLX_LOCAL
    client.hf_config = lc.HuggingFaceConfig(model_id=model_id, use_local=True)
    client._hf_pipeline = client._hf_tokenizer = None
    client._mlx_released_for_room = False
    client._mlx_model, client._mlx_tokenizer = mu.load_mlx_model(model_id)
    lc._LIVE_LOCAL_CLIENTS.add(client)
    return client


def test_loading_a_second_large_model_releases_the_first(large_models):
    client = mlx_client("a")
    first = mu._live_models["a"][0]
    mu.load_mlx_model("b")
    assert client._mlx_model is None
    assert first() is None
    assert large_models == ["a", "b"]


def test_released_client_reloads_when_used_again(large_models, monkeypatch):
    client = mlx_client("a")
    mu.load_mlx_model("b")
    monkeypatch.setattr(client, "_generate_mlx_loaded",
                        lambda *a, **k: "ok" if client._mlx_model else "missing", raising=False)
    assert client._generate_mlx_local("p", None, 10, 0.1) == "ok"
    assert large_models == ["a", "b", "a"]


def test_explicit_unload_still_needs_a_new_client(large_models):
    client = mlx_client("a")
    client.unload()
    with pytest.raises(RuntimeError, match="not initialized"):
        client._generate_mlx_local("p", None, 10, 0.1)


def test_small_models_stay_loaded_together(loader, monkeypatch):
    monkeypatch.setattr(mu, "estimate_weights_gb", lambda m: 4.0)
    monkeypatch.setattr(mu, "total_ram_gb", lambda: 32.0)
    client = mlx_client("a")
    mu.load_mlx_model("b", use_slot=False)
    assert client._mlx_model is not None


def test_rephrasing_agent_releases_and_loaded_model_cache_evicts(large_models):
    from src.ai import model_cache as mc
    from src.ai.rephrasing_agent import RephrasingAgent
    agent = RephrasingAgent(use_local_model=True, local_model_id="a")
    agent._mlx_model, agent._mlx_tokenizer = mu.load_mlx_model("a")
    cache = mc.LoadedModelCache(max_models=2, max_ram_gb=64)
    cache._cache["k"] = NS(model=agent._mlx_model, tokenizer="t", entry_id="a", estimated_ram_gb=15)
    held = mu._live_models["a"][0]
    mu.load_mlx_model("b")
    assert agent._mlx_model is None
    assert "k" not in cache._cache
    assert held() is None


def test_load_refused_rather_than_crash_when_old_model_cannot_be_released(large_models):
    stuck = mu.load_mlx_model("a")
    with pytest.raises(mu.ModelTooLargeError, match="still in use"):
        mu.load_mlx_model("b")
    assert stuck[0] is not None


def test_model_cache_never_blocks_on_its_own_lock(large_models):
    from src.ai import model_cache as mc
    cache = mc.LoadedModelCache(max_models=2, max_ram_gb=64)
    cache._cache["k"] = NS(model=FakeModel(), tokenizer="t", entry_id="a", estimated_ram_gb=1)
    locked, release = threading.Event(), threading.Event()

    def hold():
        with cache._lock:
            locked.set()
            release.wait(5)

    thread = threading.Thread(target=hold)
    thread.start()
    locked.wait(5)
    try:
        mc._release_cached_models({id(cache._cache["k"].model)})
        assert "k" in cache._cache
    finally:
        release.set()
        thread.join()
