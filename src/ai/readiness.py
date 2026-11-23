"""The readiness engine (piece 1.2b; design in 1.2a).

For each chapter of a manuscript, every registered check gives a
``CheckResult``: a status (ready, needs work, problem …), a count, and the
items found. A ``BookReport`` gathers a manuscript's chapters and one
figure, "ready for readers". Checks live in ``src/ai/readiness_checks/``;
adding one is one decorated function there.

* **Per manuscript.** ``scope`` is None for the main manuscript or a
  novella's id; ``project_report`` lists them all.
* **Counts what the editor shows.** Spelling and grammar come from the
  editor's own rules (``editor_flags``, R.6), with the project's names,
  dictionary and style sheet, and run without a window on any thread.
* **Cached** in ``readiness.json`` (``readiness_state``): a chapter's result
  for a check is reused while its text, the check's version, the settings
  that affect it and the tier are unchanged.
* **Never raises.** A check that fails is "could not check"; the rest of
  the report carries on.
* **Writes nothing but ``readiness.json``.**
* Scan tier only for now: checks that need a model show what the scan
  found and are left out of the figure (model judging arrives in 1.7).
"""

from __future__ import annotations

import hashlib
import time
import traceback
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

STAGES = ("structure", "scene", "line", "copyedit", "proof")
STAGE_LABELS = {"structure": "Structure", "scene": "Scene", "line": "Line",
                "copyedit": "Copyedit", "proof": "Proof", "info": "Information"}
FIGURE_VERSION = 1
THRESHOLDS_VERSION = 2
MAX_ITEMS = 80                   # kept per check per chapter; the count stays exact
_UNSET = object()


class Status:
    READY = "ready"
    NEEDS_WORK = "needs_work"
    PROBLEM = "problem"
    COULD_NOT_CHECK = "could_not_check"
    NEEDS_MODEL = "needs_model"
    INFO = "info"
    ALL = (READY, NEEDS_WORK, PROBLEM, COULD_NOT_CHECK, NEEDS_MODEL, INFO)
    VERDICTS = (READY, NEEDS_WORK, PROBLEM)          # the ones the figure counts
    LABELS = {READY: "Ready", NEEDS_WORK: "Needs work", PROBLEM: "Problem",
              COULD_NOT_CHECK: "Could not check", NEEDS_MODEL: "Needs a model",
              INFO: "Information"}


def _from_dict(cls, data: Dict[str, Any]):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in (data or {}).items() if k in names})


# ── Data ───────────────────────────────────────────────────────────────

@dataclass
class Item:
    start: int
    end: int
    text: str
    reason: str
    kind: str = ""
    key: str = ""
    suggestions: List[str] = field(default_factory=list)
    verdict: str = ""               # "" not judged | "problem" | "cleared" (1.7)
    chapter_id: str = ""
    paragraph: int = -1             # line number in the chapter text
    dismissed: bool = False         # set when the report is assembled (3.3)

    def to_dict(self) -> Dict[str, Any]:
        """Only what differs from the defaults (the file stays small)."""
        d = asdict(self)
        d.pop("dismissed", None)
        defaults = {"kind": "", "key": "", "suggestions": [], "verdict": "",
                    "chapter_id": "", "paragraph": -1}
        return {k: v for k, v in d.items() if k not in defaults or v != defaults[k]}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Item":
        return _from_dict(cls, data)


@dataclass
class CheckResult:
    check: str
    stage: str
    status: str
    count: int
    items: List[Item] = field(default_factory=list)
    measure: Optional[float] = None
    message: str = ""
    judged: bool = False
    version: int = 1
    error: str = ""
    found: int = 0                  # every item found, before cleared and dismissed

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["items"] = [i.to_dict() for i in self.items]
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckResult":
        r = _from_dict(cls, data)
        r.items = [Item.from_dict(i) for i in (data.get("items") or []) if isinstance(i, dict)]
        if r.status not in Status.ALL:
            r.status = Status.COULD_NOT_CHECK       # a newer app's status
        return r


@dataclass
class ChapterReport:
    scope: Optional[str]
    chapter_id: str
    number: int
    title: str
    words: int
    text_hash: str
    results: Dict[str, CheckResult] = field(default_factory=dict)
    stage: str = ""
    is_opening: bool = False
    judged: bool = False
    made_at: str = ""
    from_cache: int = 0             # how many results came from the cache
    saved: bool = True              # False when the readiness file could not be written
    # Results made in this run but not yet written (save=False); the caller
    # writes them in a batch.
    pending: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class BookReport:
    scope: Optional[str]
    name: str
    kind: str
    chapters: List[ChapterReport] = field(default_factory=list)
    book_results: Dict[str, CheckResult] = field(default_factory=dict)
    info: Dict[str, Any] = field(default_factory=dict)
    readiness: float = 0.0
    cells: int = 0                  # cells in the figure
    counted: List[str] = field(default_factory=list)
    left_out: Dict[str, str] = field(default_factory=dict)
    tier: str = "scan"
    made_at: str = ""
    complete: bool = True           # False when stopped part way
    saved: bool = True              # False when the readiness file could not be written


# ── The registry ───────────────────────────────────────────────────────

@dataclass
class Threshold:
    per_1000: Optional[Tuple[float, float]] = None   # (needs work above, problem above)
    count: Optional[Tuple[int, int]] = None

    def describe(self) -> str:
        if self.per_1000:
            a, b = self.per_1000
            return (f"Ready at {a:g} or fewer per 1,000 words; a problem above {b:g}.")
        if self.count:
            a, b = self.count
            return f"Ready at {a} or fewer; a problem above {b}."
        return ""


# Every check's threshold, in one place (per 1,000 words unless a count).
# The line-check figures were set from the Q.1 benchmark's published prose:
# "needs work" starts a little above what published books show, so a
# published chapter reads as ready (P.3 replaces these with genre figures,
# P.5 retunes them as the checks improve). Changing any figure: raise
# THRESHOLDS_VERSION so cached results are recomputed.
THRESHOLDS: Dict[str, "Threshold"] = {}


def _thresholds() -> Dict[str, "Threshold"]:
    if not THRESHOLDS:
        T = Threshold
        THRESHOLDS.update({
            # Copyedit
            "spelling_grammar": T(per_1000=(0.5, 2.0)),   # flags left: fix or add to dictionary
            "consistency": T(count=(1, 3)),               # inconsistencies, each counted once
            "style_sheet": T(count=(0, 2)),
            # Line: "needs work" just above published chapters' 90th
            # percentile (scripts/calibrate_readiness.py, 29 chapters).
            "overdescribed": T(per_1000=(7.5, 12.0)),     # model-judged (1.7); scan: not counted
            "repetition": T(per_1000=(8.0, 16.0)),        # model-judged (1.7); scan: not counted
            "echoes": T(per_1000=(9.0, 14.0)),
            "filler": T(per_1000=(6.0, 10.0)),
            "passive": T(per_1000=(6.5, 10.0)),
            "adverbs": T(per_1000=(16.0, 24.0)),
            "cliches": T(per_1000=(0.6, 1.5)),
            "sticky": T(per_1000=(40.0, 55.0)),
            # Scene
            "dialogue_fit": T(count=(1, 4)),
            "dialogue_problems": T(per_1000=(7.0, 10.0)),
            # Structure
            "pacing": T(count=(1, 2)),                    # genre risks: one is common
            "subplots": T(count=(0, 2)),
        })
    return THRESHOLDS


@dataclass
class CheckOutput:
    items: List[Item] = field(default_factory=list)
    measure: Optional[float] = None
    status: Optional[str] = None
    message: str = ""


@dataclass
class CheckSpec:
    name: str
    stage: str
    label: str
    fn: Callable[["CheckContext"], CheckOutput]
    level: str = "chapter"
    needs_model: bool = False
    counts: bool = True
    threshold: Optional[Threshold] = None
    version: int = 1
    description: str = ""
    weight: int = 50                # for the fix queue (3.2)
    # A chapter check whose result depends on the other chapters too
    # (consistency across the book): its cache key includes them all. For a
    # whole-book check, it means it looks across every manuscript
    # (continuity across novellas): its key includes them all.
    book_wide: bool = False
    display: str = "count"          # what a cell shows: "count", or "measure" (a score)


REGISTRY: Dict[str, CheckSpec] = {}

# A check returns this when it doesn't apply (no novellas to compare, …):
# no cell is shown for it.
NOT_APPLICABLE = object()


def check(*, name: str, stage: str, label: str, level: str = "chapter",
          needs_model: bool = False, counts: bool = True,
          threshold: Optional[Threshold] = None, version: int = 1,
          description: str = "", weight: int = 50, book_wide: bool = False,
          display: str = "count"):
    """Register a readiness check: one decorated function. Its threshold
    normally lives in ``THRESHOLDS`` (one table for every check)."""
    def register(fn):
        REGISTRY[name] = CheckSpec(name, stage, label, fn, level, needs_model, counts,
                                   threshold, version, description, weight, book_wide,
                                   display)
        return fn
    return register


def _load_checks() -> None:
    import src.ai.readiness_checks  # noqa: F401 — registers the checks


def checks_for(stage: Optional[str] = None, level: Optional[str] = None) -> List[CheckSpec]:
    _load_checks()
    specs = list(REGISTRY.values())
    specs.sort(key=lambda s: (STAGES.index(s.stage) if s.stage in STAGES else len(STAGES)))
    return [s for s in specs if (stage is None or s.stage == stage)
            and (level is None or s.level == level)]


# ── The context a check sees ───────────────────────────────────────────

class Scanner:
    """The editor's rules for one project, shared by every chapter of a run:
    one spell checker with the project's names, one overuse detector, the
    style sheet. ``base`` (an editor's highlighter) lends its ignored words
    and LanguageTool results; build it on the GUI thread, then use it
    anywhere."""

    def __init__(self, project: Any, base: Any = None, languagetool: Optional[bool] = None):
        from src.utils.editor_flags import allowed_words, project_vocabulary, state_for_project
        self.project = project
        self.state = state_for_project(project, base)
        words, names = project_vocabulary(project)
        kept = []
        try:
            from src.ai.style_sheet import kept_kinds
            kept = sorted(kept_kinds(project))
        except Exception:
            pass
        self.vocabulary_hash = _hash("\n".join(sorted(words) + ["--"] + sorted(names) + ["--"]
                                               + allowed_words(project) + ["--"] + kept))
        self.languagetool = self._languagetool_ready() if languagetool is None else languagetool

    @staticmethod
    def _languagetool_ready() -> bool:
        """Use LanguageTool only when it is already running (the editor
        starts it); never start Java from here unasked."""
        try:
            from src.utils.proofing import LanguageToolEngine
            return LanguageToolEngine.get().status == "ready"
        except Exception:
            return False

    def flags(self, text: str):
        """[(paragraph offset, WritingError)] — what the editor would show."""
        st = self.state
        if self.languagetool:
            todo = [p for p in dict.fromkeys(text.split("\n")) if p.strip() and p not in st._lt_cache]
            if todo:
                try:
                    from src.utils.editor_flags import languagetool_issues
                    from src.utils.proofing import LanguageToolEngine
                    engine = LanguageToolEngine.get()
                    if engine.ensure_started():
                        st._lt_cache.update(languagetool_issues(todo, engine))
                except Exception as e:
                    print(f"[readiness] LanguageTool skipped: {e}")
        if st.overuse_detector is not None:
            st.overuse_detector.update_cache(text)
        st.update_full_text(text)
        return st.flags_for_text(text)


class Book:
    """One manuscript's chapters and texts, shared by every check in a run,
    with lazily computed scans that look across chapters."""

    def __init__(self, project, scope, texts: Optional[Dict[str, str]] = None):
        self.project, self.scope = project, scope
        ms = _manuscript(project, scope)
        self.chapters = list(getattr(ms, "chapters", None) or [])
        texts = texts or {}
        self.texts = {ch.id: (texts.get(ch.id) if texts.get(ch.id) is not None
                              else (getattr(ch, "content", "") or "")).replace("\r\n", "\n")
                      for ch in self.chapters}
        self.hash = _hash("|".join(f"{ch.id}:{text_hash(self.texts[ch.id])}"
                                   for ch in self.chapters))
        self._cache: Dict[str, Any] = {}

    def lazy(self, key, make):
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]

    def words(self) -> int:
        return sum(len(t.split()) for t in self.texts.values())

    def planning_hash(self) -> str:
        sp = getattr(self.project, "story_planning", None)
        try:
            blob = sp.model_dump_json() if hasattr(sp, "model_dump_json") else repr(sp)
        except Exception:
            blob = repr(sp)
        plans = []
        for ch in self.chapters:
            pl = getattr(ch, "planning", None)
            try:
                plans.append(pl.model_dump_json() if hasattr(pl, "model_dump_json") else repr(pl))
            except Exception:
                plans.append(repr(pl))
        return _hash(blob + "|" + "|".join(plans))


class CheckContext:
    def __init__(self, project, scope, chapter, text, *, is_opening, route, genre,
                 llm=None, scanner: Optional[Scanner] = None, book: Optional[Book] = None):
        self.project, self.scope, self.chapter, self.text = project, scope, chapter, text
        self.words = len(text.split())
        self.is_opening, self.route, self.genre, self.llm = is_opening, route, genre, llm
        self._scanner = scanner
        self._book = book
        self._cache: Dict[str, Any] = {}

    @property
    def book(self) -> Book:
        if self._book is None:
            self._book = Book(self.project, self.scope, {self.chapter.id: self.text})
        return self._book

    def _lazy(self, key, make):
        if key not in self._cache:
            self._cache[key] = make()
        return self._cache[key]

    def editor_flags(self):
        """[(absolute start, WritingError)] for the whole chapter."""
        def make():
            scanner = self._scanner or Scanner(self.project)
            return [(pos + e.start, e) for pos, e in scanner.flags(self.text)]
        return self._lazy("flags", make)

    def style_issues(self):
        from src.utils.style_checks import analyze_document
        return self._lazy("style", lambda: analyze_document(self.text))

    def style_flags(self):
        """[(absolute start, StyleIssue)]: the style flags the editor shows
        with every style check on: the writer's ignored flags, allowed
        words, kept kinds and the dialogue rule applied, preference (style
        sheet) breaks included."""
        def make():
            from src.utils.style_checks import KINDS
            scanner = self._scanner or Scanner(self.project)
            st = scanner.state
            saved = st._style_kinds
            st._style_kinds = set(KINDS) - {"preference"}
            out = []
            try:
                pos = 0
                for para in self.text.split("\n"):
                    if para.strip():
                        out.extend((pos + i.start, i) for i in st.style_issues_for(para))
                    pos += len(para) + 1
            finally:
                st._style_kinds = saved
            return out
        return self._lazy("style_flags", make)

    def names(self):
        """Characters (with their other names) of the project."""
        from src.ai.canon_index import character_alias_names
        chars = getattr(self.project, "characters", None) or []
        return [c.name for c in chars] + character_alias_names(chars)

    def overdescribed(self):
        from src.ai.overdescription import scan
        return self._lazy("overdescribed", lambda: scan(self.text))

    def stats(self):
        from src.utils.writing_stats import ProWritingAnalyzer
        return self._lazy("stats", lambda: ProWritingAnalyzer().analyze(self.text))

    def paragraph_of(self, pos: int) -> int:
        return self.text.count("\n", 0, max(0, pos))

    def threshold(self, name: str) -> Optional[Threshold]:
        """A check's threshold for this chapter. Route, the opening chapter
        (1.8) and genre baselines (P.3) adjust it here, and only here."""
        found = _thresholds().get(name)
        if found is not None:
            return found
        spec = REGISTRY.get(name)
        return spec.threshold if spec else None


class BookContext(CheckContext):
    """What a whole-book check sees: the manuscript, its chapter reports,
    the plan."""

    def __init__(self, project, scope, book: Book, chapter_reports, *, route, genre,
                 llm=None, scanner: Optional[Scanner] = None):
        super().__init__(project, scope, None, "", is_opening=False, route=route, genre=genre,
                         llm=llm, scanner=scanner, book=book)
        self.chapter_reports = chapter_reports
        self.words = book.words()
        self.planning = getattr(project, "story_planning", None)


# ── Running checks ─────────────────────────────────────────────────────

def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def text_hash(text: str) -> str:
    return _hash((text or "").replace("\r\n", "\n"))


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _status_from(threshold: Optional[Threshold], count: int, words: int) -> str:
    if threshold is None:
        return Status.READY if count == 0 else Status.NEEDS_WORK
    if threshold.per_1000:
        a, b = threshold.per_1000
        rate = count * 1000.0 / max(words, 1)
    elif threshold.count:
        a, b = threshold.count
        rate = count
    else:
        return Status.READY if count == 0 else Status.NEEDS_WORK
    if rate <= a:
        return Status.READY
    return Status.NEEDS_WORK if rate <= b else Status.PROBLEM


def _run_check(spec: CheckSpec, ctx: CheckContext) -> Optional[CheckResult]:
    """Run one check; never raises. The result is "raw": count and status
    before dismissals (applied in ``_finish``)."""
    try:
        out = spec.fn(ctx)
        if out is NOT_APPLICABLE:
            return None
        out = out or CheckOutput()
        items = list(out.items)
        live = [i for i in items if i.verdict != "cleared"]
        if spec.needs_model and ctx.llm is None:
            status = Status.NEEDS_MODEL
            message = out.message or (f"The scan found {len(live)} to look at; a model decides "
                                      "which count (not in the figure without one).")
        else:
            status = out.status or _status_from(ctx.threshold(spec.name), len(live), ctx.words)
            message = out.message
        # Fewer kept where there's little to do (the count stays exact).
        keep = {Status.READY: 25, Status.NEEDS_MODEL: 40}.get(status, MAX_ITEMS)
        return CheckResult(check=spec.name, stage=spec.stage, status=status, count=len(live),
                           items=items[:keep], measure=out.measure, message=message,
                           judged=False, version=spec.version, found=len(items))
    except Exception as e:
        print(f"[readiness] {spec.name} failed: {e}\n{traceback.format_exc(limit=3)}")
        return CheckResult(check=spec.name, stage=spec.stage, status=Status.COULD_NOT_CHECK,
                           count=0, message=f"Could not check: {e}", version=spec.version,
                           error=f"{type(e).__name__}: {e}")


def _finish(spec: CheckSpec, raw: CheckResult, words: int, dismissed: set,
            threshold: Optional[Threshold]) -> CheckResult:
    """Apply dismissals (they never invalidate the cache) and settle the
    status."""
    r = CheckResult.from_dict(raw.to_dict())
    if r.status in (Status.COULD_NOT_CHECK, Status.INFO):
        return r
    gone = 0
    for i in r.items:
        if i.key and i.key in dismissed:
            i.dismissed = True
            if i.verdict != "cleared":
                gone += 1
    r.count = max(0, raw.count - gone)
    if gone and r.status in Status.VERDICTS:
        r.status = _status_from(threshold, r.count, words)
    return r


def _context_fingerprint(route: str, genre: str, is_opening: bool, scanner: Scanner) -> str:
    return _hash("|".join([route, genre, str(is_opening), str(THRESHOLDS_VERSION),
                           scanner.vocabulary_hash, f"lt={scanner.languagetool}"]))


def _scope_of(project, chapter) -> Optional[str]:
    try:
        scope, _ = project.find_chapter_with_scope(chapter.id)
        return scope
    except Exception:
        return None


def _manuscript(project, scope):
    try:
        for s, ms in project.iter_manuscripts():
            if s == scope:
                return ms
    except Exception:
        pass
    return getattr(project, "manuscript", None) if scope is None else None


def chapter_report(project, chapter, *, scope=_UNSET, text=None, llm=None, use_cache=True,
                   checks: Optional[Sequence[str]] = None, scanner: Optional[Scanner] = None,
                   save: bool = True, _goal=None, _dismissed=None,
                   book: Optional[Book] = None) -> ChapterReport:
    """Every chapter-level check for one chapter. ``text`` is the live
    text for the open chapter (else ``chapter.content``)."""
    from src.data import readiness_state as rs
    if scope is _UNSET:
        scope = _scope_of(project, chapter)
    text = (chapter.content or "") if text is None else text
    text = text.replace("\r\n", "\n")
    ms = _manuscript(project, scope)
    chapters = list(getattr(ms, "chapters", None) or [])
    is_opening = bool(chapters) and getattr(chapters[0], "id", None) == chapter.id
    if _goal is None:
        from src.data.publishing_goal import publishing_goal
        _goal = publishing_goal(project, scope)
    scanner = scanner or Scanner(project)
    dismissed = rs.dismissed_keys(project) if _dismissed is None else _dismissed
    if book is None:
        book = Book(project, scope, {chapter.id: text})
    ctx = CheckContext(project, scope, chapter, text, is_opening=is_opening,
                       route=_goal.route, genre=_goal.genre, llm=llm, scanner=scanner, book=book)
    t_hash = text_hash(text)
    fingerprint = _context_fingerprint(_goal.route, _goal.genre, is_opening, scanner)
    tier = "scan" if llm is None else f"model:{getattr(llm, 'model', '') or 'model'}"
    stored = rs.stored_chapter(project, scope, chapter.id) if use_cache else {}
    stored_results = stored.get("results") if isinstance(stored.get("results"), dict) else {}
    report = ChapterReport(scope=scope, chapter_id=chapter.id,
                           number=int(getattr(chapter, "number", 0) or 0),
                           title=getattr(chapter, "title", "") or "", words=ctx.words,
                           text_hash=t_hash, is_opening=is_opening,
                           stage=str(stored.get("stage", "") or ""), made_at=_now())
    fresh: Dict[str, Any] = {}
    for spec in checks_for(level="chapter"):
        if checks is not None and spec.name not in checks:
            continue
        key = _hash("|".join([t_hash, spec.name, str(spec.version), fingerprint, tier]
                             + ([book.hash, book.planning_hash()] if spec.book_wide else [])))
        cached = stored_results.get(spec.name)
        if use_cache and isinstance(cached, dict) and cached.get("key") == key:
            raw = CheckResult.from_dict(cached)
            report.from_cache += 1
        else:
            raw = _run_check(spec, ctx)
            if raw is None:
                continue                                 # doesn't apply here
            if raw.status != Status.COULD_NOT_CHECK:
                fresh[spec.name] = dict(raw.to_dict(), key=key, tier=tier)
        report.results[spec.name] = _finish(spec, raw, ctx.words, dismissed,
                                            ctx.threshold(spec.name))
    report.judged = any(r.judged for r in report.results.values())
    if fresh:
        fields = {"text_hash": t_hash, "context": fingerprint, "made_at": report.made_at,
                  "results": fresh}
        if save:
            report.saved = rs.store_chapter(project, scope, chapter.id, fields)
        else:
            report.pending = fields
    return report


def readiness_figure(report: BookReport) -> float:
    """Ready cells score 1, needs work ½, a problem 0; the mean over every
    counted cell. 0 when nothing counts (see ``cells``)."""
    score, cells = _figure(report)
    return score


def _figure(report: BookReport) -> Tuple[float, int]:
    _load_checks()
    weights = {Status.READY: 1.0, Status.NEEDS_WORK: 0.5, Status.PROBLEM: 0.0}
    values = []
    for ch in report.chapters:
        for name, r in ch.results.items():
            spec = REGISTRY.get(name)
            if spec is not None and spec.counts and r.status in weights:
                values.append(weights[r.status])
    for name, r in report.book_results.items():
        spec = REGISTRY.get(name)
        if spec is not None and spec.counts and r.status in weights:
            values.append(weights[r.status])
    return (sum(values) / len(values) if values else 0.0), len(values)


def book_report(project, scope: Optional[str] = None, *, texts: Optional[Dict[str, str]] = None,
                llm=None, use_cache: bool = True, progress=None, stop=None,
                scanner: Optional[Scanner] = None) -> BookReport:
    """Every chapter of one manuscript, and its readiness figure. ``texts``
    maps chapter id → live text for open chapters. ``progress(done, total,
    title)`` and ``stop()`` serve a background run."""
    from src.data import readiness_state as rs
    from src.data.publishing_goal import publishing_goal
    goal = publishing_goal(project, scope)
    ms = _manuscript(project, scope)
    try:
        name = project.scope_label(scope)
    except Exception:
        name = goal.manuscript
    report = BookReport(scope=scope, name=name, kind=goal.kind, info={"length": goal},
                        tier="scan" if llm is None else "model", made_at=_now())
    chapters = list(getattr(ms, "chapters", None) or [])
    book = Book(project, scope, texts)
    scanner = scanner or (Scanner(project) if chapters else None)
    dismissed = rs.dismissed_keys(project)
    pending: Dict[str, Any] = {}
    last_write = time.monotonic()

    def write_pending():
        nonlocal last_write
        if pending:
            report.saved = rs.store_chapters(project, scope, dict(pending)) and report.saved
            pending.clear()
        last_write = time.monotonic()

    if chapters:
        for i, ch in enumerate(chapters):
            if stop is not None and stop():
                report.complete = False
                break
            if progress is not None:
                progress(i, len(chapters), getattr(ch, "title", "") or "")
            text = (texts or {}).get(ch.id)
            cr = chapter_report(project, ch, scope=scope, text=text, llm=llm,
                                use_cache=use_cache, scanner=scanner, _goal=goal,
                                _dismissed=dismissed, book=book, save=False)
            if cr.pending:
                pending[ch.id] = cr.pending
                cr.pending = {}
            report.chapters.append(cr)
            # Written every couple of seconds, so stopping or closing loses little.
            if time.monotonic() - last_write > 2.0:
                write_pending()
        write_pending()
        if progress is not None and report.complete:
            progress(len(chapters), len(chapters), "")
    if report.complete:
        _book_checks(project, scope, book, report, goal, llm, scanner, use_cache, dismissed)
    _load_checks()
    used = {n for ch in report.chapters for n in ch.results} | set(report.book_results)
    for name in used:
        spec = REGISTRY.get(name)
        statuses = {ch.results[name].status for ch in report.chapters if name in ch.results}
        if name in report.book_results:
            statuses.add(report.book_results[name].status)
        if spec is None:
            continue
        if not spec.counts:
            report.left_out[name] = "information only"
        elif statuses <= {Status.NEEDS_MODEL}:
            report.left_out[name] = "needs a model"
        elif statuses <= {Status.COULD_NOT_CHECK}:
            report.left_out[name] = "could not check"
        else:
            report.counted.append(name)
    report.counted.sort(key=lambda n: list(REGISTRY).index(n) if n in REGISTRY else 999)
    report.readiness, report.cells = _figure(report)
    return report


def _book_checks(project, scope, book: Book, report: BookReport, goal, llm, scanner,
                 use_cache: bool, dismissed) -> None:
    """Whole-book checks: cached on every chapter's text and the plan."""
    from src.data import readiness_state as rs
    specs = checks_for(level="book")
    if not specs:
        return
    bctx = BookContext(project, scope, book, report.chapters, route=goal.route,
                       genre=goal.genre, llm=llm, scanner=scanner)
    tier = "scan" if llm is None else f"model:{getattr(llm, 'model', '') or 'model'}"
    base = "|".join([book.hash, book.planning_hash(), goal.route, goal.genre,
                     str(THRESHOLDS_VERSION), tier])
    stored = (rs.stored_book(project, scope).get("results") or {}) if use_cache else {}
    fresh: Dict[str, Any] = {}
    project_hash = None
    for spec in specs:
        extra = ""
        if spec.book_wide:                       # looks across every manuscript
            if project_hash is None:
                project_hash = _project_hash(project, scope, book)
            extra = "|" + project_hash
        key = _hash(f"{base}|{spec.name}|{spec.version}{extra}")
        cached = stored.get(spec.name)
        if use_cache and isinstance(cached, dict) and cached.get("key") == key:
            if cached.get("not_applicable"):
                continue
            raw = CheckResult.from_dict(cached)
        else:
            raw = _run_check(spec, bctx)
            if raw is None:
                fresh[spec.name] = {"key": key, "not_applicable": True}
                continue
            if raw.status != Status.COULD_NOT_CHECK:
                fresh[spec.name] = dict(raw.to_dict(), key=key, tier=tier)
        report.book_results[spec.name] = _finish(spec, raw, bctx.words, dismissed,
                                                 bctx.threshold(spec.name))
    if fresh:
        report.saved = rs.store_book(project, scope, fresh) and report.saved


def _project_hash(project, scope, book: Book) -> str:
    """Every manuscript's chapters (this one's live texts included)."""
    parts = []
    try:
        for s, ms in project.iter_manuscripts():
            for ch in ms.chapters:
                text = book.texts.get(ch.id) if s == scope else (getattr(ch, "content", "") or "")
                parts.append(f"{s}:{ch.id}:{text_hash(text or '')}")
    except Exception:
        pass
    return _hash("|".join(parts))


def project_report(project, **kw) -> List[BookReport]:
    """One report per manuscript: the main one first, then each novella."""
    from src.data.publishing_goal import manuscripts
    return [book_report(project, scope, **kw) for scope, _name, _ms in manuscripts(project)]


# ── Helpers for the screens ────────────────────────────────────────────

@dataclass
class Grid:
    columns: List[CheckSpec]
    rows: List[Tuple[ChapterReport, List[Optional[CheckResult]]]]

    def stages(self) -> List[Tuple[str, List[CheckSpec]]]:
        """Columns grouped by stage, in stage order."""
        out: List[Tuple[str, List[CheckSpec]]] = []
        for spec in self.columns:
            if out and out[-1][0] == spec.stage:
                out[-1][1].append(spec)
            else:
                out.append((spec.stage, [spec]))
        return out


BOOK_ROW = "__book__"            # the chapter id of the "Whole manuscript" row


def book_row(book: BookReport) -> ChapterReport:
    """The whole-book results as one more row (its items name their chapters)."""
    words = sum(ch.words for ch in book.chapters)
    row = ChapterReport(scope=book.scope, chapter_id=BOOK_ROW, number=0,
                        title="Whole manuscript", words=words, text_hash="",
                        results=dict(book.book_results))
    return row


def grid(book: BookReport) -> Grid:
    """Chapters down the side, checks across (grouped by stage); whole-book
    checks have their cell on a last "Whole manuscript" row."""
    used = {n for ch in book.chapters for n in ch.results} | set(book.book_results)
    columns = [s for s in checks_for() if s.name in used]
    rows = [(ch, [ch.results.get(s.name) for s in columns]) for ch in book.chapters]
    if book.book_results and book.chapters:
        row = book_row(book)
        rows.append((row, [row.results.get(s.name) for s in columns]))
    return Grid(columns, rows)


def items_for(report: ChapterReport, check_name: str) -> List[Item]:
    r = report.results.get(check_name)
    return list(r.items) if r else []


def fix_candidates_for(report, stage: Optional[str] = None) -> List[Dict[str, Any]]:
    """Items as fix candidates, in the shape of ``companion.fix_candidates``
    (label, excerpt, sentence, weight, paragraph, kind, fixed), plus the
    chapter id. Accepts a ChapterReport or a BookReport."""
    _load_checks()
    chapters = report.chapters if isinstance(report, BookReport) else [report]
    out = []
    for ch in chapters:
        for name, r in ch.results.items():
            spec = REGISTRY.get(name)
            if spec is None or (stage is not None and spec.stage != stage):
                continue
            for i in r.items:
                if i.dismissed or i.verdict == "cleared":
                    continue
                out.append({"label": f"{spec.label}: “{i.text[:40]}” — {i.reason[:90]}",
                            "excerpt": i.text, "sentence": i.text, "weight": spec.weight,
                            "paragraph": i.paragraph, "kind": name,
                            "fixed": "", "chapter_id": ch.chapter_id,
                            "suggestions": list(i.suggestions)})
    out.sort(key=lambda c: -c["weight"])
    return out
