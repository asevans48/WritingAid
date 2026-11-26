"""A voice fingerprint: the measured habits of a passage as a fixed-order
list of numbers (piece V.1).

One pure function, :func:`fingerprint`, turns any text into a
:class:`Fingerprint`. No model, no files, a few milliseconds. The same
function is used for ratings (the narration around the rated passage,
:func:`rating_text`), for the writer's chapters, and for published books
(V.2 calibrates its thresholds on those), so every fingerprint can be
compared with every other one of the same :data:`VERSION`.

The measures come from :func:`src.ai.writer_voice.analyze_writer_voice`
(narration only, dialog removed), plus person and tense as shares, mean
word length and the share of words in dialog. Their order is
:data:`MEASURES`; it never changes within a version. Any change to the
measures, their order, or to how ``analyze_writer_voice`` computes them
raises :data:`VERSION`, and stored fingerprints of an older version are
recomputed.

Too little text (fewer than :data:`MIN_SENTENCES` sentences or
:data:`MIN_WORDS` words of narration, the same bar as
``analyze_writer_voice``) gives status ``"unsorted"`` and no vector.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.ai import writer_voice as wv

VERSION = 1

#: The measures, in vector order (version 1).
MEASURES: Tuple[str, ...] = (
    "sentence_len_mean",             # words per sentence
    "sentence_len_spread",           # standard deviation of the above
    "short_sentences_pct",           # < 8 words, % of sentences
    "long_sentences_pct",            # > 25 words, % of sentences
    "sentences_per_paragraph",
    "word_len_mean",                 # letters per word
    "contractions_per_100_words",
    "adverbs_per_100_words",         # -ly adverbs
    "em_dashes_per_100_sentences",
    "semicolons_per_100_sentences",
    "colons_per_100_sentences",
    "ellipses_per_100_sentences",
    "exclamations_per_100_sentences",
    "questions_per_100_sentences",
    "first_person_pct",              # share of personal pronouns
    "second_person_pct",
    "past_tense_pct",                # past markers / (past + present)
    "opens_pronoun_pct",             # how sentences open, % of sentences
    "opens_article_pct",
    "opens_conjunction_pct",
    "opens_ing_pct",
    "opens_name_pct",
    "dialogue_pct",                  # % of all words inside quotation marks
)

#: Plain-words labels (for V.2's group descriptions and any screen).
LABELS: Dict[str, str] = {
    "sentence_len_mean": "sentence length",
    "sentence_len_spread": "sentence-length variety",
    "short_sentences_pct": "short sentences",
    "long_sentences_pct": "long sentences",
    "sentences_per_paragraph": "paragraph length",
    "word_len_mean": "word length",
    "contractions_per_100_words": "contractions",
    "adverbs_per_100_words": "-ly adverbs",
    "em_dashes_per_100_sentences": "dashes",
    "semicolons_per_100_sentences": "semicolons",
    "colons_per_100_sentences": "colons",
    "ellipses_per_100_sentences": "ellipses",
    "exclamations_per_100_sentences": "exclamations",
    "questions_per_100_sentences": "questions",
    "first_person_pct": "first person",
    "second_person_pct": "second person",
    "past_tense_pct": "past tense",
    "opens_pronoun_pct": "opening with a pronoun",
    "opens_article_pct": "opening with an article",
    "opens_conjunction_pct": "opening with And/But/So",
    "opens_ing_pct": "opening with an -ing word",
    "opens_name_pct": "opening with a name",
    "dialogue_pct": "dialogue",
}

MIN_SENTENCES = 5
MIN_WORDS = 60

STATUS_OK = "ok"
STATUS_UNSORTED = "unsorted"

# Context kept around a rated passage: enough to measure, bounded in time.
_CONTEXT_CHARS = 6000

_PUNCT_KEYS = ("em-dashes", "semicolons", "colons", "ellipses",
               "exclamations", "questions")
_OPENER_KEYS = ("a pronoun", "an article/determiner", "a conjunction (And/But/So…)",
                "an -ing participle", "a name/proper noun")


@dataclass
class Fingerprint:
    version: int = VERSION
    status: str = STATUS_UNSORTED
    vector: List[float] = field(default_factory=list)   # MEASURES order; [] if unsorted
    word_count: int = 0                                  # narration words measured
    sentence_count: int = 0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and len(self.vector) == len(MEASURES)

    def as_dict(self) -> Dict[str, float]:
        return dict(zip(MEASURES, self.vector)) if self.ok else {}


def rating_text(before: str = "", source: str = "", after: str = "") -> str:
    """The text a rating's fingerprint measures: the narration around the
    rated passage, with the passage itself (one sentence is too little)."""
    parts = [(before or "")[-_CONTEXT_CHARS:], source or "", (after or "")[:_CONTEXT_CHARS]]
    return "\n".join(p for p in parts if p.strip())


def fingerprint(text: str) -> Fingerprint:
    """The voice fingerprint of ``text``. Pure: same text, same numbers."""
    text = text or ""
    voice = wv.analyze_writer_voice(text, max_exemplars=0)
    if voice.sentence_count < MIN_SENTENCES or voice.word_count < MIN_WORDS:
        return Fingerprint(word_count=voice.word_count,
                           sentence_count=voice.sentence_count)

    narration = wv._narration_only(text)
    words = wv._words(narration)
    lower = [w.lower().replace("’", "'") for w in words]
    c = Counter(lower)
    first = sum(c[w] for w in wv._FIRST_PERSON)
    second = sum(c[w] for w in wv._SECOND_PERSON)
    third = sum(c[w] for w in wv._THIRD_PERSON)
    pronouns = first + second + third
    past = sum(c[w] for w in wv._PAST_MARKERS) + sum(1 for w in lower if w.endswith("ed"))
    pres = sum(c[w] for w in wv._PRESENT_MARKERS)
    all_words = len(wv._words(text))
    dialog_words = all_words - len(words)

    punct = voice.punctuation_per_100_sentences
    openers = voice.openers
    vector = [
        voice.avg_sentence_len,
        voice.sentence_len_stdev,
        voice.short_sentence_pct,
        voice.long_sentence_pct,
        voice.sentences_per_paragraph,
        round(sum(len(w) for w in words) / len(words), 2),
        voice.contractions_per_100_words,
        voice.adverbs_per_100_words,
        *[float(punct.get(k, 0.0)) for k in _PUNCT_KEYS],
        wv._per100(first, pronouns),
        wv._per100(second, pronouns),
        wv._per100(past, past + pres),
        *[float(openers.get(k, 0.0)) for k in _OPENER_KEYS],
        wv._per100(max(0, dialog_words), all_words),
    ]
    return Fingerprint(status=STATUS_OK, vector=[float(v) for v in vector],
                       word_count=voice.word_count, sentence_count=voice.sentence_count)


def vector_of(text: str) -> Optional[List[float]]:
    """The fingerprint's numbers, or None when there is too little text."""
    fp = fingerprint(text)
    return fp.vector if fp.ok else None
