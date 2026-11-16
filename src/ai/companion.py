"""The writing companion: where you left off, quiet margin notes, and a
reader's-eye pass. Everything works without a model; with one (local or
cloud) it adds a scene recap, judges which margin notes are worth showing
(the same "quick rules, then a model decides" pattern as the repetition
review), catches subtler problems, and reads the chapter as a reader would.
"""

from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

_QUOTE_RX = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_COLORS = set("""black brown blue green grey gray hazel amber gold golden silver white red auburn
blond blonde fair dark pale violet copper chestnut""".split())
_THOUGHT_VERBS = ("thought|wondered|felt|knew|realized|realised|hoped|feared|wished|decided|"
                  "remembered|suspected|worried|believed|longed|regretted")


def _words(text: str) -> set:
    from src.ai.event_order import _content
    return _content(text)


def _short(text: str, n: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


# ── 1. Where you left off ────────────────────────────────────────────

@dataclass
class LeftOff:
    headline: str                      # one line for the banner
    lines: List[str] = field(default_factory=list)
    recap: str = ""                    # model-written, filled in later


def _when(iso: str) -> str:
    try:
        then = datetime.fromisoformat(iso)
    except Exception:
        return ""
    days = (datetime.now().date() - then.date()).days
    return ("earlier today" if days == 0 else "yesterday" if days == 1
            else f"{days} days ago" if days < 14 else then.strftime("%b %d"))


def _last_critique_issues(project: Any, chapter_title: str, limit: int = 2) -> List[str]:
    try:
        from src.data.critique_history import load
        runs = [r for rs in load(project).values() for r in rs]
    except Exception:
        return []
    for run in sorted(runs, key=lambda r: r.get("timestamp", ""), reverse=True):
        ch = (run.get("chapters") or {}).get(chapter_title)
        if ch:
            majors = [m for rep in (ch.get("reports") or {}).values() for m in rep.get("major", [])]
            return [_short(m, 110) for m in majors[:limit]]
    return []


def left_off(project: Any, chapter: Any, text: str, before: Dict[str, Any],
             words_today: int = 0, goal: int = 0) -> LeftOff:
    plan = getattr(chapter, "planning", None)
    lines, head = [], []
    if before.get("last_session"):
        added = int(before.get("words_at_close", 0)) - int(before.get("words_at_open", 0))
        change = (f"added {added:,} words" if added > 0 else f"cut {-added:,} words" if added < 0
                  else "made edits")
        when = _when(before["last_session"])
        stopped = before.get("stopped_at", "")
        lines.append(f"Last time ({when}) you {change}" + (f" and stopped at “{_short(stopped, 90)}”"
                                                           if stopped else "") + ".")
        head.append(f"last time {change}")
    events = [e for e in getattr(plan, "events", None) or [] if getattr(e, "text", "")]
    upcoming = next((e for e in events if not getattr(e, "completed", False)), None)
    if upcoming is not None:
        lines.append(f"Next beat: {upcoming.text}"
                     + (f" — {_short(upcoming.description, 100)}" if upcoming.description else ""))
        head.append(f"next: {_short(upcoming.text, 40)}")
    elif events:
        lines.append("Every planned beat is marked done.")
    todos = [t.text for t in getattr(plan, "todos", None) or []
             if not getattr(t, "completed", False) and t.text]
    if todos:
        lines.append("To do: " + "; ".join(_short(t, 60) for t in todos[:3])
                     + (f" (+{len(todos) - 3} more)" if len(todos) > 3 else ""))
        head.append(f"{len(todos)} to-do{'s' if len(todos) != 1 else ''}")
    issues = _last_critique_issues(project, getattr(chapter, "title", ""))
    if issues:
        lines.append("From your last critique: " + " · ".join(issues))
    if goal:
        lines.append(f"Today: {words_today:,} of {goal:,} words.")
        head.append(f"{words_today:,}/{goal:,} words today")
    elif words_today:
        lines.append(f"Today: {words_today:,} words so far.")
    headline = ("Where you left off — " + " · ".join(head)) if head else ""
    return LeftOff(headline=headline, lines=lines)


def recap_text_before(text: str, stopped_at: str) -> str:
    """The text up to where the writer stopped (else the whole chapter)."""
    if stopped_at:
        i = text.find(stopped_at[:80])
        if i >= 0:
            return text[:i + len(stopped_at)]
    return text


# ── 2. Margin notes ──────────────────────────────────────────────────

@dataclass
class Note:
    kind: str                 # pov | tense | beat | appearance | voice | canon | ai
    text: str
    paragraph: int            # paragraph index in the chapter
    excerpt: str = ""         # text to jump to
    action: Optional[Dict[str, str]] = None      # {"type": "mark_beat", "event_id": …}

    @property
    def key(self) -> str:
        digest = hashlib.sha1(f"{self.kind}|{self.text}".encode("utf-8")).hexdigest()[:12]
        return f"{self.kind}:{digest}"


def _narration(text: str) -> str:
    return _QUOTE_RX.sub(" ", text or "")


def _name_rx(name: str) -> str:
    parts = [p for p in (name or "").split() if len(p) > 2]
    return "|".join(re.escape(p) for p in parts) or re.escape(name)


def _pov_notes(project, chapter, para: str, index: int) -> List[Note]:
    pov = (getattr(getattr(chapter, "planning", None), "pov_character", "") or "").strip()
    if not pov:
        return []
    narration = _narration(para)
    if re.search(r"\b(I|me|my)\b", narration):
        return []                                  # first person: not this check
    out = []
    for c in getattr(project, "characters", None) or []:
        if not c.name or c.name.lower() in pov.lower() or pov.lower() in c.name.lower():
            continue
        m = re.search(rf"\b({_name_rx(c.name)})\b(?:\s+\w+){{0,2}}?\s+({_THOUGHT_VERBS})\b",
                      narration)
        if m:
            out.append(Note("pov", f"Head-hop? This chapter is in {pov}'s point of view, but the "
                                   f"narration tells us what {c.name} {m.group(2)}.",
                            index, m.group(0)))
    return out


def _tense_notes(para: str, index: int, voice) -> List[Note]:
    want = getattr(voice, "tense", "") if voice is not None else ""
    if not want:
        return []
    from src.ai.rewrite_quality import person_and_tense
    _, got = person_and_tense(para)
    if got and got != want:
        return [Note("tense", f"Tense slip? This paragraph reads {got} tense; the chapter is "
                              f"{want}.", index, para[:60])]
    return []


def _beat_notes(chapter, para: str, index: int) -> List[Note]:
    out = []
    words = _words(para)
    for e in getattr(getattr(chapter, "planning", None), "events", None) or []:
        if getattr(e, "completed", False) or not getattr(e, "text", ""):
            continue
        beat = _words(f"{e.text} {getattr(e, 'description', '')}")
        shared = beat & words
        if len(shared) >= 2 and len(shared) / max(len(_words(e.text)) or 1, 1) >= 0.6:
            out.append(Note("beat", f"This looks like the beat “{e.text}” — mark it done?",
                            index, para[:60], {"type": "mark_beat", "event_id": e.id}))
    return out[:1]


def _feature_colors(text: str, feature: str) -> set:
    found = set()
    for m in re.finditer(rf"\b{feature}\b", text, re.I):
        window = text[max(0, m.start() - 40):m.end() + 25].lower()
        found |= {w for w in re.findall(r"[a-z]+", window) if w in _COLORS}
    return {"grey" if c == "gray" else "blond" if c == "blonde" else c for c in found}


def _appearance_notes(project, para: str, index: int) -> List[Note]:
    out = []
    narration = _narration(para)
    for c in getattr(project, "characters", None) or []:
        desc = getattr(c, "physical_description", "") or ""
        if not desc or not c.name or not re.search(rf"\b({_name_rx(c.name)})\b", narration):
            continue
        for feature in ("eyes", "hair"):
            canon, here = _feature_colors(desc, feature), _feature_colors(narration, feature)
            if canon and here and not canon & here:
                out.append(Note("appearance",
                                f"{c.name}'s {feature} are {', '.join(sorted(canon))} in their "
                                f"profile, {', '.join(sorted(here))} here.", index,
                                feature))
    return out


def paragraph_notes(project: Any, chapter: Any, paragraphs: Sequence[str],
                    indices: Sequence[int], voice: Any = None,
                    speech_profiles: Optional[Dict[str, Any]] = None) -> List[Note]:
    """Quick checks on finished paragraphs (no model)."""
    out: List[Note] = []
    names = [c.name for c in getattr(project, "characters", None) or []]
    for i in indices:
        para = paragraphs[i] if 0 <= i < len(paragraphs) else ""
        if len(para.split()) < 6:
            continue
        out += _pov_notes(project, chapter, para, i)
        out += _tense_notes(para, i, voice)
        out += _beat_notes(chapter, para, i)
        out += _appearance_notes(project, para, i)
        if speech_profiles and ('"' in para or "“" in para):
            from src.ai.dialogue_craft import dialogue_issues
            for issue in dialogue_issues(para, names, profiles=speech_profiles):
                if issue.kind == "out_of_character":
                    out.append(Note("voice", issue.message, i, issue.excerpt))
    return out


# The model as judge: keeps the quick notes that are real, drops the rest,
# and adds at most one subtler note per paragraph.
JUDGE_SYSTEM = ("You are a quiet, precise writing companion. You only speak up about real "
                "problems a careful editor would flag; when in doubt, stay silent.")
_JUDGE_CACHE: Dict[str, Tuple[List[int], Dict[int, str]]] = {}
_LOCK = threading.Lock()


def judge_prompt(paragraphs: Dict[int, str], notes: List[Note], context: str) -> str:
    parts = []
    if context.strip():
        parts.append(f"=== STORY CONTEXT ===\n{context.strip()}")
    parts.append("=== PARAGRAPHS JUST WRITTEN ===\n" + "\n\n".join(
        f"[P{i}] {p.strip()}" for i, p in sorted(paragraphs.items())))
    if notes:
        parts.append("=== QUICK-CHECK NOTES (may be false alarms) ===\n" + "\n".join(
            f"{n}. [P{note.paragraph}] {note.text}" for n, note in enumerate(notes, 1)))
    parts.append(
        ("For each quick-check note answer KEEP (a real problem) or DROP (a false alarm or not "
         "worth interrupting the writer):\n1. KEEP\n2. DROP\n\n" if notes else "")
        + "Then, only if a paragraph has a real problem the quick checks missed — it "
          "contradicts the story context or a settled decision, a character acts against "
          "their profile, or a planted promise is dropped — add one line for it:\n"
          "NOTE P<n>: <the problem in under 25 words>\n"
          "Write nothing else. If everything is fine, write only: NONE")
    return "\n\n".join(parts)


def parse_judgement(reply: str, notes: List[Note]) -> Tuple[List[int], Dict[int, str]]:
    from src.ai.output_sanitizer import strip_meta_tokens
    text = strip_meta_tokens(reply or "")
    drop = []
    for m in re.finditer(r"^\s*(\d+)[.):]?\s*\**\s*(KEEP|DROP)\b", text, re.I | re.M):
        n = int(m.group(1)) - 1
        if 0 <= n < len(notes) and m.group(2).upper() == "DROP":
            drop.append(n)
    extra: Dict[int, str] = {}
    for m in re.finditer(r"^\s*\**\s*NOTE\s*\**\s*\[?P(\d+)\]?\s*\**\s*[:—-]\s*(.+)$", text,
                         re.I | re.M):
        extra.setdefault(int(m.group(1)), m.group(2).strip().strip("*"))
    return drop, extra


def judge_notes(llm: Any, paragraphs: Dict[int, str], notes: List[Note],
                context: str = "") -> List[Note]:
    """Quick notes the model keeps, plus its own (one per paragraph at most)."""
    key = hashlib.sha1(("\n".join(f"{i}:{p}" for i, p in sorted(paragraphs.items()))
                        + "|" + "|".join(n.text for n in notes)).encode("utf-8")).hexdigest()
    with _LOCK:
        cached = _JUDGE_CACHE.get(key)
    if cached is None:
        try:
            reply = llm.generate_text(judge_prompt(paragraphs, notes, context), JUDGE_SYSTEM,
                                      max_tokens=240, temperature=0.2)
        except Exception as e:
            print(f"[companion] judge failed: {e}")
            return notes
        cached = parse_judgement(reply, notes)
        with _LOCK:
            if len(_JUDGE_CACHE) > 500:
                _JUDGE_CACHE.clear()
            _JUDGE_CACHE[key] = cached
    drop, extra = cached
    kept = [n for k, n in enumerate(notes) if k not in drop]
    for i, text in extra.items():
        if i in paragraphs:
            kept.append(Note("ai", text, i, paragraphs[i][:60]))
    return kept


def judge_context(project: Any, chapter: Any, text: str) -> str:
    """Story bible bits for the judge: decisions, POV, characters present,
    open promises."""
    from src.ai.story_memory import prompt_block
    parts = []
    memory = prompt_block(project, text, limit=6)
    if memory:
        parts.append(memory)
    from src.ai.style_sheet import prompt_block as style_sheet_block
    sheet = style_sheet_block(project)
    if sheet:
        parts.append(sheet)
    pov = (getattr(getattr(chapter, "planning", None), "pov_character", "") or "").strip()
    if pov:
        parts.append(f"Point of view: {pov}.")
    from src.ai.canon_index import format_character_profile
    for c in getattr(project, "characters", None) or []:
        if c.name and re.search(rf"\b({_name_rx(c.name)})\b", text):
            parts.append(format_character_profile(c, getattr(chapter, "number", 0) or 0,
                                                  max_field=120))
    promises = [p.title for p in getattr(getattr(project, "story_planning", None),
                                         "promises", None) or []]
    if promises:
        parts.append("Promises to the reader: " + "; ".join(promises[:6]))
    return "\n\n".join(parts)[:3500]


# ── 6. Reader's-eye pass ─────────────────────────────────────────────

@dataclass
class ReaderReport:
    dips: List[Tuple[str, str]] = field(default_factory=list)      # (quote, why)
    questions: List[str] = field(default_factory=list)
    beats: List[Tuple[str, str]] = field(default_factory=list)     # (quote, how it lands)
    overall: str = ""
    quick: bool = False                                            # no model used


READER_SYSTEM = ("You are an attentive first reader of a novel in progress — not an editor. "
                 "You report honestly how the chapter reads: where your attention slipped, "
                 "what you're wondering, and what moved you.")


def reader_prompt(text: str, title: str = "", memory: str = "") -> str:
    return ((f"{memory}\n\n" if memory else "")
            + f"CHAPTER{f' — {title}' if title else ''}:\n{text.strip()}\n\n"
            "Read it as a reader would and answer in exactly these sections:\n\n"
            "DIPS:\n- \"<quote 4-12 words where your attention drifted>\" — <why>\n\n"
            "QUESTIONS:\n- <a question you're asking as the chapter ends>\n\n"
            "BEATS:\n- \"<quote 4-12 words from an emotional moment>\" — <what you felt, and "
            "whether it landed or fell flat>\n\n"
            "OVERALL:\n<one sentence on how the chapter left you>\n\n"
            "Give 1-4 items per section. Quote the chapter exactly.")


def parse_reader(reply: str) -> ReaderReport:
    from src.ai.output_sanitizer import strip_meta_tokens
    text = strip_meta_tokens(reply or "")
    report = ReaderReport()
    heads = list(re.finditer(r"^\s*(?:#+\s*)?\**\s*(DIPS|QUESTIONS|BEATS|OVERALL)\s*\**\s*:?\s*\**\s*$",
                             text, re.I | re.M))
    for k, h in enumerate(heads):
        body = text[h.end():heads[k + 1].start() if k + 1 < len(heads) else len(text)]
        items = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", l).strip() for l in body.splitlines()
                 if l.strip()]
        name = h.group(1).upper()

        def quoted(item):
            m = re.match(r"^[\"“](.+?)[\"”]\s*[—:\-–]+\s*(.+)$", item)
            return (m.group(1).strip(), m.group(2).strip()) if m else ("", item)

        if name == "DIPS":
            report.dips = [quoted(i) for i in items][:4]
        elif name == "QUESTIONS":
            report.questions = items[:4]
        elif name == "BEATS":
            report.beats = [quoted(i) for i in items][:4]
        else:
            report.overall = " ".join(items)
    return report


def reader_pass(llm: Any, project: Any, chapter: Any, text: str, compact: bool = False) -> ReaderReport:
    limit = 14000 if compact else 40000
    body = text if len(text) <= limit else text[:limit // 2] + "\n[…]\n" + text[-limit // 2:]
    from src.ai.story_memory import prompt_block
    reply = llm.generate_text(reader_prompt(body, getattr(chapter, "title", ""),
                                            prompt_block(project, text, limit=5)),
                              READER_SYSTEM, max_tokens=700, temperature=0.4)
    report = parse_reader(reply)
    # Quotes the model invented can't be jumped to; keep the note, drop the quote.
    report.dips = [(q if q and q.lower() in text.lower() else "", w) for q, w in report.dips]
    report.beats = [(q if q and q.lower() in text.lower() else "", w) for q, w in report.beats]
    return report


def reader_pass_quick(project: Any, chapter: Any, text: str) -> ReaderReport:
    """No model: where the pace may sag (long stretches of narration with
    little action or dialogue), and the open threads a reader carries out."""
    report = ReaderReport(quick=True)
    paragraphs = [p for p in (text or "").split("\n") if p.strip()]
    sentences_all = [s for p in paragraphs for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
    avg_len = (sum(len(s.split()) for s in sentences_all) / len(sentences_all)) if sentences_all else 0
    for start in range(0, len(paragraphs), 6):
        chunk = paragraphs[start:start + 6]
        joined = " ".join(chunk)
        words = len(joined.split())
        if words < 120:
            continue
        dialogue = sum(len(q.split()) for q in _QUOTE_RX.findall(joined)) / words
        sents = [s for s in re.split(r"(?<=[.!?])\s+", _narration(joined)) if len(s.split()) > 2]
        mean = sum(len(s.split()) for s in sents) / max(len(sents), 1)
        short = sum(1 for s in sents if len(s.split()) <= 8) / max(len(sents), 1)
        if dialogue < 0.08 and mean > max(avg_len * 1.15, 18) and short < 0.2:
            first = re.split(r"(?<=[.!?])\s+", chunk[0])[0]
            report.dips.append((_short(first, 60).rstrip("…"),
                                "A long stretch of narration with little action or dialogue "
                                "— check the pace here."))
    plan = getattr(chapter, "planning", None)
    open_beats = [e.text for e in getattr(plan, "events", None) or []
                  if e.text and not getattr(e, "completed", False)]
    report.questions += [f"Unfinished beat: {b}" for b in open_beats[:2]]
    sp = getattr(project, "story_planning", None)
    report.questions += [f"Open tension: {t.title} ({t.current_state})"
                         for t in getattr(sp, "tensions", None) or []
                         if getattr(t, "current_state", "") != "resolved"][:2]
    report.overall = ("Set up a local or cloud model for a reader's reactions — this quick "
                      "pass only measures pace and lists open threads.")
    return report


# ── Today's three fixes ──────────────────────────────────────────────

@dataclass
class Fix:
    text: str                 # what to change
    why: str = ""
    excerpt: str = ""         # where (for Go to)


def fix_candidates(highlighter: Any, document: Any, notes: Sequence[Note] = ()) -> List[Dict[str, Any]]:
    """Every current flag and margin note, with a sentence and a weight."""
    from src.ai.word_suggest import sentence_around
    from src.ui.enhanced_text_editor import ErrorType, issue_weight
    labels = {ErrorType.SPELLING: "Spelling", ErrorType.GRAMMAR: "Grammar",
              ErrorType.OVERUSE: "Overused word", ErrorType.OVERUSED_PHRASE: "Repeated phrase",
              ErrorType.STYLE: "Style"}
    out = []
    for number, errors in highlighter._errors.items():
        block = document.findBlockByNumber(number)
        if not block.isValid():
            continue
        paragraph = block.text()
        for e in errors:
            sentence = sentence_around(paragraph, e.start, e.end).text
            out.append({"label": f"{labels.get(e.error_type, 'Issue')}: “{_short(e.word, 40)}” — "
                                 f"{_short(e.reason, 90)}",
                        "excerpt": sentence, "weight": issue_weight(e, paragraph),
                        "paragraph": number})
    for n in notes:
        out.append({"label": n.text, "excerpt": n.excerpt, "weight": 75 if n.kind == "ai" else 60,
                    "paragraph": n.paragraph})
    out.sort(key=lambda c: -c["weight"])
    return out


def three_fixes_quick(candidates: List[Dict[str, Any]]) -> List[Fix]:
    """No model: the heaviest issues, one per paragraph."""
    out, used = [], set()
    for c in candidates:
        if c["paragraph"] in used:
            continue
        used.add(c["paragraph"])
        out.append(Fix(c["label"], "", c["excerpt"]))
        if len(out) == 3:
            break
    return out


FIXES_SYSTEM = ("You are a trusted editor choosing what a writer should fix first. Substance "
                "(story, character, clarity) beats polish.")


def fixes_prompt(candidates: List[Dict[str, Any]], context: str = "") -> str:
    lines = [f"{n}. {c['label']}  «{_short(c['excerpt'], 140)}»" for n, c in enumerate(candidates, 1)]
    return ((f"{context.strip()}\n\n" if context.strip() else "")
            + "These are the open issues in a chapter:\n\n" + "\n".join(lines) + "\n\n"
            "Pick the THREE that would most improve the chapter for a reader if fixed today. "
            "Answer exactly three lines:\nPICK <number> — <why it matters, under 15 words>")


def three_fixes(llm: Any, candidates: List[Dict[str, Any]], context: str = "") -> List[Fix]:
    shown = candidates[:25]
    if not shown:
        return []
    try:
        reply = llm.generate_text(fixes_prompt(shown, context), FIXES_SYSTEM, max_tokens=160,
                                  temperature=0.2)
    except Exception as e:
        print(f"[companion] fixes failed: {e}")
        return three_fixes_quick(candidates)
    from src.ai.output_sanitizer import strip_meta_tokens
    out, used = [], set()
    for m in re.finditer(r"^\s*\**\s*(?:PICK\s*)?#?(\d+)\s*\**\s*[.):]?\s*[—:\-–]+\s*(.+)$",
                         strip_meta_tokens(reply), re.I | re.M):
        n = int(m.group(1)) - 1
        if 0 <= n < len(shown) and n not in used:
            used.add(n)
            out.append(Fix(shown[n]["label"], m.group(2).strip(), shown[n]["excerpt"]))
    return out[:3] or three_fixes_quick(candidates)
