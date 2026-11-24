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
import re
import time
import traceback
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

STAGES = ("structure", "scene", "line", "copyedit", "proof")
STAGE_LABELS = {"structure": "Structure", "scene": "Scene", "line": "Line",
                "copyedit": "Copyedit", "proof": "Proof", "info": "Information"}
FIGURE_VERSION = 1
THRESHOLDS_VERSION = 5
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
    note: str = ""                  # the model's reason, when it judged the item (1.7)
    dismissed: bool = False         # set when the report is assembled (3.3)

    def to_dict(self) -> Dict[str, Any]:
        """Only what differs from the defaults (the file stays small)."""
        d = asdict(self)
        d.pop("dismissed", None)
        defaults = {"kind": "", "key": "", "suggestions": [], "verdict": "",
                    "chapter_id": "", "paragraph": -1, "note": ""}
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
    opening_results: Dict[str, CheckResult] = field(default_factory=dict)   # 1.8
    opening_words: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)   # daily figures (2.4)
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
            # The story's major issues (a model's findings, each quoted)
            "character_disconnects": T(count=(0, 2)),
            "plot_jumps": T(count=(0, 2)),
            "continuity": T(count=(0, 1)),
            # Scene
            "dialogue_fit": T(count=(1, 4)),
            "dialogue_problems": T(per_1000=(7.0, 10.0)),
            # Structure
            "pacing": T(count=(1, 2)),                    # genre risks: one is common
            "subplots": T(count=(0, 2)),
            # An editor's whole-book questions (from the chapter digests)
            "scene_purpose": T(count=(0, 2)),
            "pov_slips": T(count=(0, 2)),
            "loose_threads": T(count=(0, 2)),
            "character_threads": T(count=(0, 2)),
        })
    return THRESHOLDS


# How much tighter the opening chapter's line and copyedit thresholds are.
OPENING_STRICTNESS = {"agent": 0.75, "self": 0.9}   # a convention, not research
# Checks whose threshold depends on the route (the opening checks).
_ROUTE_THRESHOLDS: Dict[str, Dict[str, "Threshold"]] = {}


def _route_thresholds():
    if not _ROUTE_THRESHOLDS:
        T = Threshold
        _ROUTE_THRESHOLDS.update({
            # Words before the first dialogue or action.
            "first_action": {"agent": T(count=(300, 800)), "self": T(count=(500, 1200))},
            # Share of the opening (per 1,000 sentences, i.e. tenths of a percent) that
            # looks back before anything happens.
            "backstory": {"agent": T(per_1000=(150, 300)), "self": T(per_1000=(200, 400))},
            # Words into the manuscript before the plan's first event shows.
            "first_plot_event": {"agent": T(count=(10_000, 20_000)),
                                 "self": T(count=(12_000, 25_000))},
        })
    return _ROUTE_THRESHOLDS


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
    judge: bool = True              # a model judges its items (1.7)
    # Where it sits in the big picture: "major" (spelling and grammar,
    # character disconnects, plot jumps, continuity), "factor" (the other
    # things to settle before polish) or "polish" (style).
    tier: str = "factor"
    model_ready: bool = True        # False: a model can't settle it here yet (stays "needs a model")
    # Something else the result depends on, as a string that goes into the
    # cache key (the story checks: the earlier chapters' recorded facts).
    depends: Optional[Callable[["CheckContext"], str]] = None


REGISTRY: Dict[str, CheckSpec] = {}

# A check returns this when it doesn't apply (no novellas to compare, …):
# no cell is shown for it.
NOT_APPLICABLE = object()


def check(*, name: str, stage: str, label: str, level: str = "chapter",
          needs_model: bool = False, counts: bool = True,
          threshold: Optional[Threshold] = None, version: int = 1,
          description: str = "", weight: int = 50, book_wide: bool = False,
          display: str = "count", judge: bool = True, model_ready: bool = True,
          tier: str = "factor", depends=None):
    """Register a readiness check: one decorated function. Its threshold
    normally lives in ``THRESHOLDS`` (one table for every check)."""
    def register(fn):
        REGISTRY[name] = CheckSpec(name, stage, label, fn, level, needs_model, counts,
                                   threshold, version, description, weight, book_wide,
                                   display, judge, tier, model_ready, depends)
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
        from src.utils import spelling_varieties
        self.vocabulary_hash = _hash("\n".join(sorted(words) + ["--"] + sorted(names) + ["--"]
                                               + allowed_words(project) + ["--"] + kept
                                               + ["--", str(spelling_varieties.current())]))
        self.languagetool = self._languagetool_ready() if languagetool is None else languagetool
        from src.utils import proof_store
        proof_store.load(project)        # a model's stored corrections show as grammar flags

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
        spec = REGISTRY.get(name)
        route = self.route if self.route in OPENING_STRICTNESS else "agent"
        found = (_route_thresholds().get(name, {}).get(route) or _thresholds().get(name)
                 or (spec.threshold if spec else None))
        if found is None:
            return None
        if self.is_opening and spec is not None and spec.stage in ("line", "copyedit"):
            # The first pages are read hardest: a tighter bar, tightest for agents.
            f = OPENING_STRICTNESS[route]
            if found.per_1000:
                a, b = found.per_1000
                found = Threshold(per_1000=(round(a * f, 2), round(b * f, 2)))
            elif found.count:
                a, b = found.count
                found = Threshold(count=(int(a * f), max(int(a * f), int(b * f))))
        return found


OPENING_WORDS = 2_500          # about ten pages: what agents report reading first


class OpeningContext(CheckContext):
    """The opening pages: the first ~2,500 words, across chapters when the
    first is short. ``locate`` maps an offset to its chapter."""

    def __init__(self, project, scope, book: "Book", *, route, genre, llm=None,
                 scanner: Optional[Scanner] = None):
        parts, spans, words = [], [], 0
        pos = 0
        for ch in book.chapters:
            text = book.texts.get(ch.id, "")
            if not text.strip():
                continue
            take = text
            tokens = text.split()
            if words + len(tokens) > OPENING_WORDS:
                need = OPENING_WORDS - words
                m = re.match(r"(?:\S+\s+){%d}" % max(need, 1), text)
                take = text[:m.end()] if m else text
                cut = re.search(r"[.!?…][\"”’]?\s", text[len(take):])  # finish the sentence
                if cut:
                    take = text[:len(take) + cut.end()]
            parts.append(take)
            spans.append((pos, pos + len(take), ch.id))
            pos += len(take) + 2
            words += len(take.split())
            if words >= OPENING_WORDS:
                break
        super().__init__(project, scope, book.chapters[0] if book.chapters else None,
                         "\n\n".join(parts), is_opening=True, route=route, genre=genre,
                         llm=llm, scanner=scanner, book=book)
        self.spans = spans

    def locate(self, pos: int) -> Tuple[str, int]:
        """(chapter id, offset in that chapter) for an offset in the opening."""
        for start, end, cid in self.spans:
            if start <= pos <= end:
                return cid, pos - start
        return (self.spans[0][2], pos) if self.spans else ("", pos)


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
        if spec.needs_model and (ctx.llm is None or not spec.model_ready):
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
    raws: Dict[str, CheckResult] = {}
    model_failed = False
    to_judge: List[CheckSpec] = []
    keys: Dict[str, Tuple[str, str]] = {}
    for spec in checks_for(level="chapter"):
        if checks is not None and spec.name not in checks:
            continue
        base = [t_hash, spec.name, str(spec.version), fingerprint] + (
            [book.hash, book.planning_hash()] if spec.book_wide else []) + (
            [spec.depends(ctx)] if spec.depends else [])
        k_scan, k_judged = _hash("|".join(base + ["scan"])), _hash("|".join(base + ["judged"]))
        keys[spec.name] = (k_scan, k_judged)
        cached = stored_results.get(spec.name) if use_cache else None
        cached_key = cached.get("key") if isinstance(cached, dict) else None
        judgeable = llm is not None and spec.judge and spec.model_ready
        # A check the model produces itself (the story read): run it with the
        # model unless its model-made result is already stored.
        model_made = (llm is not None and spec.needs_model and spec.model_ready
                      and not spec.judge)
        if cached_key == k_judged:                      # a model judged it: best there is
            raw = CheckResult.from_dict(cached)
            report.from_cache += 1
        elif model_made:
            raw = _run_check(spec, ctx)
            if raw is None:
                continue
            if raw.status == Status.COULD_NOT_CHECK:
                model_failed = True                      # tried again next time
            else:
                raw.judged = True
                fresh[spec.name] = dict(raw.to_dict(), key=k_judged, tier=tier)
        elif cached_key == k_scan:
            raw = CheckResult.from_dict(cached)
            report.from_cache += 1
            if judgeable:
                to_judge.append(spec)
        else:
            raw = _run_check(spec, ctx)
            if raw is None:
                continue                                 # doesn't apply here
            if raw.status != Status.COULD_NOT_CHECK:
                fresh[spec.name] = dict(raw.to_dict(), key=k_scan, tier="scan")
                if judgeable:
                    to_judge.append(spec)
        raws[spec.name] = raw
    judged_all = None                     # every stage judged (None: no judging this time)
    if llm is not None and to_judge:
        judged_all = _judge_chapter(project, scope, text, llm, to_judge, raws, ctx, keys, fresh)
    elif llm is not None:
        judged_all = True                  # everything judgeable was already judged
    if judged_all and model_failed:
        judged_all = False
    for name, raw in raws.items():
        spec = REGISTRY[name]
        report.results[name] = _finish(spec, raw, ctx.words, dismissed, ctx.threshold(name))
    same_text = stored.get("text_hash") == t_hash
    report.judged = (judged_all if judged_all is not None
                     else bool(stored.get("judged")) and same_text)
    if fresh or (judged_all is not None and stored.get("judged") != judged_all):
        fields = {"text_hash": t_hash, "context": fingerprint, "made_at": report.made_at,
                  "results": fresh, "judged": bool(report.judged)}
        if save:
            report.saved = rs.store_chapter(project, scope, chapter.id, fields)
        else:
            report.pending = fields
    return report


def _judge_chapter(project, scope, text, llm, specs, raws, ctx, keys, fresh) -> bool:
    """One model request per stage; judged results replace the scan's and
    are cached under their own key. A stage whose request fails keeps the
    scan result (and is tried again next time)."""
    from src.ai import readiness_judge as rj
    compact = False
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        compact = bool(is_local_llm(llm))
    except Exception:
        pass
    context = rj.voice_block(project, scope)
    by_stage: Dict[str, List[CheckSpec]] = {}
    for spec in specs:
        if raws.get(spec.name) is not None and raws[spec.name].status != Status.COULD_NOT_CHECK:
            by_stage.setdefault(spec.stage, []).append(spec)
    tier = f"model:{getattr(llm, 'model', '') or 'model'}"
    all_ok = True
    for stage, stage_specs in by_stage.items():
        results = [(spec, raws[spec.name]) for spec in stage_specs]
        with_items = [(sp, r) for sp, r in results if any(i.end > i.start for i in r.items)]
        ok = True
        if with_items:
            ok = rj.judge_stage(llm, stage, with_items, text, context, compact) > 0
        if ok and stage == "copyedit":      # the model also proofreads (P.4)
            target = next((r for sp, r in results if sp.name == "spelling_grammar"), None)
            try:
                if target is not None:
                    from src.ai import proofread
                    proofread.add_findings(target, llm, text, ctx, compact)
            except Exception as e:
                print(f"[readiness] proofreading failed: {e}")
                ok = False
        if not ok:
            all_ok = False                 # tried again next time
            continue
        for spec, r in results:
            live = [i for i in r.items if i.verdict != "cleared"]
            cleared = len(r.items) - len(live)
            r.count = max(0, r.count - cleared)
            r.judged = True
            if r.status in Status.VERDICTS + (Status.NEEDS_MODEL,):
                r.status = _status_from(ctx.threshold(spec.name), r.count, ctx.words)
                r.message = (r.message if not r.message.startswith("The scan found") else "")
            if cleared:
                r.message = (r.message + " " if r.message else "") + \
                    f"The model cleared {cleared} of {len(r.items)} it judged."
            fresh[spec.name] = dict(r.to_dict(), key=keys[spec.name][1], tier=tier)
    return all_ok


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
    for name, r in list(report.book_results.items()) + list(report.opening_results.items()):
        spec = REGISTRY.get(name)
        if spec is not None and spec.counts and r.status in weights:
            values.append(weights[r.status])
    return (sum(values) / len(values) if values else 0.0), len(values)


def book_report(project, scope: Optional[str] = None, *, texts: Optional[Dict[str, str]] = None,
                llm=None, use_cache: bool = True, progress=None, stop=None,
                scanner: Optional[Scanner] = None, partial=None) -> BookReport:
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
            # Written every couple of seconds, or after every chapter when a model
            # is judging (each takes a while), so stopping or closing loses little.
            if llm is not None or time.monotonic() - last_write > 2.0:
                write_pending()
            if partial is not None:
                partial(_snapshot(report))
        write_pending()
        if progress is not None and report.complete:
            progress(len(chapters), len(chapters), "")
    if report.complete:
        _book_checks(project, scope, book, report, goal, llm, scanner, use_cache, dismissed)
        _book_checks(project, scope, book, report, goal, llm, scanner, use_cache, dismissed,
                     level="opening")
    _load_checks()
    used = ({n for ch in report.chapters for n in ch.results} | set(report.book_results)
            | set(report.opening_results))
    for name in used:
        spec = REGISTRY.get(name)
        statuses = {ch.results[name].status for ch in report.chapters if name in ch.results}
        for extra in (report.book_results, report.opening_results):
            if name in extra:
                statuses.add(extra[name].status)
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
    judged = [ch.judged for ch in report.chapters]
    report.tier = ("model" if judged and all(judged) else
                   "mixed" if any(judged) else "scan")
    report.readiness, report.cells = _figure(report)
    _record_history(project, scope, report)
    return report


def _snapshot(report: BookReport) -> BookReport:
    """A copy of a report in progress, safe to hand to the screen."""
    copy = BookReport(scope=report.scope, name=report.name, kind=report.kind,
                      chapters=list(report.chapters), info=dict(report.info),
                      tier=report.tier, made_at=report.made_at, complete=False)
    judged = [ch.judged for ch in copy.chapters]
    copy.tier = "model" if judged and all(judged) else "mixed" if any(judged) else "scan"
    copy.readiness, copy.cells = _figure(copy)
    return copy


def model_work(project, scope: Optional[str] = None,
               texts: Optional[Dict[str, str]] = None) -> Tuple[int, int]:
    """(chapters a model would judge, chapters in the manuscript): those
    whose text changed, or that no model has judged yet (for the estimate)."""
    from src.data import readiness_state as rs
    book = Book(project, scope, texts)
    from src.ai import chapter_digest, story_ledger
    ledger = story_ledger.for_book(book)
    digests = chapter_digest.for_book(book)
    todo = 0
    for ch in book.chapters:
        text = book.texts.get(ch.id, "")
        if not text.strip():
            continue
        stored = rs.stored_chapter(project, scope, ch.id)
        if (stored.get("text_hash") != text_hash(text) or not stored.get("judged")
                or not ledger.is_current(ch, text, text_hash(text))
                or digests.get(ch, text) is None):
            todo += 1         # changed, never judged, not outlined, or earlier facts changed
    return todo, len(book.chapters)


# ── The verdict: a finish line, not a score ───────────────────────────
#
# A percentage invites chasing 100%, which published books don't reach
# either. The headline is a verdict built on three tiers:
#
# 1. **Major issues**: errors a reader trips on. Spelling and grammar left,
#    character disconnects, plot jumps, continuity breaks (``tier="major"``).
# 2. **Other factors**: things to settle before polish. Pacing, dialogue,
#    the opening pages, consistency, subplots (``tier="factor"``).
# 3. **Polish**: style (``tier="polish"``). Never blocks.
#
# Why these: docs/publishing/background.md. The percentage stays, in the
# tooltip and the history.

TIERS = ("major", "factor", "polish")
TIER_LABELS = {"major": "Major issues", "factor": "Other factors", "polish": "Polish"}


@dataclass
class Verdict:
    level: str                       # "ready" | "nearly" | "revise" | "unchecked"
    title: str
    detail: str
    majors: int = 0                  # major-tier cells not ready
    factors: int = 0                 # other-factor cells at "problem"
    polish: int = 0                  # everything else not ready (optional)
    chapters: int = 0                # chapters with a major issue
    unread: List[str] = field(default_factory=list)   # major checks waiting for the model
    lines: Dict[str, List[str]] = field(default_factory=dict)   # tier → what's there


def _cells(report: BookReport):
    """(row id, check name, result) for every cell of a counted check."""
    _load_checks()
    rows = [(ch.chapter_id, ch.results) for ch in report.chapters]
    rows.append((BOOK_ROW, report.book_results))
    rows.append((OPENING_ROW, report.opening_results))
    for row, results in rows:
        for name, r in results.items():
            spec = REGISTRY.get(name)
            if spec is not None and spec.counts:
                yield row, name, r


def verdict(report: BookReport) -> Verdict:
    """Needs a revision pass (a major issue is a problem somewhere), Nearly
    there (lighter major issues, or another factor is a problem), or Ready
    to send (polish only)."""
    plural = lambda n, w: f"{n} {w}{'s' if n != 1 else ''}"
    found: Dict[str, Dict[str, Dict[str, Any]]] = {t: {} for t in TIERS}
    unread, any_cell = [], False
    major_rows = set()
    for row, name, r in _cells(report):
        spec = REGISTRY[name]
        if r.status == Status.NEEDS_MODEL and spec.tier == "major":
            if spec.label not in unread:
                unread.append(spec.label)
            continue
        if r.status not in Status.VERDICTS:
            continue
        any_cell = True
        if r.status == Status.READY:
            continue
        entry = found[spec.tier].setdefault(name, {"rows": 0, "items": 0, "problem": 0})
        entry["rows"] += 1
        entry["items"] += r.count
        entry["problem"] += r.status == Status.PROBLEM
        if spec.tier == "major" and row not in (BOOK_ROW, OPENING_ROW):
            major_rows.add(row)
    if not any_cell:
        return Verdict("unchecked", "Not checked yet",
                       "Nothing counts yet: check readiness to see where the book stands.",
                       unread=unread)

    def describe(name: str, e: Dict[str, Any]) -> str:
        spec = REGISTRY[name]
        label = spec.label[0].lower() + spec.label[1:]
        if spec.level != "chapter":
            return f"{label} ({e['items']})" if e["items"] else label
        if spec.needs_model and not spec.judge:          # the model's quoted findings
            return f"{plural(e['items'], label[:-1] if label.endswith('s') else label)}" \
                   f" in {plural(e['rows'], 'chapter')}"
        return f"{label} in {plural(e['rows'], 'chapter')}"

    order = lambda tier: sorted(found[tier], key=lambda n: (-found[tier][n]["problem"],
                                                            -REGISTRY[n].weight))
    lines = {t: [describe(n, found[t][n]) for n in order(t)] for t in TIERS}
    majors = sum(e["rows"] for e in found["major"].values())
    major_problems = sum(e["problem"] for e in found["major"].values())
    factor_problems = sum(e["problem"] for e in found["factor"].values())
    polish = (sum(e["rows"] for e in found["polish"].values())
              + sum(e["rows"] - e["problem"] for e in found["factor"].values()))
    bits = []
    if lines["major"]:
        bits.append("Major issues: " + "; ".join(lines["major"]) + ".")
    blocking_factors = [describe(n, found["factor"][n]) for n in order("factor")
                        if found["factor"][n]["problem"]]
    if blocking_factors:
        bits.append(("Then: " if lines["major"] else "Before polish: ")
                    + "; ".join(blocking_factors) + ".")
    if polish:
        bits.append(f"{plural(polish, 'optional polish item')}.")
    if unread:
        bits.append("Not read yet (needs the model): " + ", ".join(u.lower() for u in unread) + ".")
    if major_problems:
        level, title = "revise", "Needs a revision pass"
    elif majors or factor_problems:
        level, title = "nearly", "Nearly there"
    else:
        level, title = "ready", ("Ready to send" if not unread else "Ready, as far as checked")
        bits.insert(0, "No major issues.")
    return Verdict(level, title, " ".join(bits), majors, factor_problems, polish,
                   len(major_rows), unread, lines)


def majors_change(report: BookReport) -> Optional[Tuple[int, str]]:
    """(change in major issues, the earlier day) against the last check on an
    earlier day, measured the same way; None when there is none."""
    h = [e for e in report.history if "majors" in e]
    if not h or h[-1].get("date") != _today():
        return None
    today = h[-1]
    for earlier in reversed(h[:-1]):
        if earlier.get("date") == today.get("date"):
            continue
        if earlier.get("thresholds_version") != today.get("thresholds_version"):
            return None
        return today["majors"] - earlier["majors"], earlier["date"]
    return None


def _today() -> str:
    return time.strftime("%Y-%m-%d")


def _record_history(project, scope, report: BookReport) -> None:
    """Today's figure, kept per manuscript (2.4). Only a complete check
    with something counted is recorded."""
    from src.data import readiness_state as rs
    if report.complete and report.cells and report.saved:
        v = verdict(report)
        entry = {"date": _today(), "readiness": round(report.readiness, 4),
                 "figure_version": FIGURE_VERSION, "thresholds_version": THRESHOLDS_VERSION,
                 "tier": report.tier, "cells": report.cells,
                 "verdict": v.level, "majors": v.majors, "polish": v.polish}
        rs.record_history(project, scope, entry)
    try:
        report.history = rs.history(project, scope)
    except Exception:
        report.history = []


def change_since_last(report: BookReport) -> Optional[Tuple[float, str]]:
    """(change in the figure, the earlier day) against the last check on an
    earlier day, measured the same way; None when there is none."""
    h = report.history
    if not h:
        return None
    today = h[-1]
    for earlier in reversed(h[:-1]):
        if earlier.get("date") == today.get("date"):
            continue
        same = (earlier.get("figure_version") == today.get("figure_version")
                and earlier.get("thresholds_version") == today.get("thresholds_version"))
        if not same:
            return None                         # measured differently: not comparable
        return round(today["readiness"] - earlier["readiness"], 4), earlier["date"]
    return None


def _book_checks(project, scope, book: Book, report: BookReport, goal, llm, scanner,
                 use_cache: bool, dismissed, level: str = "book") -> None:
    """Whole-book checks (or, with ``level="opening"``, the opening pages'
    checks, 1.8): cached on every chapter's text and the plan."""
    from src.data import readiness_state as rs
    specs = checks_for(level=level)
    if not specs:
        return
    if level == "opening":
        bctx = OpeningContext(project, scope, book, route=goal.route, genre=goal.genre,
                              llm=llm, scanner=scanner)
        if not bctx.text.strip():
            return
        report.opening_words = bctx.words
        target = report.opening_results
    else:
        bctx = BookContext(project, scope, book, report.chapters, route=goal.route,
                           genre=goal.genre, llm=llm, scanner=scanner)
        target = report.book_results
    tier = "scan" if llm is None else f"model:{getattr(llm, 'model', '') or 'model'}"
    base = "|".join([book.hash, book.planning_hash(), goal.route, goal.genre,
                     str(THRESHOLDS_VERSION)])
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
        rerun_with_model = (llm is not None and spec.needs_model and spec.model_ready
                            and isinstance(cached, dict) and cached.get("tier", "scan") == "scan")
        if use_cache and isinstance(cached, dict) and cached.get("key") == key \
                and not rerun_with_model:
            if cached.get("not_applicable"):
                continue
            raw = CheckResult.from_dict(cached)
        else:
            raw = _run_check(spec, bctx)
            if raw is None:
                fresh[spec.name] = {"key": key, "not_applicable": True}
                continue
            if llm is not None and spec.needs_model and spec.model_ready:
                raw.judged = True
            if raw.status != Status.COULD_NOT_CHECK:
                fresh[spec.name] = dict(raw.to_dict(), key=key,
                                        tier=tier if raw.judged else "scan")
        target[spec.name] = _finish(spec, raw, bctx.words, dismissed,
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
OPENING_ROW = "__opening__"      # the chapter id of the "Opening pages" row (1.8)


def opening_row(book: BookReport) -> ChapterReport:
    return ChapterReport(scope=book.scope, chapter_id=OPENING_ROW, number=0,
                         title="Opening pages", words=book.opening_words, text_hash="",
                         results=dict(book.opening_results), is_opening=True)


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
    used = ({n for ch in book.chapters for n in ch.results} | set(book.book_results)
            | set(book.opening_results))
    columns = [s for s in checks_for() if s.name in used]
    rows = [(ch, [ch.results.get(s.name) for s in columns]) for ch in book.chapters]
    if book.opening_results and book.chapters:
        row = opening_row(book)
        rows.insert(0, (row, [row.results.get(s.name) for s in columns]))
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
