"""AI features with novellas: chats/edits target the manuscript in focus;
worldbuilding and character analysis read every manuscript.

Run:
    python -m tests.test_subproject_ai_scope
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.models.project import Chapter, Character, Manuscript, WriterProject  # noqa: E402


def _project():
    p = WriterProject(name="U", manuscript=Manuscript(title="Book One"))
    m1 = Chapter(id="m1", number=1, title="Chapter 1")
    m1.content = "Aldric lit the brass lantern in the main book."
    p.manuscript.chapters.append(m1)
    p.characters.append(Character(id="c1", name="Aldric", character_type="protagonist",
                                  personality="stubborn"))
    sp = p.create_subproject("Rifle Creek")
    p.activate_subproject(sp.id)
    n1 = Chapter(id="n1", number=1, title="Chapter 1",
                 folder_root=p.manuscript.folder_root)
    n1.content = "Katherine carried the lantern up Rifle Creek in the novella."
    p.manuscript.chapters.append(n1)
    p.activate_subproject(None)
    return p, sp


def test_chapter_texts_all_vs_focus_and_unique_keys():
    p, sp = _project()
    all_texts = p.chapter_texts(all_manuscripts=True)
    assert set(all_texts) == {"Book One › Chapter 1", "Rifle Creek › Chapter 1"}
    assert "Katherine" in all_texts["Rifle Creek › Chapter 1"]
    assert list(p.chapter_texts(all_manuscripts=False)) == ["Book One › Chapter 1"]
    p.activate_subproject(sp.id)
    assert list(p.chapter_texts(all_manuscripts=False)) == ["Rifle Creek › Chapter 1"]
    assert len(p.chapter_texts()) == 2  # all, regardless of focus


def test_projects_without_novellas_keep_plain_titles():
    p = WriterProject(name="U", manuscript=Manuscript(title="Solo"))
    for i, t in enumerate(("Intro", "Intro"), 1):  # duplicate title
        ch = Chapter(id=f"c{i}", number=i, title=t)
        ch.content = f"text {i}"
        p.manuscript.chapters.append(ch)
    texts = p.chapter_texts()
    assert texts == {"Intro": "text 1", "Intro (2)": "text 2"}  # no overwrite


def test_all_chapters_in_reading_order():
    p, sp = _project()
    p.activate_subproject(sp.id)  # order doesn't depend on focus
    assert [(s, c.id) for s, c in p.all_chapters()] == [(None, "m1"), (sp.id, "n1")]
    assert p.chapter_label(sp.id, p.find_chapter("n1")) == "Rifle Creek › Chapter 1"


def test_rag_indexes_all_manuscripts_and_filters_by_focus():
    from src.ai.enhanced_rag import EnhancedRAGSystem
    p, sp = _project()
    rag = EnhancedRAGSystem(project=p)
    rag.rebuild_index()

    def chapter_hits():
        return sorted(r.metadata.get("chapter_id") for r in rag.search("lantern", top_k=10)
                      if r.metadata.get("chapter_id"))

    assert chapter_hits() == ["m1", "n1"]          # unfiltered: everything
    names = {r.source_name for r in rag.search("lantern", top_k=10)}
    assert any(n.startswith("Rifle Creek › ") for n in names), names
    rag.chapter_scope_filter = {""}                # main in focus
    assert chapter_hits() == ["m1"]
    rag.chapter_scope_filter = {sp.id}             # novella in focus
    assert chapter_hits() == ["n1"]
    # Shared material is never filtered.
    assert any(r.source_type == "character" for r in rag.search("Aldric stubborn", top_k=10))
    rag.chapter_scope_filter = None
    assert chapter_hits() == ["m1", "n1"]


def test_rag_without_novellas_is_unchanged():
    from src.ai.enhanced_rag import EnhancedRAGSystem
    p = WriterProject(name="U", manuscript=Manuscript(title="Solo"))
    ch = Chapter(id="c1", number=1, title="Intro")
    ch.content = "The lantern flickered."
    p.manuscript.chapters.append(ch)
    rag = EnhancedRAGSystem(project=p)
    rag.rebuild_index()
    hits = [r for r in rag.search("lantern", top_k=5) if r.metadata.get("chapter_id")]
    assert hits and hits[0].source_name == "Ch. 1: Intro"


def _run_all() -> int:
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"  FAIL {t.__name__}")
            traceback.print_exc()
    print()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
