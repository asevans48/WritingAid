"""Threaded sounddevice + soundfile based mic recorder.

PyQt6's ``QMediaRecorder`` with the Wave file format ships
broken on macOS for several PyQt6 / Qt 6.x releases — the mic
input registers and the recorder reports ``RecordingState`` but
the file on disk stays zero bytes. We hit it in the slide editor
and the group editor.

This module sidesteps the Qt recorder entirely. It uses
PortAudio (via ``sounddevice``) to pull raw float32 frames into
memory on a background thread and writes them to disk via
``soundfile`` when the writer hits stop. The result is a
deterministic WAV file we can hand to ``edit_audio()`` or
ffmpeg without any further conversion.

Usage::

    rec = AudioRecorder(samplerate=44100, channels=1)
    rec.start(Path("take.wav"), device_index=2)
    ...                               # writer talks
    take = rec.stop()                 # blocks until file is closed
    print(take.path, take.duration_seconds)
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RecordedTake:
    """The artefact ``AudioRecorder.stop()`` returns. ``path``
    is the WAV file on disk, ``duration_seconds`` is computed
    from the frame count and the sample rate so we don't need
    to probe the file again."""

    path: Path
    duration_seconds: float
    samplerate: int
    channels: int


class AudioRecorder:
    """Single-shot WAV recorder. Each ``start()`` / ``stop()``
    pair captures one take. Calling ``start()`` while a
    recording is in flight raises ``RuntimeError``."""

    def __init__(
        self,
        samplerate: int = 44100,
        channels: int = 1,
        subtype: str = "PCM_16",
    ):
        self._samplerate = int(samplerate)
        self._channels = int(channels)
        self._subtype = subtype
        self._stream = None  # type: ignore[assignment]
        self._writer_thread: Optional[threading.Thread] = None
        self._frame_queue: "queue.Queue[Optional[bytes]]" = (
            queue.Queue())
        self._dest: Optional[Path] = None
        self._frames_written = 0
        self._lock = threading.Lock()
        self._error: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def is_recording(self) -> bool:
        return self._stream is not None

    def start(
        self,
        dest: Path,
        *,
        device_index: Optional[int] = None,
        device_name: Optional[str] = None,
    ) -> None:
        """Open the input stream and start writing to ``dest``.

        ``device_index`` overrides device picking when set; when
        ``None``, we resolve ``device_name`` against PortAudio's
        device list and fall back to the system default when no
        match is found.
        """
        import sounddevice as sd  # local import — keeps cold start cheap
        import soundfile as sf

        if self.is_recording:
            raise RuntimeError("Recorder is already running.")
        self._error = None
        self._frames_written = 0
        # Reset the queue — a stale sentinel from a prior aborted
        # session would close the writer thread before any frames
        # made it through.
        self._frame_queue = queue.Queue()
        self._dest = Path(dest)
        self._dest.parent.mkdir(parents=True, exist_ok=True)

        resolved_index = device_index
        if resolved_index is None and device_name:
            resolved_index = self._lookup_device_index(
                device_name)

        # Open the SoundFile up-front so the writer thread can
        # just stream into it. PortAudio's callback runs on a
        # real-time thread and must NEVER block on disk IO, so we
        # buffer through a queue.
        sf_writer = sf.SoundFile(
            str(self._dest), mode="w",
            samplerate=self._samplerate,
            channels=self._channels,
            subtype=self._subtype)

        def _writer_loop() -> None:
            try:
                while True:
                    chunk = self._frame_queue.get()
                    if chunk is None:
                        break
                    sf_writer.buffer_write(chunk, dtype="float32")
            except Exception as exc:  # pragma: no cover
                with self._lock:
                    self._error = str(exc)
            finally:
                try:
                    sf_writer.close()
                except Exception:
                    pass

        self._writer_thread = threading.Thread(
            target=_writer_loop,
            name="AudioRecorder-writer",
            daemon=True)
        self._writer_thread.start()

        def _callback(indata, frames, time_info, status):
            # PortAudio fires this on its own thread. Avoid heavy
            # work here — just hand the raw bytes to the writer.
            if status:
                # Underflows / overflows aren't fatal; we just log
                # to stderr like the rest of the studio code.
                print(f"[recorder] portaudio status: {status}")
            try:
                self._frame_queue.put_nowait(bytes(indata))
                self._frames_written += frames
            except Exception as exc:  # pragma: no cover
                with self._lock:
                    self._error = str(exc)

        try:
            self._stream = sd.InputStream(
                samplerate=self._samplerate,
                channels=self._channels,
                dtype="float32",
                device=resolved_index,
                callback=_callback)
            self._stream.start()
        except Exception:
            # Tear down the writer before re-raising so we don't
            # leak threads on a failed open.
            self._frame_queue.put(None)
            if self._writer_thread is not None:
                self._writer_thread.join(timeout=2.0)
            self._writer_thread = None
            raise

    def stop(self) -> Optional[RecordedTake]:
        """Flush the input stream and finalize the WAV file.
        Returns the take metadata, or ``None`` when no recording
        was in flight."""
        if self._stream is None:
            return None
        try:
            self._stream.stop()
            self._stream.close()
        except Exception as exc:
            print(f"[recorder] stream close error: {exc}")
        finally:
            self._stream = None
        # Tell the writer loop to drain and close.
        self._frame_queue.put(None)
        if self._writer_thread is not None:
            self._writer_thread.join(timeout=5.0)
            self._writer_thread = None
        if self._error:
            print(f"[recorder] writer error: {self._error}")
        if self._dest is None:
            return None
        duration = (
            self._frames_written / float(self._samplerate)
            if self._samplerate > 0 else 0.0)
        take = RecordedTake(
            path=self._dest,
            duration_seconds=duration,
            samplerate=self._samplerate,
            channels=self._channels)
        self._dest = None
        return take

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _lookup_device_index(name: str) -> Optional[int]:
        """Resolve a human-readable device description (the one
        Qt's ``QAudioDevice.description()`` returns) to a
        PortAudio device index. Matching is case-insensitive
        substring — PortAudio and Qt sometimes report subtly
        different names for the same physical device, so an
        exact-match lookup is too brittle."""
        try:
            import sounddevice as sd
            needle = name.strip().lower()
            for idx, info in enumerate(sd.query_devices()):
                if info.get("max_input_channels", 0) <= 0:
                    continue
                if needle in str(info.get("name", "")).lower():
                    return idx
        except Exception as exc:
            print(
                f"[recorder] device lookup failed for "
                f"'{name}': {exc}")
        return None


def list_input_devices() -> list[tuple[int, str]]:
    """Return ``(portaudio_index, name)`` tuples for every
    input device PortAudio sees. Used as a fallback when the Qt
    ``QMediaDevices`` enumeration returns no devices (which has
    happened on fresh macOS installs without mic permission)."""
    try:
        import sounddevice as sd
        out: list[tuple[int, str]] = []
        for idx, info in enumerate(sd.query_devices()):
            if info.get("max_input_channels", 0) > 0:
                out.append((idx, str(info.get("name", ""))))
        return out
    except Exception as exc:
        print(f"[recorder] list_input_devices failed: {exc}")
        return []
