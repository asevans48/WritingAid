"""Chapter-deck editor — arrange + transition + voiceover a finished
chapter into a single shareable video.

The writer picks a chapter; the editor pre-fills its segment list
from the scenes in scene order (each scene's favorite output becomes
one segment). They can then:

  * Re-order segments (↑ / ↓).
  * Drop in custom files to fill gaps (📥 Add file).
  * Pick a transition into each segment + transition duration.
  * Record / import voiceover takes on a master timeline that
    plays over everything (reuses the per-scene
    ``VoiceoverEditorDialog`` machinery for record + trim + fade +
    gain).
  * Export the finished deck as MP4 — the stitcher chains
    ``stitch_with_transitions`` and ``mix_voiceover_segments``
    so transitions and voiceover both land in a single pass.

The deck lives on ``VideoStudio.chapter_decks`` so the writer
can come back to a half-edited deck across sessions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget,
)

from src.video_studio.models import (
    CHAPTER_TRANSITIONS, ChapterDeck, ChapterDeckSegment,
)


class ChapterDeckEditorDialog(QDialog):
    """Edit a ChapterDeck end-to-end before exporting.

    Constructor wants:
      * the studio (for chapter_decks persistence + scene lookup)
      * a chapter scene list (already ordered by the studio's
        ``collect_chapter_scenes``)
      * an output directory (for voiceover recordings + the
        exported MP4)
      * an LLM/RAG-free callable ``on_export`` that the host
        wires to ``stitch_with_transitions`` + ``mix_voiceover_segments``.
    """

    def __init__(
        self,
        studio: Any,
        chapter_id: str,
        chapter_label: str,
        chapter_scenes: List[Any],
        output_dir: Path,
        on_export,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Chapter deck editor — {chapter_label}")
        self.setModal(True)
        self.resize(960, 680)
        self.setMinimumSize(720, 520)
        self._studio = studio
        self._chapter_id = chapter_id
        self._chapter_label = chapter_label
        self._chapter_scenes = chapter_scenes
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._on_export = on_export
        # Reuse an existing ChapterDeck record for this chapter if
        # one exists, otherwise spin up a fresh one (the writer can
        # iterate without losing transitions / takes).
        existing = None
        for d in getattr(studio, "chapter_decks", []) or []:
            if d.chapter_id == chapter_id:
                existing = d
                break
        if existing is None:
            existing = ChapterDeck(
                chapter_id=chapter_id,
                name=chapter_label or "Chapter deck")
            self._seed_segments_from_scenes(existing)
            studio.chapter_decks.append(existing)
        self._deck: ChapterDeck = existing
        self._selected_segment_id: Optional[str] = None
        self._build_ui()
        self._refresh_segments()

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------
    def _seed_segments_from_scenes(self, deck: ChapterDeck) -> None:
        """First-time seed: one segment per scene, in scene order,
        with the studio's default transition between adjacent scenes."""
        for idx, scene in enumerate(self._chapter_scenes):
            deck.segments.append(ChapterDeckSegment(
                scene_id=scene.id,
                label=scene.name or f"Scene {idx + 1}",
                transition_in=(
                    "cut" if idx == 0
                    else deck.transition_default),
                transition_seconds=(
                    0.0 if idx == 0
                    else deck.transition_seconds_default),
                order=idx,
            ))

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        header = QLabel(
            "Arrange the chapter's segments, pick transitions, "
            "and (optionally) layer voiceover over the whole "
            "thing. The export renders everything in one pass.")
        header.setWordWrap(True)
        header.setStyleSheet("color: #475569; font-size: 11px;")
        outer.addWidget(header)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── Left: segment list + reorder + add-file ─────────────
        left = QWidget()
        left_v = QVBoxLayout(left)
        left_v.setContentsMargins(0, 0, 0, 0)
        left_v.addWidget(QLabel("Segments (plays in this order):"))
        self._segment_list = QListWidget()
        self._segment_list.itemSelectionChanged.connect(
            self._on_segment_selected)
        left_v.addWidget(self._segment_list, stretch=1)
        seg_btns = QHBoxLayout()
        self._move_up_btn = QPushButton("↑")
        self._move_up_btn.setToolTip("Move selected segment up.")
        self._move_up_btn.clicked.connect(
            lambda: self._move_segment(-1))
        self._move_down_btn = QPushButton("↓")
        self._move_down_btn.setToolTip("Move selected segment down.")
        self._move_down_btn.clicked.connect(
            lambda: self._move_segment(+1))
        self._add_file_btn = QPushButton("📥 Add file…")
        self._add_file_btn.setToolTip(
            "Drop in any image / video file as a new segment — "
            "title cards, b-roll, an external render, anything.")
        self._add_file_btn.clicked.connect(self._on_add_file)
        self._remove_seg_btn = QPushButton("Remove")
        self._remove_seg_btn.clicked.connect(self._on_remove_segment)
        seg_btns.addWidget(self._move_up_btn)
        seg_btns.addWidget(self._move_down_btn)
        seg_btns.addWidget(self._add_file_btn)
        seg_btns.addWidget(self._remove_seg_btn)
        seg_btns.addStretch()
        left_v.addLayout(seg_btns)
        splitter.addWidget(left)

        # ── Right: detail + transitions + master controls ───────
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QScrollArea.Shape.NoFrame)
        right_inner = QWidget()
        right_v = QVBoxLayout(right_inner)

        detail_box = QGroupBox("Selected segment")
        form = QFormLayout(detail_box)
        self._label_edit = QLineEdit()
        self._label_edit.editingFinished.connect(
            self._commit_segment_fields)
        form.addRow("Label", self._label_edit)

        self._transition_combo = QComboBox()
        for key, label in CHAPTER_TRANSITIONS:
            self._transition_combo.addItem(label, key)
        self._transition_combo.setToolTip(
            "How this segment transitions IN from the previous "
            "one. The first segment ignores its transition.")
        self._transition_combo.currentIndexChanged.connect(
            self._commit_segment_fields)
        form.addRow("Transition in", self._transition_combo)

        self._transition_seconds_spin = QDoubleSpinBox()
        self._transition_seconds_spin.setRange(0.0, 5.0)
        self._transition_seconds_spin.setDecimals(2)
        self._transition_seconds_spin.setSingleStep(0.1)
        self._transition_seconds_spin.setSuffix(" s")
        self._transition_seconds_spin.editingFinished.connect(
            self._commit_segment_fields)
        form.addRow(
            "Transition length",
            self._transition_seconds_spin)

        self._duration_override_spin = QDoubleSpinBox()
        self._duration_override_spin.setRange(0.0, 600.0)
        self._duration_override_spin.setDecimals(2)
        self._duration_override_spin.setSingleStep(0.5)
        self._duration_override_spin.setSpecialValueText(
            "natural length")
        self._duration_override_spin.setSuffix(" s")
        self._duration_override_spin.setToolTip(
            "Override how long this segment plays. 0 means use "
            "the scene's natural duration (or 4 s for a still).")
        self._duration_override_spin.editingFinished.connect(
            self._commit_segment_fields)
        form.addRow(
            "Duration", self._duration_override_spin)

        self._open_segment_btn = QPushButton("👁 Open segment file")
        self._open_segment_btn.clicked.connect(
            self._on_open_segment_file)
        form.addRow("", self._open_segment_btn)
        right_v.addWidget(detail_box)

        # Master deck settings.
        master_box = QGroupBox("Deck defaults")
        master_form = QFormLayout(master_box)
        self._default_transition_combo = QComboBox()
        for key, label in CHAPTER_TRANSITIONS:
            self._default_transition_combo.addItem(label, key)
        self._default_transition_combo.setToolTip(
            "Used when 'Apply default to all segments' is clicked.")
        master_form.addRow(
            "Default transition", self._default_transition_combo)
        self._default_transition_seconds_spin = QDoubleSpinBox()
        self._default_transition_seconds_spin.setRange(0.0, 5.0)
        self._default_transition_seconds_spin.setDecimals(2)
        self._default_transition_seconds_spin.setSingleStep(0.1)
        self._default_transition_seconds_spin.setSuffix(" s")
        master_form.addRow(
            "Default length",
            self._default_transition_seconds_spin)
        self._apply_default_btn = QPushButton(
            "Apply default to all segments")
        self._apply_default_btn.clicked.connect(
            self._on_apply_default_transition)
        master_form.addRow("", self._apply_default_btn)
        right_v.addWidget(master_box)

        # Voiceover panel — opens the existing per-scene editor
        # but bound to the deck's master timeline.
        vo_box = QGroupBox("Master voiceover")
        vo_v = QVBoxLayout(vo_box)
        vo_v.addWidget(QLabel(
            "Record, import, and arrange voiceover takes that "
            "play OVER the whole chapter deck."))
        self._vo_count_label = QLabel("")
        vo_v.addWidget(self._vo_count_label)
        self._open_vo_btn = QPushButton(
            "🎤 Open voiceover editor…")
        self._open_vo_btn.clicked.connect(
            self._on_open_voiceover_editor)
        vo_v.addWidget(self._open_vo_btn)
        right_v.addWidget(vo_box)

        right_v.addStretch()
        right.setWidget(right_inner)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, stretch=1)

        # Bottom row — two export formats + Close. MP4 renders
        # with transitions + master voiceover via the stitcher.
        # PowerPoint composes one slide per segment with images
        # embedded (videos become movie objects), per-slide audio
        # if voiceovers map cleanly to segments, and auto-advance
        # timings — gives writers an editable handoff.
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close)
        self._export_mp4_btn = QPushButton("🎬 Export MP4…")
        self._export_mp4_btn.clicked.connect(
            self._on_export_clicked)
        self._export_pptx_btn = QPushButton("📊 Export PowerPoint…")
        self._export_pptx_btn.setToolTip(
            "Save as .pptx — one slide per segment with the "
            "favorite image / video embedded. Per-segment voiceover "
            "slices auto-play on slide entry; slides auto-advance "
            "based on each segment's duration. No text overlays.")
        self._export_pptx_btn.clicked.connect(
            self._on_export_pptx_clicked)
        buttons.addButton(
            self._export_mp4_btn,
            QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(
            self._export_pptx_btn,
            QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.rejected.connect(self.accept)
        outer.addWidget(buttons)

        # Initial load of master fields.
        idx = self._default_transition_combo.findData(
            self._deck.transition_default)
        if idx >= 0:
            self._default_transition_combo.setCurrentIndex(idx)
        self._default_transition_seconds_spin.setValue(
            float(self._deck.transition_seconds_default))
        self._default_transition_combo.currentIndexChanged.connect(
            self._commit_default_fields)
        self._default_transition_seconds_spin.editingFinished.connect(
            self._commit_default_fields)
        self._set_detail_enabled(False)

    def _set_detail_enabled(self, enabled: bool) -> None:
        for w in (
            self._label_edit,
            self._transition_combo,
            self._transition_seconds_spin,
            self._duration_override_spin,
            self._open_segment_btn,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    # Segment helpers
    # ------------------------------------------------------------------
    def _segment_file_path(
        self, segment: ChapterDeckSegment,
    ) -> Optional[Path]:
        """Resolve a segment to a concrete file: scene favorite
        clip when scene_id is set, otherwise the custom path."""
        if segment.custom_path:
            p = Path(segment.custom_path)
            return p if p.exists() else None
        if segment.scene_id:
            for scene in self._chapter_scenes:
                if scene.id == segment.scene_id:
                    clip = scene.favorite_clip()
                    if clip and clip.file_path:
                        p = Path(clip.file_path)
                        return p if p.exists() else None
        return None

    def _segment_duration(
        self, segment: ChapterDeckSegment,
    ) -> float:
        if segment.duration_override > 0:
            return float(segment.duration_override)
        if segment.scene_id:
            for scene in self._chapter_scenes:
                if scene.id == segment.scene_id:
                    clip = scene.favorite_clip()
                    if clip:
                        return max(
                            1.0,
                            float(clip.duration_seconds or 4.0))
        return 4.0

    def _selected_segment(self) -> Optional[ChapterDeckSegment]:
        if self._selected_segment_id is None:
            return None
        for s in self._deck.segments:
            if s.id == self._selected_segment_id:
                return s
        return None

    def _refresh_segments(self) -> None:
        self._segment_list.clear()
        for idx, seg in enumerate(self._deck.segments, start=1):
            transition = (
                "—" if (idx == 1 or seg.transition_in == "cut")
                else f"{seg.transition_in}/{seg.transition_seconds:.1f}s")
            file_present = (
                self._segment_file_path(seg) is not None)
            mark = "" if file_present else " ⚠ no file"
            text = (
                f"{idx}. {seg.label or seg.scene_id or 'segment'}"
                f"   ({self._segment_duration(seg):.1f}s) — {transition}"
                f"{mark}")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, seg.id)
            self._segment_list.addItem(item)
        # Restore selection.
        for i in range(self._segment_list.count()):
            item = self._segment_list.item(i)
            if (item.data(Qt.ItemDataRole.UserRole)
                    == self._selected_segment_id):
                self._segment_list.setCurrentRow(i)
                return
        if self._selected_segment_id is not None:
            self._selected_segment_id = None
            self._set_detail_enabled(False)
        self._refresh_vo_summary()

    def _refresh_vo_summary(self) -> None:
        n = len(self._deck.voiceovers)
        self._vo_count_label.setText(
            f"{n} take" + ("s" if n != 1 else "")
            + " on the master timeline.")

    def _on_segment_selected(self) -> None:
        item = self._segment_list.currentItem()
        if item is None:
            self._selected_segment_id = None
            self._set_detail_enabled(False)
            return
        self._selected_segment_id = item.data(
            Qt.ItemDataRole.UserRole)
        seg = self._selected_segment()
        if seg is None:
            return
        self._set_detail_enabled(True)
        for w in (
            self._label_edit, self._transition_combo,
            self._transition_seconds_spin,
            self._duration_override_spin,
        ):
            w.blockSignals(True)
        self._label_edit.setText(seg.label)
        idx = self._transition_combo.findData(seg.transition_in)
        self._transition_combo.setCurrentIndex(
            idx if idx >= 0 else 0)
        self._transition_seconds_spin.setValue(
            float(seg.transition_seconds))
        self._duration_override_spin.setValue(
            float(seg.duration_override))
        for w in (
            self._label_edit, self._transition_combo,
            self._transition_seconds_spin,
            self._duration_override_spin,
        ):
            w.blockSignals(False)
        # The first segment has no transition-in — disable those
        # controls so writers don't think they did something wrong.
        is_first = (
            self._deck.segments
            and self._deck.segments[0].id == seg.id)
        self._transition_combo.setEnabled(not is_first)
        self._transition_seconds_spin.setEnabled(not is_first)

    def _commit_segment_fields(self) -> None:
        seg = self._selected_segment()
        if seg is None:
            return
        seg.label = self._label_edit.text().strip()
        seg.transition_in = (
            self._transition_combo.currentData() or "cut")
        seg.transition_seconds = float(
            self._transition_seconds_spin.value())
        seg.duration_override = float(
            self._duration_override_spin.value())
        from datetime import datetime
        self._deck.updated_at = datetime.now()
        self._refresh_segments()

    def _commit_default_fields(self) -> None:
        self._deck.transition_default = (
            self._default_transition_combo.currentData() or "fade")
        self._deck.transition_seconds_default = float(
            self._default_transition_seconds_spin.value())

    def _on_apply_default_transition(self) -> None:
        kind = self._deck.transition_default
        secs = self._deck.transition_seconds_default
        for idx, seg in enumerate(self._deck.segments):
            if idx == 0:
                seg.transition_in = "cut"
                seg.transition_seconds = 0.0
                continue
            seg.transition_in = kind
            seg.transition_seconds = secs
        self._refresh_segments()

    def _move_segment(self, delta: int) -> None:
        seg = self._selected_segment()
        if seg is None:
            return
        idx = next(
            (i for i, s in enumerate(self._deck.segments)
             if s.id == seg.id),
            -1)
        new_idx = idx + delta
        if idx < 0 or not (0 <= new_idx < len(self._deck.segments)):
            return
        self._deck.segments.pop(idx)
        self._deck.segments.insert(new_idx, seg)
        for i, s in enumerate(self._deck.segments):
            s.order = i
        self._refresh_segments()

    def _on_add_file(self) -> None:
        picked, _ = QFileDialog.getOpenFileNames(
            self, "Add file as deck segment", "",
            "Media (*.png *.jpg *.jpeg *.webp *.gif *.mp4 *.mov "
            "*.webm *.mkv);;All files (*)")
        if not picked:
            return
        for path_str in picked:
            p = Path(path_str)
            if not p.exists():
                continue
            seg = ChapterDeckSegment(
                custom_path=str(p),
                label=p.stem,
                transition_in=self._deck.transition_default,
                transition_seconds=self._deck.transition_seconds_default,
                order=len(self._deck.segments),
            )
            self._deck.segments.append(seg)
        self._refresh_segments()

    def _on_remove_segment(self) -> None:
        seg = self._selected_segment()
        if seg is None:
            return
        reply = QMessageBox.question(
            self, "Remove segment?",
            f"Drop '{seg.label or seg.id}' from the deck?")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._deck.segments = [
            s for s in self._deck.segments if s.id != seg.id]
        for i, s in enumerate(self._deck.segments):
            s.order = i
        self._selected_segment_id = None
        self._refresh_segments()

    def _on_open_segment_file(self) -> None:
        seg = self._selected_segment()
        if seg is None:
            return
        path = self._segment_file_path(seg)
        if path is None:
            QMessageBox.warning(
                self, "No file",
                "This segment has no file on disk yet. Generate "
                "the scene's favorite output first, or drop in a "
                "file via 📥 Add file…")
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(path.resolve())))

    def _on_open_voiceover_editor(self) -> None:
        """Reuse the per-scene voiceover editor for the deck's
        master timeline by wrapping the deck in a stub scene that
        exposes ``voiceover_segments`` + ``effective_duration``."""
        from src.ui.video_studio.voiceover_editor import (
            VoiceoverEditorDialog)
        deck = self._deck

        class _DeckScene:
            id = f"deck_{deck.id}"
            name = f"{self._chapter_label} (master)"
            mode = "video"
            voiceover_segments = deck.voiceovers
            actions: list = []
            image_display_seconds = 4.0
            target_duration_seconds = sum(
                self._segment_duration(s)
                for s in self._deck.segments) or 0.0

            def is_slideshow(self):
                return False

            def favorite_clip(self):
                return None

        dlg = VoiceoverEditorDialog(
            _DeckScene(),
            self._output_dir / "voiceover",
            parent=self)
        dlg.exec()
        # The editor mutates deck.voiceovers directly via the
        # stub scene's reference — refresh count.
        self._refresh_vo_summary()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _on_export_clicked(self) -> None:
        valid = [
            (s, self._segment_file_path(s))
            for s in self._deck.segments]
        valid = [(s, p) for s, p in valid if p is not None]
        if not valid:
            QMessageBox.information(
                self, "Nothing to export",
                "None of the segments resolve to a file on disk. "
                "Generate scene favorites or drop in custom "
                "files first.")
            return
        out_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save chapter deck (MP4)",
            str(
                self._output_dir
                / f"{self._chapter_label.replace('/', '-')}_edited.mp4"),
            "MP4 video (*.mp4)")
        if not out_str:
            return
        self._on_export(
            deck=self._deck,
            chapter_scenes=self._chapter_scenes,
            output_path=Path(out_str))

    def _on_export_pptx_clicked(self) -> None:
        """Compose the chapter deck as a .pptx using the slide-deck
        exporter. Each segment becomes one slide; images embed
        inline, videos embed as movie objects, per-segment
        voiceover slices (when present on the master timeline at
        an overlapping offset) become per-slide audio with auto-
        play and auto-advance timings."""
        resolved = []
        for seg in self._deck.segments:
            path = self._segment_file_path(seg)
            if path is None:
                continue
            resolved.append((seg, path))
        if not resolved:
            QMessageBox.information(
                self, "Nothing to export",
                "None of the segments resolve to a file on disk.")
            return
        out_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save chapter deck (PowerPoint)",
            str(
                self._output_dir
                / f"{self._chapter_label.replace('/', '-')}_edited.pptx"),
            "PowerPoint (*.pptx)")
        if not out_str:
            return
        # Build a transient SlideDeckProject from the segments so
        # we can reuse the slide-deck exporter as-is.
        from src.video_studio.models import (
            SlideDeckProject, SlidePage)
        from src.video_studio.slide_deck import (
            export_slide_deck_to_pptx)
        slide_deck = SlideDeckProject(
            name=self._chapter_label or "Chapter deck",
            working_dir=str(self._output_dir))
        # Compute each segment's start time so voiceover slices
        # can be matched. xfade overlaps shorten the previous
        # segment's effective end — we ignore that fine-grain
        # detail here since per-slide voiceover slicing is a
        # best-effort mapping rather than a frame-precise mux.
        running = 0.0
        per_segment_audio = self._slice_master_voiceovers(
            resolved)
        for idx, (seg, path) in enumerate(resolved):
            duration = self._segment_duration(seg)
            slide = SlidePage(
                index=idx,
                label=seg.label or path.stem,
                image_path=str(path),
                duration_seconds=max(1.0, duration),
            )
            audio_path = per_segment_audio.get(seg.id)
            if audio_path is not None:
                slide.audio_path = str(audio_path)
                slide.audio_duration_seconds = duration
            slide_deck.pages.append(slide)
            running += duration
        ok, msg, skipped = export_slide_deck_to_pptx(
            slide_deck, Path(out_str))
        if not ok:
            QMessageBox.warning(self, "Export failed", msg)
            return
        body = msg
        if skipped:
            body += (
                "\n\nNotes:\n  • "
                + "\n  • ".join(skipped[:10])
                + ("\n  • …" if len(skipped) > 10 else ""))
        QMessageBox.information(
            self, "PowerPoint deck saved", body)

    def _slice_master_voiceovers(
        self, resolved_segments,
    ) -> dict:
        """For each segment, look for master-voiceover takes whose
        playback window overlaps the segment's slot. When a take
        does, render the overlapping slice as a per-slide WAV via
        ffmpeg so PowerPoint can embed it. Returns a dict mapping
        ``segment.id`` → ``Path`` (or skipped when no overlap or
        ffmpeg unavailable).
        """
        result: dict = {}
        if not self._deck.voiceovers:
            return result
        import shutil as _sh
        if not _sh.which("ffmpeg"):
            return result
        import subprocess as _sp
        slice_dir = (
            self._output_dir
            / f"vo_slices_{self._deck.id}")
        slice_dir.mkdir(parents=True, exist_ok=True)
        running = 0.0
        for idx, (seg, _path) in enumerate(resolved_segments):
            seg_start = running
            seg_dur = self._segment_duration(seg)
            seg_end = seg_start + seg_dur
            running += seg_dur
            # Find the first voiceover that overlaps this window.
            for vo in self._deck.voiceovers:
                if not vo.audio_path:
                    continue
                source = Path(vo.audio_path)
                if not source.exists():
                    continue
                start = float(vo.start_at or 0.0)
                effective_end = (
                    start + (vo.out_point - vo.in_point
                             if vo.out_point > vo.in_point
                             else vo.source_duration_seconds))
                if effective_end <= seg_start or start >= seg_end:
                    continue
                # Compute the slice within the source. The
                # voiceover's own in_point + offset into its
                # take produces the cut.
                slice_start = max(0.0, seg_start - start)
                slice_in = vo.in_point + slice_start
                slice_dur = min(
                    seg_dur,
                    effective_end - max(seg_start, start))
                slice_out = (
                    slice_dir
                    / f"seg_{idx:03d}_{vo.id}.wav")
                if slice_out.exists():
                    result[seg.id] = slice_out
                    break
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{slice_in:.3f}",
                    "-t", f"{slice_dur:.3f}",
                    "-i", str(source.resolve()),
                    "-c:a", "pcm_s16le",
                    str(slice_out),
                ]
                try:
                    proc = _sp.run(
                        cmd, capture_output=True,
                        text=True, timeout=60)
                    if proc.returncode == 0 and slice_out.exists():
                        result[seg.id] = slice_out
                        break
                except Exception:
                    continue
        return result
