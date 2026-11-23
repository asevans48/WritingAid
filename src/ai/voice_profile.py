"""An AI reading of the author's style and voice, when a model is configured.

The writer's voice is always *measured* first (``writer_voice``: sentence
length, punctuation, person, tense …), which needs no model. When AI is
configured, the Critique also asks the model once to *read* the author's
narration and say, in a few lines, what the voice and style are and which
habits are deliberate: things a mechanical style check would flag (fragments,
adverbs in dialogue tags, long cumulative sentences) that are this author's
choice. That reading rides on the ``WriterVoice`` into every Critique report
and every rewrite prompt, beside the measurements.

**Cost.** One short model call per manuscript, cached in the project's
readiness file (``readiness.json``, key ``"voice"``, one entry per
manuscript) and made again only when the sampled prose changes. Places that
only *use* the voice (rewrites, passage critique, the companion) read the
cached reading and never call a model.

**Never in the way.** With AI switched off, no model, a model error or too
little prose, nothing is added and the measured voice is used as before.
"""

from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Callable, Dict, List, Optional

from src.ai.writer_voice import _QUOTE_RE, _words

PROMPT_VERSION = 1
SAMPLE_WORDS = 2500           # cloud models
SAMPLE_WORDS_COMPACT = 1200   # on-device models
MIN_WORDS = 300               # less than this is not enough to read a voice
MAX_HABITS = 5

SYSTEM_PROMPT = (
    "You are a literary editor with a sharp ear. You describe an author's style and "
    "voice from samples of their own narration. Describe; do not judge, praise or "
    "rewrite. Be specific to this prose, never generic.")


# ── Is AI available? ───────────────────────────────────────────────────

def ai_enabled() -> bool:
    try:
        from src.config.ai_config import get_ai_config
        return not get_ai_config().is_ai_disabled()
    except Exception:
        return False


# ── The sample ─────────────────────────────────────────────────────────

def _manuscript(project: Any, scope: Optional[str]):
    if project is None:
        return None
    if scope and hasattr(project, "get_manuscript_for"):
        try:
            return project.get_manuscript_for(scope)
        except Exception:
            return None
    try:
        for s, ms in project.iter_manuscripts():
            if s is None:
                return ms
    except Exception:
        pass
    return getattr(project, "manuscript", None)


def voice_sample(project: Any, scope: Optional[str] = None,
                 words: int = SAMPLE_WORDS) -> str:
    """The author's narration from across the manuscript: dialog-free
    paragraphs from chapters spread evenly through it, about ``words``
    long. Deterministic, so the same prose gives the same sample."""
    ms = _manuscript(project, scope)
    chapters = [ch for ch in (getattr(ms, "chapters", None) or [])
                if (getattr(ch, "content", "") or "").strip()]
    if not chapters:
        return ""
    picks = min(len(chapters), 6)
    step = len(chapters) / picks
    chosen = [chapters[int(i * step)] for i in range(picks)]
    per_chapter = max(150, words // picks)
    parts: List[str] = []
    total = 0
    for ch in chosen:
        paras = [p.strip() for p in re.split(r"\n\s*\n|\n", ch.content or "")
                 if p.strip() and not _QUOTE_RE.search(p) and '"' not in p
                 and len(_words(p)) >= 12]
        if not paras:
            continue
        start = len(paras) // 3          # past the chapter's opening set-up
        taken = 0
        for p in paras[start:] + paras[:start]:
            n = len(_words(p))
            parts.append(p)
            taken += n
            total += n
            if taken >= per_chapter or total >= words:
                break
        if total >= words:
            break
    return "\n\n".join(parts)


def sample_key(sample: str) -> str:
    return hashlib.sha1(f"{PROMPT_VERSION}\n{sample}".encode("utf-8")).hexdigest()[:16]


# ── The cache (the readiness file) ─────────────────────────────────────

def cached(project: Any, scope: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The stored reading for a manuscript, or None."""
    try:
        from src.data import publishing_goal as pg
        entry = pg.load(project).get("voice", {}).get(pg.scope_key(scope))
    except Exception:
        return None
    if isinstance(entry, dict) and (entry.get("voice") or entry.get("style")):
        return entry
    return None


def _store(project: Any, scope: Optional[str], entry: Dict[str, Any]) -> None:
    from src.data import readiness_state as rs

    def change(data):                       # every other key is kept
        if not isinstance(data.get("voice"), dict):
            data["voice"] = {}
        data["voice"][rs.scope_key(scope)] = entry
    rs.update(project, change)


# ── Asking the model ───────────────────────────────────────────────────

def build_prompt(sample: str, voice: Any = None) -> str:
    measured = ""
    if voice is not None and getattr(voice, "has_measurements", False):
        import dataclasses                 # the numbers only, not an older reading
        measured = dataclasses.replace(voice, ai_voice="", ai_style="",
                                       ai_habits=[]).to_critique_prompt()
    stated = ""
    targets = getattr(voice, "stated_targets", None) or {}
    if targets:
        stated = "THE AUTHOR'S OWN DESCRIPTION OF THEIR AIMS:\n" + "\n".join(
            f"- {k}: {v}" for k, v in targets.items())
    blocks = [b for b in (measured, stated) if b]
    return (("\n\n".join(blocks) + "\n\n" if blocks else "")
            + "SAMPLES OF THE AUTHOR'S NARRATION:\n" + sample + "\n\n"
            "Answer in exactly this format, one item per line, nothing else:\n"
            "VOICE: <2-3 sentences: diction, register, rhythm, narrative distance, "
            "what the prose notices and what it skips>\n"
            "STYLE: <1-2 sentences: sentence shapes, punctuation, figurative language, "
            "balance of description and action>\n"
            "HABIT: <one deliberate habit of this author that a mechanical style checker "
            "might wrongly flag as a fault, e.g. fragments, adverbs, passive, repetition, "
            "long sentences; say briefly why it works here>\n"
            f"(2 to {MAX_HABITS} HABIT lines)")


_LINE = re.compile(r"^\W*(VOICE|STYLE|HABIT)\W*\s*[:\-–—]\s*(.+)$", re.IGNORECASE)


def parse_reading(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {"voice": "", "style": "", "habits": []}
    for raw in (text or "").splitlines():
        m = _LINE.match(raw.strip())
        if not m:
            continue
        tag, body = m.group(1).upper(), m.group(2).strip().strip("*").strip()
        if not body:
            continue
        if tag == "HABIT":
            if len(out["habits"]) < MAX_HABITS and body not in out["habits"]:
                out["habits"].append(body)
        elif not out[tag.lower()]:
            out[tag.lower()] = body
    return out


def _model_name(llm: Any) -> str:
    for attr in ("model", "model_name", "model_id"):
        v = getattr(llm, attr, None)
        if isinstance(v, str) and v:
            return v
    return type(llm).__name__


def read_voice(llm: Any, sample: str, voice: Any = None,
               compact: bool = False) -> Optional[Dict[str, Any]]:
    """Ask the model for a reading; None when it gives nothing usable."""
    try:
        response = llm.generate_text(build_prompt(sample, voice), SYSTEM_PROMPT,
                                     max_tokens=350 if compact else 500,
                                     temperature=0.3)
    except Exception as e:
        print(f"[voice] AI reading failed: {e}")
        return None
    response = (response or "").strip()
    if not response or response.startswith("Error generating text:"):
        print(f"[voice] AI reading failed: {response[:200]}")
        return None
    reading = parse_reading(response)
    if not (reading["voice"] or reading["style"]):
        return None
    return reading


# ── Attaching it to the measured voice ─────────────────────────────────

def apply(voice: Any, entry: Optional[Dict[str, Any]]) -> Any:
    """Put a stored reading on a ``WriterVoice``; returns the voice."""
    if voice is None or not entry:
        return voice
    voice.ai_voice = str(entry.get("voice", "") or "")
    voice.ai_style = str(entry.get("style", "") or "")
    voice.ai_habits = [str(h) for h in (entry.get("habits") or []) if h][:MAX_HABITS]
    voice.ai_model = str(entry.get("model", "") or "")
    return voice


def attach_cached(voice: Any, project: Any, scope: Optional[str] = None) -> Any:
    """Add the stored reading, if any, without calling a model."""
    if voice is None or project is None or not ai_enabled():
        return voice
    return apply(voice, cached(project, scope))


def ensure(voice: Any, project: Any, scope: Optional[str], llm: Any,
           progress: Optional[Callable[[str], None]] = None) -> Any:
    """Make sure the voice carries an AI reading: the cached one when the
    sampled prose is unchanged, otherwise a fresh one from ``llm``. Any
    failure leaves the voice as it was."""
    if voice is None or project is None or llm is None or not ai_enabled():
        return voice
    try:
        from src.ai.chapter_analysis_agent import is_local_llm
        compact = bool(is_local_llm(llm))
    except Exception:
        compact = False
    try:
        sample = voice_sample(project, scope,
                              SAMPLE_WORDS_COMPACT if compact else SAMPLE_WORDS)
        if len(_words(sample)) < MIN_WORDS:
            return attach_cached(voice, project, scope)
        key = sample_key(sample)
        entry = cached(project, scope)
        if entry and entry.get("sample") == key:
            return apply(voice, entry)
        if progress:
            progress("Reading your style and voice…")
        reading = read_voice(llm, sample, voice, compact)
        if reading is None:
            return apply(voice, entry)           # an older reading beats none
        reading.update(sample=key, model=_model_name(llm),
                       made_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                       version=PROMPT_VERSION)
        try:
            _store(project, scope, reading)
        except Exception as e:
            print(f"[voice] could not store the reading: {e}")
        return apply(voice, reading)
    except Exception as e:                       # never break the caller
        print(f"[voice] AI reading skipped: {e}")
        return voice


def scope_of_chapter(project: Any, chapter: Any) -> Optional[str]:
    cid = getattr(chapter, "id", None)
    if project is None or not cid or not hasattr(project, "find_chapter_with_scope"):
        return None
    try:
        scope, _ = project.find_chapter_with_scope(cid)
        return scope
    except Exception:
        return None


def note_on_section(voice: Any, section: Any) -> None:
    """Show the reading at the top of the Critique's Voice section."""
    if voice is None or not getattr(voice, "has_ai_reading", False):
        return
    reading = " ".join(x for x in (voice.ai_voice, voice.ai_style) if x)
    section.summary = (f"Your voice, as the model reads it: {reading}\n\n"
                       + (section.summary or "")).strip()
