"""Show less at once on the Write screen (piece D.7, parts 1 and 2).

**Part 1: the Write screen's buttons, grouped by row** (24 visible become
19; every action is still one click away and calls the same method):

* **Novellas:** "＋ Novella", "⇢ Move main chapters…" and "🗑 Drop novella"
  become one **Novellas ▾**.
* **Manuscript drafts:** ＋ (save as a new draft), 🗑 (drop this draft) and
  ↗ (open a draft in its own window) become one **Drafts ▾** beside the
  "Editing:" selector. "⇅ Split View" stays a button. (The chapter's own
  "📄 Draft ▾" holds the *chapter's* saved drafts, a different thing, so
  these are not put there.)
* **Annotations:** 📝 (add, Ctrl+Shift+N) and 📋 (view all) become one
  **📝** button: a click adds, its arrow lists them.

The old buttons are kept, hidden: other code enables, disables and renames
them, and a menu item copies its button's enabled state when the menu
opens and works by clicking it. Shortcuts are unchanged.

**Part 2: a shorter hover card.** The card on a flagged word keeps its
fixes, the "Fix all N like this" box, "Ignore", and the main answer for
its kind ("Add to dictionary" for a spelling, "Rewrite with AI" for a
style flag) in view. Its other links (Ask, Suggest in context, See all N…)
go behind **More ▾** on the same row, which shows them in place: no
pop-up, so the card cannot close under the pointer. With fewer than two
to fold, nothing is folded.
"""

from __future__ import annotations

from typing import Any, Iterable, List

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMenu, QPushButton, QToolButton


# ── Part 1 ─────────────────────────────────────────────────────────────

def _menu_for(parent: Any, text: str, tip: str, buttons: Iterable[Any],
              labels: Iterable[str]) -> QToolButton:
    btn = QToolButton(parent)
    btn.setText(text)
    btn.setToolTip(tip)
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    btn.setStyleSheet("QToolButton { font-size: 11px; padding: 2px 6px; }"
                      "QToolButton::menu-indicator { image: none; width: 0px; }")
    menu = QMenu(btn)
    pairs = []
    for b, label in zip(buttons, labels):
        act = menu.addAction(label)
        act.setToolTip(b.toolTip())
        act.triggered.connect(lambda _=False, b=b: b.click())
        pairs.append((act, b))
        b.setVisible(False)
    menu.setToolTipsVisible(True)

    def sync():
        for act, b in pairs:
            act.setEnabled(b.isEnabled())
    menu.aboutToShow.connect(sync)
    btn.setMenu(menu)
    return btn


def _replace_in_layout(first: Any, new: Any) -> bool:
    """Put ``new`` where ``first`` sits in its parent's layout."""
    parent = first.parentWidget()
    lay = parent.layout() if parent is not None else None
    stack = [lay] if lay is not None else []
    while stack:
        layout = stack.pop()
        i = layout.indexOf(first)
        if i >= 0:
            layout.insertWidget(i, new)
            return True
        for n in range(layout.count()):
            child = layout.itemAt(n).layout()
            if child is not None:
                stack.append(child)
    return False


def install(manuscript_editor: Any) -> None:
    """Novellas ▾ and Drafts ▾ (the call line in ``ManuscriptEditor``)."""
    me = manuscript_editor
    try:
        novellas = _menu_for(
            me, "Novellas ▾", "Start, fill or drop a novella in this project's universe",
            (me.new_subproject_btn, me.move_to_novella_btn, me.drop_novella_btn),
            ("＋ New novella…", "⇢ Move main chapters into a novella…", "🗑 Drop a novella…"))
        _replace_in_layout(me.new_subproject_btn, novellas)
        me.novellas_menu_btn = novellas
        drafts = _menu_for(
            me, "Drafts ▾", "Save, drop or open manuscript drafts",
            (me.new_draft_btn, me.drop_draft_btn, me.popout_draft_btn),
            ("＋ Save the manuscript as a new draft", "🗑 Drop this draft…",
             "↗ Open a draft in its own window…"))
        _replace_in_layout(me.new_draft_btn, drafts)
        me.drafts_menu_btn = drafts
    except Exception as e:                       # never break the Write tab
        print(f"[write toolbar] not grouped: {e}")


def annotations_button(toolbar: Any, add_action: Any, view_action: Any) -> QToolButton:
    """One 📝 button: click adds an annotation, the arrow lists them. Both
    actions keep their objects, text and shortcut (Ctrl+Shift+N)."""
    btn = QToolButton(toolbar)
    btn.setDefaultAction(add_action)            # click = add; the shortcut lives here
    btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
    menu = QMenu(btn)
    # The shortcut stays on ``add_action`` only: the same keys on a second
    # action would be ambiguous and neither would fire.
    keys = add_action.shortcut().toString()
    add = menu.addAction("📝 Add annotation here" + (f"\t{keys}" if keys else ""))
    add.triggered.connect(add_action.trigger)
    view = menu.addAction("📋 View all annotations")
    view.triggered.connect(view_action.trigger)
    btn.setMenu(menu)
    toolbar.addWidget(btn)
    toolbar.annotations_btn = btn
    return btn


# ── Part 2 ─────────────────────────────────────────────────────────────

# The commonest answer for each kind stays in view: Ignore for any flag,
# Add to dictionary for a spelling, Rewrite with AI for a style flag.
KEEP_ON_CARD = ("Ignore", "Add to dictionary", "✨ Rewrite with AI")


def fold_card_row(card: Any, row: Any) -> None:
    """Behind "More ▾": every link on ``row`` but the ones kept in view.
    Called by ``ErrorCard.show_for`` once the row is built."""
    links: List[QPushButton] = []
    for n in range(row.count()):
        w = row.itemAt(n).widget()
        if isinstance(w, QPushButton) and w.objectName() == "act" \
                and w.text() not in KEEP_ON_CARD:
            links.append(w)
    if len(links) < 2:                           # nothing worth folding
        return
    for w in links:
        w.setVisible(False)
    more = QPushButton("More ▾")
    more.setObjectName("act")
    more.setCursor(Qt.CursorShape.PointingHandCursor)
    more.setToolTip(", ".join(w.text() for w in links))

    def show_all(_=False):
        for w in links:
            w.setVisible(True)
        more.setVisible(False)
        card.adjustSize()
    more.clicked.connect(show_all)
    at = row.indexOf(links[0])
    row.insertWidget(at, more)
    card.more_btn = more
