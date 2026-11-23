"""Overused words and repeated phrases in a chapter.

Moved out of ``src/ui/enhanced_text_editor.py`` in piece R.3, unchanged, so
chapters can be checked without the editor (no Qt here). The old import
path still works.
"""

import bisect
import re
from collections import Counter
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


def _sentence_at(text: str, pos: int, limit: int = 180) -> str:
    """The sentence around ``pos`` (clipped)."""
    start = max(text.rfind(". ", 0, pos), text.rfind("\n", 0, pos), text.rfind("? ", 0, pos),
                text.rfind("! ", 0, pos))
    start = 0 if start < 0 else start + 1
    ends = [i for i in (text.find(". ", pos), text.find("\n", pos), text.find("? ", pos),
                        text.find("! ", pos)) if i >= 0]
    end = min(ends) + 1 if ends else len(text)
    sentence = " ".join(text[start:end].split())
    return sentence if len(sentence) <= limit else sentence[:limit - 1] + "…"


def _sentences_with(text: str, word: str, limit: int = 3) -> List[str]:
    out = []
    for m in re.finditer(rf"(?<![A-Za-z']){re.escape(word)}(?![A-Za-z])", text, re.I):
        sentence = _sentence_at(text, m.start())
        if sentence not in out:
            out.append(sentence)
        if len(out) >= limit:
            break
    return out


class OveruseDetector:
    """Detects overused words and phrases, providing synonym suggestions."""

    # Words to ignore (common words that are expected to repeat)
    IGNORE_WORDS = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
        'she', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your',
        'his', 'her', 'our', 'their', 'what', 'which', 'who', 'whom', 'whose',
        'if', 'then', 'else', 'when', 'where', 'why', 'how', 'all', 'each',
        'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
        'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
        'also', 'now', 'here', 'there', 'still', 'already', 'even', 'again',
    }

    # Common phrases to ignore (expected to repeat)
    IGNORE_PHRASES = {
        'he said', 'she said', 'i said', 'they said',
        'it was', 'there was', 'there were', 'it is',
        'i was', 'he was', 'she was', 'they were',
        'i am', 'he is', 'she is', 'they are',
        'in the', 'on the', 'at the', 'to the', 'of the', 'for the',
        'and the', 'but the', 'with the', 'from the',
        'i had', 'he had', 'she had', 'they had',
        'i have', 'he has', 'she has', 'they have',
        'as if', 'as though', 'even if', 'even though',
        'out of', 'in front of', 'on top of', 'because of',
        'a lot', 'a lot of', 'some of', 'all of', 'one of',
    }

    # Common synonyms for overused words
    SYNONYMS = {
        'said': ['replied', 'responded', 'answered', 'stated', 'remarked', 'declared', 'exclaimed', 'muttered', 'whispered', 'shouted'],
        'walked': ['strolled', 'ambled', 'strode', 'marched', 'trudged', 'sauntered', 'paced', 'wandered', 'meandered', 'trekked'],
        'looked': ['glanced', 'gazed', 'stared', 'peered', 'observed', 'watched', 'examined', 'studied', 'surveyed', 'inspected'],
        'went': ['traveled', 'journeyed', 'proceeded', 'headed', 'moved', 'advanced', 'continued', 'departed', 'left', 'ventured'],
        'got': ['obtained', 'acquired', 'received', 'gained', 'secured', 'fetched', 'retrieved', 'collected', 'gathered', 'earned'],
        'good': ['excellent', 'great', 'fine', 'wonderful', 'superb', 'outstanding', 'remarkable', 'exceptional', 'splendid', 'admirable'],
        'bad': ['terrible', 'awful', 'dreadful', 'poor', 'inferior', 'substandard', 'unpleasant', 'disagreeable', 'unfavorable', 'negative'],
        'big': ['large', 'huge', 'enormous', 'massive', 'immense', 'vast', 'substantial', 'considerable', 'significant', 'grand'],
        'small': ['tiny', 'little', 'minute', 'miniature', 'compact', 'petite', 'modest', 'slight', 'minor', 'diminutive'],
        'nice': ['pleasant', 'agreeable', 'delightful', 'lovely', 'enjoyable', 'charming', 'appealing', 'attractive', 'pleasing', 'wonderful'],
        'happy': ['joyful', 'elated', 'delighted', 'pleased', 'content', 'cheerful', 'thrilled', 'ecstatic', 'overjoyed', 'blissful'],
        'sad': ['unhappy', 'sorrowful', 'melancholy', 'dejected', 'downcast', 'gloomy', 'miserable', 'despondent', 'heartbroken', 'forlorn'],
        'very': ['extremely', 'highly', 'incredibly', 'remarkably', 'exceptionally', 'particularly', 'especially', 'tremendously', 'immensely', 'greatly'],
        'really': ['truly', 'genuinely', 'actually', 'indeed', 'certainly', 'definitely', 'absolutely', 'positively', 'undoubtedly', 'unquestionably'],
        'thing': ['object', 'item', 'element', 'aspect', 'matter', 'subject', 'entity', 'article', 'component', 'detail'],
        'things': ['objects', 'items', 'elements', 'aspects', 'matters', 'subjects', 'entities', 'articles', 'components', 'details'],
        'stuff': ['material', 'items', 'belongings', 'possessions', 'goods', 'objects', 'articles', 'equipment', 'supplies', 'gear'],
        'like': ['such as', 'similar to', 'resembling', 'comparable to', 'akin to'],
        'beautiful': ['gorgeous', 'stunning', 'lovely', 'attractive', 'exquisite', 'magnificent', 'elegant', 'radiant', 'striking', 'breathtaking'],
        'fast': ['quick', 'rapid', 'swift', 'speedy', 'hasty', 'brisk', 'fleet', 'expeditious', 'prompt', 'nimble'],
        'slow': ['sluggish', 'leisurely', 'unhurried', 'gradual', 'deliberate', 'measured', 'plodding', 'languid', 'lethargic', 'torpid'],
        'think': ['believe', 'consider', 'suppose', 'reckon', 'assume', 'imagine', 'presume', 'surmise', 'speculate', 'ponder'],
        'know': ['understand', 'realize', 'recognize', 'comprehend', 'perceive', 'grasp', 'fathom', 'discern', 'appreciate', 'acknowledge'],
        'see': ['observe', 'notice', 'perceive', 'witness', 'spot', 'detect', 'discern', 'view', 'behold', 'glimpse'],
        'make': ['create', 'produce', 'construct', 'build', 'form', 'generate', 'manufacture', 'craft', 'fabricate', 'fashion'],
        'take': ['grab', 'seize', 'grasp', 'snatch', 'acquire', 'obtain', 'secure', 'capture', 'collect', 'gather'],
        'come': ['arrive', 'approach', 'appear', 'emerge', 'materialize', 'surface', 'show up', 'turn up', 'reach', 'enter'],
        'give': ['provide', 'offer', 'present', 'supply', 'grant', 'bestow', 'donate', 'contribute', 'deliver', 'hand over'],
        'tell': ['inform', 'notify', 'advise', 'explain', 'describe', 'relate', 'recount', 'narrate', 'disclose', 'reveal'],
        'feel': ['sense', 'experience', 'perceive', 'detect', 'notice', 'undergo', 'encounter', 'endure', 'suffer', 'enjoy'],
        'eyes': ['gaze', 'vision', 'sight', 'glance', 'stare', 'look'],
        'face': ['expression', 'countenance', 'features', 'visage', 'appearance', 'complexion'],
        'began': ['started', 'commenced', 'initiated', 'launched', 'embarked', 'undertook', 'opened', 'set out'],
        'suddenly': ['abruptly', 'unexpectedly', 'instantly', 'immediately', 'swiftly', 'rapidly', 'quickly', 'all at once'],
    }

    def __init__(self, threshold: int = 3, phrase_threshold: int = 2, window_size: int = 500):
        """Initialize overuse detector.

        Args:
            threshold: Number of times a word must appear to be flagged
            phrase_threshold: Number of times a phrase must appear to be flagged
            window_size: Number of words to consider for frequency analysis
        """
        self.threshold = threshold
        self.phrase_threshold = phrase_threshold
        self.window_size = window_size
        self._ignored_words: Set[str] = set()
        self._ignored_phrases: Set[str] = set()
        # Cache for word counts to avoid recalculating for every word
        self._cached_counts: Dict[str, int] = {}
        self._cached_text_hash: int = 0
        # Cache for phrase counts (2, 3, 4, 5-word ngrams)
        self._cached_phrase_counts: Dict[str, int] = {}
        # Cache phrase positions for highlighting: phrase -> [(start, end), ...]
        self._cached_phrase_positions: Dict[str, List[Tuple[int, int]]] = {}
        # Occurrences sorted by start, built on first range query.
        self._phrase_index = None
        # Light repeats (a word 3–5 times, a phrase 2–3 times) are only
        # flagged when they weaken the writing — judged by a model when one
        # is set up (``apply_verdicts``), else by proximity and how unusual
        # the word is. Off by default; the editor turns it on.
        self.review_low_counts = False
        self.strong_threshold = 6
        self.phrase_strong_threshold = 4
        self._verdicts: Dict[str, Tuple[bool, str]] = {}   # "w:word" / "p:phrase"
        self._names: Set[str] = set()                       # never overused
        self._word_index: Dict[str, List[int]] = {}         # word → token positions
        self._total_words = 0
        self._text = ""
        self._review_pending_phrases: Dict[str, List[Tuple[int, int]]] = {}

    # Contraction endings of helper words ("didn't", "it's", "we'll") — these
    # repeat by nature, like the IGNORE_WORDS they're built from.
    _CONTRACTION_TAILS = ("n't", "'s", "'re", "'ve", "'ll", "'d", "'m")

    def _count_key(self, token: str) -> Optional[str]:
        """Word as counted for overuse: possessives count toward the base
        word ("Mara's" → "mara"); helper-word contractions are skipped."""
        t = token.lower().replace("\u2011", "-")     # non-breaking hyphen = hyphen
        if "'" not in t:
            return t
        if t.endswith("n't") or t.split("'", 1)[0] in self.IGNORE_WORDS:
            return None
        if t.endswith("'s"):
            return t[:-2]
        return None

    @staticmethod
    def _tokens(text_lower: str) -> List[str]:
        from src.utils.proofing import compound_tokens
        return compound_tokens(text_lower)      # "one-half", "didn't" stay whole

    def _extract_ngrams(self, words: List[str], n: int) -> List[str]:
        """Extract n-grams from a list of words."""
        if len(words) < n:
            return []
        return [' '.join(words[i:i+n]) for i in range(len(words) - n + 1)]

    def update_cache(self, text: str):
        """Update the cached word and phrase counts for a text."""
        text_hash = hash(text)
        if text_hash != self._cached_text_hash:
            self._cached_text_hash = text_hash
            from src.utils.proofing import COMPOUND_TOKEN_RX, normalize_apostrophes
            # Normalised 1:1, so phrase positions still index the original.
            text_lower = normalize_apostrophes(text.lower())
            spans = [m.span() for m in COMPOUND_TOKEN_RX.finditer(text_lower)]
            words = [text_lower[s:e] for s, e in spans]
            keys = [self._count_key(w) for w in words]
            self._cached_counts = Counter(k for k in keys if k)
            self._total_words = len(words)
            self._text = text
            self._word_index = {}
            if self.review_low_counts:
                for i, k in enumerate(keys):
                    if k and self._cached_counts[k] >= self.threshold:
                        self._word_index.setdefault(k, []).append(i)

            # Extract and count phrases (2, 3, 4, 5-word ngrams)
            grams = [self._extract_ngrams(words, n) for n in range(2, 6)]
            self._cached_phrase_counts = Counter(p for ngrams in grams for p in ngrams)
            self._index_phrase_positions(text_lower, spans, grams)

    def _index_phrase_positions(self, text: str, spans: List[Tuple[int, int]],
                                grams: List[List[str]]) -> None:
        """Locate every overused phrase in one pass over the tokens.

        An occurrence is n tokens separated only by whitespace, not embedded
        in a longer word or compound. Occurrences of one phrase never overlap.
        """
        self._phrase_index = None
        self._cached_phrase_positions.clear()
        # Light repeats not flagged (yet): the judge may still flag them.
        self._review_pending_phrases = {}
        wanted = {p for p, c in self._cached_phrase_counts.items()
                  if c >= self.phrase_threshold
                  and p not in self.IGNORE_PHRASES and p not in self._ignored_phrases}
        if self.review_low_counts:
            # A phrase needs two real words: "of her" / "out of the" are
            # grammar, and "the boat" is just the word "boat" (checked alone).
            wanted = {p for p in wanted if not self._only_names(p) and self._content_words(p) >= 2}
        if not wanted:
            return

        def word_char(c: str) -> bool:
            return c.isalnum() or c == "_"

        size = len(text)
        count = len(spans)
        # runs[i]: how many tokens after token i are joined by whitespace alone.
        runs = [0] * count
        for i in range(count - 2, -1, -1):
            if text[spans[i][1]:spans[i + 1][0]].isspace():
                runs[i] = runs[i + 1] + 1

        found: Dict[str, List[Tuple[int, int]]] = {}
        for n, ngrams in enumerate(grams, start=2):
            for i, phrase in enumerate(ngrams):
                if phrase not in wanted or runs[i] < n - 1:
                    continue
                start, end = spans[i][0], spans[i + n - 1][1]
                before = text[start - 1] if start else ""
                if before and (word_char(before) or before in "'-\u2011"):
                    continue
                after = text[end] if end < size else ""
                if after and (word_char(after) or after in "'\u2011"
                              or (after == "-" and end + 1 < size and word_char(text[end + 1]))):
                    continue
                positions = found.setdefault(phrase, [])
                if not positions or positions[-1][1] <= start:
                    positions.append((start, end))

        # Same order as the phrase counts: later phrases draw over earlier ones.
        for phrase in self._cached_phrase_counts:
            if phrase in found:
                if self.review_low_counts and not self.phrase_verdict(phrase, found[phrase])[0]:
                    self._review_pending_phrases[phrase] = found[phrase]
                    continue
                self._cached_phrase_positions[phrase] = found[phrase]

    def analyze_text(self, text: str) -> Dict[str, int]:
        """Analyze text and return word frequencies for non-ignored words."""
        self.update_cache(text)

        # Filter out ignored words and short words
        return {
            word: count for word, count in self._cached_counts.items()
            if word not in self.IGNORE_WORDS
            and word not in self._ignored_words
            and len(word) > 2
            and count >= self.threshold
        }

    def is_overused(self, word: str, text: str) -> Tuple[bool, int]:
        """Check if a word is overused in the text.

        Returns:
            Tuple of (is_overused, count)
        """
        from src.utils.proofing import normalize_apostrophes
        word_lower = self._count_key(normalize_apostrophes(word))
        if word_lower is None:
            return False, 0

        if word_lower in self.IGNORE_WORDS or word_lower in self._ignored_words:
            return False, 0

        if len(word_lower) <= 2:
            return False, 0

        # Use cached counts if available
        if self._cached_text_hash == hash(text):
            count = self._cached_counts.get(word_lower, 0)
        else:
            # Fallback to direct count (slower)
            self.update_cache(text)
            count = self._cached_counts.get(word_lower, 0)

        if count < self.threshold:
            return False, count
        if self.review_low_counts:
            if word_lower in self._names or word_lower in self._FUNCTION_WORDS:
                return False, count
            return self.word_verdict(word_lower, count)[0], count
        return True, count

    # ── Which light repeats matter ───────────────────────────────

    RARE_FREQUENCY = 3e-6          # rarer than this, a word stands out when repeated
    ECHO_WORDS = 50                # two uses this close are an echo
    PHRASE_ECHO_CHARS = 600

    def set_names(self, names: Iterable[str]) -> None:
        """Character and place names: repeating them is how stories work."""
        tokens = set()
        for name in names or []:
            for t in re.findall(r"[A-Za-z][A-Za-z'’-]+", name or ""):
                tokens.add(t.lower())
        self._names = tokens
        self._cached_text_hash = 0          # recount with the names excluded

    _FUNCTION_WORDS = set("""into onto out off over under along through past around about before
    after behind across toward towards upon without within against between among like down up
    away back then there than into upon via per""".split())

    def _content_words(self, phrase: str) -> int:
        return sum(1 for w in phrase.split()
                   if len(w) > 2 and w not in self.IGNORE_WORDS and w not in self._FUNCTION_WORDS
                   and w not in self._names)

    def _only_names(self, phrase: str) -> bool:
        words = [w for w in phrase.split() if w not in self.IGNORE_WORDS]
        return bool(words) and all(w in self._names for w in words)

    def _strong(self) -> int:
        # Longer chapters can carry a few more uses before they grate.
        return max(self.strong_threshold, self._total_words // 500)

    def _word_frequency(self, word: str) -> float:
        try:
            from src.ai import rewrite_quality
            rewrite_quality._known_word("the")      # loads the dictionary once
            d = rewrite_quality._dictionary
            return d.word_usage_frequency(word) if d else 1.0
        except Exception:
            return 1.0

    def heuristic_verdict(self, word: str, count: int) -> Tuple[bool, str]:
        """No model: flag a light repeat if two uses are close together, or
        the word is unusual enough that readers notice it coming back."""
        positions = self._word_index.get(word, [])
        gaps = [b - a for a, b in zip(positions, positions[1:])]
        if gaps and min(gaps) <= self.ECHO_WORDS:
            return True, f"Two uses within {min(gaps)} words of each other."
        if self._word_frequency(word) < self.RARE_FREQUENCY:
            return True, "A distinctive word — readers notice it coming back."
        return False, ""

    def _close_echo(self, word: str) -> int:
        """Words between the two closest uses (0 if none are close)."""
        positions = self._word_index.get(word, [])
        gaps = [b - a for a, b in zip(positions, positions[1:])]
        return min(gaps) if gaps and min(gaps) <= self.ECHO_WORDS else 0

    def word_verdict(self, word: str, count: int) -> Tuple[bool, str]:
        if count >= self._strong():
            return True, ""
        gap = self._close_echo(word)
        if gap:                       # a reader hears it — no model can talk it away
            return True, f"Two uses within {gap} words of each other."
        if f"w:{word}" in self._verdicts:
            return self._verdicts[f"w:{word}"]
        return self.heuristic_verdict(word, count)

    def phrase_verdict(self, phrase: str, positions: List[Tuple[int, int]]) -> Tuple[bool, str]:
        if len(positions) >= self.phrase_strong_threshold:
            return True, ""
        gaps = [b[0] - a[1] for a, b in zip(positions, positions[1:])]
        if gaps and min(gaps) <= self.PHRASE_ECHO_CHARS:
            return True, "Repeated close together."
        if f"p:{phrase}" in self._verdicts:
            return self._verdicts[f"p:{phrase}"]
        return False, ""

    def verdict_reason(self, key: str) -> str:
        """The judge's reason for flagging a word ("w:…") or phrase ("p:…")."""
        flagged, reason = self._verdicts.get(key, (False, ""))
        return reason if flagged else ""

    def review_items(self, limit: int = 40) -> List[Dict[str, Any]]:
        """Light repeats for the judge: each with the sentences it's in.
        Close echoes and distinctive words first."""
        if not self.review_low_counts or not self._text:
            return []
        text = self._text
        items = []
        strong = self._strong()
        for word, count in self._cached_counts.items():
            if (self.threshold <= count < strong and len(word) > 2
                    and word not in self.IGNORE_WORDS and word not in self._ignored_words
                    and word not in self._names and word not in self._FUNCTION_WORDS
                    and not self._close_echo(word)):          # already decided: shown
                items.append({"key": f"w:{word}", "text": word, "count": count,
                              "sentences": _sentences_with(text, word),
                              "suspicion": self.heuristic_verdict(word, count)[0]})
        light = dict(self._review_pending_phrases)
        light.update(self._cached_phrase_positions)
        for phrase, positions in light.items():
            gaps = [b[0] - a[1] for a, b in zip(positions, positions[1:])]
            if gaps and min(gaps) <= self.PHRASE_ECHO_CHARS:
                continue                                      # already decided: shown
            if len(positions) < self.phrase_strong_threshold:
                items.append({"key": f"p:{phrase}", "text": phrase, "count": len(positions),
                              "sentences": [_sentence_at(text, s) for s, _ in positions[:3]],
                              "suspicion": self.phrase_verdict(phrase, positions)[0]})
        items.sort(key=lambda i: not i["suspicion"])
        return items[:limit]

    def apply_verdicts(self, verdicts: Dict[str, Tuple[bool, str]]) -> None:
        """Results from the judge; recount so phrase highlights follow."""
        self._verdicts.update(verdicts)
        self._cached_text_hash = 0
        if self._text:
            self.update_cache(self._text)

    def get_synonyms(self, word: str) -> List[str]:
        """Get synonyms for a word."""
        word_lower = word.lower()

        # Check our built-in synonyms first
        if word_lower in self.SYNONYMS:
            return self.SYNONYMS[word_lower]

        # Try nltk wordnet if available
        try:
            from nltk.corpus import wordnet
            synonyms = set()
            for syn in wordnet.synsets(word_lower):
                for lemma in syn.lemmas():
                    if lemma.name() != word_lower and '_' not in lemma.name():
                        synonyms.add(lemma.name())
            return list(synonyms)[:10]
        except:
            pass

        return []

    # Words that make the next one an adverb of direction: "went home".
    _MOTION = set("""went go goes going gone came come comes coming headed head heads drove
    drive driving walked walk walking ran run running got get getting sent send brought bring
    flew fly hurried rushed returned return returning made make way back""".split())
    _NOUN_BEFORE = set("""a an the their his her my our your its this that these those every
    each another some any no whose""".split())

    def _guess_pos(self, word: str, paragraph: str, position: Optional[int]) -> Optional[str]:
        """"noun", "verb", "adverb" or None — from the word's form and the
        word before it (a full tagger takes seconds to load)."""
        from src.utils.word_forms import form_of
        if form_of(word) in ("past", "ing"):
            return "verb"
        if position is None or not paragraph:
            return None
        before = re.findall(r"[A-Za-z']+", paragraph[:position])
        prev = before[-1].lower() if before else ""
        if prev in self._MOTION:
            return "adverb"
        if prev in self._NOUN_BEFORE or prev.endswith("'s"):
            return "noun"
        if prev in ("to", "will", "would", "could", "should", "might", "must", "can", "did",
                    "do", "does", "not", "never"):
            return "verb"
        return None

    # Repeated phrases with a standard fix: (pattern, replacements). "" means
    # cut it; \1 keeps a captured word ("nodded her head" → "nodded").
    PHRASE_FIXES = [
        (r"for a (?:moment|second|minute|beat)", ["", "briefly"]),
        (r"(?:at|in) that (?:very )?moment", ["", "then"]),
        (r"all of a sudden", ["suddenly", ""]),
        (r"out of nowhere", ["suddenly", ""]),
        (r"at the same time", ["meanwhile", "together"]),
        (r"in the middle of", ["amid", "in"]),
        (r"a little bit", ["a little", "slightly"]),
        (r"(?:kind|sort) of", ["", "somewhat"]),
        (r"seemed to be", ["seemed", "was"]),
        (r"a lot of", ["many", "much"]),
        (r"the fact that", ["that"]),
        (r"(nodded|shook) (?:his|her|their|my|your) heads?", [r"\1"]),
        (r"(shrugged) (?:his|her|their|my|your) shoulders", [r"\1"]),
        (r"(blinked) (?:his|her|their|my|your) eyes", [r"\1"]),
        (r"(turned|spun|whirled) around", [r"\1"]),
        (r"(stood|stands|standing) up", [r"\1", "rose"]),
        (r"(sat|sits|sitting) down", [r"\1"]),
        (r"(clapped) (?:his|her|their|my|your) hands", [r"\1"]),
    ]

    def phrase_alternatives(self, phrase: str):
        """``(start, end, options)`` for the part of a repeated phrase with a
        standard fix (padding, redundant body language, wordy phrasing), or
        None. Options replace ``phrase[start:end]``; "" cuts it."""
        from src.utils.style_checks import WORDY
        text = phrase or ""
        best = None
        candidates = list(self.PHRASE_FIXES) + [
            (re.escape(k), [v]) for k, v in WORDY.items() if v is not None]
        for pattern, options in candidates:
            m = re.search(rf"(?<![A-Za-z]){pattern}(?![A-Za-z])", text, re.I)
            if m and (best is None or (m.end() - m.start()) > (best[1] - best[0])):
                best = (m.start(), m.end(), [m.expand(o) if "\\" in o else o for o in options])
        if best is None:
            return None
        start, end, options = best
        original = text[start:end]
        fixed = []
        for o in options:
            if o and original[:1].isupper():
                o = o[:1].upper() + o[1:]
            if o.lower() != original.lower() and o not in fixed:
                fixed.append(o)
        return (start, end, fixed) if fixed else None

    def _common_sense_synonyms(self, word: str, pos_hint: Optional[str] = None) -> List[str]:
        """WordNet synonyms from the word's commonest meanings only — "home"
        gives dwelling, abode…, not "plate" (baseball); "house" a building,
        not a firm. Meanings are ranked by how often the word is used in
        each (WordNet's sense counts)."""
        from src.utils.word_forms import base_of, form_of
        if pos_hint == "adverb":
            return []          # "went home": no single word swaps in cleanly
        try:
            from src.utils.thesaurus import _ensure_wordnet
            if not _ensure_wordnet():
                return []
            from nltk.corpus import wordnet as wn
        except Exception:
            return []
        base = base_of(word) if form_of(word) != "base" else word.lower()
        pos = {"verb": wn.VERB, "noun": wn.NOUN}.get(pos_hint or "")
        synsets = wn.synsets(base, pos=pos) if pos else wn.synsets(base)
        if not synsets:
            return []

        def uses(syn):
            return sum(l.count() for l in syn.lemmas() if l.name().lower() == base)

        ranked = sorted(synsets, key=uses, reverse=True)
        top = uses(ranked[0])
        senses = [s for s in ranked if top == 0 or uses(s) >= top * 0.25][:2]
        out: List[str] = []
        for syn in senses:
            for lemma in sorted(syn.lemmas(), key=lambda l: -l.count()):
                name = lemma.name().replace("_", " ")
                if name.lower() not in (base, word.lower()) and name not in out:
                    out.append(name)
        return out

    def contextual_synonyms(self, word: str, paragraph: str = "", full_text: str = "",
                            limit: int = 7, position: Optional[int] = None) -> List[str]:
        """Synonyms fitted to where the word is: in its form ("looked" →
        "glanced"), minus ones already in the paragraph or themselves
        overused, words the author already uses first. No model needed."""
        from src.utils.word_forms import base_of, form_of, match_form
        curated = self.SYNONYMS.get(word.lower()) or self.SYNONYMS.get(base_of(word))
        pos = self._guess_pos(word, paragraph, position)
        if pos == "adverb":
            return []
        candidates = list(curated) if curated else self._common_sense_synonyms(word, pos)
        if full_text and self._cached_text_hash != hash(full_text):
            self.update_cache(full_text)
        in_paragraph = {w.lower() for w in re.findall(r"[A-Za-z'’-]+", paragraph or "")}
        out, seen = [], {word.lower()}
        for cand in candidates:
            fitted = match_form(cand, word)
            low = fitted.lower()
            if low in seen or low in in_paragraph:
                continue
            seen.add(low)
            if self._cached_counts.get(low, 0) >= self.threshold:
                continue                       # swapping one overused word for another
            out.append(fitted)
        # Words already in the author's vocabulary first (stable otherwise).
        used = lambda w: self._cached_counts.get(w.lower().split()[0], 0) > 0
        out.sort(key=lambda w: not used(w))
        return out[:limit]

    def ignore_word(self, word: str):
        """Add word to ignored list."""
        self._ignored_words.add(word.lower())

    def is_ignored(self, word: str) -> bool:
        """Check if word is in ignored list."""
        return word.lower() in self._ignored_words

    # Phrase detection methods

    def analyze_phrases(self, text: str) -> Dict[str, int]:
        """Analyze text and return phrase frequencies for non-ignored phrases.

        Returns phrases that appear at least phrase_threshold times.
        """
        self.update_cache(text)

        return {
            phrase: count for phrase, count in self._cached_phrase_counts.items()
            if phrase not in self.IGNORE_PHRASES
            and phrase not in self._ignored_phrases
            and count >= self.phrase_threshold
        }

    def is_phrase_overused(self, phrase: str) -> Tuple[bool, int]:
        """Check if a phrase is overused based on cached counts.

        Returns:
            Tuple of (is_overused, count)
        """
        phrase_lower = phrase.lower()

        if phrase_lower in self.IGNORE_PHRASES or phrase_lower in self._ignored_phrases:
            return False, 0

        count = self._cached_phrase_counts.get(phrase_lower, 0)
        return count >= self.phrase_threshold, count

    def get_overused_phrases_in_range(self, text: str, start: int, end: int) -> List[Tuple[str, int, int, int]]:
        """Get all overused phrases that overlap with a given text range.

        Args:
            text: Full document text (for cache validation)
            start: Start position in document
            end: End position in document

        Returns:
            List of (phrase, phrase_start, phrase_end, count) tuples
        """
        # Ensure cache is current
        if self._cached_text_hash != hash(text):
            self.update_cache(text)

        if self._phrase_index is None:
            rows = sorted(
                (pos_start, pos_end, rank, phrase)
                for rank, (phrase, positions) in enumerate(self._cached_phrase_positions.items())
                for pos_start, pos_end in positions)
            longest = max((row[1] - row[0] for row in rows), default=0)
            self._phrase_index = ([row[0] for row in rows], rows, longest)

        starts, rows, longest = self._phrase_index
        first = bisect.bisect_left(starts, start - longest)
        last = bisect.bisect_left(starts, end)
        hits = [row for row in rows[first:last] if row[1] > start]
        hits.sort(key=lambda row: (row[2], row[0]))     # phrase order, then position
        return [(phrase, s, e, self._cached_phrase_counts.get(phrase, 0))
                for s, e, _rank, phrase in hits]

    def get_phrase_at_position(self, text: str, position: int) -> Optional[Tuple[str, int, int, int]]:
        """Get overused phrase at a specific position, if any.

        Args:
            text: Full document text
            position: Character position to check

        Returns:
            Tuple of (phrase, start, end, count) or None
        """
        # Ensure cache is current
        if self._cached_text_hash != hash(text):
            self.update_cache(text)

        # Check all overused phrases for one that contains this position
        # Prefer longer phrases over shorter ones
        best_match = None
        for phrase, positions in self._cached_phrase_positions.items():
            count = self._cached_phrase_counts.get(phrase, 0)
            for pos_start, pos_end in positions:
                if pos_start <= position < pos_end:
                    if best_match is None or len(phrase) > len(best_match[0]):
                        best_match = (phrase, pos_start, pos_end, count)

        return best_match

    def ignore_phrase(self, phrase: str):
        """Add phrase to ignored list."""
        self._ignored_phrases.add(phrase.lower())
        # Remove from cached positions
        phrase_lower = phrase.lower()
        if phrase_lower in self._cached_phrase_positions:
            del self._cached_phrase_positions[phrase_lower]
            self._phrase_index = None

    def is_phrase_ignored(self, phrase: str) -> bool:
        """Check if phrase is in ignored list."""
        return phrase.lower() in self._ignored_phrases
