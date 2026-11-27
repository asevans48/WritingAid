"""A reverse outline without a model (piece 7.1).

What the draft of a chapter contains, scene by scene: where each scene
starts, how long it is, who speaks and how much is dialogue. An editor's
reverse outline, from the text alone. The model's reading of the same
scenes (whose point of view, what happens, what it changes) is
``chapter_digest``; piece 7.2 joins the two.

**Scenes** are split at a scene-break line (``***``, ``* * *``, ``#`` …:
``markdown_editor.SCENE_BREAKS``) or at two or more blank lines in a row.
This is the one rules-based scene splitter; other code should use
``split_scenes``. **Scene markers** (7.4, ``src/data/scene_marks``) are
breaks kept beside the text, never in it: pass their offsets as
``marks`` and a scene starts at each of them as well.

**Speakers** come from ``dialogue_speakers.attribute_lines`` (tags and
action beats). A line whose speaker it cannot tell counts as dialogue but
not for anyone.

**Cached** in memory by the text's hash and the character names, so
showing the outline again costs nothing. Writes nothing. No Qt.
"""

from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from src.utils.markdown_editor import is_scene_break

_QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_CACHE: "OrderedDict[str, List[Scene]]" = OrderedDict()
_CACHE_SIZE = 64


@dataclass
class Scene:
    number: int
    start: int                    # offset of the scene's first character in the text
    end: int
    words: int
    dialogue_words: int
    speakers: List[Tuple[str, int]] = field(default_factory=list)   # (name, lines), most first
    unattributed: int = 0         # quoted lines with no clear speaker
    opening: str = ""             # the scene's first words, to find it

    @property
    def dialogue_share(self) -> float:
        return self.dialogue_words / self.words if self.words else 0.0


def _words(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9’']+", text))


def split_scenes(text: str, marks: Iterable[int] = ()) -> List[Tuple[int, int]]:
    """[(start, end)] of each scene in ``text``; breaks are not part of a
    scene. A text with no breaks is one scene. ``marks`` are offsets where
    a scene also starts (the scene markers, 7.4: each the start of a
    paragraph); one already at a scene's start changes nothing."""
    text = text or ""
    spans: List[Tuple[int, int]] = []
    start = 0
    pos = 0
    blank_run = 0
    blank_from = 0
    for line in text.split("\n"):
        line_end = pos + len(line)
        if is_scene_break(line):
            spans.append((start, pos))
            start = line_end + 1
            blank_run = 0
        elif not line.strip():
            if blank_run == 0:
                blank_from = pos
            blank_run += 1
            if blank_run == 2:                     # two blank lines in a row
                spans.append((start, blank_from))
                start = line_end + 1
            elif blank_run > 2:
                start = line_end + 1
        else:
            blank_run = 0
        pos = line_end + 1
    spans.append((start, len(text)))
    spans = [(s, e) for s, e in spans if text[s:e].strip()]
    for m in sorted({int(m) for m in marks or () if 0 < int(m) < len(text)}):
        for i, (s, e) in enumerate(spans):
            if s < m < e and text[s:m].strip() and text[m:e].strip():
                spans[i:i + 1] = [(s, m), (m, e)]
                break
    return spans


def _opening(text: str, n: int = 10) -> str:
    words = text.strip().split()
    return " ".join(words[:n])


def outline(text: str, names: Iterable[str] = (), marks: Iterable[int] = ()) -> List[Scene]:
    """The chapter's scenes, in order (``marks``: as ``split_scenes``)."""
    names = sorted({n for n in names if n})
    marks = sorted({int(m) for m in marks or ()})
    key = hashlib.sha1(((text or "") + "\x00" + "\x01".join(names) + "\x00"
                        + ",".join(map(str, marks))).encode("utf-8")).hexdigest()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    from src.ai.dialogue_speakers import attribute_lines
    scenes: List[Scene] = []
    for n, (s, e) in enumerate(split_scenes(text, marks), 1):
        part = text[s:e]
        counts: Dict[str, int] = {}
        unattributed = 0
        for line in attribute_lines(part, names):
            if line.speaker:
                counts[line.speaker] = counts.get(line.speaker, 0) + 1
            else:
                unattributed += 1
        dialogue = sum(_words(m.group(0)) for m in _QUOTED.finditer(part))
        lead = len(part) - len(part.lstrip())
        scenes.append(Scene(number=n, start=s + lead, end=e, words=_words(part),
                            dialogue_words=dialogue,
                            speakers=sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])),
                            unattributed=unattributed, opening=_opening(part)))
    _CACHE[key] = scenes
    if len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return scenes


def describe(scene: Scene) -> str:
    """One line for the outline: length, dialogue, who speaks."""
    share = round(scene.dialogue_share * 100)
    who = ", ".join(f"{name} ({n})" for name, n in scene.speakers[:4])
    if scene.unattributed:
        who = (who + ", " if who else "") + f"unclear ({scene.unattributed})"
    talk = f"{share}% dialogue" + (f": {who}" if who else "") if scene.dialogue_words \
        else "no dialogue"
    return f"{scene.words:,} words · {talk}"
