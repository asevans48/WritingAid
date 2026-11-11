"""Who says each line of dialogue — from tags and action beats, no model.

Small models misread dialogue: a name inside the quote ("Please, Mara")
is taken for the speaker, or a line is pinned on whoever was mentioned
last. Labelling each line from the text's own evidence first and giving
the labels to the model prevents that.

Evidence, strongest first:
  * a dialogue tag naming the speaker — ``"Go," Tobin said`` /
    ``said Tobin`` / ``Tobin asked, "Why?"``
  * an action beat in the same paragraph whose subject is a character —
    ``Tobin pushed off. "Go."``
  * a pronoun tag (``she said``) — the character the paragraph (or the
    one before) is about, marked as likely.
Names inside the quote followed or preceded by a comma are addressed,
not speaking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List

SPEECH_VERBS = (
    "said|says|asked|asks|replied|replies|whispered|whispers|shouted|shouts|muttered|mutters|"
    "called|calls|answered|answers|snapped|snaps|hissed|hisses|murmured|murmurs|yelled|yells|"
    "cried|cries|added|adds|continued|continues|began|begins|demanded|demands|insisted|"
    "insists|growled|growls|breathed|breathes|told|tells|warned|warns|laughed|laughs|"
    "sighed|sighs|admitted|admits|repeated|repeats|offered|offers|pleaded|pleads|"
    "protested|protests|went on|shot back|managed")
_QUOTE_RX = re.compile(r'"([^"\n]+)"|“([^”\n]+)”')
_PRONOUN = r"(?:he|she|they|I|we)"


@dataclass
class Line:
    quote: str
    speaker: str = ""          # canonical character name, or ""
    certainty: str = ""        # "tag", "beat", "likely" or ""
    addressed: str = ""        # a character named inside the quote as addressee

    def label(self) -> str:
        who = (self.speaker if self.certainty in ("tag", "beat") else
               f"probably {self.speaker}" if self.speaker else "unclear")
        if self.addressed and self.addressed == self.speaker:
            to = f" (but the line addresses {self.addressed} — check the tag)"
        else:
            to = f" (speaking to {self.addressed})" if self.addressed else ""
        return f"“{_short(self.quote)}” — {who}{to}"


def _short(text: str, n: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _name_index(names: Iterable[str]) -> Dict[str, str]:
    """Variant (full name, first name, surname) → canonical name."""
    index: Dict[str, str] = {}
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        index.setdefault(name, name)
        parts = name.split()
        if len(parts) > 1:
            for part in (parts[0], parts[-1]):
                if len(part) > 2:
                    index.setdefault(part, name)
    return index


def _alternation(index: Dict[str, str]) -> str:
    return "|".join(sorted((re.escape(v) for v in index), key=len, reverse=True))


def attribute_lines(text: str, names: Iterable[str]) -> List[Line]:
    """Every quoted line in ``text`` with its most likely speaker."""
    index = _name_index(names)
    if not index:
        return [Line(q.group(1) or q.group(2)) for q in _QUOTE_RX.finditer(text or "")]
    alts = _alternation(index)
    rx = re.compile(rf"\b({alts})\b")
    tag_after = re.compile(rf"^\s*,?\s*(?:(?P<n1>{alts})\s+(?:{SPEECH_VERBS})"
                           rf"|(?:{SPEECH_VERBS})\s+(?P<n2>{alts})"
                           rf"|(?P<p>{_PRONOUN})\s+(?:{SPEECH_VERBS}))\b")
    tag_before = re.compile(rf"\b(?P<n>{alts})\s+(?:{SPEECH_VERBS})\s*,?\s*:?\s*$")

    lines: List[Line] = []
    paragraphs = (text or "").split("\n")
    recent: List[str] = []                       # names mentioned, latest last
    for para in paragraphs:
        prose = _QUOTE_RX.sub(" ", para)
        mentioned = [index[m.group(1)] for m in rx.finditer(prose)]
        in_paragraph: List[Line] = []
        for q in _QUOTE_RX.finditer(para):
            quote = q.group(1) or q.group(2)
            line = Line(quote)
            inside = [m for m in rx.finditer(quote)]
            for m in inside:
                around = quote[max(0, m.start() - 2):m.end() + 1]
                if "," in around or m.end() == len(quote.rstrip(".!?…")):
                    line.addressed = index[m.group(1)]
                    break
            after = para[q.end():q.end() + 60]
            before = para[max(0, q.start() - 60):q.start()]
            m_after, m_before = tag_after.search(after), tag_before.search(before)
            if m_after and (m_after.group("n1") or m_after.group("n2")):
                line.speaker = index[m_after.group("n1") or m_after.group("n2")]
                line.certainty = "tag"
            elif m_before:
                line.speaker, line.certainty = index[m_before.group("n")], "tag"
            else:
                # Action beat: the last prose sentence before the quote in this
                # paragraph, if it opens with a character's name.
                beat = re.split(r"(?<=[.!?…])\s+", _QUOTE_RX.sub(" ", para[:q.start()]).strip())[-1]
                opener = rx.match(beat.strip()) if beat else None
                if opener:
                    line.speaker, line.certainty = index[opener.group(1)], "beat"
                elif m_after and m_after.group("p"):          # "she said"
                    candidates = [n for n in (mentioned or recent[-3:]) if n != line.addressed]
                    if candidates:
                        line.speaker, line.certainty = candidates[-1], "likely"
            if not line.speaker and in_paragraph and in_paragraph[-1].speaker:
                # A paragraph is one speaker's: '"Because," she said, "the bells."'
                line.speaker = in_paragraph[-1].speaker
                line.certainty = in_paragraph[-1].certainty
            in_paragraph.append(line)
            lines.append(line)
        recent += mentioned
    return lines


def speaker_notes(text: str, names: Iterable[str], limit: int = 12) -> str:
    """Prompt block labelling each line of dialogue in ``text``."""
    lines = attribute_lines(text, names)
    if not lines:
        return ""
    return "\n".join(f"- {l.label()}" for l in lines[:limit])
