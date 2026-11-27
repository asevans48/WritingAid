"""How much tension each scene carries, as a model reads it (piece 7.2).

One request per chapter. The chapter is sent with its scenes numbered as
``reverse_outline.split_scenes`` finds them (the one rules-based splitter),
(with the writer's scene markers, 7.4) so every rating belongs to a
scene the writer can see; the model answers
one line per scene:

    TENSION | scene number | 1 to 5 | why, under 12 words

(the request asks for each scene as a whole, with one example, and to
begin "TENSION | 1 |"; bare rows are read only when they are clearly one
per numbered scene). 1 is calm (nothing at stake), 3 is a live conflict or question, 5 the
chapter's peak. **Stored** in ``readiness.json`` under ``"tension"``, per
manuscript and chapter, with the text's hash and the scene count: a
chapter is read again only when it changes. An answer that can't be read
is stored as "couldn't be read" for that model, so it is not asked again
until the chapter, its markers or the chosen model change; nothing is shown.

**Repeatable before it is shown.** A rating is only worth a line on a
chart if the same model gives the same chapter much the same ratings
twice. ``agreement`` measures two runs; the trial and its bar are in
``docs/publishing/pieces/58-7.2-reverse-outline-with-a-model.md``.

The chart (``outline_chart``, through ``plan_match.set_tension_source``)
and the outline read stored ratings only; they never run the model.
No Qt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

KEY = "tension"
VERSION = 1
MAX_WORDS = 3500
MAX_WORDS_COMPACT = 1500
TEMPERATURE = 0.2

SYSTEM = ("You are a developmental editor rating the tension of each scene in one chapter "
          "of a novel. You rate what the text does, not how well it is written.")

PROMPT = 2               # 2: the firmer prompt (27 Nov); a "couldn't be read" from an
                         # older prompt is asked again

SCALE = ("1 calm: nothing is at stake in the scene\n"
         "2 low: a small worry or question in the background\n"
         "3 live: a conflict, danger or open question drives the scene\n"
         "4 high: the conflict sharpens; something may be lost\n"
         "5 peak: confrontation, danger or a decision under pressure, at its height\n")

EXAMPLE = ("For example, for a chapter of two scenes the whole answer would be:\n"
           "TENSION | 1 | 2 | a quiet supper with an unspoken worry\n"
           "TENSION | 2 | 4 | the stranger draws a knife\n")


def ask(scenes: int) -> str:
    """The request after the chapter: rate each numbered scene as a whole."""
    lines = f"exactly {scenes} line{'s' if scenes != 1 else ''}"
    return (f"Rate each numbered scene above as a whole, from 1 to 5. Do not split a scene "
            f"into parts; there {'is' if scenes == 1 else 'are'} {scenes} "
            f"scene{'s' if scenes != 1 else ''}.\n" + SCALE + EXAMPLE +
            f"Answer with {lines}, one per scene, in order, and nothing else. Each line is: "
            f"TENSION | scene number | 1 to 5 | why, under 12 words\n"
            f"Begin your answer with: TENSION | 1 |")


def build_prompt(chapter: Any, text: str, spans: Sequence[Tuple[int, int]],
                 compact: bool = False) -> str:
    """The chapter with its scenes numbered; a long chapter is cut evenly,
    so every scene keeps its start."""
    cap = MAX_WORDS_COMPACT if compact else MAX_WORDS
    total = sum(len(text[s:e].split()) for s, e in spans) or 1
    parts = []
    for n, (s, e) in enumerate(spans, 1):
        words = text[s:e].split()
        keep = max(40, int(cap * len(words) / total)) if total > cap else len(words)
        body = " ".join(words[:keep]) + (" …" if keep < len(words) else "")
        parts.append(f"[SCENE {n}]\n{body}")
    title = getattr(chapter, "title", "") or "this chapter"
    return f"CHAPTER ({title}), {len(spans)} scene{'s' if len(spans) != 1 else ''}:\n\n" \
           + "\n\n".join(parts) + f"\n\n{ask(len(spans))}"


_LINE = re.compile(r"^\W*TENSION\W*\|\s*(?:scene\s*)?(\d+)\s*\|\s*([1-5])\b[^|]*(?:\|(.*))?$",
                   re.I | re.M)
_BARE2 = re.compile(r"^\W*(\d+)\s*\|\s*([1-5])\s*(?:\|(.*))?$", re.M)
_BARE3 = re.compile(r"^\W*(\d+)\s*\|\s*(\d+)\s*\|\s*([1-5])\s*(?:\|(.*))?$", re.M)


def _why(text: Optional[str]) -> str:
    return (text or "").strip().strip("*_ ").rstrip(".")[:120]


def parse(reply: str, scenes: int) -> Dict[str, List[Any]]:
    """{"values": [1..5 or None per scene], "why": [str per scene]}.

    ``TENSION | n | v | why`` lines first. Without any, bare rows (a model
    that drops the word, as Cydonia does) are read only when they clearly
    are one row per numbered scene: exactly ``scenes`` rows numbered 1 to
    ``scenes`` in order, as ``n | v | why`` or ``n | n | v | why`` (the
    number repeated). Anything else, such as rows for beats the model split
    a scene into, is never guessed at: no ratings."""
    values: List[Optional[int]] = [None] * scenes
    why = [""] * scenes
    found = list(_LINE.finditer(reply or ""))
    for m in found:
        n = int(m.group(1))
        if 1 <= n <= scenes and values[n - 1] is None:
            values[n - 1] = int(m.group(2))
            why[n - 1] = _why(m.group(3))
    if found:
        return {"values": values, "why": why}
    want = list(range(1, scenes + 1))
    rows3 = [m for m in _BARE3.finditer(reply or "")]
    if rows3:
        if ([int(m.group(1)) for m in rows3] == want
                and [int(m.group(2)) for m in rows3] == want):
            return {"values": [int(m.group(3)) for m in rows3],
                    "why": [_why(m.group(4)) for m in rows3]}
        return {"values": values, "why": why}              # rows that aren't the scenes
    rows2 = [m for m in _BARE2.finditer(reply or "")]
    if [int(m.group(1)) for m in rows2] == want:
        return {"values": [int(m.group(2)) for m in rows2],
                "why": [_why(m.group(3)) for m in rows2]}
    return {"values": values, "why": why}


class Unreadable(RuntimeError):
    """The model answered, but not in a form that can be read as ratings."""


def model_id(llm: Any) -> str:
    """Which model answered: its id, else its provider, else its kind."""
    for attr in ("model", "model_id"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v:
            return v
    hf = getattr(getattr(llm, "hf_config", None), "model_id", "")
    if hf:
        return str(hf)
    return str(getattr(llm, "provider", "") or type(llm).__name__)


def rate_chapter(llm: Any, chapter: Any, text: str, compact: bool = False,
                 temperature: float = TEMPERATURE, marks: Sequence[int] = ()) -> Dict[str, Any]:
    """One request: the chapter's tension, scene by scene (``marks``: the
    scene markers' offsets, 7.4). Raises when the model fails or rates no scene."""
    from src.ai.reverse_outline import split_scenes
    spans = split_scenes(text, marks)
    if not spans:
        raise RuntimeError("the chapter is empty")
    reply = llm.generate_text(build_prompt(chapter, text, spans, compact), SYSTEM,
                              max_tokens=120 + 40 * len(spans), temperature=temperature) or ""
    if reply.startswith("Error generating text:"):
        raise RuntimeError(reply.split(":", 1)[1].strip())
    try:
        from src.ai.output_sanitizer import strip_meta_tokens
        reply = strip_meta_tokens(reply)
    except Exception:
        pass
    found = parse(reply, len(spans))
    if all(v is None for v in found["values"]):
        raise Unreadable("the model's tension ratings couldn't be read")
    found["scenes"] = len(spans)
    if marks:
        found["marks"] = sorted(int(m) for m in marks)    # 7.4: the split it was made for
    found["model"] = model_id(llm)
    return found


# ── Stored ratings ───────────────────────────────────────────────────

def _entries(project: Any) -> Dict[str, Dict[str, Any]]:
    """{scope key: {chapter id: entry}} from the readiness file; {} on any error."""
    try:
        from src.data import readiness_state as rs
        store = rs.load(project).get(KEY, {})
        return store if isinstance(store, dict) else {}
    except Exception:
        return {}


def _matching(project: Any, chapter_id: str, text: str,
              scope: Optional[str]) -> Optional[Dict[str, Any]]:
    """The stored entry made from the text, markers and split as they are
    now (ratings or "couldn't be read"), or None."""
    if project is None or not (text or "").strip():
        return None
    from src.ai.readiness import text_hash
    from src.ai.reverse_outline import split_scenes
    want = text_hash(text)
    store = _entries(project)
    if scope is not None:
        from src.data import readiness_state as rs
        store = {rs.scope_key(scope): store.get(rs.scope_key(scope), {})}
    marks = _marks(project, chapter_id, text, scope)
    for entries in store.values():
        entry = (entries or {}).get(chapter_id) if isinstance(entries, dict) else None
        if (isinstance(entry, dict) and entry.get("text_hash") == want
                and entry.get("v") == VERSION
                and entry.get("scenes") == len(split_scenes(text, marks))
                and list(entry.get("marks") or []) == marks):
            return entry
    return None


def stored(project: Any, chapter_id: str, text: str,
           scope: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The chapter's ratings if they were made from the text as it is now.
    ``scope`` None looks in every manuscript (chapter ids are unique). A
    stored "couldn't be read" is not ratings: None, and nothing is shown."""
    entry = _matching(project, chapter_id, text, scope)
    return None if entry is None or entry.get("unreadable") else entry


def _marks(project: Any, chapter_id: str, text: str, scope: Optional[str]) -> List[int]:
    """The scene markers' offsets (7.4); a rating made before a marker was
    added or moved is not this split's."""
    from src.data import scene_marks
    return sorted(scene_marks.offsets(project, chapter_id, text,
                                      scene_marks.ANY if scope is None else scope))


def save(project: Any, scope: Optional[str], chapter_id: str, entry: Dict[str, Any]) -> bool:
    try:
        from src.data import readiness_state as rs

        def change(data):                         # every other key is kept
            store = data.get(KEY)
            if not isinstance(store, dict):
                store = data[KEY] = {}
            store.setdefault(rs.scope_key(scope), {})[chapter_id] = entry
        return bool(rs.update(project, change))
    except Exception as e:
        print(f"[tension] not saved: {e}")
        return False


def ensure(llm: Any, project: Any, scope: Optional[str], chapter: Any, text: str,
           compact: bool = False) -> Dict[str, Any]:
    """The chapter's ratings: stored ones if the text is unchanged, else one request.

    An answer that can't be read is stored as "couldn't be read" with the
    text's hash, the markers and the model, and that model is not asked
    again until the chapter, its markers or the model change (another model
    chosen in Settings is asked fresh; so is any model after the prompt
    changes). Raises ``Unreadable`` then; nothing is shown."""
    entry = _matching(project, chapter.id, text, scope)
    me = model_id(llm)
    if entry is not None and not entry.get("unreadable"):
        return entry
    if (entry is not None and entry.get("model") == me
            and entry.get("prompt") == PROMPT):
        raise Unreadable(f"{me} couldn't rate this chapter's tension (not asked again "
                         "until the chapter changes)")
    from src.ai.readiness import text_hash
    marks = _marks(project, chapter.id, text, scope)
    try:
        entry = dict(rate_chapter(llm, chapter, text, compact, marks=marks),
                     text_hash=text_hash(text), v=VERSION, prompt=PROMPT)
    except Unreadable:
        from src.ai.reverse_outline import split_scenes
        failed = dict(unreadable=True, model=me, prompt=PROMPT, text_hash=text_hash(text),
                      v=VERSION, scenes=len(split_scenes(text, marks)))
        if marks:
            failed["marks"] = sorted(int(m) for m in marks)
        save(project, scope, chapter.id, failed)
        raise
    save(project, scope, chapter.id, entry)
    return entry


def as_fractions(entry: Optional[Dict[str, Any]]) -> Optional[List[Optional[float]]]:
    """1..5 → 0..1 for the chart (None stays None); None without ratings."""
    if not entry:
        return None
    return [None if v is None else (int(v) - 1) / 4 for v in entry.get("values", [])]


def install(project_of) -> None:
    """Give the scene chart its tension: ``project_of()`` is the open project.
    Reads stored ratings only."""
    from src.ai import plan_match

    def source(chapter_id: str, text: str, spans) -> Optional[List[Optional[float]]]:
        values = as_fractions(stored(project_of(), chapter_id, text))
        return values if values and len(values) == len(spans) else None
    plan_match.set_tension_source(source)


# ── Repeatability ────────────────────────────────────────────────────

def agreement(a: Sequence[Optional[int]], b: Sequence[Optional[int]]) -> Dict[str, float]:
    """Two runs' ratings of the same scenes: share exactly equal, share within
    one point, and quadratic-weighted kappa (agreement beyond chance, which a
    model that says 3 everywhere cannot fake). Scenes either run missed are
    left out; ``n`` is how many were compared."""
    pairs = [(int(x), int(y)) for x, y in zip(a, b) if x is not None and y is not None]
    n = len(pairs)
    if not n:
        return {"n": 0, "exact": 0.0, "within_one": 0.0, "kappa": float("nan")}
    exact = sum(x == y for x, y in pairs) / n
    within = sum(abs(x - y) <= 1 for x, y in pairs) / n
    k = 5
    obs = [[0.0] * k for _ in range(k)]
    for x, y in pairs:
        obs[x - 1][y - 1] += 1
    ra = [sum(row) for row in obs]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = (i - j) ** 2 / (k - 1) ** 2
            num += w * obs[i][j]
            den += w * ra[i] * rb[j] / n
    kappa = 1.0 - num / den if den else float("nan")     # one rating everywhere: unknown
    return {"n": n, "exact": exact, "within_one": within, "kappa": kappa}
