"""Right-click Suggestions: critique of a highlighted passage + rewrites."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai import passage_critique as pc
from src.models.project import Chapter, Character, WriterProject
from src.models.worldbuilding_objects import Faction, FactionType

TEXT = ("The storm broke at dusk. Mara ran to the pier, where Dr. Voss waited. "
        "\"Too late,\" he said. She didn't answer.\n\n"
        "The Ash Wardens' lanterns burned on the hill. Nobody slept.")


def span(sub):
    i = TEXT.index(sub)
    return i, i + len(sub)


# ── Widening to whole sentences ───────────────────────────────────

@pytest.mark.parametrize("picked,expected", [
    ("ran to the pier", "Mara ran to the pier, where Dr. Voss waited."),
    ("Dr. Voss", "Mara ran to the pier, where Dr. Voss waited."),          # not split at "Dr."
    ("late,\" he", "\"Too late,\" he said."),
    ("said. She", "\"Too late,\" he said. She didn't answer."),
    ("The storm broke at dusk.", "The storm broke at dusk."),               # already whole
    ("burned on", "The Ash Wardens' lanterns burned on the hill."),
    ("t answer.\n\nThe Ash", "She didn't answer.\n\nThe Ash Wardens' lanterns burned on the hill."),
])
def test_selection_widens_to_whole_sentences(picked, expected):
    s, e = pc.expand_to_sentences(TEXT, *span(picked))
    assert TEXT[s:e] == expected


def test_closing_quote_and_ellipsis_included():
    text = "He paused… \"Run!\" she cried. Then quiet."
    s, e = pc.expand_to_sentences(text, text.index("Run"), text.index("Run") + 2)
    assert text[s:e] == "\"Run!\" she cried."


def test_whitespace_selection_is_left_alone():
    assert pc.expand_to_sentences("A.  B.", 2, 4) == (4, 4)


def test_utf16_positions_map_to_python_indices():
    text = "Fire 🔥 burned. Then ash."
    qt = len(text[:text.index("Then")].encode("utf-16-le")) // 2
    assert pc.qt_to_py_index(text, qt) == text.index("Then")
    assert pc.py_to_qt_index(text, text.index("Then")) == qt


# ── Context ───────────────────────────────────────────────────────

@pytest.fixture
def project():
    p = WriterProject(name="Saga")
    p.characters = [
        Character(id="c1", name="Mara Venn", character_type="protagonist",
                  personality="guarded", speaking_style="clipped, never says please"),
        Character(id="c2", name="Voss", character_type="minor", personality="pedantic"),
        Character(id="c3", name="Absent", character_type="minor", personality="loud"),
    ]
    p.worldbuilding.factions = [
        Faction(id="f1", name="Ash Wardens", faction_type=FactionType.MILITARY,
                description="Seized Greywater ten years ago."),
        Faction(id="f2", name="Salt Guild", faction_type=FactionType.MILITARY,
                description="Unrelated."),
    ]
    sp = p.story_planning
    sp.main_plot = "Mara must decide whether to betray the Wardens."
    sp.freytag_pyramid.climax = "The pier burns."
    return p


@pytest.fixture
def chapter():
    ch = Chapter(id="ch", number=4, title="Pier", content=TEXT)
    ch.planning.outline = "Mara reaches the pier; Voss warns her."
    ch.planning.pov_character = "Mara Venn"
    return ch


def test_context_has_every_source(project, chapter):
    s, e = pc.expand_to_sentences(TEXT, *span("ran to the pier"))
    ctx = pc.build_context(project, chapter, TEXT, s, e, related=lambda q: "Greywater lore")
    assert ctx.passage.startswith("Mara ran")
    assert "The storm broke" in ctx.before and "Too late" in ctx.after
    assert "Mara Venn" in ctx.characters and "clipped" in ctx.characters
    assert "point-of-view" in ctx.characters
    assert "Voss" in ctx.characters and "Absent" not in ctx.characters
    assert "Ash Wardens" in ctx.world and "Salt Guild" not in ctx.world
    assert "betray the Wardens" in ctx.plot
    assert "The pier burns" in ctx.story_outline
    assert "Voss warns her" in ctx.chapter
    assert ctx.related == "Greywater lore"
    prompt = pc.build_prompt(ctx, focus="more dread")
    for heading in ("STORY OUTLINE", "PLOT", "THIS CHAPTER", "CHARACTERS", "WORLDBUILDING",
                    "PASSAGE TO CRITIQUE", "more dread", "SUGGESTION 3"):
        assert heading in prompt


def test_compact_context_is_smaller_for_local_models(project, chapter):
    long_text = ("Mara walked the long pier past the Ash Wardens. " * 400)
    s, e = 9000, 9050
    full = pc.build_context(project, chapter, long_text, s, e)
    small = pc.build_context(project, chapter, long_text, s, e, compact=True)
    assert len(pc.build_prompt(small)) < len(pc.build_prompt(full))


def test_context_without_project(chapter):
    ctx = pc.build_context(None, chapter, TEXT, 0, 24)
    assert ctx.passage == "The storm broke at dusk." and ctx.characters == ""


def test_failing_search_does_not_stop_the_critique(project, chapter):
    def broken(_q):
        raise RuntimeError("index missing")
    ctx = pc.build_context(project, chapter, TEXT, 0, 24, related=broken)
    assert ctx.related == ""


# ── Parsing model output ──────────────────────────────────────────

CLEAN = """WHAT WORKS:
- The storm-to-pier movement is quick.
- "Too late" lands.

WHAT DOESN'T WORK:
- Mara's fear is told, not shown.

SUGGESTION 1:
Mara sprinted for the pier.
WHY: Faster verb.

SUGGESTION 2:
The pier. Mara ran for it, and Voss was already there.
WHY: Fragment adds urgency.

SUGGESTION 3:
She reached the pier with salt in her mouth; Voss had waited.
WHY: Sensory anchor.
"""

MESSY = """<|channel>thought
planning<channel|>**What works**
1. Tight rhythm
2. Clear POV

### What doesn't work (and why):
* Voss speaks out of character —
  he's pedantic in his profile.

**Suggestion 1 (quieter):**
"Mara ran to the pier. Voss was waiting, of course."
**Why:** keeps her guarded voice.

Option 2 — Mara ran.
Version 2 of the plan had failed.
Rationale: echoes the plot.
"""


def test_parses_the_requested_format():
    r = pc.parse_critique(CLEAN)
    assert len(r.works) == 2 and len(r.issues) == 1
    assert [s.why for s in r.suggestions] == ["Faster verb.", "Fragment adds urgency.",
                                               "Sensory anchor."]
    assert r.suggestions[1].text.startswith("The pier. Mara ran")


def test_parses_what_small_models_actually_write():
    r = pc.parse_critique(MESSY)
    assert r.works == ["Tight rhythm", "Clear POV"]
    assert r.issues == ["Voss speaks out of character — he's pedantic in his profile."]
    assert r.suggestions[0].text == "Mara ran to the pier. Voss was waiting, of course."
    assert r.suggestions[0].why == "keeps her guarded voice."
    assert r.suggestions[1].text == "Mara ran.\nVersion 2 of the plan had failed."
    assert "thought" not in r.raw and "planning" not in r.raw


def test_unreadable_reply_is_empty():
    assert pc.parse_critique("Sorry, I can't help with that.").empty


class FakeLLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    def generate_text(self, prompt, system_prompt=None, **kw):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_tops_up_to_three_suggestions(project, chapter):
    first = CLEAN.split("SUGGESTION 2:")[0]
    llm = FakeLLM(first, "SUGGESTION 1:\nTwo.\nWHY: a\n\nSUGGESTION 2:\nThree.\nWHY: b")
    ctx = pc.build_context(project, chapter, TEXT, 0, 24)
    r = pc.critique_passage(llm, ctx)
    assert sorted(s.text for s in r.suggestions) == ["Mara sprinted for the pier.", "Three.", "Two."]
    assert "already suggested" in llm.prompts[1]


def test_drops_a_suggestion_identical_to_the_passage(project, chapter):
    reply = CLEAN.replace("Mara sprinted for the pier.", "The storm broke at dusk.")
    ctx = pc.build_context(project, chapter, TEXT, 0, 24)
    r = pc.critique_passage(FakeLLM(reply, "SUGGESTION 1:\nNew.\nWHY: x"), ctx)
    assert "The storm broke at dusk." not in [s.text for s in r.suggestions]


# ── Dialog + editor ───────────────────────────────────────────────

@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def run_now(reply_llm):
    """Worker factory that runs synchronously with a fake model."""
    from src.ui.passage_critique_dialog import SuggestionWorker

    class Now(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (reply_llm, ""),
                             search_factory=lambda p: None)

        def start(self):
            self.run()

    return Now


def test_dialog_shows_discussion_and_returns_edited_choice(app, project, chapter):
    from src.ui.passage_critique_dialog import PassageCritiqueDialog
    s, e = pc.expand_to_sentences(TEXT, *span("ran to the pier"))
    dlg = PassageCritiqueDialog(TEXT, s, e, project, chapter, selection=span("ran to the pier"),
                                worker_factory=run_now(FakeLLM(CLEAN)))
    assert "start of the sentence" in dlg.expanded_label.text()
    html = dlg.discussion.toHtml()
    assert "What works" in html and "told, not shown" in html
    assert dlg.suggestion_list.count() == 3
    dlg.suggestion_list.setCurrentRow(2)
    assert "salt in her mouth" in dlg.preview_edit.toPlainText()
    dlg.preview_edit.setPlainText("My own edit.")
    dlg._use_selected()
    assert dlg.replacement == "My own edit."


def test_dialog_reports_missing_model(app, project, chapter):
    from src.ui.passage_critique_dialog import PassageCritiqueDialog, SuggestionWorker

    class NoModel(SuggestionWorker):
        def __init__(self, *a):
            super().__init__(*a, llm_factory=lambda: (None, "No AI model is configured."))

        def start(self):
            self.run()

    dlg = PassageCritiqueDialog(TEXT, 0, 24, project, chapter, worker_factory=NoModel)
    assert "No AI model" in dlg.discussion.toPlainText()
    assert not dlg.use_btn.isEnabled()


def test_editor_replaces_the_whole_sentences(app, project, chapter, monkeypatch):
    from PyQt6.QtGui import QTextCursor
    from PyQt6.QtWidgets import QDialog
    from src.ui import passage_critique_dialog as pd
    from src.ui.manuscript_editor import ChapterEditor

    seen = {}

    class Accepting:
        def __init__(self, text, start, end, *a, **k):
            seen["passage"] = text[start:end]
            self.replacement = "Mara walked to the pier."

        def exec(self):
            return QDialog.DialogCode.Accepted

    monkeypatch.setattr(pd, "PassageCritiqueDialog", Accepting)
    chapter.content = "🔥 " + TEXT          # emoji: Qt and Python positions differ
    ed = ChapterEditor(chapter, project=project)
    doc = ed.editor.toPlainText()
    i = doc.index("ran to the pier")
    cursor = ed.editor.textCursor()
    cursor.setPosition(pc.py_to_qt_index(doc, i))
    cursor.setPosition(pc.py_to_qt_index(doc, i + len("ran to")), QTextCursor.MoveMode.KeepAnchor)
    ed.editor.setTextCursor(cursor)
    ed._suggest_for_selection()
    assert seen["passage"] == "Mara ran to the pier, where Dr. Voss waited."
    assert ed.editor.toPlainText() == doc.replace(seen["passage"], "Mara walked to the pier.")


def test_context_menu_offers_suggestions(app, project, chapter, monkeypatch):
    from PyQt6.QtWidgets import QMenu
    from src.ui.manuscript_editor import ChapterEditor
    ed = ChapterEditor(chapter, project=project)
    cursor = ed.editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(10, cursor.MoveMode.KeepAnchor)
    ed.editor.setTextCursor(cursor)
    labels = []
    monkeypatch.setattr(QMenu, "exec", lambda self, *a: labels.extend(
        x.text() for x in self.actions()))
    ed._show_context_menu(ed.editor.rect().center())
    assert any(label.startswith("💡 Suggestions") for label in labels)


# ── Order, and not retelling earlier text ─────────────────────────

SCENE = ("The patrol boat swung its lamp across the harbor. Mara crouched behind the crates "
         "and held her breath until the light passed.\n\n"
         "Mara held her breath behind the crates while the lamp passed over. She flinched at "
         "the gunshot. A shot cracked across the water. Tobin cursed.")


def scene_ctx():
    s = SCENE.index("Mara held her breath behind")
    e = SCENE.index(" Tobin cursed.")
    return pc.build_context(None, None, SCENE, s, e)


def test_passage_is_marked_in_place_and_numbered():
    ctx = scene_ctx()
    prompt = pc.build_prompt(ctx)
    assert "⟦PASSAGE START⟧ Mara held her breath behind" in prompt
    assert "gunshot. A shot cracked across the water. ⟦PASSAGE END⟧" in prompt
    assert "[2] She flinched at the gunshot." in prompt and "[3] A shot cracked" in prompt
    assert "ORDER AND FLOW" in prompt and "reacts after" in prompt
    assert "CHAPTER TEXT BEFORE" not in prompt


def test_scan_notices_the_passage_retelling_earlier_text():
    ctx = scene_ctx()
    assert len(ctx.observations) == 1 and ctx.observations[0].startswith("Sentence [1]")
    assert "already noticed".upper() in pc.build_prompt(ctx).upper()


def test_order_section_is_parsed_and_scan_notes_kept():
    ctx = scene_ctx()
    reply = ("WHAT WORKS:\n- Tense.\n\n**Order and flow:**\n- [2] reacts to the shot before "
             "[3] fires it — swap them.\n\nSUGGESTION 1:\nA shot cracked across the water. "
             "Mara flinched behind the crates.\nWHY: cause first.")
    llm = type("L", (), {"generate_text": lambda self, *a, **k: reply})()
    r = pc.critique_passage(llm, ctx)
    assert r.order[0].startswith("[2] reacts to the shot")
    assert any(o.startswith("Sentence [1] largely restates") for o in r.order)


def test_rewrite_that_retells_earlier_text_is_flagged():
    from src.ai.rewrite_quality import check_rewrite
    ctx = scene_ctx()
    retold = ("The patrol boat's lamp swept over the harbor and Mara hid behind the crates. "
              "A shot cracked across the water and she flinched.")
    fixed = "A shot cracked across the water. Mara flinched and pressed lower behind the crates."
    bad = check_rewrite(ctx.passage, retold, before=ctx.before, after=ctx.after)
    assert any("retells" in p for p in bad.serious), bad.serious
    assert check_rewrite(ctx.passage, fixed, before=ctx.before, after=ctx.after).ok


def test_similarity_catches_paraphrase_not_just_copying():
    from src.ai.rewrite_quality import similarity
    assert similarity("The patrol boat swung its lamp across the harbor.",
                      "Across the harbor, the patrol boat's lamp swung.") >= 0.6
    assert similarity("The patrol boat swung its lamp across the harbor.",
                      "Tobin cursed and reached for the oars.") < 0.3


def test_sharing_names_and_places_is_not_retelling():
    from src.ai.rewrite_quality import restated_sentences
    earlier = "Mara crouched behind the crates and held her breath until the light passed."
    assert restated_sentences("Mara pressed against the crates, listening.", earlier) == []
    assert restated_sentences("Tobin and Mara argued about the crates for an hour.", earlier) == []
