"""Floating slide-deck preview window.

Pops out of the slide editor when the writer hits **🖥 Preview…**
The old in-dialog preview was cramped on laptop screens —
splitting the slide tab into a form + preview made both halves
unusable. This window lives on its own so the writer can park
it on a second monitor (or just full-screen it) while editing.

It can also **play through the deck**: a QTimer ticks at each
slide's ``duration_seconds`` and advances to the next one. When
a slide belongs to a group with overlay audio, the audio plays
in sync at the slide's ``start_time_seconds_in_group`` offset.
Per-slide ``audio_path`` falls back to playing when no group
overlay is wired.

The window mutates nothing — it's a pure viewer. Closing it is
safe at any time (the QTimer stops, the player stops). Re-using
an existing instance is recommended via
``SlidePreviewWindow.ensure_open(editor)`` so the writer doesn't
end up with a stack of preview windows.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication, QPixmap
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

from src.video_studio.models import (
    SlideDeckProject, SlideGroup, SlidePage,
)


class SlidePreviewWindow(QDialog):
    """A floating, non-modal preview + playback window.

    Pass the live ``SlideDeckProject`` and an initial slide id.
    ``set_current(slide_id)`` updates the visible slide; the
    slide editor wires this so navigating the slide list
    refreshes the preview window in lockstep.
    """

    def __init__(
        self,
        deck: SlideDeckProject,
        initial_slide_id: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ):
        # Parent is None so the window stacks independently —
        # the slide editor can be foregrounded behind it without
        # the preview tagging along.
        super().__init__(None)
        self.setWindowTitle("Slide preview")
        self.setModal(False)
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMinMaxButtonsHint)
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        # Default to a comfortable 16:9 viewport. Cap at 80% of
        # the screen so it never opens larger than the monitor.
        target_w = 800
        target_h = 540
        if avail is not None:
            target_w = max(
                420, min(target_w, int(avail.width() * 0.7)))
            target_h = max(
                300, min(target_h, int(avail.height() * 0.7)))
        self.resize(target_w, target_h)
        self.setMinimumSize(360, 240)
        self._deck = deck
        self._current_id: Optional[str] = initial_slide_id
        self._playing = False
        # Index of the slide currently on screen DURING playback.
        # Mirrors ``_current_id`` but tracked by position so the
        # advance timer can step through ``deck.pages`` in order.
        self._play_idx: int = 0
        # Active overlay-audio path; lets us avoid restarting
        # playback when consecutive slides share a group.
        self._active_audio_path: str = ""
        # Auto-advance timer — single-shot per slide; restart
        # in ``_show_index`` after the slide is on screen.
        self._advance_timer = QTimer(self)
        self._advance_timer.setSingleShot(True)
        self._advance_timer.timeout.connect(self._on_advance)
        # Audio player — used for both group overlays and per-
        # slide audio. Only one source is active at a time.
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._build_ui()
        if self._current_id is not None:
            self.set_current(self._current_id)
        else:
            self._render_blank("Empty deck.")

    # ------------------------------------------------------------------
    # External API
    # ------------------------------------------------------------------
    def set_deck(self, deck: SlideDeckProject) -> None:
        """Swap in a refreshed deck snapshot. Use after the
        slide editor mutates the project structurally (added
        slides, removed slides, etc.) so the preview catches up."""
        self._deck = deck
        if self._current_id is not None:
            self.set_current(self._current_id)

    def set_current(self, slide_id: Optional[str]) -> None:
        """Show ``slide_id`` (or blank when not found / None).
        No-op when the writer is mid-playback — auto-advance
        owns the visible slide during play."""
        self._current_id = slide_id
        if self._playing:
            return
        idx = self._find_index(slide_id) if slide_id else -1
        if idx < 0:
            self._render_blank("Select a slide.")
            return
        self._play_idx = idx
        self._show_index(idx, autoplay=False)

    def closeEvent(self, event) -> None:
        try:
            self._advance_timer.stop()
        except Exception:
            pass
        try:
            self._player.stop()
            self._player.setSource(QUrl())
        except Exception:
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        # Slide image area — fills everything.
        self._image_label = QLabel("Select a slide.")
        self._image_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet(
            "background: #0f172a; color: #94a3b8; "
            "border: 1px solid #1e293b;")
        self._image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding)
        self._image_label.setMinimumSize(360, 200)
        outer.addWidget(self._image_label, stretch=1)
        # Transport row.
        transport = QHBoxLayout()
        self._prev_btn = QPushButton("⏮ Prev")
        self._prev_btn.setToolTip(
            "Step back one slide. Stops playback.")
        self._prev_btn.clicked.connect(self._on_prev)
        transport.addWidget(self._prev_btn)
        self._play_btn = QPushButton("▶ Play")
        self._play_btn.setToolTip(
            "Auto-advance through the deck. Each slide stays "
            "on screen for its ``duration_seconds``; group "
            "overlay audio plays in sync.")
        self._play_btn.clicked.connect(self._on_play_pause)
        transport.addWidget(self._play_btn)
        self._next_btn = QPushButton("⏭ Next")
        self._next_btn.setToolTip(
            "Step forward one slide. Stops playback.")
        self._next_btn.clicked.connect(self._on_next)
        transport.addWidget(self._next_btn)
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setToolTip(
            "Stop playback and rewind to the first slide.")
        self._stop_btn.clicked.connect(self._on_stop)
        transport.addWidget(self._stop_btn)
        self._replay_btn = QPushButton("⟲ Replay")
        self._replay_btn.setToolTip(
            "Rewind to the first slide and play.")
        self._replay_btn.clicked.connect(self._on_replay)
        transport.addWidget(self._replay_btn)
        transport.addStretch()
        self._position_label = QLabel("")
        self._position_label.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        transport.addWidget(self._position_label)
        outer.addLayout(transport)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _show_index(self, idx: int, *, autoplay: bool) -> None:
        if idx < 0 or idx >= len(self._deck.pages):
            self._on_stop()
            return
        page = self._deck.pages[idx]
        self._current_id = page.id
        self._render_page(page)
        self._update_position(idx)
        self._sync_audio_to(page)
        if autoplay:
            # Single-shot timer for THIS slide's duration. The
            # ``_on_advance`` callback bumps the index and re-
            # arms the timer for the next slide.
            secs = max(
                0.5, float(page.duration_seconds or 1.0))
            self._advance_timer.start(int(secs * 1000))

    def _render_page(self, page: SlidePage) -> None:
        if not page.image_path:
            self._image_label.setText(
                f"(no image for {page.label or 'this slide'})")
            self._image_label.setPixmap(QPixmap())
            return
        path = Path(page.image_path)
        if not path.exists():
            self._image_label.setText(
                f"(image missing: {path.name})")
            self._image_label.setPixmap(QPixmap())
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            self._image_label.setText(
                "(cannot decode image)")
            self._image_label.setPixmap(QPixmap())
            return
        scaled = pix.scaled(
            self._image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)
        self._image_label.setPixmap(scaled)
        self._image_label.setText("")

    def _render_blank(self, message: str) -> None:
        self._image_label.setText(message)
        self._image_label.setPixmap(QPixmap())
        self._position_label.setText("")

    def _update_position(self, idx: int) -> None:
        total = len(self._deck.pages)
        page = self._deck.pages[idx]
        self._position_label.setText(
            f"Slide {idx + 1} of {total}  ·  "
            f"{page.duration_seconds:.2f} s")

    def resizeEvent(self, event) -> None:
        """Re-render the current slide at the new label size so
        the image stays sharp when the writer drags the window
        wider. ``setPixmap`` doesn't re-scale on resize on its
        own; we have to redo the scale ourselves."""
        super().resizeEvent(event)
        page = self._current_page()
        if page is not None and not self._playing:
            # During playback the auto-advance redraws on its
            # own cadence; skip the re-render so we don't
            # double-draw on every resize tick.
            self._render_page(page)

    # ------------------------------------------------------------------
    # Audio sync
    # ------------------------------------------------------------------
    def _sync_audio_to(self, page: SlidePage) -> None:
        """Decide what audio (if any) this slide should play
        and start / seek the player accordingly."""
        group = self._group_for(page)
        # 1. Group overlay path — preferred when the slide is
        # placed on a group's audio timeline.
        if (group is not None
                and group.overlay_audio_path
                and page.start_time_seconds_in_group is not None):
            self._play_overlay(group, page)
            return
        # 2. Per-slide audio fallback.
        if page.audio_path:
            self._play_per_slide_audio(page)
            return
        # 3. Silence.
        self._stop_audio()

    def _play_overlay(
            self, group: SlideGroup, page: SlidePage) -> None:
        path_str = group.overlay_audio_path
        if path_str != self._active_audio_path:
            self._player.setSource(
                QUrl.fromLocalFile(
                    str(Path(path_str).resolve())))
            self._active_audio_path = path_str
        # Always re-seek — the writer can also navigate
        # backwards, which means the same overlay might need
        # rewinding to an earlier offset.
        offset_ms = int(
            (page.start_time_seconds_in_group or 0.0) * 1000)
        self._player.setPosition(offset_ms)
        if self._playing:
            self._player.play()

    def _play_per_slide_audio(self, page: SlidePage) -> None:
        path_str = page.audio_path
        path = Path(path_str)
        if not path.exists():
            self._stop_audio()
            return
        if path_str != self._active_audio_path:
            self._player.setSource(
                QUrl.fromLocalFile(str(path.resolve())))
            self._active_audio_path = path_str
        self._player.setPosition(0)
        if self._playing:
            self._player.play()

    def _stop_audio(self) -> None:
        self._player.stop()
        self._player.setSource(QUrl())
        self._active_audio_path = ""

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------
    def _on_play_pause(self) -> None:
        if self._playing:
            # Pause: stop the advance timer but keep the visible
            # slide pinned. Audio pauses too so resume is gapless.
            self._playing = False
            self._advance_timer.stop()
            try:
                self._player.pause()
            except Exception:
                pass
            self._play_btn.setText("▶ Play")
            return
        if not self._deck.pages:
            return
        self._playing = True
        self._play_btn.setText("⏸ Pause")
        # Resume from the current slide (or step into the
        # selected one when no playback was in flight).
        idx = self._play_idx
        if idx < 0 or idx >= len(self._deck.pages):
            idx = max(
                0, self._find_index(self._current_id))
            self._play_idx = idx
        self._show_index(idx, autoplay=True)

    def _on_advance(self) -> None:
        if not self._playing:
            return
        next_idx = self._play_idx + 1
        if next_idx >= len(self._deck.pages):
            # Reached the end. Stop cleanly so the writer sees
            # the final slide pinned with audio off.
            self._on_stop(rewind=False)
            return
        self._play_idx = next_idx
        self._show_index(next_idx, autoplay=True)

    def _on_prev(self) -> None:
        self._playing = False
        self._advance_timer.stop()
        self._play_btn.setText("▶ Play")
        if not self._deck.pages:
            return
        idx = max(0, self._play_idx - 1)
        self._play_idx = idx
        self._show_index(idx, autoplay=False)

    def _on_next(self) -> None:
        self._playing = False
        self._advance_timer.stop()
        self._play_btn.setText("▶ Play")
        if not self._deck.pages:
            return
        idx = min(
            len(self._deck.pages) - 1,
            self._play_idx + 1)
        self._play_idx = idx
        self._show_index(idx, autoplay=False)

    def _on_stop(self, *, rewind: bool = True) -> None:
        self._playing = False
        self._advance_timer.stop()
        self._play_btn.setText("▶ Play")
        self._stop_audio()
        if rewind and self._deck.pages:
            self._play_idx = 0
            self._show_index(0, autoplay=False)

    def _on_replay(self) -> None:
        if not self._deck.pages:
            return
        self._on_stop()
        self._play_idx = 0
        self._playing = True
        self._play_btn.setText("⏸ Pause")
        self._show_index(0, autoplay=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _find_index(
            self, slide_id: Optional[str]) -> int:
        if slide_id is None:
            return -1
        for i, p in enumerate(self._deck.pages):
            if p.id == slide_id:
                return i
        return -1

    def _current_page(self) -> Optional[SlidePage]:
        if self._current_id is None:
            return None
        for p in self._deck.pages:
            if p.id == self._current_id:
                return p
        return None

    def _group_for(
            self,
            page: SlidePage) -> Optional[SlideGroup]:
        if not page.group_id:
            return None
        for g in self._deck.groups:
            if g.id == page.group_id:
                return g
        return None
