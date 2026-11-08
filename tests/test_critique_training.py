"""Rating critique analyses (sections, parts, findings) into training rows,
the analysis-model picker resolution, and the critique training recipe."""

import json
import sqlite3
import tempfile
from pathlib import Path

import tests.test_critique_canon_reports as canon
from src.ai.chapter_analysis_agent import ReportType
from src.data import critique_training as ct
from src.data.rephrase_database import RephraseDatabase, SOURCE_CRITIQUE


def _meta(section):
    return {"report_type": section.report_type.value, "genre": "default",
            "genre_name": "General", "chapter_title": section.chapter_title,
            "project_path": "/p", "has_llm": True}


def _local_section(rt=ReportType.CHARACTER):
    return canon._run(rt, canon.LocalLLM())


def _tmp_db():
    return RephraseDatabase(Path(tempfile.mkdtemp()) / "t.db")


# ── Call capture on analyzers ─────────────────────────────────────

def test_local_run_records_each_focused_call():
    s = _local_section()
    kinds = {c["kind"] for c in s.calls}
    assert kinds == {"focused"}
    labels = [c["label"] for c in s.calls]
    assert "Mara" in labels and "Tobin" in labels and "unprofiled speakers" in labels
    mara = next(c for c in s.calls if c["label"] == "Mara")
    assert "CHARACTER RECORD" in mara["prompt"] and mara["system"]
    # Findings know which call produced them.
    drift = next(x for x in s.major_issues if x.startswith("Mara — Fears"))
    assert s.item_sources[drift] == mara["id"]


def test_cloud_run_records_report_and_repair_calls():
    class Forgetful(canon.FakeLLM):
        def generate_text(self, prompt, system, max_tokens=900, temperature=0.5, **kw):
            if prompt.startswith("Below is an editor's report"):
                return "- [DRIFT] Mara — Fears: dives in"
            return "## Mara\nShe dives in, against her fear of water."
    s = canon._run(ReportType.CHARACTER, Forgetful(""))
    assert [c["kind"] for c in s.calls] == ["report", "repair"]
    assert "CHARACTER RECORDS" in s.calls[0]["prompt"]


# ── Row building ──────────────────────────────────────────────────

def test_section_rows_one_per_call_with_exact_system_prompt():
    s = _local_section()
    rows = ct.section_rows(s, _meta(s), "good")
    assert len(rows) == len(s.calls)
    assert {r["source_text"] for r in rows} == {c["prompt"] for c in s.calls}
    assert all(r["system_prompt"] for r in rows)
    assert all("critique_unit=section" in r["notes"] and "local=1" in r["notes"] for r in rows)


def test_bad_items_are_curated_out_of_positive_rows():
    s = _local_section()
    drift = next(x for x in s.major_issues if x.startswith("Mara — Fears"))
    rows = ct.section_rows(s, _meta(s), "good", {drift: "bad"})
    mara = next(r for r in rows if "MARA APPEARS" in r["source_text"])
    assert "black sea" not in mara["output_text"] and "curated=1" in mara["notes"]
    # Negative ratings keep the full output (it's the rejected sample).
    bad_rows = ct.section_rows(s, _meta(s), "bad", {drift: "bad"})
    assert any("black sea" in r["output_text"] for r in bad_rows)


def test_parts_local_and_cloud():
    s = _local_section()
    parts = ct.iter_parts(s)
    assert [p.label for p in parts][:2] == ["Mara", "Tobin"] and all(p.real for p in parts)
    row = ct.part_rows(s, parts[0], _meta(s), "excellent")[0]
    assert row["source_text"] == parts[0].prompt and "critique_unit=part" in row["notes"]

    cloud = canon._run(ReportType.CHARACTER, canon.FakeLLM(
        "## Mara\nGood.\n\n## Ensemble\nFine.\n=== TAGGED SUMMARY ===\n- [ON TRACK] Mara — wry"))
    cparts = ct.iter_parts(cloud)
    assert [p.label for p in cparts] == ["Mara", "Ensemble"] and not cparts[0].real
    crow = ct.part_rows(cloud, cparts[1], _meta(cloud), "good")[0]
    assert 'Write ONLY the "Ensemble" section' in crow["source_text"]
    assert "prompt_kind=part_synthesised" in crow["notes"]


def test_item_rows_share_prompt_for_preference_pairs():
    s = canon._run(ReportType.WORLDBUILDING, canon.LocalLLM())
    good = ct.item_rows(s, "strengths", next(x for x in s.strengths if x.startswith("Greywater")),
                        _meta(s), "good")[0]
    bad = ct.item_rows(s, "major_issues", s.major_issues[-1], _meta(s), "bad")[0]
    assert good["output_text"].startswith("[ON TRACK] Greywater")
    assert bad["output_text"].startswith("[DIFFERS] ")       # worldbuilding tag
    # Same producing call + same list → same source_text (DPO pairing).
    other_good = ct.item_rows(s, "major_issues", s.major_issues[-1], _meta(s), "good")[0]
    assert other_good["source_text"] == bad["source_text"]


def test_legacy_section_without_calls_still_saves():
    s = _local_section()
    s.calls, s.item_sources, s.prompt = [], {}, ""
    rows = ct.section_rows(s, _meta(s), "good")
    assert len(rows) == 1 and "prompt_kind=dashboard_synthesised" in rows[0]["notes"]


# ── Database: system prompt column + export ───────────────────────

def test_system_prompt_column_migrates_and_exports():
    d = Path(tempfile.mkdtemp()) / "old.db"
    con = sqlite3.connect(d)
    con.execute("""CREATE TABLE rephrases (id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL, source_text TEXT NOT NULL, output_text TEXT NOT NULL,
        source_type TEXT DEFAULT 'rephrase', style TEXT DEFAULT '', voice TEXT DEFAULT '',
        surrounding_before TEXT DEFAULT '', surrounding_after TEXT DEFAULT '',
        character_name TEXT DEFAULT '', genre TEXT DEFAULT '', accepted INTEGER DEFAULT 1,
        rating TEXT DEFAULT 'neutral', project_path TEXT DEFAULT '', notes TEXT DEFAULT '')""")
    con.commit(); con.close()
    db = RephraseDatabase(d)
    s = _local_section()
    n = ct.save_rows(ct.section_rows(s, _meta(s), "good"), db, SOURCE_CRITIQUE)
    assert n == len(s.calls)
    out = Path(tempfile.mkdtemp()) / "x.jsonl"
    db.export_jsonl(out, fmt="chat", min_rating="good", source_types=[SOURCE_CRITIQUE])
    rows = [json.loads(l) for l in out.read_text().splitlines()]
    assert rows
    systems = {r["messages"][0]["content"] for r in rows}
    assert any("developmental editor checking one fictional character" in x for x in systems)
    assert all(r["messages"][1]["content"] for r in rows)


# ── UI: rating links save rows ────────────────────────────────────

def test_grader_rating_links_save_rows(monkeypatch):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    import src.data.rephrase_database as rdb
    from src.ai.chapter_analysis_agent import CritiqueOrchestrator
    from src.ui.grader_widget import GraderWidget
    db = _tmp_db()
    monkeypatch.setattr(rdb, "get_rephrase_database", lambda *a, **k: db)
    monkeypatch.setattr(rdb, "is_collection_enabled", lambda: True)

    w = GraderWidget()
    r = CritiqueOrchestrator(primary_llm=canon.LocalLLM(), project=canon._project()).run(
        chapters=[{"title": "Chapter 2", "text": canon.CHAPTER, "index": 1}],
        report_types=[ReportType.CHARACTER], genre_key_or_text="default", manuscript_context="")
    w._render_critique_report(r)
    sec = r.chapters[0].sections[0]
    html = w._format_section_html(sec)
    assert "rate-item:character-0:" in html and "rate-part:character-0:0:good" in html
    assert "rate-section:character-0:excellent" in html

    lists = list(ct.section_lists(sec).keys())
    drift_idx = sec.major_issues.index(next(x for x in sec.major_issues if x.startswith("Mara — Fears")))
    w._handle_rating_link(f"rate-item:character-0:{lists.index('major_issues')}:{drift_idx}:bad")
    w._handle_rating_link("rate-part:character-0:0:excellent")
    w._handle_rating_link("rate-section:character-0:good")
    rows = [dict(x) for x in db._conn().execute("SELECT * FROM rephrases").fetchall()]
    units = [ct_kv for ct_kv in (RephraseDatabase._parse_notes_kv(x["notes"]).get("critique_unit") for x in rows)]
    assert units.count("item") == 1 and units.count("part") == 1
    assert units.count("section") == len(sec.calls)
    assert all(x["source_type"] == SOURCE_CRITIQUE and x["system_prompt"] for x in rows)
    # The bad finding was curated out of the positive section rows.
    sec_rows = [x for x in rows if "critique_unit=section" in x["notes"] and "MARA APPEARS" in x["source_text"]]
    assert sec_rows and "black sea" not in sec_rows[0]["output_text"]
    assert "[rated bad]" in w._format_section_html(sec)

    # Saved critique round-trips calls so it can still be rated later.
    r2 = w._deserialize_report(w._serialize_report(r))
    assert r2.chapters[0].sections[0].calls == sec.calls


# ── Analysis model resolution + training recipe ───────────────────

def test_critique_model_resolution_order(monkeypatch):
    import src.ai.task_llm as tl
    import src.config.creativeos_config as cc
    built = []
    monkeypatch.setattr(tl, "build_llm_from_spec", lambda spec: built.append(spec) or f"llm:{spec}")
    monkeypatch.setattr(tl, "build_task_llm_override", lambda task: f"task:{task}")

    class Cfg:
        def __init__(self, d): self.d = d
        def get(self, k, default=None): return self.d.get(k, default)
    monkeypatch.setattr(cc, "get_creativeos_config", lambda: Cfg({"model_for_critique": "trained:crit"}))
    assert tl.build_critique_llm("mlx:gemma") == "llm:mlx:gemma"           # picker wins
    assert tl.build_critique_llm() == "llm:trained:crit"                   # task setting
    monkeypatch.setattr(cc, "get_creativeos_config", lambda: Cfg({"model_for_plot": "x"}))
    assert tl.build_critique_llm() == "task:plot"                          # legacy fallback
    monkeypatch.setattr(cc, "get_creativeos_config", lambda: Cfg({}))
    assert tl.build_critique_llm() is None                                 # global default
    assert "model_for_critique" in cc.TASK_MODEL_KEYS


def test_critique_training_recipe():
    from src.ai.model_builder_agent import build_recipe
    r = build_recipe("an editor that critiques my chapters and checks continuity",
                     use_llm=False, corpus_size=400)
    assert r.intent == "critique" and r.source_types == [SOURCE_CRITIQUE]
    assert r.export_format == "chat" and r.recommended_corpora == []
    assert build_recipe("x", goal_hint="critique", use_llm=False).intent == "critique"
