"""LanguageTool's extra n-gram data: where it lives, download and remove (P.6).

LanguageTool can use word-sequence counts from Google Books to catch
confused words its rules miss ("put on the breaks", "their" for "there").
The data is a separate download, offered in Settings ▸ Language:

  * the file: ``ngrams-en-20150817.zip`` from
    https://languagetool.org/download/ngram-data/ (8,961,853,713 bytes, 9.0 GB;
    15.4 GB once unpacked into an ``en`` folder);
  * where: ``<LanguageTool cache>/ngrams/en`` — the same cache
    language_tool_python uses (``LTP_PATH``, else
    ``~/.cache/language_tool_python``). LanguageTool is pointed at the
    ``ngrams`` folder (its ``languageModel`` option), never at ``en``;
  * licence: the counts come from the Google Books Ngram corpus, which
    Google released under Creative Commons Attribution 3.0.

Without the data nothing changes. No Qt here: the download runs on a plain
thread and reports through a :class:`DownloadState` the UI polls, so it
keeps going (and stays safe) if the Settings window is closed.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

NGRAM_URL = "https://languagetool.org/download/ngram-data/ngrams-en-20150817.zip"
NGRAM_ZIP_NAME = "ngrams-en-20150817.zip"
NGRAM_ZIP_BYTES = 8_961_853_713
# Measured after unpacking the file above (see the P.6 brief's Outcome).
NGRAM_UNPACKED_BYTES = 15_401_820_145
NGRAM_LICENCE = "Google Books Ngram data, Creative Commons Attribution 3.0"
_CHUNK = 1 << 20


def lt_cache_dir() -> Path:
    """language_tool_python's cache (does not create it)."""
    return Path(os.environ.get("LTP_PATH")
                or Path.home() / ".cache" / "language_tool_python")


def ngram_root() -> Path:
    """The folder LanguageTool's ``languageModel`` option points at."""
    return lt_cache_dir() / "ngrams"


def _work_dir() -> Path:
    return ngram_root() / ".download"


def is_installed(root: Optional[Path] = None) -> bool:
    """True when ``<root>/en`` holds the unpacked n-gram index folders."""
    en = (root or ngram_root()) / "en"
    try:
        return en.is_dir() and any(p.is_dir() and p.name.endswith("grams")
                                   for p in en.iterdir())
    except OSError:
        return False


def language_model_dir() -> Optional[Path]:
    """The folder to pass as ``languageModel``, or None without the data."""
    root = ngram_root()
    return root if is_installed(root) else None


def installed_bytes(root: Optional[Path] = None) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk((root or ngram_root()) / "en"):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def human_size(n: float) -> str:
    gb = n / 1e9
    return f"{gb:.1f} GB" if gb >= 1 else f"{n / 1e6:.0f} MB"


def free_bytes(path: Optional[Path] = None) -> int:
    p = path or lt_cache_dir()
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 0


def space_needed() -> int:
    """The zip and its unpacked copy exist together for a moment."""
    return NGRAM_ZIP_BYTES + NGRAM_UNPACKED_BYTES + 1_000_000_000


def remove() -> None:
    """Delete the data (and any half-finished download)."""
    shutil.rmtree(ngram_root(), ignore_errors=True)
    _restart_languagetool()


def _restart_languagetool() -> None:
    try:
        from src.utils.proofing import LanguageToolEngine
        LanguageToolEngine.get().request_restart()
    except Exception:
        pass


# ── Download ────────────────────────────────────────────────────────

@dataclass
class DownloadState:
    phase: str = "idle"          # idle | downloading | unpacking | done | failed | cancelled
    done: int = 0
    total: int = NGRAM_ZIP_BYTES
    message: str = ""

    @property
    def running(self) -> bool:
        return self.phase in ("downloading", "unpacking")

    @property
    def percent(self) -> int:
        return int(100 * self.done / self.total) if self.total else 0


_state = DownloadState()
_thread: Optional[threading.Thread] = None
_cancel = threading.Event()
_lock = threading.Lock()


def state() -> DownloadState:
    return _state


def cancel() -> None:
    _cancel.set()


def start_download(opener: Optional[Callable] = None) -> bool:
    """Start the download on a background thread. False if one is running
    or there is not enough room (``state().message`` says why)."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        need, free = space_needed(), free_bytes()
        if free < need:
            _state.phase = "failed"
            _state.message = (f"Not enough free disk space: it needs about "
                              f"{human_size(need)}, {human_size(free)} is free.")
            return False
        _cancel.clear()
        _state.phase, _state.done, _state.total, _state.message = (
            "downloading", 0, NGRAM_ZIP_BYTES, "Starting…")
        _thread = threading.Thread(target=_run, args=(opener,), daemon=True,
                                   name="lt-ngram-download")
        _thread.start()
        return True


def wait(timeout: Optional[float] = None) -> None:
    if _thread is not None:
        _thread.join(timeout)


def _run(opener: Optional[Callable]) -> None:
    try:
        download_and_unpack(_state, _cancel, opener)
    except _Cancelled:
        _state.phase, _state.message = "cancelled", "Download stopped. It resumes where it left off."
    except Exception as e:      # never escape the thread
        _state.phase, _state.message = "failed", f"Download failed: {e}"


class _Cancelled(Exception):
    pass


def download_and_unpack(st: DownloadState, cancel_event: threading.Event,
                        opener: Optional[Callable] = None,
                        url: str = NGRAM_URL) -> Path:
    """Download (resuming a partial file), unpack safely, move into place.
    Blocking. ``opener(request)`` stands in for ``urllib.request.urlopen``."""
    opener = opener or (lambda req: urllib.request.urlopen(req, timeout=60))
    work = _work_dir()
    work.mkdir(parents=True, exist_ok=True)
    part = work / (NGRAM_ZIP_NAME + ".part")
    have = part.stat().st_size if part.exists() else 0

    st.phase = "downloading"
    if have < st.total:
        req = urllib.request.Request(url, headers={"User-Agent": "WritingAid"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        with opener(req) as resp:
            if have and getattr(resp, "status", 206) != 206:
                have = 0                         # server ignored the range
            length = resp.headers.get("Content-Length") if hasattr(resp, "headers") else None
            if length:
                st.total = have + int(length)
            with open(part, "ab" if have else "wb") as out:
                st.done = have
                last = time.monotonic()
                while True:
                    if cancel_event.is_set():
                        raise _Cancelled()
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    st.done += len(chunk)
                    if time.monotonic() - last > 0.5:
                        st.message = f"Downloading… {human_size(st.done)} of {human_size(st.total)}"
                        last = time.monotonic()
    if part.stat().st_size < st.total:
        raise IOError("the download ended early; press Download again to resume")

    st.phase, st.done, st.message = "unpacking", 0, "Unpacking…"
    unpack = work / "unpacked"
    shutil.rmtree(unpack, ignore_errors=True)
    _safe_unzip(part, unpack, st, cancel_event)
    en = _find_en(unpack)
    if en is None:
        raise IOError("the file did not contain LanguageTool's 'en' folder")
    target = ngram_root() / "en"
    shutil.rmtree(target, ignore_errors=True)
    os.replace(en, target)
    shutil.rmtree(work, ignore_errors=True)
    st.phase, st.message = "done", "Installed."
    _restart_languagetool()
    return target


def _safe_unzip(zip_path: Path, dest: Path, st: DownloadState,
                cancel_event: threading.Event) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        st.total = sum(m.file_size for m in members) or 1
        for m in members:
            if cancel_event.is_set():
                raise _Cancelled()
            out = (dest / m.filename).resolve()
            if root not in out.parents and out != root:
                raise IOError(f"unsafe path in the file: {m.filename}")
            if m.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(m) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst, _CHUNK)
            st.done += m.file_size
            st.message = f"Unpacking… {st.percent}%"


def _find_en(unpacked: Path) -> Optional[Path]:
    if is_installed(unpacked):
        return unpacked / "en"
    for child in unpacked.iterdir():
        if child.is_dir() and is_installed(child):
            return child / "en"
    return None


# ── Starting LanguageTool with the data ─────────────────────────────

_config_lock = threading.Lock()


def start_language_tool(language: str = "en-US", tool_class=None):
    """Start LanguageTool, with the n-gram data when it is installed.
    Returns ``(tool, with_ngrams)``. If starting with the data fails, it
    starts as before without it, so the check never gets worse."""
    if tool_class is None:
        import language_tool_python
        tool_class = language_tool_python.LanguageTool
    model = language_model_dir()
    if model is not None:
        try:
            with _directory_language_model():
                return tool_class(language, config={"languageModel": str(model)}), True
        except Exception as e:
            print(f"[proofing] LanguageTool with n-gram data failed, starting without: {e}")
    return tool_class(language), False


class _directory_language_model:
    """language_tool_python 3.4 checks that ``languageModel`` is a *file*,
    but LanguageTool wants the folder holding ``en``. Accept a folder while
    the config is written."""

    def __enter__(self):
        _config_lock.acquire()
        self._saved = None
        try:
            from language_tool_python import config_file as cf
            spec = cf.CONFIG_SCHEMA.get("languageModel")
            if spec is not None:
                self._saved = (cf, spec)
                cf.CONFIG_SCHEMA["languageModel"] = cf.OptionSpec(
                    spec.py_types, spec.encoder, _directory_validator)
        except Exception:
            pass
        return self

    def __exit__(self, *exc):
        try:
            if self._saved:
                cf, spec = self._saved
                cf.CONFIG_SCHEMA["languageModel"] = spec
        finally:
            _config_lock.release()
        return False


def _directory_validator(v) -> None:
    if not Path(v).is_dir():
        raise ValueError(f"n-gram folder does not exist: {v}")
