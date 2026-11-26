"""Pausing Read Aloud with a sound-file voice (Kokoro, Chatterbox, VibeVoice,
Edge, the basic `say` voices). The player is no longer frozen with SIGSTOP
(which left the Mac's audio looping a scrap of sound: the stutter); it is
stopped and the rest of the sound plays on from the place.

Nothing is played: the "player" is a sleeping Python process, and the
sound is a short WAV written in a temporary folder."""

import os
import sys
import threading
import time

import numpy as np
import pytest

sf = pytest.importorskip("soundfile")

from src.services import tts_service
from src.services.tts_service import TTSEngine, TTSService

RATE = 8000


def _wav(tmp_path, seconds=4.0):
    p = tmp_path / "speech.wav"
    t = np.arange(int(seconds * RATE)) / RATE
    sf.write(str(p), (0.1 * np.sin(2 * np.pi * 220 * t)).astype("float32"), RATE)
    return str(p)


def _service():
    s = TTSService.__new__(TTSService)       # no engine set-up
    s._is_speaking = True
    s._is_paused = False
    s._stop_requested = False
    s._file_playback = True
    s._audio_proc = None
    s._macos_say_proc = None
    s._avspeech_synth = None
    return s


class _Player:
    """Records what was played; each play is a sleeping process."""

    def __init__(self):
        self.played = []

    def __call__(self, path):
        self.played.append((path, sf.info(path).duration if path.endswith(".wav") else 0))
        return [sys.executable, "-c", "import time; time.sleep(30)"]


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture(autouse=True)
def _no_freezing(monkeypatch):
    import signal
    import subprocess
    real = subprocess.Popen.send_signal

    def _refuse(self, sig):
        if sig in (signal.SIGSTOP, signal.SIGCONT):
            raise AssertionError("the player must never be frozen or thawed")
        return real(self, sig)
    monkeypatch.setattr(subprocess.Popen, "send_signal", _refuse)


def _play_in_thread(svc, path, player):
    th = threading.Thread(target=svc._play_pausable,
                          args=(path, "_audio_proc", player), daemon=True)
    th.start()
    return th


def test_pause_stops_the_player_and_resume_plays_on_from_the_place(tmp_path):
    path = _wav(tmp_path, 4.0)
    svc, player = _service(), _Player()
    th = _play_in_thread(svc, path, player)
    assert _wait(lambda: svc._audio_proc is not None)
    first = svc._audio_proc
    time.sleep(1.0)
    assert svc.pause() is True and svc.is_paused
    assert _wait(lambda: first.poll() is not None)          # stopped, not frozen
    assert svc._audio_proc is None
    time.sleep(0.3)
    assert len(player.played) == 1                          # nothing plays while paused
    assert svc.resume() is True
    assert _wait(lambda: len(player.played) == 2)
    rest_path, rest = player.played[1]
    assert rest_path != path
    # About 1 s was played; the rest is ~3 s plus the quarter-second back.
    assert 2.6 < rest < 3.6
    svc._stop_requested = True
    th.join(3)
    assert not th.is_alive()
    assert not os.path.exists(rest_path)                    # the copy is removed
    assert os.path.exists(path)                             # the voice's own file is left


def test_stop_while_paused_ends_playback(tmp_path):
    path = _wav(tmp_path)
    svc, player = _service(), _Player()
    th = _play_in_thread(svc, path, player)
    assert _wait(lambda: svc._audio_proc is not None)
    svc.pause()
    assert _wait(lambda: svc._audio_proc is None)
    svc._stop_requested = True
    th.join(3)
    assert not th.is_alive() and len(player.played) == 1


def test_a_pause_before_the_sound_starts_waits(tmp_path):
    """Paused while the voice is still making the sound: nothing plays
    until resume."""
    path = _wav(tmp_path)
    svc, player = _service(), _Player()
    assert svc.pause() is True
    th = _play_in_thread(svc, path, player)
    time.sleep(0.3)
    assert player.played == []
    svc.resume()
    assert _wait(lambda: len(player.played) == 1)
    assert player.played[0][0] == path
    svc._stop_requested = True
    th.join(3)


def test_a_sound_that_cannot_be_cut_plays_this_part_again(tmp_path):
    path = str(tmp_path / "speech.mp3")
    open(path, "wb").write(b"not really sound")
    svc, player = _service(), _Player()
    th = _play_in_thread(svc, path, player)
    assert _wait(lambda: svc._audio_proc is not None)
    svc.pause()
    assert _wait(lambda: svc._audio_proc is None)
    svc.resume()
    assert _wait(lambda: len(player.played) == 2)
    assert player.played[1][0] == path
    svc._stop_requested = True
    th.join(3)


def test_the_rest_of_a_sound(tmp_path):
    path = _wav(tmp_path, 2.0)
    rest = TTSService._sound_from(path, 0.5)
    assert abs(sf.info(rest).duration - 1.5) < 0.01
    os.unlink(rest)
    assert TTSService._sound_from(path, 5.0) == ""
    assert TTSService._sound_from(str(tmp_path / "missing.wav"), 0.5) is None


def test_pause_only_when_it_can_be_honoured():
    svc = _service()
    svc._is_speaking = False
    assert svc.pause() is False                             # nothing playing
    svc._is_speaking, svc._file_playback = True, False      # e.g. pyttsx3 off the Mac
    assert svc.pause() is False
    assert svc.resume() is False


def test_which_readings_play_from_a_file(monkeypatch):
    import platform
    svc = _service()
    svc._on_start = None
    svc._voice_id = None
    svc._paragraph_pause_ms = 0
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    for engine, system, expected in [(TTSEngine.KOKORO, "Linux", True),
                                     (TTSEngine.EDGE, "Windows", True),
                                     (TTSEngine.SYSTEM, "Darwin", True),
                                     (TTSEngine.SYSTEM, "Linux", False)]:
        svc._current_engine = engine
        monkeypatch.setattr(platform, "system", lambda s=system: s)
        svc._start_speech_thread("Hello.")
        assert svc._file_playback is expected, (engine, system)


def test_a_pause_between_paragraphs_holds_the_next_one():
    svc = _service()
    svc._paragraph_pause_ms = 10
    svc._on_end = None
    spoken = []

    def engine(chunk):
        spoken.append(chunk)
        if len(spoken) == 1:
            svc._is_paused = True                            # paused in the gap
    th = threading.Thread(target=svc._speak_paragraphs_threaded,
                          args=(engine, "One.\n\nTwo."), daemon=True)
    th.start()
    time.sleep(0.3)
    assert spoken == ["One."]
    svc._is_paused = False
    th.join(3)
    assert spoken == ["One.", "Two."]
