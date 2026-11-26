"""The current chapter beside the Prose Profile, at a glance (no model).

The Prose Profile tab sets the project's targets (tone, style, voice,
genre). This measures one chapter against what can be counted: sentence
length and variety, dialogue, adverbs, passive voice, readability and
length. Each is compared with the same bar the checks use: published books
in the genre where the app has figures for them (``genre_baseline``, P.3),
else the genre profile's fixed band or the check's fixed threshold.

Tone, style and voice can't be counted; the summary lists them as the
targets the full review (Analyze ▸ Prose, the Critique's "Prose profile
fit" report, which needs a model) reads the chapter against.

Used by the Prose Profile tab ("This chapter") and the AI chat ("prose
profile", "summarise my prose"). Pure Python: nothing here touches Qt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, List, Optional, Tuple

MIN_WORDS = 150          # fewer and the counts say little


@dataclass
class Row:
    label: str
    value: str
    target: str             # "" when there is nothing to compare with
    verdict: str            # "on target", "above", "below" or ""
    source: str = ""        # "published thrillers (CONLIT, 300 books)", "genre guide", …


@dataclass
class Snapshot:
    chapter_title: str
    words: int
    genre_label: str
    rows: List[Row] = field(default_factory=list)
    targets: List[Tuple[str, str]] = field(default_factory=list)   # (Tone, "dark, tense")
    note: str = ""          # why there are no rows, when there are none

    @property
    def off_target(self) -> List[Row]:
        return [r for r in self.rows if r.verdict in ("above", "below")]

    def headline(self) -> str:
        if not self.rows:
            return self.note
        off = self.off_target
        compared = [r for r in self.rows if r.verdict]
        if not off:
            return f"All {len(compared)} measures are within the target for {self.genre_label}."
        names = ", ".join(r.label.lower() for r in off)
        return (f"{len(compared) - len(off)} of {len(compared)} measures on target; "
                f"outside it: {names}.")

    def markdown(self, review_hint: bool = True) -> str:
        """For the chat: a short summary in Markdown."""
        head = f"**Prose profile — “{self.chapter_title}”** ({self.words:,} words"
        head += f", measured against {self.genre_label})" if self.genre_label else ")"
        lines = [head, "", self.headline()]
        if self.rows:
            lines.append("")
            for r in self.rows:
                mark = {"on target": "✓", "above": "▲", "below": "▼"}.get(r.verdict, "·")
                tail = f" (target {r.target})" if r.target else ""
                lines.append(f"- {mark} **{r.label}:** {r.value}{tail}")
        if self.targets:
            lines.append("")
            lines.append("Profile targets the counts can't measure: "
                         + "; ".join(f"**{k}** {v}" for k, v in self.targets) + ".")
        if review_hint:
            lines.append("")
            lines.append("For a full read against tone, style and voice, say *review my prose* "
                         "(it runs the Prose profile fit report in the Critique).")
        return "\n".join(lines)

    def context_text(self) -> str:
        """For the chat's context: one line per measure, plain."""
        out = [f"=== CURRENT CHAPTER MEASURED (“{self.chapter_title}”, {self.words:,} words) ==="]
        if not self.rows:
            out.append(self.note)
        for r in self.rows:
            out.append(f"{r.label}: {r.value}" + (f" — target {r.target} ({r.verdict})"
                                                  if r.target else ""))
        return "\n".join(out)


def _fmt(v: float, digits: int = 1) -> str:
    s = f"{v:.{digits}f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def _band(value: float, low: Optional[float], high: Optional[float]) -> str:
    if low is not None and value < low:
        return "below"
    if high is not None and value > high:
        return "above"
    return "on target"


def _targets(project: Any) -> List[Tuple[str, str]]:
    pp = getattr(project, "prose_profile", None)
    out = []
    for label, attr in (("Tone", "tone"), ("Style", "style"), ("Voice", "voice")):
        value = (getattr(pp, attr, "") or "").strip() if pp is not None else ""
        if value:
            out.append((label, value))
    return out


_CACHE: dict = {}          # (text, genre, targets, title) → Snapshot; the last few only


def measure(project: Any, text: str, chapter_title: str = "",
            scope: Optional[str] = None) -> Snapshot:
    """The chapter's measures beside the Prose Profile's genre targets
    (remembered while the text and the profile are unchanged)."""
    from src.ai import genre_baseline as gb
    from src.data.publishing_goal import genre_of
    pp = getattr(project, "prose_profile", None)
    key = (hash(text or ""), chapter_title, scope, gb.fingerprint(genre_of(project)[0]),
           tuple((getattr(pp, a, "") or "") for a in ("genre", "tone", "style", "voice")))
    if key in _CACHE:
        return _CACHE[key]
    snap = _measure(project, text, chapter_title, scope)
    if len(_CACHE) > 8:
        _CACHE.clear()
    _CACHE[key] = snap
    return snap


def _measure(project: Any, text: str, chapter_title: str, scope: Optional[str]) -> Snapshot:
    from src.ai import genre_baseline as gb
    from src.ai.chapter_analysis_agent import resolve_genre_profile
    from src.data.publishing_goal import genre_of

    text = text or ""
    words = len(text.split())
    genre_key, genre_name = genre_of(project)
    stated = (getattr(getattr(project, "prose_profile", None), "genre", "") or "").strip()
    profile = resolve_genre_profile(stated)
    label = genre_name or (profile.name if profile.key != "default" else "general fiction")
    snap = Snapshot(chapter_title=chapter_title or "This chapter", words=words,
                    genre_label=label, targets=_targets(project))
    if words < MIN_WORDS:
        snap.note = (f"The chapter has {words} words; write at least {MIN_WORDS} and its "
                     "measures will show here.")
        return snap

    from src.ai import readiness as rd
    rd._load_checks()
    ctx = rd.CheckContext(project, scope, SimpleNamespace(id="prose-snapshot", title="", number=1),
                          text, is_opening=False, route="agent", genre=genre_key,
                          scanner=rd.Scanner(project, languagetool=False))
    s = ctx.stats()

    def published(measure_name):
        r = gb.usable(genre_key, measure_name)
        if r is None:
            return None, ""
        src = f"{r.note}, {r.books:,} books" if r.note else f"{r.books} books"
        return r, f"published {gb.plural(genre_key)} ({src})"

    guide = f"{profile.name} guide"

    # Sentence length
    v = float(s.avg_sentence_length)
    r, src = published("sentence_length")
    lo, hi = (r.low, r.high) if r else profile.avg_sentence_target
    snap.rows.append(Row("Sentence length", f"{_fmt(v)} words", f"{_fmt(lo)}–{_fmt(hi)} words",
                         _band(v, lo, hi), src or guide))
    # Sentence variety (a floor)
    v = float(s.sentence_length_score)
    r, src = published("sentence_variety")
    floor = r.low if r else profile.variety_score_target
    snap.rows.append(Row("Sentence variety", f"{v:.0f} of 100", f"{floor:.0f} or more",
                         _band(v, floor, None), src or guide))
    # Dialogue
    v = float(s.dialogue_percentage)
    r, src = published("dialogue_share")
    lo, hi = (r.low, r.high) if r else profile.dialog_pct_target
    snap.rows.append(Row("Dialogue", f"{v:.0f}%", f"{lo:.0f}–{hi:.0f}%", _band(v, lo, hi),
                         src or guide))
    # Adverbs and passive voice: the checks' own count and bar (genre-aware).
    for name, label_ in (("adverbs", "Adverbs"), ("passive", "Passive voice")):
        try:
            v = float(rd.REGISTRY[name].fn(ctx).measure or 0.0)
            t = ctx.threshold(name)
            cap = t.per_1000[0] if t is not None and t.per_1000 else None
        except Exception:
            continue
        r, src = published(name)
        snap.rows.append(Row(label_, f"{_fmt(v)} per 1,000 words",
                             f"{_fmt(cap)} or fewer" if cap is not None else "",
                             _band(v, None, cap) if cap is not None else "",
                             src or "the check's usual figure"))
    # Readability: only against published books (no fixed bar exists).
    v = float(s.flesch_reading_ease)
    r, src = published("readability")
    snap.rows.append(Row("Readability", f"{v:.0f}",
                         f"{r.low:.0f}–{r.high:.0f}" if r else "",
                         _band(v, r.low, r.high) if r else "", src))
    # Length
    from src.ai.readiness_checks.structure import TYPICAL_CHAPTER
    r, src = published("chapter_length")
    lo, hi = (r.low, r.high) if r else TYPICAL_CHAPTER
    snap.rows.append(Row("Length", f"{words:,} words",
                         f"{int(round(lo, -1)):,}–{int(round(hi, -1)):,} words",
                         _band(words, lo, hi), src or "a common guide"))
    return snap
