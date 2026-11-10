"""Editor speed-ups must not change what the editor reports."""

import os
import random
import re
from collections import Counter

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai.output_sanitizer import strip_meta_tokens
from src.ui.enhanced_text_editor import OveruseDetector, SpellChecker
from src.utils import thesaurus as thesaurus_module

WORDS = ["the", "old", "pier", "one-half", "don't", "Mara's", "held", "breath", "tide", "x",
         "well-known", "it's", "wait", "dogs'", "ran", "abc1", "2nd", "a_b", "non‑stop"]
SEPARATORS = [" ", " ", " ", "  ", "\n", "\t", ", ", ". ", "; ", "-", " - ", "--", "'", " '", "’ "]


def random_text(rng: random.Random, n: int) -> str:
    out = []
    for _ in range(n):
        out.append(rng.choice(WORDS))
        out.append(rng.choice(SEPARATORS))
    return "".join(out)


def legacy_positions(detector: OveruseDetector, text: str):
    """The per-phrase regex search the single-pass index replaced."""
    from src.utils.proofing import normalize_apostrophes
    text_lower = normalize_apostrophes(text.lower())
    words = detector._tokens(text_lower)
    all_phrases = []
    for n in range(2, 6):
        all_phrases.extend(detector._extract_ngrams(words, n))
    counts = Counter(all_phrases)
    positions = {}
    for phrase, count in counts.items():
        if (count >= detector.phrase_threshold and phrase not in detector.IGNORE_PHRASES
                and phrase not in detector._ignored_phrases):
            pattern = (r"(?<![\w'\-‑])"
                       + r"\s+".join(re.escape(w) for w in phrase.split())
                       + r"(?![\w'‑]|-\w)")
            found = [(m.start(), m.end()) for m in re.finditer(pattern, text_lower)]
            if found:
                positions[phrase] = found
    return counts, positions


def legacy_range(detector, start, end):
    return [(phrase, s, e, detector._cached_phrase_counts.get(phrase, 0))
            for phrase, spans in detector._cached_phrase_positions.items()
            for s, e in spans if s < end and e > start]


@pytest.mark.parametrize("seed", range(40))
def test_phrase_index_matches_regex_search(seed):
    rng = random.Random(seed)
    text = random_text(rng, rng.randint(0, 400))
    detector = OveruseDetector(phrase_threshold=rng.choice([1, 2, 3]))
    detector.update_cache(text)
    counts, positions = legacy_positions(detector, text)
    assert detector._cached_phrase_counts == counts
    assert detector._cached_phrase_positions == positions
    assert list(detector._cached_phrase_positions) == list(positions)   # draw order


@pytest.mark.parametrize("seed", range(20))
def test_range_query_keeps_results_and_order(seed):
    rng = random.Random(1000 + seed)
    text = random_text(rng, 300)
    detector = OveruseDetector(phrase_threshold=2)
    detector.update_cache(text)
    for _ in range(50):
        a = rng.randint(0, len(text))
        b = rng.randint(a, min(len(text), a + 200))
        assert detector.get_overused_phrases_in_range(text, a, b) == legacy_range(detector, a, b)


def test_range_query_sees_ignored_phrase():
    text = "the old pier stood. the old pier fell."
    detector = OveruseDetector(phrase_threshold=2)
    detector.update_cache(text)
    assert any(r[0] == "old pier" for r in detector.get_overused_phrases_in_range(text, 0, len(text)))
    detector.ignore_phrase("old pier")
    assert all(r[0] != "old pier" for r in detector.get_overused_phrases_in_range(text, 0, len(text)))


def test_overlapping_occurrences_stay_non_overlapping():
    detector = OveruseDetector(phrase_threshold=2)
    text = "tide tide tide tide tide"
    detector.update_cache(text)
    assert detector._cached_phrase_positions["tide tide"] == [(0, 9), (10, 19)]


@pytest.mark.parametrize("seed", range(20))
def test_starts_sentence_matches_regex(seed):
    from src.ui.enhanced_text_editor import WritingHighlighter

    def legacy(text, pos):
        before = re.sub(r"[\"“”‘'(\[\-—–\s*_]+$", "", text[:pos])
        return not before or bool(re.search(r"[.!?…:]$", before))

    rng = random.Random(seed)
    text = "".join(rng.choice("ab .!?…:\"“”‘'([-—–*_\n\t,;") for _ in range(300))
    for pos in range(len(text) + 1):
        assert WritingHighlighter._starts_sentence(text, pos) == legacy(text, pos), (text, pos)


class Issue:
    def __init__(self, start, end):
        self.start, self.end = start, end


def remap(old, spans, new):
    from src.ui.enhanced_text_editor import WritingHighlighter
    moved = WritingHighlighter._remap_issues(old, [Issue(*s) for s in spans], new)
    return [(i.start, i.end) for i in moved]


def test_remap_moves_issues_after_an_insertion():
    old = "He dont know. She dont care."
    new = "Well, he dont know. She dont care."
    assert remap(old, [(3, 7), (18, 22)], new.replace("he", "He", 1)) == [(9, 13), (24, 28)]


def test_remap_keeps_issues_between_two_separate_edits():
    old = "aaa bbb dont ccc ddd"
    new = "aXa bbb dont ccc dYd"
    assert remap(old, [(8, 12)], new) == [(8, 12)]


def test_remap_drops_issue_whose_word_changed():
    assert remap("I walk home", [(2, 6)], "I walked home") == []


def test_remap_on_huge_paragraph_is_fast():
    import time
    old = ("word " * 40000).strip()
    new = "x" + old
    started = time.perf_counter()
    moved = remap(old, [(5, 9)], new)
    assert moved == [(6, 10)]
    assert time.perf_counter() - started < 1.0


def test_spell_checkers_share_dictionary_but_not_custom_words():
    first, second = SpellChecker(), SpellChecker()
    if first._pyspellchecker is None:
        pytest.skip("pyspellchecker not installed")
    assert first._pyspellchecker is second._pyspellchecker
    first.add_word("Zanthor")
    assert "zanthor" in first._custom_words
    assert "zanthor" not in second._custom_words
    assert second.check_word("zanthor")[0] is False


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_chapter_load_highlights_each_block_once(qapp, monkeypatch):
    from src.models.project import Chapter, WriterProject
    from src.ui.enhanced_text_editor import WritingHighlighter
    from src.ui.manuscript_editor import ChapterEditor

    original = WritingHighlighter.highlightBlock
    runs = []

    def counting(self, text):
        if not self._suspended and text in ("First line.", "Second line."):
            runs.append(text)
        original(self, text)

    monkeypatch.setattr(WritingHighlighter, "highlightBlock", counting)
    chapter = Chapter(id="c1", number=1, title="One", content="First line.\nSecond line.")
    editor = ChapterEditor(chapter, project=WriterProject(name="t"))
    assert sorted(runs) == ["First line.", "Second line."]
    assert editor.editor.writing_highlighter._suspended is False


def test_overuse_suggestions_resolved_on_demand(qapp):
    from PyQt6.QtGui import QTextDocument
    from src.ui.enhanced_text_editor import CheckMode, ErrorType, WritingHighlighter

    doc = QTextDocument()
    detector = OveruseDetector(threshold=2)
    highlighter = WritingHighlighter(doc, SpellChecker(), None, detector)
    highlighter.set_overuse_mode(CheckMode.REALTIME)
    text = "walked walked walked"
    doc.setPlainText(text)
    detector.update_cache(text)
    highlighter.update_full_text(text)
    highlighter.rehighlight()
    stored = [e for e in highlighter._errors[0] if e.error_type == ErrorType.OVERUSE]
    assert stored and stored[0].suggestions is None
    error = highlighter.get_error_at(0, 1)
    assert error.suggestions == OveruseDetector.SYNONYMS["walked"]


def test_thesaurus_import_does_not_load_nltk():
    import subprocess
    import sys
    code = ("import sys; import src.utils.thesaurus as t; assert 'nltk' not in sys.modules;"
            "assert t.get_thesaurus() is not None; assert 'nltk' not in sys.modules")
    subprocess.run([sys.executable, "-c", code], check=True, capture_output=True)


def test_wordnet_loaded_on_first_lookup():
    thesaurus_module._wordnet_probed = False
    available = thesaurus_module.is_wordnet_available()
    assert available == thesaurus_module._WORDNET_AVAILABLE
    assert thesaurus_module._wordnet_probed is True
    assert thesaurus_module.get_synonyms("happy")


@pytest.mark.parametrize("raw,expected", [
    ("<|channel>thought\nplan it<channel|>The tide fell.", "The tide fell."),
    ("<|channel>thought\nnever finished", ""),
    ("Before. <|channel>thought\nmid<channel|> After.", "Before.  After."),
    ("<|channel>thought\n<channel|>Clean.", "Clean."),
    ("He had a thought about it.", "He had a thought about it."),
])
def test_gemma_reasoning_removed(raw, expected):
    assert strip_meta_tokens(raw) == expected


def test_template_turns_gemma_thinking_off_only_for_templates_that_support_it():
    from src.ai.chat_template_fallbacks import apply_chat_template_safe

    class Tok:
        def __init__(self, template):
            self.chat_template, self.kwargs = template, None

        def apply_chat_template(self, messages, tokenize, add_generation_prompt, **kwargs):
            self.kwargs = kwargs
            return "prompt"

    gemma = Tok("{% if enable_thinking %}<|channel>thought{% endif %}")
    plain = Tok("{{ messages }}")
    msgs = [{"role": "user", "content": "hi"}]
    assert apply_chat_template_safe(gemma, msgs) == "prompt"
    assert gemma.kwargs == {"enable_thinking": False}
    apply_chat_template_safe(plain, msgs)
    assert plain.kwargs == {}
