"""Run a critique in parts: one report for one chapter at a time.

``run_in_parts`` does what ``CritiqueOrchestrator.run`` does, but
report by report, so:

* **results arrive as they are ready:** ``on_part(report)`` gets a copy of
  the report so far after each part;
* **it can stop:** ``stop()`` is checked between parts; what is finished
  is kept, and the report is marked ``stopped``;
* **a stopped run resumes:** each report a model wrote is kept
  (``critique_resume``) and reused by the next run with the same chapter
  text, report, model and settings. A run that completes empties the store,
  so a fresh run always gets fresh reports.

The reports themselves are made exactly as before (``run_chapter``).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, List, Optional

from src.ai.chapter_analysis_agent import (
    ChapterReport, CritiqueReport, ReportSection, ReportType, resolve_genre_profile,
)


# ── A section as stored data (the saved-critique format) ───────────────

def section_to_dict(s: ReportSection) -> Dict[str, Any]:
    return {
        "report_type": s.report_type.value,
        "summary": s.summary,
        "narrative": s.narrative,
        "metrics": s.metrics,
        "findings": s.findings,
        "suggestions": s.suggestions,
        "strengths": s.strengths,
        "major_issues": s.major_issues,
        "minor_issues": s.minor_issues,
        "extra_lists": s.extra_lists,
        "prompt": s.prompt,
        "system_prompt": s.system_prompt,
        "calls": s.calls,
        "item_sources": s.item_sources,
    }


def section_from_dict(s: Dict[str, Any], chapter_title: str = "",
                      chapter_index: int = 0) -> ReportSection:
    try:
        rt = ReportType(s.get("report_type", "style"))
    except ValueError:
        rt = ReportType.STYLE
    return ReportSection(
        report_type=rt,
        chapter_title=chapter_title,
        chapter_index=chapter_index,
        summary=s.get("summary", ""),
        narrative=s.get("narrative", ""),
        metrics=s.get("metrics", {}) or {},
        findings=s.get("findings", []) or [],
        suggestions=s.get("suggestions", []) or [],
        strengths=s.get("strengths", []) or [],
        major_issues=s.get("major_issues", []) or [],
        minor_issues=s.get("minor_issues", []) or [],
        extra_lists=s.get("extra_lists", {}) or {},
        prompt=s.get("prompt", "") or "",
        system_prompt=s.get("system_prompt", "") or "",
        calls=s.get("calls", []) or [],
        item_sources=s.get("item_sources", {}) or {},
    )


# ── Running ─────────────────────────────────────────────────────────────

def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _context_fields(critique_context: Any) -> Any:
    if critique_context is None:
        return None
    try:
        return asdict(critique_context) if is_dataclass(critique_context) else vars(critique_context)
    except Exception:
        return repr(critique_context)


def snapshot(report: CritiqueReport, extra: Optional[Dict[str, Any]] = None) -> CritiqueReport:
    """A copy safe to hand to the screen while the run goes on."""
    copy = CritiqueReport(
        chapters=[ChapterReport(chapter_title=c.chapter_title, chapter_index=c.chapter_index,
                                word_count=c.word_count, sections=list(c.sections),
                                entity_mentions=dict(c.entity_mentions))
                  for c in report.chapters],
        genre=report.genre, overall_summary=report.overall_summary, has_llm=report.has_llm,
        estimated_cost=report.estimated_cost)
    for name in ("parts_done", "parts_total", "parts_reused", "stopped", "partial"):
        setattr(copy, name, getattr(report, name, None))
    for name, value in (extra or {}).items():
        setattr(copy, name, value)
    return copy


def run_in_parts(orchestrator, chapters: List[Dict[str, Any]], report_types: List[ReportType],
                 genre_key_or_text: str, manuscript_context: str, critique_context=None,
                 progress_cb: Optional[Callable[[str], None]] = None,
                 on_part: Optional[Callable[[CritiqueReport], None]] = None,
                 stop: Optional[Callable[[], bool]] = None,
                 project: Any = None, model: str = "",
                 extra: Optional[Dict[str, Any]] = None) -> CritiqueReport:
    """The orchestrator's run, one report at a time (see the module notes).
    ``project`` and ``model`` enable resuming; ``extra`` attributes (scope
    label …) are put on every copy handed to ``on_part``."""
    from src.data import critique_resume as resume
    genre = resolve_genre_profile(genre_key_or_text)
    orchestrator._rag_cache.clear()
    orchestrator._rag_cache_hits = 0
    orchestrator._rag_cache_misses = 0
    report = CritiqueReport(chapters=[], genre=genre,
                            has_llm=orchestrator.primary_llm is not None)
    runnable = [ch for ch in chapters if (ch.get("text") or "").strip()]
    report.parts_total = len(runnable) * len(report_types)
    report.parts_done = 0
    report.parts_reused = 0
    report.stopped = False
    report.partial = True
    can_resume = project is not None and orchestrator.primary_llm is not None and bool(model)
    voice = orchestrator.writer_voice
    shared = {
        "model": model, "genre": genre.key, "context": _context_fields(critique_context),
        "manuscript": _digest(manuscript_context),
        "voice": voice.to_critique_prompt() if voice is not None else "",
    }
    for ch in chapters:
        title = ch.get("title", "Untitled")
        index = ch.get("index", 0)
        text = ch.get("text", "") or ""
        cr = ChapterReport(chapter_title=title, chapter_index=index,
                           word_count=len(text.split()) if text else 0)
        report.chapters.append(cr)
        if not text.strip():
            continue
        if progress_cb:
            progress_cb(f"Analyzing chapter: {title}")
        for rt in report_types:
            if stop is not None and stop():
                report.stopped = True
                break
            key = resume.part_key(text=_digest(text), report=rt.value, title=title, **shared)
            kept = resume.get(project, key) if can_resume else None
            section = None
            if kept is not None:
                section = section_from_dict(kept["section"], title, index)
                for ent in kept.get("entities") or []:
                    k = tuple(ent)
                    cr.entity_mentions[k] = cr.entity_mentions.get(k, 0) + 1
                report.parts_reused += 1
                if progress_cb:
                    progress_cb(f"  {title}: {rt.value} report kept from the stopped run")
            else:
                part = orchestrator.run_chapter(
                    chapter_text=text, chapter_title=title, chapter_index=index,
                    report_types=[rt], genre=genre, manuscript_context=manuscript_context,
                    critique_context=critique_context, progress_cb=progress_cb)
                for k, n in part.entity_mentions.items():
                    cr.entity_mentions[k] = cr.entity_mentions.get(k, 0) + n
                section = part.sections[0] if part.sections else None
                if (section is not None and can_resume and (section.narrative or "").strip()
                        and not any(str(f).startswith(("(analysis error", "(narrative skipped"))
                                    for f in section.findings)):
                    resume.put(project, key, section_to_dict(section), part.entity_mentions.keys())
            if section is not None:
                cr.sections.append(section)
            report.parts_done += 1
            if on_part is not None:
                if progress_cb:
                    progress_cb(f"{report.parts_done} of {report.parts_total} reports ready")
                on_part(snapshot(report, extra))
        if report.stopped:
            break
    report.partial = False
    if report.stopped or orchestrator.primary_llm is None or not runnable:
        summary = orchestrator._dashboard_summary(report)
        if report.stopped:
            summary = (f"Stopped after {report.parts_done} of {report.parts_total} reports. "
                       "Run Critique again with the same settings to finish: the finished "
                       "reports are kept and reused.\n\n" + summary)
        report.overall_summary = summary
    else:
        if progress_cb:
            progress_cb("Composing overall summary…")
        report.overall_summary = orchestrator._build_overall_summary(report)
        report.overall_prompt = getattr(orchestrator, "_overall_prompt", "")
        report.overall_system = getattr(orchestrator, "_overall_system", "")
    return report


def finished(project: Any, report: CritiqueReport) -> None:
    """Called when a run completes: nothing is left to resume."""
    if not getattr(report, "stopped", False):
        from src.data import critique_resume as resume
        resume.clear(project)
