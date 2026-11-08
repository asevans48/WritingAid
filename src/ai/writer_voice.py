"""Writer-voice fingerprint for rephrasing.

Measures how *this author* actually writes — from their own manuscript
text, not a genre default — and turns it into concrete prompt
directives plus a cheap fit score for candidate rewrites.

Pure Python (regex-level parsing), so it runs on a chapter in a few ms
and works in every rephrase mode, including offline/local models.

What it measures, all on narration (text outside quotation marks) so a
dialog-heavy chapter doesn't distort the author's own prose habits:

  * sentence length — mean, spread, share of short and long sentences
  * paragraph length (sentences per paragraph)
  * contraction rate, -ly adverb rate
  * punctuation habits — em-dashes, semicolons, colons, ellipses,
    exclamations, questions (per 100 sentences)
  * narrative person and tense
  * how sentences open (pronoun / article / conjunction / -ing)
  * recurring content words (the author's lexical fingerprint)
  * exemplar sentences — real narration sentences from near the
    selection, used as few-shot style anchors

It also pulls a character's own dialog lines from the manuscript so
the model hears how that character actually talks in this book.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_SENT_SPLIT = re.compile(r'(?<=[.!?…])["”’\')\]]*\s+(?=["“‘\'(\[]?[A-Z])')
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’]*")
_QUOTE_RE = re.compile(r'"[^"\n]*"|“[^”\n]*”')
_CONTRACTION_RE = re.compile(
    r"\b[A-Za-z]+(?:n['’]t|['’](?:s|re|ve|ll|d|m))\b", re.IGNORECASE)
_LY_EXCEPTIONS = {
    "only", "family", "early", "reply", "fly", "ally", "belly", "holy",
    "lily", "jelly", "rely", "supply", "apply", "ugly", "silly", "jolly",
    "daily", "likely", "lonely", "lovely", "friendly", "italy", "july",
    "emily", "kelly", "sally", "molly", "billy", "rally", "bully",
}
_FIRST_PERSON = {"i", "me", "my", "mine", "myself", "we", "us", "our"}
_SECOND_PERSON = {"you", "your", "yours", "yourself"}
_THIRD_PERSON = {"he", "she", "him", "her", "his", "hers", "they", "them",
                 "their", "himself", "herself", "themselves"}
_PAST_MARKERS = {"was", "were", "had", "did", "said", "went", "came",
                 "saw", "knew", "thought", "felt", "looked", "turned"}
_PRESENT_MARKERS = {"is", "are", "has", "does", "says", "goes", "comes",
                    "sees", "knows", "thinks", "feels", "looks", "turns", "am"}
_CONJ_OPENERS = {"and", "but", "so", "or", "yet", "because", "then"}
_ARTICLES = {"the", "a", "an", "this", "that"}
_STOPWORDS = set("""
a about above after again against all am an and any are as at be because
been before being below between both but by can could did do does doing
down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just me
more most my myself no nor not now of off on once only or other our ours
out over own same she should so some such than that the their theirs
them themselves then there these they this those through to too under
until up very was we were what when where which while who whom why will
with would you your yours yourself said like back one two still even
into onto upon around away then than through again didn't don't couldn't
wasn't weren't hadn't wouldn't it's i'm he's she's they're we're that's
there's what's let's i'd i'll i've you're you'll you've
""".split())


def _narration_only(text: str) -> str:
    """Strip quoted dialog, keeping the author's own prose."""
    return _QUOTE_RE.sub(" ", text or "")


def _sentences(text: str) -> List[str]:
    out = []
    for para in re.split(r"\n\s*\n|\n", text or ""):
        para = para.strip()
        if not para:
            continue
        out.extend(s.strip() for s in _SENT_SPLIT.split(para) if s.strip())
    return out


def _words(text: str) -> List[str]:
    return _WORD_RE.findall(text or "")


def _per100(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


@dataclass
class WriterVoice:
    """Measured voice of the author, plus their stated targets."""
    word_count: int = 0
    sentence_count: int = 0
    avg_sentence_len: float = 0.0
    sentence_len_stdev: float = 0.0
    short_sentence_pct: float = 0.0   # < 8 words
    long_sentence_pct: float = 0.0    # > 25 words
    sentences_per_paragraph: float = 0.0
    contractions_per_100_words: float = 0.0
    adverbs_per_100_words: float = 0.0
    punctuation_per_100_sentences: Dict[str, float] = field(default_factory=dict)
    person: str = ""
    tense: str = ""
    openers: Dict[str, float] = field(default_factory=dict)
    signature_words: List[str] = field(default_factory=list)
    exemplars: List[str] = field(default_factory=list)
    stated_targets: Dict[str, str] = field(default_factory=dict)

    @property
    def has_measurements(self) -> bool:
        return self.sentence_count >= 5

    @property
    def can_judge_absence(self) -> bool:
        """Enough text that "never uses X" is a real habit, not chance."""
        return self.sentence_count >= 30

    @property
    def is_empty(self) -> bool:
        return not self.has_measurements and not self.stated_targets

    # ------------------------------------------------------------------
    def to_prompt(self) -> str:
        """Concrete, checkable directives for the LLM."""
        if self.is_empty:
            return ""
        lines = ["AUTHOR'S VOICE — the rewrite must read as if this author wrote it. "
                 "Match these measured habits of their prose (narration, not dialog):"]
        if self.has_measurements:
            lines.append(
                f"• Sentence length: ~{self.avg_sentence_len:.0f} words on average "
                f"(spread ±{self.sentence_len_stdev:.0f}); "
                f"{self.short_sentence_pct:.0f}% short (<8 words), "
                f"{self.long_sentence_pct:.0f}% long (>25). Keep that rhythm.")
            if self.sentences_per_paragraph:
                lines.append(f"• Paragraphs run ~{self.sentences_per_paragraph:.1f} sentences.")
            if self.person or self.tense:
                lines.append(f"• Narration: {self.person or 'mixed'} person, "
                             f"{self.tense or 'mixed'} tense — do not switch.")
            c = self.contractions_per_100_words
            if c >= 1.5:
                lines.append(f"• Uses contractions freely in narration ({c:.1f}/100 words).")
            elif c <= 0.3:
                lines.append("• Avoids contractions in narration — keep them out of narrative lines.")
            a = self.adverbs_per_100_words
            if a <= 0.6:
                lines.append("• Sparing with -ly adverbs; carry meaning in verbs instead.")
            elif a >= 2.0:
                lines.append(f"• Comfortable with -ly adverbs ({a:.1f}/100 words).")
            used, avoided = [], []
            for mark, rate in self.punctuation_per_100_sentences.items():
                if rate >= 8:
                    used.append(f"{mark} ({rate:.0f}/100 sentences)")
                elif rate == 0 and self.can_judge_absence:
                    avoided.append(mark)
            if used:
                lines.append("• Punctuation habits: " + ", ".join(used) + ".")
            if avoided:
                lines.append("• Never uses: " + ", ".join(avoided)
                             + " — do not introduce them.")
            top_openers = [k for k, v in sorted(self.openers.items(), key=lambda kv: -kv[1])
                           if v >= 15][:3]
            if top_openers:
                lines.append("• Sentences commonly open with: " + ", ".join(
                    f"{k} ({self.openers[k]:.0f}%)" for k in top_openers) + ".")
            if self.signature_words:
                lines.append("• Recurring vocabulary (the author's word palette): "
                             + ", ".join(self.signature_words) + ".")
        if self.stated_targets:
            lines.append("Author's stated targets for this project:")
            for k, v in self.stated_targets.items():
                lines.append(f"  - {k}: {v}")
        if self.exemplars:
            lines.append("Samples of the author's own narration — match the voice, "
                         "do NOT copy content:")
            lines.extend(f'  » "{e}"' for e in self.exemplars)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def fit_score(self, candidate: str) -> Optional[float]:
        """0–1 estimate of how well a candidate matches the measured voice.

        Returns None when there's not enough author text to judge.
        Deliberately coarse: it catches obvious drift (sentence rhythm,
        punctuation the author never uses, contraction register,
        person/tense flips) rather than ranking subtle prose quality.
        """
        if not self.has_measurements or not (candidate or "").strip():
            return None
        narr = _narration_only(candidate)
        sents = _sentences(narr) or _sentences(candidate)
        words = _words(narr)
        if not sents or not words:
            return None
        penalties = 0.0

        avg = len(words) / len(sents)
        tol = max(self.sentence_len_stdev, 4.0)
        penalties += min(abs(avg - self.avg_sentence_len) / (2 * tol), 1.0) * 0.35

        for mark, rate in self.punctuation_per_100_sentences.items():
            if rate == 0 and self.can_judge_absence and mark in _PUNCT_PATTERNS and _PUNCT_PATTERNS[mark].search(narr):
                penalties += 0.1

        contr = len(_CONTRACTION_RE.findall(narr))
        if self.contractions_per_100_words <= 0.3 and contr and self.can_judge_absence:
            penalties += 0.1
        lower = [w.lower() for w in words]
        if self.person == "first" and not any(w in _FIRST_PERSON for w in lower) \
                and any(w in _THIRD_PERSON for w in lower):
            penalties += 0.2
        if self.person == "third" and any(w in {"i", "me", "my"} for w in lower):
            penalties += 0.2
        if self.tense:
            past = sum(w in _PAST_MARKERS for w in lower)
            pres = sum(w in _PRESENT_MARKERS for w in lower)
            if self.tense == "past" and pres > past + 1:
                penalties += 0.15
            if self.tense == "present" and past > pres + 1:
                penalties += 0.15
        return round(max(0.0, 1.0 - penalties), 2)


_PUNCT_PATTERNS = {
    "em-dashes": re.compile(r"—|--| - "),
    "semicolons": re.compile(r";"),
    "colons": re.compile(r":"),
    "ellipses": re.compile(r"\.\.\.|…"),
    "exclamations": re.compile(r"!"),
    "questions": re.compile(r"\?"),
}


def analyze_writer_voice(
    manuscript_text: str,
    selection: str = "",
    stated_targets: Optional[Dict[str, str]] = None,
    max_exemplars: int = 4,
) -> WriterVoice:
    """Build a WriterVoice from the author's own text.

    Args:
        manuscript_text: The author's prose (current chapter, ideally
            plus more). The selection itself is excluded so a sentence
            being rewritten doesn't anchor its own rewrite.
        selection: The passage being rephrased.
        stated_targets: Non-empty Prose Profile fields (tone/style/voice/notes).
        max_exemplars: How many sample sentences to quote back.
    """
    voice = WriterVoice(stated_targets={k: v for k, v in (stated_targets or {}).items()
                                        if v and str(v).strip()})
    text = manuscript_text or ""
    sel_pos = text.find(selection) if selection else -1
    if sel_pos >= 0:
        before, after = text[:sel_pos], text[sel_pos + len(selection):]
        text = before + "\n" + after
    else:
        before = text

    narration = _narration_only(text)
    paragraphs = [p for p in re.split(r"\n\s*\n|\n", narration) if len(_words(p)) >= 3]
    sents = [s for s in _sentences(narration) if len(_words(s)) >= 2]
    words = _words(narration)
    if len(sents) < 5 or len(words) < 60:
        return voice

    lens = [len(_words(s)) for s in sents]
    voice.word_count = len(words)
    voice.sentence_count = len(sents)
    voice.avg_sentence_len = round(statistics.mean(lens), 1)
    voice.sentence_len_stdev = round(statistics.pstdev(lens), 1)
    voice.short_sentence_pct = _per100(sum(l < 8 for l in lens), len(lens))
    voice.long_sentence_pct = _per100(sum(l > 25 for l in lens), len(lens))
    if paragraphs:
        voice.sentences_per_paragraph = round(len(sents) / len(paragraphs), 1)

    voice.contractions_per_100_words = _per100(len(_CONTRACTION_RE.findall(narration)), len(words))
    lower = [w.lower().replace("’", "'") for w in words]
    adverbs = [w for w in lower if w.endswith("ly") and len(w) > 4 and w not in _LY_EXCEPTIONS]
    voice.adverbs_per_100_words = _per100(len(adverbs), len(words))

    voice.punctuation_per_100_sentences = {
        mark: _per100(len(rx.findall(narration)), len(sents))
        for mark, rx in _PUNCT_PATTERNS.items()
    }

    c = Counter(lower)
    first = sum(c[w] for w in _FIRST_PERSON)
    third = sum(c[w] for w in _THIRD_PERSON)
    second = sum(c[w] for w in _SECOND_PERSON)
    if first > max(third, second) * 0.6 and c["i"] + c["me"] + c["my"] >= 3:
        voice.person = "first"
    elif second > max(first, third):
        voice.person = "second"
    elif third:
        voice.person = "third"
    past = sum(c[w] for w in _PAST_MARKERS) + sum(1 for w in lower if w.endswith("ed"))
    pres = sum(c[w] for w in _PRESENT_MARKERS)
    if past > pres * 1.5:
        voice.tense = "past"
    elif pres > past * 1.2:
        voice.tense = "present"

    # Words capitalized nearly every time they appear are names of
    # people/places — informative for worldbuilding, not for voice.
    caps = Counter(w.lower().replace("’", "'") for w in words if w[0].isupper())

    openers = Counter()
    for s in sents:
        ws = _words(s)
        if not ws:
            continue
        w0 = ws[0].lower()
        if w0 in _FIRST_PERSON | _THIRD_PERSON | _SECOND_PERSON:
            openers["a pronoun"] += 1
        elif w0 in _ARTICLES:
            openers["an article/determiner"] += 1
        elif w0 in _CONJ_OPENERS:
            openers["a conjunction (And/But/So…)"] += 1
        elif w0.endswith("ing"):
            openers["an -ing participle"] += 1
        elif w0 not in _STOPWORDS and caps[w0] >= c[w0] * 0.8:
            openers["a name/proper noun"] += 1
    voice.openers = {k: _per100(v, len(sents)) for k, v in openers.items()}

    content = [w for w in lower if len(w) >= 4 and w not in _STOPWORDS
               and caps[w] < c[w] * 0.5 and not w.endswith("'s")]
    voice.signature_words = [w for w, n in Counter(content).most_common(12) if n >= 3][:10]

    # Exemplars: sentences from dialog-free paragraphs nearest the
    # selection (preceding text first — that's the voice the passage
    # continues). Paragraphs with quotes are skipped entirely so we
    # never quote a dangling dialog tag back as "the author's voice".
    def clean_paras(chunk: str) -> List[str]:
        return [p for p in re.split(r"\n+", chunk)
                if p.strip() and not _QUOTE_RE.search(p) and '"' not in p]

    near_before = clean_paras(before[-4000:])[::-1]
    near_after = clean_paras(text[len(before):len(before) + 3000]) if sel_pos >= 0 else []
    rest = clean_paras(text)
    seen = set()
    for para in near_before + near_after + rest:
        for sent in _sentences(para):
            n = len(_words(sent))
            if 6 <= n <= 40 and sent not in seen:
                seen.add(sent)
                voice.exemplars.append(sent)
                break  # one per paragraph keeps the samples varied
        if len(voice.exemplars) >= max_exemplars:
            break
    return voice


def character_dialog_samples(text: str, name: str, max_lines: int = 4,
                             other_names: Optional[List[str]] = None) -> List[str]:
    """Quoted lines the manuscript attributes to ``name``.

    Uses the prose convention of one speaker per paragraph: a paragraph
    counts as this character's when their name appears in its narration
    (outside the quotes — being *addressed* by name doesn't count) and no
    other known character is named there too. Good enough to let the
    model hear real lines without an LLM call.
    """
    if not text or not (name or "").strip():
        return []

    def name_rx(n: str):
        n = n.strip()
        variants = {n}
        first = n.split()[0] if n else ""
        if len(first) >= 3:
            variants.add(first)
        return re.compile(r"\b(" + "|".join(re.escape(v) for v in variants) + r")\b")

    me = name_rx(name)
    others = [name_rx(o) for o in (other_names or [])
              if o and o.strip() and o.strip().lower() != name.strip().lower()]
    out: List[str] = []
    for para in re.split(r"\n+", text):
        narration = _narration_only(para)
        if not me.search(narration):
            continue
        if any(o.search(narration) for o in others):
            continue
        for m in _QUOTE_RE.finditer(para):
            line = m.group(0).strip('"“” ')
            if 3 <= len(_words(line)) <= 60 and line not in out:
                out.append(line)
                if len(out) >= max_lines:
                    return out
    return out
