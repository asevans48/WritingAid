"""Manuscript-wide consistency checks.

Finds the slips readers notice and per-chapter checks miss, across every
chapter (and novella):

  name          — character / place / faction names misspelled against the
                  project's records ("Marra" for Mara, "Grewater")
  name_case     — a recorded name written in the wrong case ("ash wardens")
  variant       — the same word spelled two ways (grey/gray, OK/okay,
                  toward/towards) — includes UK vs US spellings
  hyphenation   — e-mail / email / e mail
  capitalization — a word capitalised in some places and not others
                  ("the Council" / "the council")
  numbers       — digits and spelled-out numbers mixed in prose
  punctuation   — straight vs curly quotes, "..." vs "…", "--" vs "—"

Each finding is a group with the forms used and a preferred form (the
canonical name, or the majority usage), plus every occurrence so the UI
can jump to each and "change all".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

Chapter = Tuple[str, str, str]  # (chapter_id, title, text)


@dataclass
class Occurrence:
    chapter_id: str
    chapter_title: str
    start: int
    end: int
    text: str
    replacement: str = ""       # what "change all to <preferred>" writes here


@dataclass
class ConsistencyGroup:
    kind: str
    key: str
    title: str
    message: str
    forms: Dict[str, int]
    preferred: str
    # Every occurrence of every form for variant / hyphenation /
    # capitalisation (so any form can be chosen); only the ones to fix
    # for the other kinds.
    occurrences: List[Occurrence] = field(default_factory=list)
    review: bool = False        # judgement call (may be intentional)

    @property
    def targets(self) -> List[str]:
        """Forms the writer can unify on (preferred first)."""
        if self.kind in ("variant", "hyphenation", "capitalization"):
            return [self.preferred] + [f for f in self.forms if f != self.preferred]
        return [self.preferred]

    def replacement_for(self, occ: Occurrence, target: str) -> str:
        """Replacement for ``occ`` when unifying on ``target``."""
        if self.kind in ("numbers", "punctuation"):
            return occ.replacement if target == self.preferred else occ.text
        if self.kind == "capitalization":
            if occ.text.lower() != target.lower():
                return occ.text
            return target
        if self.kind in ("name", "name_case"):
            return target
        return _match_case(occ.text, target)

    def changes(self, target: Optional[str] = None) -> List[Occurrence]:
        """Occurrences that unifying on ``target`` would change."""
        target = target or self.preferred
        return [o for o in self.occurrences if self.replacement_for(o, target) != o.text]


KIND_LABELS = {
    "name": "Name spellings", "name_case": "Name capitalisation", "variant": "Spelling variants",
    "hyphenation": "Hyphenation", "capitalization": "Capitalisation", "numbers": "Numbers",
    "punctuation": "Punctuation style",
}

VARIANT_PAIRS: List[Tuple[str, ...]] = [
    ("grey", "gray"), ("okay", "ok", "o.k."), ("toward", "towards"), ("afterward", "afterwards"),
    ("backward", "backwards"), ("forward", "forwards"), ("upward", "upwards"),
    ("alright", "all right"), ("judgement", "judgment"), ("acknowledgement", "acknowledgment"),
    ("amongst", "among"), ("whilst", "while"), ("learnt", "learned"), ("spelt", "spelled"),
    ("burnt", "burned"), ("dreamt", "dreamed"), ("leapt", "leaped"), ("knelt", "kneeled"),
    ("smelt", "smelled"), ("spilt", "spilled"), ("dove", "dived"), ("mum", "mom"),
    ("colour", "color"), ("honour", "honor"), ("favour", "favor"), ("armour", "armor"),
    ("harbour", "harbor"), ("rumour", "rumor"), ("labour", "labor"), ("neighbour", "neighbor"),
    ("behaviour", "behavior"), ("humour", "humor"), ("valour", "valor"), ("vapour", "vapor"),
    ("splendour", "splendor"), ("parlour", "parlor"), ("odour", "odor"), ("ardour", "ardor"),
    ("centre", "center"), ("theatre", "theater"), ("metre", "meter"), ("sombre", "somber"),
    ("spectre", "specter"), ("sabre", "saber"), ("fibre", "fiber"), ("calibre", "caliber"),
    ("realise", "realize"), ("realised", "realized"), ("recognise", "recognize"),
    ("recognised", "recognized"), ("apologise", "apologize"), ("organise", "organize"),
    ("organised", "organized"), ("analyse", "analyze"), ("paralysed", "paralyzed"),
    ("travelled", "traveled"), ("travelling", "traveling"), ("cancelled", "canceled"),
    ("modelled", "modeled"), ("labelled", "labeled"), ("fuelled", "fueled"),
    ("defence", "defense"), ("offence", "offense"), ("licence", "license"), ("pretence", "pretense"),
    ("plough", "plow"), ("sceptic", "skeptic"), ("sceptical", "skeptical"), ("jewellery", "jewelry"),
    ("cheque", "check"), ("tyre", "tire"), ("kerb", "curb"), ("aeroplane", "airplane"),
    ("grey-haired", "gray-haired"), ("greyish", "grayish"),
]


def _match_case(src: str, target: str) -> str:
    # All-caps only carries over for real shouting ("GREY"), not short
    # forms like "OK" → "Okay".
    if src.isupper() and len(src) > 3:
        return target.upper()
    if src[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def _edit_distance(a: str, b: str) -> int:
    if abs(len(a) - len(b)) > 2:
        return 3
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _is_sentence_start(text: str, pos: int) -> bool:
    # Only the few characters before the word matter (re-scanning the
    # whole prefix made long chapters quadratic).
    window = text[max(0, pos - 16):pos]
    before = re.sub(r"[ \t\"“‘'(\[\-—–*_]+$", "", window)
    if not before:
        return pos - len(window) <= 0 or text[max(0, pos - 17)] == "\n"
    return before[-1] in ".!?…:\n"


def _inside_quotes(text: str, pos: int) -> bool:
    line_start = text.rfind("\n", 0, pos) + 1
    seg = text[line_start:pos]
    return (seg.count('"') % 2 == 1) or (seg.count("“") > seg.count("”"))


_SMALL = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
          "fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_to_words(n: int) -> str:
    if n < 20:
        return _SMALL[n]
    if n < 100:
        t, u = divmod(n, 10)
        return _TENS[t - 2] + ("" if u == 0 else "-" + _SMALL[u])
    return str(n)


_WORD_NUMBER_RX = re.compile(r"\b(?:" + "|".join(_SMALL[1:] + _TENS) + r")(?:-(?:"
                             + "|".join(_SMALL[1:10]) + r"))?\b", re.I)


class ConsistencyChecker:
    def __init__(self, chapters: Sequence[Chapter], canon_names: Iterable[str] = (),
                 is_known_word: Optional[Callable[[str], bool]] = None,
                 ignored: Iterable[str] = ()):
        self.chapters = [c for c in chapters if (c[2] or "").strip()]
        self.canon = [n for n in canon_names if n and n.strip()]
        self.is_known = is_known_word or _default_known_word()
        self.ignored = set(ignored)

    def run(self) -> List[ConsistencyGroup]:
        groups: List[ConsistencyGroup] = []
        for fn in (self._names, self._name_case, self._variants, self._hyphenation,
                   self._capitalization, self._numbers, self._punctuation):
            try:
                groups.extend(fn())
            except Exception as e:      # one bad check shouldn't sink the rest
                print(f"[consistency] {fn.__name__} failed: {e}")
        groups = [g for g in groups if g.key not in self.ignored and g.changes()]
        order = list(KIND_LABELS)
        return sorted(groups, key=lambda g: (order.index(g.kind), g.review,
                                             -len(g.changes())))

    # ── helpers ────────────────────────────────────────────────────

    def _find_all(self, rx: "re.Pattern") -> List[Tuple[Chapter, "re.Match"]]:
        out = []
        for ch in self.chapters:
            for m in rx.finditer(ch[2]):
                out.append((ch, m))
        return out

    @staticmethod
    def _occ(ch: Chapter, start: int, end: int, replacement: str = "") -> Occurrence:
        return Occurrence(ch[0], ch[1], start, end, ch[2][start:end], replacement)

    # ── checks ─────────────────────────────────────────────────────

    def _names(self) -> List[ConsistencyGroup]:
        tokens: Dict[str, str] = {}
        for name in self.canon:
            for t in re.findall(r"[A-Za-z][A-Za-z'’]+", name):
                if len(t) >= 4:
                    tokens[t.lower()] = t
        if not tokens:
            return []
        groups: Dict[str, ConsistencyGroup] = {}
        cap_rx = re.compile(r"\b[A-Z][a-z'’]{2,}\b")
        counts = Counter()
        for ch, m in self._find_all(cap_rx):
            w = m.group(0).rstrip("'’s")
            low = w.lower()
            if low in tokens:
                counts[tokens[low]] += 1
                continue
            if self.is_known(low):
                continue
            best = None
            for tlow, canon in tokens.items():
                limit = 1 if len(tlow) <= 5 else 2
                if tlow[0] == low[0] or tlow[-2:] == low[-2:]:
                    d = _edit_distance(low, tlow)
                    if d <= limit and (best is None or d < best[0]):
                        best = (d, canon)
            if best is None:
                continue
            canon = best[1]
            g = groups.get(canon)
            if g is None:
                g = groups[canon] = ConsistencyGroup(
                    "name", f"name:{canon}", f"{canon}",
                    f"Looks like a misspelling of “{canon}” (from your project's records).",
                    {}, canon)
            g.forms[w] = g.forms.get(w, 0) + 1
            g.occurrences.append(self._occ(ch, m.start(), m.start() + len(w), canon))
        for canon, g in groups.items():
            g.forms = {canon: counts.get(canon, 0), **g.forms}
            g.title = f"{canon} — also spelled " + ", ".join(
                f"“{f}” ({n}×)" for f, n in g.forms.items() if f != canon)
        return list(groups.values())

    def _name_case(self) -> List[ConsistencyGroup]:
        groups = []
        for name in self.canon:
            if not any(c.isupper() for c in name) or len(name) < 4:
                continue
            rx = re.compile(r"\b" + re.escape(name) + r"\b", re.I)
            wrong = []
            right = 0
            for ch, m in self._find_all(rx):
                if m.group(0) == name:
                    right += 1
                elif m.group(0).lower() == name.lower() and not (
                        _is_sentence_start(ch[2], m.start()) and m.group(0)[0].isupper()):
                    # Common-word names ("Will", "Hope") written lowercase
                    # are usually the ordinary word, not the name.
                    if " " not in name and self.is_known(name.lower()):
                        continue
                    wrong.append(self._occ(ch, m.start(), m.end(), name))
            # The record is the authority: a wrongly-cased name is flagged
            # even if the manuscript never writes it correctly.
            if wrong:
                groups.append(ConsistencyGroup(
                    "name_case", f"case:{name}", f"{name} — written “{wrong[0].text}” "
                    f"{len(wrong)}×", f"Recorded as “{name}”.",
                    {name: right, wrong[0].text: len(wrong)}, name, wrong))
        return groups

    def _variants(self) -> List[ConsistencyGroup]:
        groups = []
        for forms in VARIANT_PAIRS:
            rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(f) for f in forms) + r")(?![\w-])",
                            re.I)
            hits = self._find_all(rx)
            by_form: Dict[str, list] = {}
            for ch, m in hits:
                f = m.group(1).lower()
                if f == "ok" and m.group(1) not in ("OK", "Ok", "ok"):
                    continue
                by_form.setdefault(f, []).append((ch, m))
            if len(by_form) < 2:
                continue
            counts = {f: len(v) for f, v in by_form.items()}
            preferred = max(counts, key=lambda f: (counts[f], -forms.index(f)))
            occ = [self._occ(ch, m.start(1), m.end(1)) for v in by_form.values() for ch, m in v]
            groups.append(ConsistencyGroup(
                "variant", "variant:" + "/".join(forms), " / ".join(
                    f"“{f}” ({counts.get(f, 0)}×)" for f in forms if f in counts),
                f"Pick one spelling — “{preferred}” is used most.", counts, preferred, occ))
        return groups

    def _hyphenation(self) -> List[ConsistencyGroup]:
        hyph = Counter(m.group(0).lower() for _, m in
                       self._find_all(re.compile(r"\b[A-Za-z]+-[A-Za-z]{2,}\b")))
        groups = []
        for h in hyph:
            a, b = h.split("-", 1)
            if a.lower() in ("self", "ex") or len(a) + len(b) < 5:
                continue
            closed_rx = re.compile(rf"\b{re.escape(a + b)}\b", re.I)
            open_rx = re.compile(rf"\b{re.escape(a)} {re.escape(b)}\b", re.I)
            hyph_rx = re.compile(rf"\b{re.escape(a)}-{re.escape(b)}\b", re.I)
            found = {h: self._find_all(hyph_rx), a + b: self._find_all(closed_rx)}
            if not self.is_known(a + b) and not found[a + b]:
                found.pop(a + b)
            opens = self._find_all(open_rx)
            if opens and len(opens) <= 20 and len(hyph_rx.pattern) > 8:
                # "e mail" — only count the open form for short compounds
                # where it's clearly the same word.
                if len(a) <= 3:
                    found[f"{a} {b}"] = opens
            found = {f: v for f, v in found.items() if v}
            if len(found) < 2:
                continue
            counts = {f: len(v) for f, v in found.items()}
            preferred = max(counts, key=lambda f: (counts[f], f == h))
            occ = [self._occ(ch, m.start(), m.end()) for v in found.values() for ch, m in v]
            groups.append(ConsistencyGroup(
                "hyphenation", f"hyphen:{a}{b}", " / ".join(f"“{f}” ({n}×)" for f, n in counts.items()),
                f"Hyphenation varies — “{preferred}” is used most.", counts, preferred, occ))
        return groups

    def _capitalization(self) -> List[ConsistencyGroup]:
        canon_low = {t.lower() for n in self.canon for t in re.findall(r"[A-Za-z]+", n)}
        caps: Dict[str, list] = {}
        lows: Dict[str, list] = {}
        word_rx = re.compile(r"\b[A-Za-z]{4,}\b")
        for ch, m in self._find_all(word_rx):
            w = m.group(0)
            low = w.lower()
            if low in canon_low or _is_sentence_start(ch[2], m.start()):
                continue
            if w[0].isupper() and w[1:].islower():
                caps.setdefault(low, []).append((ch, m))
            elif w.islower():
                lows.setdefault(low, []).append((ch, m))
        groups = []
        for low, cap_hits in caps.items():
            low_hits = lows.get(low, [])
            if len(cap_hits) < 2 or not low_hits or not self.is_known(low):
                continue
            preferred_cap = len(cap_hits) >= len(low_hits)
            preferred = low.capitalize() if preferred_cap else low
            occ = [self._occ(ch, m.start(), m.end()) for ch, m in cap_hits + low_hits]
            groups.append(ConsistencyGroup(
                "capitalization", f"caps:{low}",
                f"“{low.capitalize()}” ({len(cap_hits)}×) / “{low}” ({len(low_hits)}×)",
                "Capitalised in some places and not others — fine if one is a title or "
                "name and the other the ordinary word; otherwise pick one.",
                {low.capitalize(): len(cap_hits), low: len(low_hits)}, preferred, occ,
                review=True))
        return groups

    def _numbers(self) -> List[ConsistencyGroup]:
        digit_rx = re.compile(r"(?<![\w.,:/$£€#-])([1-9][0-9]?)(?![\w.,:/%°-])")
        digits = [(ch, m) for ch, m in self._find_all(digit_rx)
                  if not _inside_quotes(ch[2], m.start())]
        words = [(ch, m) for ch, m in self._find_all(_WORD_NUMBER_RX)
                 if not _inside_quotes(ch[2], m.start())]
        if not digits or not words:
            return []
        # Fiction convention: spell out numbers under 100 in narration.
        if len(words) * 3 < len(digits):
            return []
        occ = []
        for ch, m in digits:
            word = number_to_words(int(m.group(1)))
            if _is_sentence_start(ch[2], m.start(1)):
                word = word[:1].upper() + word[1:]
            occ.append(self._occ(ch, m.start(1), m.end(1), word))
        return [ConsistencyGroup(
            "numbers", "numbers", f"Numbers: {len(words)} spelled out, {len(digits)} as digits",
            "Narration mixes digits and words; fiction usually spells out numbers under 100.",
            {"words": len(words), "digits": len(digits)}, "words", occ)]

    def _text(self, chapter_id: str) -> str:
        return next((c[2] for c in self.chapters if c[0] == chapter_id), "")

    def _punctuation(self) -> List[ConsistencyGroup]:
        groups = []
        straight = self._find_all(re.compile(r'"'))
        curly = self._find_all(re.compile(r"[“”]"))
        if straight and curly:
            prefer_curly = len(curly) >= len(straight)
            if prefer_curly:
                occ = []
                for ch, m in straight:
                    prev = ch[2][m.start() - 1] if m.start() else " "
                    opening = prev.isspace() or prev in "([{—–-"
                    occ.append(self._occ(ch, m.start(), m.end(), "“" if opening else "”"))
            else:
                occ = [self._occ(ch, m.start(), m.end(), '"') for ch, m in curly]
            groups.append(ConsistencyGroup(
                "punctuation", "quotes", f"Quotes: {len(curly)} curly, {len(straight)} straight",
                "Straight and curly quotation marks are mixed.",
                {"curly": len(curly), "straight": len(straight)},
                "curly" if prefer_curly else "straight", occ))
        for key, a_rx, a, b_rx, b, label in (
                ("ellipsis", r"(?<!\.)\.\.\.(?!\.)", "...", r"…", "…", "Ellipses"),
                ("dash", r"(?<!-)--(?!-)", "--", r"—", "—", "Dashes")):
            ahits, bhits = self._find_all(re.compile(a_rx)), self._find_all(re.compile(b_rx))
            if ahits and bhits:
                pref_b = len(bhits) >= len(ahits)
                minority, repl = (ahits, b) if pref_b else (bhits, a)
                occ = [self._occ(ch, m.start(), m.end(), repl) for ch, m in minority]
                groups.append(ConsistencyGroup(
                    "punctuation", key, f"{label}: “{a}” ({len(ahits)}×) / “{b}” ({len(bhits)}×)",
                    f"{label} are typed two ways.", {a: len(ahits), b: len(bhits)},
                    b if pref_b else a, occ))
        return groups


def _default_known_word() -> Callable[[str], bool]:
    try:
        from spellchecker import SpellChecker
        sp = SpellChecker()
        cache: Dict[str, bool] = {}

        def known(w: str) -> bool:
            if w not in cache:
                cache[w] = bool(sp.known([w.lower()]))
            return cache[w]
        return known
    except Exception:
        return lambda w: False


def apply_group(group: ConsistencyGroup, target: str, texts: Dict[str, str],
                occurrences: Optional[List[Occurrence]] = None) -> Tuple[Dict[str, str], int]:
    """Return updated chapter texts with ``group`` unified on ``target``.
    Occurrences whose text no longer matches (edited since) are skipped."""
    occurrences = occurrences if occurrences is not None else group.changes(target)
    out = dict(texts)
    changed = 0
    by_ch: Dict[str, List[Occurrence]] = {}
    for o in occurrences:
        by_ch.setdefault(o.chapter_id, []).append(o)
    for cid, occs in by_ch.items():
        text = out.get(cid)
        if text is None:
            continue
        for o in sorted(occs, key=lambda o: -o.start):
            if text[o.start:o.end] != o.text:
                continue
            new = group.replacement_for(o, target)
            if new != o.text:
                text = text[:o.start] + new + text[o.end:]
                changed += 1
        out[cid] = text
    return out, changed
