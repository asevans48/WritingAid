"""The order things happen in — and rewrites that reverse it.

Small local models often reorder actions while rewriting: someone
returns to their room before going to the bathroom. This module lists a
passage's actions in the order they happen (reading "after", "before",
"once" correctly, so "Before returning to her room, she went to the
bathroom" is bathroom first) and reports when a rewrite puts an action
before one that has to come first.

Only actions count (clauses with a verb like "went", "opened",
"returned"); moving a description ("The room was dark") is not a problem.
A reorder the critique itself asked for ("[3] should come before [2]")
is allowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, List, Optional, Set, Tuple

_IRREGULAR = set("""went came ran sat stood took got left made saw put found gave told said held fell
brought began drew drank ate rose shut threw wore woke wrote kept led lay slept swam caught bought
built cut dug fed felt fought flew forgot froze grabbed hid hit hung knelt knew lit lost meant met
paid read rode rang sang sank shook shot slid spoke spun stole struck swept swung taught tore thought
understood won wound goes comes runs sits stands takes gets leaves makes sees puts finds gives tells
says holds falls brings begins opens closes walks returns turns steps pulls pushes reaches climbs
drops picks lifts""".split())
_NOT_ACTIONS = {"was", "were", "had", "seemed", "looked", "felt", "need", "needed", "used",
                "red", "bed", "shed", "seed", "need", "speed", "tired", "scared", "worried"}
_STOP = set("""the a an and or but of to in on at by for with from as is was were be been are it its
this that these those not no so than then into about over his her him she he they them their there
here had has have did does do would could should will just only very what when where which who whom
while all any some out off up down back again still even once i me my we us our you your
behind beneath under below above across inside outside along around through toward towards past
near beside between against onto upon within without""".split())
_WORD_RX = re.compile(r"[A-Za-z][A-Za-z'’]*")
_SENT_RX = re.compile(r"(?<=[.!?…])[\"”’']?\s+(?=[\"“‘']?[A-Z])")
_SPLIT_RX = re.compile(r"\s*(?:;|\s—\s|—|, and then |, then | and then | then |, and | and )\s*",
                       re.I)
_REORDER_WORDS = ("order", "reorder", "re-order", "swap", "move", "earlier", "later", "first",
                  "flashback", "sequence")


@dataclass
class Event:
    text: str
    sentence: int                  # 1-based sentence number in the passage
    words: Set[str] = field(default_factory=set)
    flashback: bool = False        # "she had gone…", "…first": told out of order on purpose


_FLASHBACK_RX = re.compile(r"\bhad\s+(?:\w+ly\s+|already\s+|just\s+)?\w+(?:ed|en|ne|one|ght|t|wn|un|ung)\b"
                           r"|\b(?:first|earlier|already|beforehand)\b", re.I)


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


# Verbs too common to say two clauses are the same action ("went to the
# bathroom" vs "went back to her room").
_GENERIC_VERBS = set("""went go goe come came cam got get took tak made mak put turn turned
look looked mov moved step stepped walk walked sat stood ran run said""".split())

# Stems of the words that make a clause an action (as stored in Event.words).
_STEMMED_VERBS = {w[:-2] if w.endswith("ed") and len(w) > 4 else w for w in _IRREGULAR}


def _verbish(w: str) -> bool:
    return w in _IRREGULAR or ((w.endswith("ed") or w.endswith("ing")) and len(w) > 4)


def _content(text: str) -> Set[str]:
    out = set()
    for raw in _WORD_RX.findall(text or ""):
        w = raw.lower().replace("’", "'")
        if raw[0].isupper() and not _verbish(w):   # names (a capitalised verb still counts)
            continue
        if len(w) >= 3 and w not in _STOP:
            out.add(_stem(w))
    return out


def _is_action(text: str) -> bool:
    for raw in _WORD_RX.findall(text or ""):
        w = raw.lower()
        if w in _NOT_ACTIONS:
            continue
        if w in _IRREGULAR or (w.endswith("ed") and len(w) > 4):
            return True
    return False


def _temporal_parts(sentence: str) -> List[str]:
    """A sentence's parts in the order they happen."""
    s = sentence.strip().rstrip(".!?…\"”'")
    m = re.match(r"^(?:after|once|as soon as|when|having)\s+(.+?),\s*(.+)$", s, re.I)
    if m:
        return [m.group(1), m.group(2)]
    m = re.match(r"^before\s+(.+?),\s*(.+)$", s, re.I)
    if m:
        return [m.group(2), m.group(1)]
    m = re.match(r"^(.+?),?\s+(?:after|once)\s+(.+)$", s, re.I)
    if m and _is_action(m.group(2)):
        # "X after Y, then Z": Y, X, Z — the "then" part follows the main action.
        earlier, *later = re.split(r",\s*(?:and\s+)?then\s+|;\s*", m.group(2), maxsplit=1)
        return [earlier, m.group(1)] + later
    m = re.match(r"^(.+?),?\s+before\s+(.+)$", s, re.I)
    if m and _is_action(m.group(2)):
        return [m.group(1), m.group(2)]
    return [s]


def _sentences(text: str) -> List[str]:
    out = []
    for para in (text or "").split("\n"):
        out += [s for s in _SENT_RX.split(para.strip()) if s.strip()]
    return out


def events(text: str) -> List[Event]:
    """The passage's actions, in the order they happen."""
    out: List[Event] = []
    for n, sentence in enumerate(_sentences(text), 1):
        for part in _temporal_parts(sentence):
            for clause in _SPLIT_RX.split(part):
                clause = clause.strip(" ,")
                words = _content(clause)
                if len(words) >= 2 and _is_action(clause):
                    out.append(Event(clause, n, words, bool(_FLASHBACK_RX.search(clause))))
    return out


def events_prompt(text: str) -> str:
    """Prompt block: the actions in order, to keep."""
    evs = events(text)
    if len(evs) < 2:
        return ""
    return ("EVENTS IN THE ORDER THEY HAPPEN (keep this order in every rewrite unless you "
            "named an order problem):\n" + "\n".join(f"{i}. {e.text}" for i, e in enumerate(evs, 1)))


ORDER_RULE = (
    "Keep events in the order they happen. Never move an action before something that has "
    "to happen first (someone goes to the bathroom before they return to their room). "
    "Change the order only to fix an order problem you named; \"After X, Y\" and "
    "\"Before Y, X\" both mean X happens first.")


def _overlap(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _match(original: List[Event], rewrite: List[Event]) -> List[Tuple[int, Event]]:
    """(index of the original event, rewrite event), in rewrite order."""
    pairs = []
    for j, r in enumerate(rewrite):
        for i, o in enumerate(original):
            shared = o.words & r.words
            # Same action = same verb, or two shared words — sharing only the
            # place ("behind the crates") isn't the same action.
            same_verb = any((_verbish(w) or w in _STEMMED_VERBS) and w not in _GENERIC_VERBS
                            for w in shared)
            score = _overlap(o.words, r.words)
            if score >= 0.5 and (len(shared) >= 2 or same_verb):
                pairs.append((score, i, j))
    pairs.sort(key=lambda p: -p[0])
    used_o, used_r, matched = set(), set(), {}
    for score, i, j in pairs:
        if i in used_o or j in used_r:
            continue
        # A match must be clearly better than this rewrite event's next best.
        used_o.add(i)
        used_r.add(j)
        matched[j] = i
    return [(matched[j], rewrite[j]) for j in sorted(matched)]


def allowed_swaps(notes: Iterable[str]) -> Set[FrozenSet[int]]:
    """Sentence-number pairs the critique said were out of order:
    "[3] should come before [2]", "swap [2] and [3]", "[2] and [3] are
    out of order"."""
    out: Set[FrozenSet[int]] = set()
    for note in notes:
        low = (note or "").lower()
        if not any(w in low for w in ("before", "after", "swap", "order", "revers", "first")):
            continue
        nums = [int(n) for n in re.findall(r"\[(\d+)\]", note)]
        for a in nums:
            for b in nums:
                if a != b:
                    out.add(frozenset((a, b)))
    return out


def order_problems(original: str, rewrite: str,
                   allowed: Optional[Set[FrozenSet[int]]] = None) -> List[str]:
    """Places where ``rewrite`` makes an action happen before one that comes
    first in ``original``."""
    allowed = allowed or set()
    orig = events(original)
    if len(orig) < 2:
        return []
    # A rewrite may tell something as a flashback ("she had gone…") — the
    # past perfect keeps the real order.
    matched = [(i, e) for i, e in _match(orig, events(rewrite)) if not e.flashback]
    out = []
    for x in range(len(matched)):
        for y in range(x + 1, len(matched)):
            i, ri = matched[x]
            k, rk = matched[y]
            if i <= k:
                continue
            a, b = orig[k], orig[i]          # a happens first in the original
            if a.sentence != b.sentence and frozenset((a.sentence, b.sentence)) in allowed:
                continue
            out.append(f"reverses the order of events: “{_short(ri.text)}” now happens "
                       f"before “{_short(rk.text)}”")
            return out
    return out


def asks_for_reorder(focus: str) -> bool:
    low = (focus or "").lower()
    return any(w in low for w in _REORDER_WORDS)


def _short(text: str, n: int = 50) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"
