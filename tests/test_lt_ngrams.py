"""P.6: LanguageTool's n-gram data — presence, start, download, remove, UI.
Nothing here downloads or starts Java: the data and the engine are faked."""

import io
import threading
import zipfile
from types import SimpleNamespace

import pytest

from src.utils import lt_ngrams as ng
from src.utils.proofing import GrammarIssue, LanguageToolEngine


def _fake_data(root):
    for n in ("1grams", "2grams", "3grams"):
        (root / "en" / n).mkdir(parents=True, exist_ok=True)
        (root / "en" / n / "segments_1").write_bytes(b"x" * 10)


class FakeTool:
    calls = []
    fail_with_config = False

    def __init__(self, language, config=None):
        if config is not None:
            # what language_tool_python does with the config: encode and validate it
            from language_tool_python import config_file as cf
            cf._encode_config(config)
            if FakeTool.fail_with_config:
                raise RuntimeError("no memory")
        FakeTool.calls.append((language, config))
        self.disabled_rules = set()

    def check(self, text):
        return [SimpleNamespace(rule_id="CONFUSION_RULE", offset=0, error_length=5,
                                message="Did you mean 'there'?", replacements=["There"])]

    def close(self):
        pass


RESTARTS = []
_REAL_RESTART = ng._restart_languagetool


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    """Never restart the shared LanguageTool other tests use: a restart
    mid-suite leaves an editor's grammar thread waiting on it."""
    FakeTool.calls, FakeTool.fail_with_config = [], False
    RESTARTS.clear()
    monkeypatch.setattr(ng, "_restart_languagetool", lambda: RESTARTS.append(1))
    yield


# ── presence ──

def test_absent_by_default_in_tests():
    assert not ng.is_installed()
    assert ng.language_model_dir() is None


def test_present_when_en_holds_index_folders():
    _fake_data(ng.ngram_root())
    assert ng.is_installed()
    assert ng.language_model_dir() == ng.ngram_root()   # the parent of en, as LT wants
    assert ng.installed_bytes() == 30


def test_empty_en_folder_is_not_installed():
    (ng.ngram_root() / "en").mkdir(parents=True)
    assert not ng.is_installed()


# ── starting LanguageTool ──

def test_start_without_data_is_unchanged():
    tool, with_data = ng.start_language_tool("en-US", FakeTool)
    assert with_data is False
    assert FakeTool.calls == [("en-US", None)]


def test_start_with_data_passes_the_folder():
    _fake_data(ng.ngram_root())
    tool, with_data = ng.start_language_tool("en-US", FakeTool)
    assert with_data is True
    assert FakeTool.calls == [("en-US", {"languageModel": str(ng.ngram_root())})]


def test_folder_check_is_put_back_after_start():
    from language_tool_python import config_file as cf
    before = cf.CONFIG_SCHEMA["languageModel"]
    _fake_data(ng.ngram_root())
    ng.start_language_tool("en-US", FakeTool)
    assert cf.CONFIG_SCHEMA["languageModel"] is before


def test_start_falls_back_without_data_when_it_fails():
    _fake_data(ng.ngram_root())
    FakeTool.fail_with_config = True
    tool, with_data = ng.start_language_tool("en-US", FakeTool)
    assert with_data is False
    assert FakeTool.calls == [("en-US", None)]


def _engine(monkeypatch):
    eng = LanguageToolEngine()
    monkeypatch.setattr(LanguageToolEngine, "prerequisites", staticmethod(lambda: (True, "")))
    monkeypatch.setattr(ng, "start_language_tool",
                        lambda lang: (FakeTool(lang, None), ng.is_installed()))
    return eng


def test_engine_says_when_it_uses_the_data(monkeypatch):
    eng = _engine(monkeypatch)
    assert eng.ensure_started()
    assert eng.describe() == "LanguageTool"
    _fake_data(ng.ngram_root())
    eng.request_restart()
    issues = eng.check("Their is a dog.")
    assert eng.ngrams and eng.describe() == "LanguageTool, with n-gram data"
    assert issues and issues[0].rule_id == "CONFUSION_RULE"


def test_restart_after_remove_drops_the_data(monkeypatch):
    eng = _engine(monkeypatch)
    _fake_data(ng.ngram_root())
    eng.ensure_started()
    assert eng.ngrams
    eng.request_restart()
    import shutil
    shutil.rmtree(ng.ngram_root())
    eng.ensure_started()
    assert not eng.ngrams and eng.status == "ready"


def test_confused_words_from_the_data_stay_out_of_fix_all():
    from src.ui import fix_all
    issue = GrammarIssue(0, 5, "Their", "Did you mean 'there'?", ["There"],
                         "CONFUSION_RULE", "languagetool")
    err = SimpleNamespace(kind="grammar", rule_id=issue.rule_id, text=issue.text,
                          suggestions=issue.suggestions, message=issue.message)
    assert fix_all.is_confusable(err)


# ── download ──

def _zip_bytes(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n in names:
            zf.writestr(n, b"data")
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _opener(data, seen=None):
    def opener(req):
        rng = req.get_header("Range")
        if seen is not None:
            seen.append(rng)
        if rng:
            start = int(rng.split("=")[1].rstrip("-"))
            return FakeResponse(data[start:], 206)
        return FakeResponse(data)
    return opener


def test_download_unpacks_into_place_and_tidies_up():
    data = _zip_bytes(["en/1grams/a", "en/2grams/b", "en/3grams/c"])
    st = ng.DownloadState(total=len(data))
    target = ng.download_and_unpack(st, threading.Event(), _opener(data))
    assert target == ng.ngram_root() / "en"
    assert ng.is_installed() and st.phase == "done"
    assert not (ng.ngram_root() / ".download").exists()


def test_download_resumes_a_partial_file():
    data = _zip_bytes(["en/1grams/a"])
    work = ng.ngram_root() / ".download"
    work.mkdir(parents=True)
    (work / (ng.NGRAM_ZIP_NAME + ".part")).write_bytes(data[:10])
    seen = []
    st = ng.DownloadState(total=len(data))
    ng.download_and_unpack(st, threading.Event(), _opener(data, seen))
    assert seen == ["bytes=10-"]
    assert ng.is_installed()


def test_download_can_be_stopped():
    data = _zip_bytes(["en/1grams/a"])
    ev = threading.Event()
    ev.set()
    with pytest.raises(ng._Cancelled):
        ng.download_and_unpack(ng.DownloadState(total=len(data)), ev, _opener(data))
    assert not ng.is_installed()


def test_unsafe_paths_in_the_file_are_refused():
    data = _zip_bytes(["../../evil", "en/1grams/a"])
    with pytest.raises(IOError):
        ng.download_and_unpack(ng.DownloadState(total=len(data)), threading.Event(), _opener(data))
    assert not ng.is_installed()


def test_a_file_without_en_is_refused():
    data = _zip_bytes(["de/1grams/a"])
    with pytest.raises(IOError):
        ng.download_and_unpack(ng.DownloadState(total=len(data)), threading.Event(), _opener(data))


def test_not_enough_space_refuses_to_start(monkeypatch):
    monkeypatch.setattr(ng, "free_bytes", lambda path=None: 1_000_000)
    assert ng.start_download(_opener(b"")) is False
    assert "Not enough free disk space" in ng.state().message
    ng.state().phase = "idle"


def test_background_download_finishes(monkeypatch):
    data = _zip_bytes(["en/1grams/a"])
    monkeypatch.setattr(ng, "NGRAM_ZIP_BYTES", len(data))
    monkeypatch.setattr(ng, "free_bytes", lambda path=None: 10 ** 12)
    assert ng.start_download(_opener(data))
    ng.wait(10)
    assert ng.state().phase == "done" and ng.is_installed() and RESTARTS == [1]
    ng.state().phase = "idle"


def test_remove_deletes_and_restarts():
    _fake_data(ng.ngram_root())
    ng.remove()
    assert not ng.is_installed() and RESTARTS == [1]


def test_restart_reaches_the_engine(monkeypatch):
    eng = LanguageToolEngine.get()
    asked = []
    monkeypatch.setattr(eng, "request_restart", lambda: asked.append(1))
    _REAL_RESTART()
    assert asked == [1]


# ── Settings entry ──

@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_settings_entry_download_then_remove(qapp, monkeypatch):
    from src.ui.ngram_download import NgramDataGroup
    started = []
    monkeypatch.setattr(ng, "start_download", lambda: started.append(1) or True)
    w = NgramDataGroup(confirm=lambda t, s: True)
    assert w.action_btn.text() == "Download"
    assert "8.4 GB" in w.title_label.text() or "9.0 GB" in w.title_label.text()
    assert "Not installed" in w.status_label.text()
    w.action_btn.click()
    assert started == [1]

    _fake_data(ng.ngram_root())
    w.refresh()
    assert w.action_btn.text() == "Remove" and "Installed" in w.status_label.text()
    w.action_btn.click()
    assert not ng.is_installed() and w.action_btn.text() == "Download"


def test_settings_entry_shows_progress_and_stop(qapp, monkeypatch):
    from src.ui.ngram_download import NgramDataGroup
    st = ng.state()
    st.phase, st.done, st.total, st.message = "downloading", 50, 100, "Downloading… 50%"
    try:
        w = NgramDataGroup(confirm=lambda t, s: True)
        assert w.action_btn.text() == "Stop" and w.progress.value() == 50
        w.action_btn.click()
        assert ng._cancel.is_set()
    finally:
        ng._cancel.clear()
        st.phase = "idle"


def test_declining_does_nothing(qapp, monkeypatch):
    from src.ui.ngram_download import NgramDataGroup
    monkeypatch.setattr(ng, "start_download", lambda: pytest.fail("should not start"))
    w = NgramDataGroup(confirm=lambda t, s: False)
    w.action_btn.click()
    assert w.action_btn.text() == "Download"


def test_language_page_has_the_entry(qapp):
    """The Language page builds the entry. Built on a stand-in for the
    dialog: a whole SettingsDialog starts background work of its own."""
    from src.ui.settings_dialog import SettingsDialog

    class Host:
        def __getattr__(self, name):
            if name.startswith("_"):
                return lambda *a, **k: None
            raise AttributeError(name)

    host = Host()
    page = SettingsDialog._create_language_resources_tab(host)
    try:
        assert host.ngram_data_group.action_btn.text() == "Download"
        assert host.ngram_data_group.window() is page.window()
    finally:
        page.deleteLater()
