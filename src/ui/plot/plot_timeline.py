"""Vertical timeline view of plot events, grouped by act.

Replaces the old flat-list event view. Events are rendered as cards
under per-act section headers, in ``sort_order`` within each act.
The widget is read-mostly; mutations (add/edit/remove/move) are
delegated back to the host via signals so the existing handlers in
PlotManagerWidget keep being the single source of truth for plot
mutations.

The host wires this up by:
  * setting initial data via ``set_events(events, num_acts, act_names)``
  * calling ``set_events(...)`` again whenever events change
  * subscribing to the signals to perform the actual mutation
"""

from __future__ import annotations

from typing import List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from src.models.project import PlotEvent


# Colors for the stage chip. Match the existing pyramid color scheme
# so the two views feel like the same project speaking with one
# voice.
_STAGE_COLORS = {
    "exposition":     "#3b82f6",   # blue
    "rising_action":  "#10b981",   # green
    "climax":         "#ef4444",   # red
    "falling_action": "#f59e0b",   # amber
    "resolution":     "#8b5cf6",   # purple
}

_STAGE_NAMES = {
    "exposition":     "Exposition",
    "rising_action":  "Rising Action",
    "climax":         "Climax",
    "falling_action": "Falling Action",
    "resolution":     "Resolution",
}


def _stage_order(stage: str) -> int:
    """Stage rank for stable secondary sort within an act."""
    return {"exposition": 0, "rising_action": 1, "climax": 2,
            "falling_action": 3, "resolution": 4}.get(stage, 1)


class _EventCard(QFrame):
    """One event rendered as a card. Knows its event id and emits
    coarse-grained signals — the parent timeline aggregates them."""

    edit_requested = pyqtSignal(str)         # event_id
    delete_requested = pyqtSignal(str)       # event_id
    move_up_requested = pyqtSignal(str)      # event_id
    move_down_requested = pyqtSignal(str)    # event_id
    selected = pyqtSignal(str)               # event_id (on click)

    def __init__(
        self,
        event: PlotEvent,
        index_in_act: int,
        can_move_up: bool,
        can_move_down: bool,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.event_id = event.id
        self.setObjectName("plotEventCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame#plotEventCard {"
            "  background-color: #ffffff;"
            "  border: 1px solid #d1d5db;"
            "  border-radius: 6px;"
            "}"
            "QFrame#plotEventCard:hover {"
            "  border-color: #6b7280;"
            "}"
        )
        self._build(event, index_in_act, can_move_up, can_move_down)

    def _build(
        self,
        event: PlotEvent,
        index_in_act: int,
        can_move_up: bool,
        can_move_down: bool,
    ) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(10)

        # Numbered badge — the event's position within its act. Gives
        # the writer a clear sense of "this is beat 3 of Act II."
        badge = QLabel(str(index_in_act))
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            "background-color: #1f2937; color: white; "
            "border-radius: 14px; font-weight: 600;")
        outer.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        # Body column
        body = QVBoxLayout()
        body.setSpacing(4)

        # Title row: title + stage chip
        title_row = QHBoxLayout()
        title_label = QLabel(event.title or "(untitled event)")
        title_font = QFont()
        title_font.setBold(True)
        title_font.setPointSize(11)
        title_label.setFont(title_font)
        title_label.setWordWrap(True)
        title_row.addWidget(title_label, stretch=1)

        chip = QLabel(_STAGE_NAMES.get(event.stage, event.stage))
        chip_color = _STAGE_COLORS.get(event.stage, "#6b7280")
        chip.setStyleSheet(
            f"background-color: {chip_color}; color: white; "
            f"padding: 2px 8px; border-radius: 10px; "
            f"font-size: 10px; font-weight: 600;")
        chip.setFixedHeight(20)
        title_row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(title_row)

        # Intensity bar — visualized as 10 small blocks filled to the
        # event's intensity / 10. Keeps the "dramatic weight" cue
        # from the pyramid view available in the timeline.
        intensity = max(0, min(100, getattr(event, "intensity", 50)))
        filled = round(intensity / 10)
        bar_label = QLabel(
            "intensity " + ("▆" * filled) + ("▁" * (10 - filled))
            + f"  ({intensity})")
        bar_label.setStyleSheet(
            "font-family: monospace; color: #4b5563; font-size: 11px;")
        body.addWidget(bar_label)

        # Description excerpt — first ~160 chars. Truncated with an
        # ellipsis; the full text is visible in the editor dialog.
        desc = (getattr(event, "description", "") or "").strip()
        if desc:
            if len(desc) > 160:
                desc = desc[:160].rstrip() + "…"
            desc_label = QLabel(desc)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet(
                "color: #4b5563; font-size: 11px;")
            body.addWidget(desc_label)

        # Action row
        actions = QHBoxLayout()
        actions.setSpacing(6)

        edit_btn = QPushButton("Edit")
        edit_btn.clicked.connect(
            lambda: self.edit_requested.emit(self.event_id))
        actions.addWidget(edit_btn)

        up_btn = QPushButton("↑")
        up_btn.setFixedWidth(32)
        up_btn.setEnabled(can_move_up)
        up_btn.setToolTip(
            "Move up within this act (and stage)"
            if can_move_up
            else "Already at the top of this act/stage group")
        up_btn.clicked.connect(
            lambda: self.move_up_requested.emit(self.event_id))
        actions.addWidget(up_btn)

        down_btn = QPushButton("↓")
        down_btn.setFixedWidth(32)
        down_btn.setEnabled(can_move_down)
        down_btn.setToolTip(
            "Move down within this act (and stage)"
            if can_move_down
            else "Already at the bottom of this act/stage group")
        down_btn.clicked.connect(
            lambda: self.move_down_requested.emit(self.event_id))
        actions.addWidget(down_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setStyleSheet("color: #b91c1c;")
        delete_btn.clicked.connect(
            lambda: self.delete_requested.emit(self.event_id))
        actions.addWidget(delete_btn)

        actions.addStretch()
        body.addLayout(actions)

        outer.addLayout(body, stretch=1)

    def mousePressEvent(self, ev) -> None:  # type: ignore[override]
        # Forward click to "selected" so the host can keep its
        # idea of "currently focused event" in sync — matches the
        # selection semantic the old QListWidget had.
        self.selected.emit(self.event_id)
        super().mousePressEvent(ev)


class PlotTimelineWidget(QWidget):
    """Vertical timeline grouped by act.

    Pure view: mutations are emitted as signals; the parent owns
    ``freytag_pyramid.events`` and applies the change, then calls
    ``set_events(...)`` to refresh.
    """

    add_event_requested = pyqtSignal(int)           # act_number
    edit_event_requested = pyqtSignal(str)          # event_id
    delete_event_requested = pyqtSignal(str)        # event_id
    move_event_up_requested = pyqtSignal(str)       # event_id
    move_event_down_requested = pyqtSignal(str)     # event_id
    event_selected = pyqtSignal(str)                # event_id

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._events: List[PlotEvent] = []
        self._num_acts: int = 3
        self._act_names: List[str] = ["Act I", "Act II", "Act III"]
        self._selected_event_id: Optional[str] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self._scroll)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(12, 12, 12, 12)
        self._content_layout.setSpacing(12)
        self._scroll.setWidget(self._content)

        self._render_empty()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_events(
        self,
        events: List[PlotEvent],
        num_acts: int,
        act_names: List[str],
    ) -> None:
        """Replace the rendered events. Triggers a full rebuild — the
        list is short enough (typically <100 beats) that incremental
        diffing isn't worth the complexity."""
        self._events = list(events or [])
        self._num_acts = max(1, int(num_acts or 1))
        self._act_names = list(act_names or [])
        self._render()

    def selected_event_id(self) -> Optional[str]:
        """The event the user last clicked. Used by toolbar handlers
        in the host so 'Edit' / 'Delete' / 'Move Up' / 'Move Down'
        keep their semantics from the old list view."""
        return self._selected_event_id

    def select_event(self, event_id: Optional[str]) -> None:
        """Programmatically set the selection (e.g. to re-select an
        event after a move-up shuffles its index)."""
        self._selected_event_id = event_id
        # Visual selection style update is implicit — we re-render on
        # every change, and the next render reads selected_event_id.

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _clear_layout(self) -> None:
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                # Recursively delete widgets in nested layouts.
                self._clear_nested(child_layout)

    def _clear_nested(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            child = item.layout()
            if child is not None:
                self._clear_nested(child)

    def _render(self) -> None:
        self._clear_layout()
        if not self._events:
            self._render_empty()
            return

        # Bucket events by act. Within each act, sort by (stage_order,
        # sort_order) — same ordering the old flat list used so the
        # data semantics are preserved.
        by_act: dict = {}
        for ev in self._events:
            by_act.setdefault(ev.act, []).append(ev)
        for act_events in by_act.values():
            act_events.sort(
                key=lambda e: (_stage_order(e.stage), e.sort_order))

        # Iterate over every configured act (not just acts that have
        # events) so empty acts still show a section with an "Add
        # event" button. Lets the writer build out structure top-down.
        for act_num in range(1, self._num_acts + 1):
            self._render_act_section(act_num, by_act.get(act_num, []))

        self._content_layout.addStretch()

    def _render_empty(self) -> None:
        empty = QLabel(
            "No plot events yet. Use the toolbar above to add one — "
            "or add events to specific acts below.")
        empty.setStyleSheet(
            "color: #6b7280; font-style: italic; padding: 24px;")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        self._content_layout.addWidget(empty)
        # Even with no events, render the per-act add buttons so the
        # writer can scaffold a plan.
        for act_num in range(1, self._num_acts + 1):
            self._render_act_section(act_num, [])
        self._content_layout.addStretch()

    def _render_act_section(
        self,
        act_num: int,
        events_in_act: List[PlotEvent],
    ) -> None:
        # Section header
        header_row = QHBoxLayout()
        header_row.setSpacing(8)
        name = (self._act_names[act_num - 1]
                if act_num <= len(self._act_names)
                else f"Act {act_num}")
        header = QLabel(f"━━ {name} ━━")
        header_font = QFont()
        header_font.setBold(True)
        header_font.setPointSize(13)
        header.setFont(header_font)
        header.setStyleSheet("color: #1f2937; padding: 4px 0;")
        header_row.addWidget(header)
        count_chip = QLabel(
            f"{len(events_in_act)} event"
            f"{'s' if len(events_in_act) != 1 else ''}")
        count_chip.setStyleSheet(
            "color: #6b7280; font-size: 11px;")
        header_row.addWidget(count_chip)
        header_row.addStretch()
        self._content_layout.addLayout(header_row)

        # Divider line under the header
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("color: #d1d5db;")
        self._content_layout.addWidget(divider)

        # Group events within this act by stage so we can render
        # stage sub-headers when an act spans multiple stages. The
        # main reason this matters: pre-redesign projects often have
        # every event at act=1, so without per-stage grouping a
        # 30-event Act I would render as one unscannable pile.
        # Insertion-ordered dict keeps stage order stable across
        # renders.
        by_stage: dict = {}
        for ev in events_in_act:
            by_stage.setdefault(ev.stage, []).append(ev)
        show_stage_headers = len(by_stage) > 1

        # Event cards, grouped by stage where applicable. The
        # ``idx`` badge counts across the whole act so users see a
        # continuous 1..N sequence per act.
        idx = 0
        for stage, stage_events in by_stage.items():
            if show_stage_headers:
                sub_header = QLabel(
                    f"   ─ {_STAGE_NAMES.get(stage, stage)} ─")
                sub_font = QFont()
                sub_font.setBold(True)
                sub_font.setPointSize(11)
                sub_header.setFont(sub_font)
                sub_color = _STAGE_COLORS.get(stage, "#6b7280")
                sub_header.setStyleSheet(
                    f"color: {sub_color}; padding: 4px 0 2px 0;")
                self._content_layout.addWidget(sub_header)
            for stage_idx, ev in enumerate(stage_events):
                idx += 1
                # can_move_up/down are *within the stage group* — the
                # host's move handler swaps within (act, stage), so
                # the cap matches the actual swap behavior.
                card = _EventCard(
                    event=ev,
                    index_in_act=idx,
                    can_move_up=stage_idx > 0,
                    can_move_down=stage_idx < len(stage_events) - 1,
                    parent=self._content,
                )
                card.edit_requested.connect(
                    self.edit_event_requested.emit)
                card.delete_requested.connect(
                    self.delete_event_requested.emit)
                card.move_up_requested.connect(
                    self.move_event_up_requested.emit)
                card.move_down_requested.connect(
                    self.move_event_down_requested.emit)
                card.selected.connect(self._on_card_selected)
                self._content_layout.addWidget(card)

        # Per-act add button
        add_btn = QPushButton(f"+ Add event to {name}")
        add_btn.setStyleSheet(
            "QPushButton { color: #2563eb; border: 1px dashed #93c5fd;"
            " background-color: transparent; padding: 6px 10px;"
            " border-radius: 4px; }"
            "QPushButton:hover { background-color: #eff6ff; }")
        add_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed)
        add_btn.clicked.connect(
            lambda _checked=False, n=act_num:
            self.add_event_requested.emit(n))
        self._content_layout.addWidget(add_btn)

    def _on_card_selected(self, event_id: str) -> None:
        self._selected_event_id = event_id
        self.event_selected.emit(event_id)
