"""The editor's six Analyze ▾ analyses, as Critique reports (piece D.5).

Each Analyze ▾ entry now runs one or more reports on the current chapter in
the Critique, where the result is rated, saved, exported and kept in the
critique history. Existing reports are used where they cover the analysis;
where they cover less, the analysis keeps its own prompt as a new report
kind, so the writer never gets a weaker result than the old window gave:

=================================  ==========================================
Analyze ▾ entry                    Reports it runs
=================================  ==========================================
Promises & character consistency   Promises (new; the PromiseChecker, as before)
Prose — tone, style & voice        Prose profile fit (new; the old prompt)
Characters                         Characters, Character check (new; old prompt)
Worldbuilding                      Worldbuilding
Plot & pacing                      Plot, Pacing, Plot vs plan (new; old prompt)
Writing hints                      Writing hints (new)
=================================  ==========================================

**No model.** A new kind needs a model. Without one its tab says so in one
line and shows what the word scans offer (voice and style measures for the
prose, the style scan for hints, who appears for promises); the existing
reports run as their usual scans. No tab is ever empty.

**Stored apart.** The new kinds are their own enum, ``AnalysisKind``, not
new ``ReportType`` values. An older app parses a saved section's kind with
``ReportType(value)``; to keep it from misfiling one, saved critiques keep
new-kind sections under ``analysis_sections`` and the critique history keeps
them under ``analyses`` (see ``critique_parts.split_sections`` and
``critique_history.snapshot``). Older code reads only the keys it knows, so
it skips them; nothing it reads changes.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from src.ai.chapter_analysis_agent import (
    _ANALYZER_REGISTRY, _BaseAnalyzer, _attribute_items, CharacterAnalyzer,
    ReportSection, ReportType, StyleAnalyzer, VoiceAnalyzer, is_local_llm,
)
from src.ai import analysis_prompts as prompts


class AnalysisKind(Enum):
    """Report kinds added by D.5 (stored by ``.value``, like ReportType)."""
    PROMISES = "promises"
    PROSE_FIT = "prose_fit"
    CHARACTER_CHECK = "character_check"
    PLOT_PLAN = "plot_plan"
    HINTS = "hints"

    @property
    def kept_apart(self) -> bool:
        """Stored where an older app does not look (see the module notes)."""
        return True


LABELS: Dict[AnalysisKind, str] = {
    AnalysisKind.PROMISES: "Promises",
    AnalysisKind.PROSE_FIT: "Prose profile fit",
    AnalysisKind.CHARACTER_CHECK: "Character check",
    AnalysisKind.PLOT_PLAN: "Plot vs plan",
    AnalysisKind.HINTS: "Writing hints",
}

# Analyze ▾ entry → (label, reports to run: the familiar result first).
ITEMS: Dict[str, Tuple[str, List[Any]]] = {
    "promises": ("Promises & character consistency", [AnalysisKind.PROMISES]),
    "prose": ("Prose — tone, style & voice", [AnalysisKind.PROSE_FIT]),
    "characters": ("Characters", [AnalysisKind.CHARACTER_CHECK, ReportType.CHARACTER]),
    "world": ("Worldbuilding", [ReportType.WORLDBUILDING]),
    "plot": ("Plot & pacing", [AnalysisKind.PLOT_PLAN, ReportType.PLOT, ReportType.PACING]),
    "hints": ("Writing hints", [AnalysisKind.HINTS]),
}

RUN_KIND_PREFIX = "analysis:"
NO_MODEL = ("No model is set up, so {what} could not run. {shown} "
            "Add a model under Settings › AI Configuration or Local Models.")


def kind_for(value: str) -> Optional[AnalysisKind]:
    try:
        return AnalysisKind(value)
    except ValueError:
        return None


def is_kept_apart(report_type: Any) -> bool:
    return bool(getattr(report_type, "kept_apart", False))


def item_of(run_kind: str) -> str:
    """The Analyze ▾ entry a run was started from ("" for other runs)."""
    run_kind = run_kind or ""
    return run_kind[len(RUN_KIND_PREFIX):] if run_kind.startswith(RUN_KIND_PREFIX) else ""


def item_for_kind(kind: Any) -> str:
    """The Analyze ▾ entry whose main report this is ("" if none)."""
    return next((key for key, (_l, kinds) in ITEMS.items() if kinds and kinds[0] == kind), "")


def overall_summary(report: Any) -> str:
    """The Summary tab of an analysis run: its reports' own summaries (an
    analysis makes no extra model call for a roll-up, as before)."""
    lines = []
    for ch in getattr(report, "chapters", []) or []:
        for s in ch.sections:
            label = LABELS.get(s.report_type) or s.report_type.value.replace("_", " ").title()
            if (s.summary or "").strip():
                lines.append(f"- **{label}:** {s.summary.strip()}")
    return "\n".join(lines) or "No chapter text to analyse."


# ── The reports ────────────────────────────────────────────────────────

class _Analysis(_BaseAnalyzer):
    """One model call with the analysis's own prompt; a one-line notice and
    the related scans without a model."""
    max_tokens = 2048
    what = "this analysis"
    scans: Tuple[type, ...] = ()
    shown = "The scan below is what can be shown without one."
    system = ("You are an experienced fiction editor. Answer in Markdown with the "
              "sections asked for, and quote the chapter exactly when you cite it.")

    def run(self, text, chapter_title, chapter_index, genre, manuscript_context,
            rag_context, critique_context, llm) -> ReportSection:
        section = ReportSection(report_type=self.report_type, chapter_title=chapter_title,
                                chapter_index=chapter_index)
        self._chapter = self._find_chapter(chapter_title)
        if llm is None:
            self._scan(text, section, genre, critique_context)
            return section
        self.compact = is_local_llm(llm)
        self._llm = llm
        self._section = section
        try:
            self._ask(text, section, llm)
            _attribute_items(section)
        except Exception as e:                         # model errors land in the report
            section.summary = f"The model could not finish {self.what}: {e}"
            section.findings.append(f"(analysis error: {e})")
        if section.narrative:
            section.narrative = link_quotes(section.narrative, self._chapter, text)
        return section

    # Without a model ────────────────────────────────────────────────

    def _scan(self, text, section, genre, critique_context) -> None:
        section.summary = NO_MODEL.format(
            what=self.what, shown=self.shown if self.scans else "There is no scan for it.")
        for cls in self.scans:
            try:
                sub = cls(story_planning=self.story_planning, manuscript=self.manuscript,
                          project=self.project).run(
                    text, section.chapter_title, section.chapter_index, genre, "", "",
                    critique_context, None)
            except Exception as e:                    # pragma: no cover — defensive
                print(f"[analysis] scan failed: {e}")
                continue
            if sub.summary:
                section.findings.append(sub.summary)
            for name in ("strengths", "major_issues", "minor_issues", "findings", "suggestions"):
                getattr(section, name).extend(
                    x for x in getattr(sub, name) if x not in getattr(section, name))
            for k, v in (sub.metrics or {}).items():
                section.metrics.setdefault(k, v)
            for k, v in (sub.extra_lists or {}).items():
                section.extra_lists.setdefault(k, list(v))

    # With a model ───────────────────────────────────────────────────

    def prompt(self, text: str) -> Optional[str]:
        raise NotImplementedError

    missing = ""        # said when ``prompt`` returns None (nothing to check against)

    def _ask(self, text, section, llm) -> None:
        prompt = self.prompt(text)
        if prompt is None:
            section.summary = self.missing
            return
        from src.ai.editorial_standards import with_standards
        section.prompt = prompt
        section.system_prompt = with_standards(self.system, self.compact)
        section.narrative = self._generate(llm, prompt, self.system, self.max_tokens)
        self._record_call("Full report", "report", self.system, prompt, section.narrative)
        section.summary = _first_line(section.narrative)


class ProseFitAnalyzer(_Analysis):
    report_type = AnalysisKind.PROSE_FIT
    what = "the prose analysis (tone, style, voice, genre and fit with the Prose Profile)"
    scans = (VoiceAnalyzer, StyleAnalyzer)
    shown = "Below are the voice and style measures from the word scan."

    def prompt(self, text):
        return prompts.prose_prompt(self.project, text)


class CharacterCheckAnalyzer(_Analysis):
    report_type = AnalysisKind.CHARACTER_CHECK
    what = "the character check against the profiles"
    shown = "The Characters tab shows what the scan found."
    missing = "No characters are defined in the project yet. Add them in Story ▸ Characters."

    def _scan(self, text, section, genre, critique_context):
        section.summary = NO_MODEL.format(what=self.what, shown=self.shown)

    def prompt(self, text):
        return prompts.character_prompt(self.project, self._chapter, text)


class PlotPlanAnalyzer(_Analysis):
    report_type = AnalysisKind.PLOT_PLAN
    what = "the check against the story plan"
    shown = "The Plot and Pacing tabs show what the scans found."
    missing = ("No story plan or chapter plan is set yet. Add a main plot or events in "
               "Story ▸ Plot, or a plan for this chapter in Write's Planner.")

    def _scan(self, text, section, genre, critique_context):
        section.summary = NO_MODEL.format(what=self.what, shown=self.shown)

    def prompt(self, text):
        return prompts.plot_prompt(self.project, self._chapter, text)


class HintsAnalyzer(_Analysis):
    report_type = AnalysisKind.HINTS
    what = "the writing hints"
    scans = (StyleAnalyzer,)
    shown = "Below are the style scan's notes, which are hints of a plainer kind."

    def prompt(self, text):
        return prompts.hints_prompt(self.project, self._chapter, text)


class PromisesAnalyzer(_Analysis):
    """The PromiseChecker the old window ran, with its own prompt and parser."""
    report_type = AnalysisKind.PROMISES
    what = "the promise and character-consistency check"
    scans = (CharacterAnalyzer,)
    shown = "Below is who the scan found in the chapter."
    missing = ("No story promises or characters are defined yet. Add promises in "
               "Story ▸ Plot ▸ Promises and characters in Story ▸ Characters.")

    def _ask(self, text, section, llm) -> None:
        from src.ai.chapter_analysis_agent import PromiseChecker
        from src.ai.chat_actions import promise_check_inputs
        promises, characters, plot = promise_check_inputs(self.project)
        if not promises and not characters:
            section.summary = self.missing
            return
        recorder = _Recorder(llm)
        result = PromiseChecker(recorder).check_chapter(
            chapter_content=text, chapter_title=section.chapter_title,
            promises=promises, characters=characters, plot_outline=plot)
        if recorder.calls:
            prompt, system, output = recorder.calls[-1]
            section.prompt, section.system_prompt = prompt, system
            self._record_call("Promise check", "report", system, prompt, output)
        fill_promise_section(section, result)


class _Recorder:
    """Passes calls to the model and keeps them (for the training rows)."""

    def __init__(self, llm):
        self.llm = llm
        self.calls: List[Tuple[str, str, str]] = []

    def __getattr__(self, name):
        return getattr(self.llm, name)

    def generate_text(self, prompt, system_prompt="", **kw):
        out = self.llm.generate_text(prompt, system_prompt, **kw)
        text = out if isinstance(out, str) else str(out or "")
        if text.startswith("Error generating text:"):
            raise RuntimeError(text[len("Error generating text:"):].strip())
        self.calls.append((prompt, system_prompt, text))
        return out


_ADHERENCE = {"excellent": "✅", "good": "👍", "needs_attention": "⚠️", "problematic": "❌"}


def fill_promise_section(section: ReportSection, result: Any) -> None:
    """A PromiseCheckResult as a report: what the old window showed, as the
    narrative, plus rateable lists (major / minor issues, suggestions)."""
    adherence = (result.overall_adherence or "").replace("_", " ").title() or "Unknown"
    section.summary = f"Overall: {adherence}. {result.summary or ''}".strip()
    lines = [f"### {_ADHERENCE.get(result.overall_adherence, '📝')} Overall: {adherence}",
             result.summary or "", "",
             f"**Tone assessment:** {result.tone_assessment or '—'}", "",
             f"**Plot alignment:** {result.plot_alignment or '—'}", ""]
    if result.promise_violations:
        lines.append("#### ⚠️ Promise violations")
        for v in result.promise_violations:
            icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(v.severity, "⚪")
            lines.append(f"- {icon} **{v.promise_title}** ({v.promise_type})"
                         + (f" — “{v.quote}”" if v.quote else "")
                         + (f"  \n  Issue: {v.violation_description}" if v.violation_description else "")
                         + (f"  \n  💡 {v.suggestion}" if v.suggestion else ""))
            item = f"{v.promise_title} ({v.promise_type}): {v.violation_description}".strip()
            (section.minor_issues if v.severity == "low" else section.major_issues).append(item)
            if v.suggestion:
                section.suggestions.append(f"{v.promise_title}: {v.suggestion}")
    else:
        lines.append("✅ No promise violations detected")
        section.strengths.append("No promise violations detected.")
    lines.append("")
    if result.character_inconsistencies:
        lines.append("#### 👤 Character inconsistencies")
        for c in result.character_inconsistencies:
            lines.append(f"- **{c.character_name}** ({c.inconsistency_type})"
                         + (f" — “{c.quote}”" if c.quote else "")
                         + (f"  \n  Expected: {c.expected_behavior}" if c.expected_behavior else "")
                         + (f"  \n  💡 {c.suggestion}" if c.suggestion else ""))
            section.major_issues.append(
                f"{c.character_name} ({c.inconsistency_type}): {c.description or c.expected_behavior}")
            if c.suggestion:
                section.suggestions.append(f"{c.character_name}: {c.suggestion}")
    else:
        lines.append("✅ No character inconsistencies detected")
        section.strengths.append("No character inconsistencies detected.")
    section.narrative = "\n".join(lines).strip()


def _first_line(narrative: str) -> str:
    """A one-sentence summary from the model's answer, for the Summary tab and
    the history (the first line of prose under the first heading)."""
    for line in (narrative or "").splitlines():
        line = line.strip().lstrip("-*• ").strip()
        if line and not line.startswith("#") and len(line) > 20:
            line = line.replace("**", "")
            return line if len(line) <= 220 else line[:219].rstrip() + "…"
    return ""


def link_quotes(narrative: str, chapter: Any, text: str) -> str:
    """Put a "↗" link after each quote from the chapter (opens the chapter in
    Write with the passage selected, like the scorecard's Show in chapter)."""
    chapter_id = getattr(chapter, "id", "") or ""
    if not chapter_id or not text:
        return narrative
    try:
        from src.ai.text_links import add_passage_links
        return add_passage_links(narrative, [(chapter_id, getattr(chapter, "title", ""), text)],
                                 chapter_id, min_words=3)
    except Exception as e:                            # pragma: no cover — defensive
        print(f"[analysis] quote links failed: {e}")
        return narrative


for _cls in (PromisesAnalyzer, ProseFitAnalyzer, CharacterCheckAnalyzer, PlotPlanAnalyzer,
             HintsAnalyzer):
    _ANALYZER_REGISTRY.setdefault(_cls.report_type, _cls)
