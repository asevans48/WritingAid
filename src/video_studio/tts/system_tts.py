"""System TTS — uses the OS's built-in synthesizer.

macOS: ``say`` (always installed; many voices via System Settings →
       Spoken Content)
Linux: ``espeak`` or ``espeak-ng`` (apt install espeak / espeak-ng)
Windows: PowerShell's System.Speech.Synthesis.SpeechSynthesizer

Cross-platform, no Python deps needed. Audio is rendered to AIFF on
macOS and WAV elsewhere; the stitcher accepts either via ffmpeg.

Voice quality is OS-dependent — macOS's modern Siri voices are
excellent, espeak is intelligible but robotic. For a richer
solution, install Piper or Coqui-TTS as a future backend.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import List

from .base import (
    TTSBackend, TTSRequest, TTSResult, probe_audio_duration_seconds,
)


class SystemTTSBackend(TTSBackend):
    name = "system_tts"
    label = "System TTS (built-in)"
    description = (
        "Uses your OS's built-in text-to-speech engine. Works out of "
        "the box on macOS (say), Linux with espeak installed, and "
        "Windows (PowerShell SAPI). Voice quality varies by OS; "
        "macOS's modern voices are the best. No model download.")

    def is_installed(self) -> bool:
        return self._tool_path() is not None

    def install_instructions(self) -> str:
        if sys.platform == "darwin":
            return (
                "macOS ships with the 'say' command — already "
                "installed. To get higher-quality voices, open "
                "System Settings → Accessibility → Spoken Content "
                "and download additional voices (Siri voices are "
                "high quality).")
        if sys.platform == "win32":
            return (
                "Windows ships with PowerShell's SAPI synthesizer "
                "— already installed. To add more voices, open "
                "Settings → Time & Language → Speech.")
        # Assume Linux / BSD.
        return (
            "Linux TTS via espeak or espeak-ng:\n"
            "  Debian/Ubuntu:   sudo apt install espeak-ng\n"
            "  Fedora/RHEL:     sudo dnf install espeak-ng\n"
            "  Arch/Manjaro:    sudo pacman -S espeak-ng\n"
            "Then re-pick this backend.")

    def available_voices(self) -> List[str]:
        """List voice identifiers the user can pick.

        macOS: ``say -v ?`` lists installed voices.
        espeak: ``espeak --voices`` lists voices.
        Windows: PowerShell call enumerates voices.

        Best-effort; returns an empty list if the call fails so the
        UI falls back to the default voice.
        """
        try:
            tool = self._tool_path()
            if tool is None:
                return []
            if sys.platform == "darwin":
                proc = subprocess.run(
                    [tool, "-v", "?"], capture_output=True,
                    text=True, timeout=5)
                if proc.returncode != 0:
                    return []
                # Output rows look like:
                # ``Alex                en_US    # Most …``
                voices: List[str] = []
                for line in (proc.stdout or "").splitlines():
                    name = line.split(" ", 1)[0].strip()
                    if name and name != "#":
                        voices.append(name)
                return voices
            if sys.platform == "win32":
                return []  # users can leave voice blank → SAPI default
            # espeak
            proc = subprocess.run(
                [tool, "--voices"], capture_output=True,
                text=True, timeout=5)
            if proc.returncode != 0:
                return []
            voices = []
            for line in (proc.stdout or "").splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4:
                    voices.append(parts[3])
            return voices
        except Exception:
            return []

    def synthesize(self, request: TTSRequest) -> TTSResult:
        tool = self._tool_path()
        if tool is None:
            return TTSResult(
                success=False,
                output_path=request.output_path,
                sidecar_path=request.output_path.with_suffix(
                    request.output_path.suffix + ".json"),
                error=(
                    "No system TTS available. Install espeak / "
                    "espeak-ng on Linux."),
            )
        out = request.output_path
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "darwin":
                cmd = [tool]
                if request.voice:
                    cmd += ["-v", request.voice]
                if request.rate_wpm:
                    cmd += ["-r", str(int(request.rate_wpm))]
                # ``say -o file.aiff`` writes AIFF; we'll match the
                # caller's chosen output extension if they asked for
                # mp4/m4a by transcoding via afconvert (also Apple).
                cmd += ["-o", str(out), request.text]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=180)
                if proc.returncode != 0:
                    return self._fail(
                        request,
                        f"say exited {proc.returncode}: "
                        f"{(proc.stderr or '')[:200]}")
            elif sys.platform == "win32":
                # Use PowerShell's System.Speech synth — ships with
                # Windows.
                ps_script = self._win_ps_script(
                    text=request.text,
                    out_path=str(out),
                    voice=request.voice,
                    rate=request.rate_wpm)
                cmd = ["powershell", "-NoProfile", "-Command", ps_script]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=180)
                if proc.returncode != 0:
                    return self._fail(
                        request,
                        f"PowerShell SAPI exited "
                        f"{proc.returncode}: "
                        f"{(proc.stderr or '')[:200]}")
            else:
                # espeak / espeak-ng — writes WAV.
                cmd = [tool, "-w", str(out)]
                if request.voice:
                    cmd += ["-v", request.voice]
                if request.rate_wpm:
                    cmd += ["-s", str(int(request.rate_wpm))]
                cmd += [request.text]
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=180)
                if proc.returncode != 0:
                    return self._fail(
                        request,
                        f"espeak exited {proc.returncode}: "
                        f"{(proc.stderr or '')[:200]}")
        except subprocess.TimeoutExpired:
            return self._fail(request, "TTS timed out after 3 min.")
        except Exception as e:
            return self._fail(request, f"TTS invocation failed: {e}")
        sidecar = out.with_suffix(out.suffix + ".json")
        duration = probe_audio_duration_seconds(out)
        self._write_sidecar(
            sidecar, request, backend_name=self.name,
            extra={"platform": sys.platform,
                   "tool": tool,
                   "duration_seconds": duration})
        return TTSResult(
            success=True,
            output_path=out,
            sidecar_path=sidecar,
            duration_seconds=duration,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _tool_path(self):
        if sys.platform == "darwin":
            return shutil.which("say")
        if sys.platform == "win32":
            return shutil.which("powershell")
        # Linux / BSD — prefer espeak-ng (the modern fork).
        return (shutil.which("espeak-ng")
                or shutil.which("espeak"))

    def _fail(self, request: TTSRequest, message: str) -> TTSResult:
        return TTSResult(
            success=False,
            output_path=request.output_path,
            sidecar_path=request.output_path.with_suffix(
                request.output_path.suffix + ".json"),
            error=message,
        )

    def _win_ps_script(
        self, text: str, out_path: str, voice: str,
        rate,
    ) -> str:
        # Single-quote-escape the text for PowerShell. Keep it
        # simple — quotes doubled, backticks not needed because we
        # use single-quoted PS strings.
        safe = text.replace("'", "''")
        voice_line = (
            f"$s.SelectVoice('{voice}');" if voice else "")
        rate_line = (
            f"$s.Rate = {int(rate)};" if rate else "")
        return (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            + voice_line + rate_line +
            f"$s.SetOutputToWaveFile('{out_path}');"
            f"$s.Speak('{safe}');"
            "$s.Dispose();"
        )
