"""Writing statistics: sentence length and variety, sticky sentences,
echoes, passive voice, dialogue, readability, adverbs and cliches.

Moved out of ``src/ui/enhanced_text_editor.py`` in piece R.3, unchanged, so
chapters can be checked without the editor (no Qt here). The old import
path still works.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from src.utils import style_checks as _style_checks

# The style checks the editor runs, so sticky sentences skip long ones as
# they do in the editor.
EDITOR_STYLE_KINDS = {"passive", "adverb", "cliche", "sticky_sentence", "echo",
                      "long_sentence"}


@dataclass
class WritingStats:
    """Comprehensive writing statistics like ProWritingAid."""
    word_count: int = 0
    sentence_count: int = 0
    paragraph_count: int = 0
    avg_sentence_length: float = 0.0
    avg_word_length: float = 0.0

    # Sentence length variation
    short_sentences: int = 0  # < 10 words
    medium_sentences: int = 0  # 10-20 words
    long_sentences: int = 0  # 21-35 words
    very_long_sentences: int = 0  # > 35 words
    sentence_length_score: float = 0.0  # 0-100, higher is better variety

    # Sticky sentences (high % of glue words)
    sticky_sentences: List[str] = None
    sticky_sentence_count: int = 0
    avg_glue_index: float = 0.0

    # Echoes (repeated words in close proximity)
    echoes: List[Tuple[str, int, int]] = None  # (word, first_pos, second_pos)
    echo_count: int = 0

    # Passive voice
    passive_sentences: List[str] = None
    passive_count: int = 0
    passive_percentage: float = 0.0

    # Dialogue
    dialogue_percentage: float = 0.0
    dialogue_tags: Dict[str, int] = None  # tag -> count
    overused_dialogue_tags: List[str] = None

    # Readability
    flesch_reading_ease: float = 0.0
    flesch_grade_level: float = 0.0

    # Adverbs
    adverbs: List[str] = None
    adverb_count: int = 0
    adverb_percentage: float = 0.0

    # Clichés
    cliches: List[str] = None
    cliche_count: int = 0

    def __post_init__(self):
        """Initialize mutable defaults."""
        if self.sticky_sentences is None:
            self.sticky_sentences = []
        if self.echoes is None:
            self.echoes = []
        if self.passive_sentences is None:
            self.passive_sentences = []
        if self.dialogue_tags is None:
            self.dialogue_tags = {}
        if self.overused_dialogue_tags is None:
            self.overused_dialogue_tags = []
        if self.adverbs is None:
            self.adverbs = []
        if self.cliches is None:
            self.cliches = []


class ProWritingAnalyzer:
    """ProWritingAid-style comprehensive text analysis."""

    # Common glue words (function words that don't add meaning)

    # Passive voice indicators

    # Passive voice, adverbs, clichés, sticky sentences and echoes are the
    # editor's style checks (src/utils/style_checks.py): one implementation of
    # each, so the Critique and the editor count the same things (piece R.4).
    # These names stay for existing readers of the class.
    GLUE_WORDS = frozenset(_style_checks.GLUE)
    CLICHES = frozenset(_style_checks.CLICHES)

    # Common dialogue tags
    DIALOGUE_TAGS = {
        'said', 'asked', 'replied', 'answered', 'responded', 'exclaimed',
        'whispered', 'shouted', 'yelled', 'screamed', 'muttered', 'murmured',
        'declared', 'announced', 'stated', 'remarked', 'commented', 'noted',
        'added', 'continued', 'explained', 'insisted', 'demanded', 'suggested',
        'wondered', 'questioned', 'inquired', 'cried', 'called', 'sighed',
        'groaned', 'moaned', 'breathed', 'gasped', 'hissed', 'snapped',
        'barked', 'growled', 'laughed', 'chuckled', 'giggled', 'sobbed',
    }

    # Common clichés in writing

    # Common adverbs to flag

    def __init__(self):
        """Initialize analyzer."""

    def analyze(self, text: str) -> WritingStats:
        """Perform comprehensive text analysis.

        Args:
            text: The text to analyze

        Returns:
            WritingStats with all metrics
        """
        stats = WritingStats()

        if not text or not text.strip():
            return stats

        # Basic counts
        from src.utils.proofing import compound_tokens
        words = compound_tokens(text)      # "didn't", "one-half" are one word
        stats.word_count = len(words)

        # Sentence detection
        sentences = self._split_sentences(text)
        stats.sentence_count = len(sentences)

        # Paragraph count
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        stats.paragraph_count = len(paragraphs) if paragraphs else 1

        if stats.word_count == 0 or stats.sentence_count == 0:
            return stats

        # Average lengths
        stats.avg_sentence_length = stats.word_count / stats.sentence_count
        stats.avg_word_length = sum(len(w) for w in words) / len(words)

        # The editor's style checks, once, for the measures they share (R.4).
        self._style = _style_checks.analyze_document(text, EDITOR_STYLE_KINDS)

        # Sentence length analysis
        self._analyze_sentence_lengths(sentences, stats)

        # Sticky sentences
        self._analyze_sticky_sentences(sentences, stats)

        # Echoes
        self._analyze_echoes(text, stats)

        # Passive voice
        self._analyze_passive_voice(sentences, stats)

        # Dialogue analysis
        self._analyze_dialogue(text, sentences, stats)

        # Readability
        self._calculate_readability(text, words, sentences, stats)

        # Adverbs
        self._analyze_adverbs(words, stats)

        # Clichés
        self._detect_cliches(text, stats)

        return stats

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        # Simple sentence splitter
        # Handle abbreviations, dialogue, etc.
        sentences = []

        # First, protect common abbreviations
        protected = text
        abbreviations = ['Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.', 'Jr.', 'Sr.',
                        'vs.', 'etc.', 'e.g.', 'i.e.', 'St.', 'Ave.', 'Blvd.']
        for abbr in abbreviations:
            protected = protected.replace(abbr, abbr.replace('.', '<DOT>'))

        # Split on sentence-ending punctuation
        parts = re.split(r'(?<=[.!?])\s+', protected)

        for part in parts:
            # Restore dots
            sentence = part.replace('<DOT>', '.')
            if sentence.strip():
                sentences.append(sentence.strip())

        return sentences

    def _analyze_sentence_lengths(self, sentences: List[str], stats: WritingStats):
        """Analyze sentence length distribution."""
        lengths = []

        for sentence in sentences:
            from src.utils.proofing import compound_tokens
            words = len(compound_tokens(sentence))
            lengths.append(words)

            if words < 10:
                stats.short_sentences += 1
            elif words <= 20:
                stats.medium_sentences += 1
            elif words <= 35:
                stats.long_sentences += 1
            else:
                stats.very_long_sentences += 1

        # Calculate variety score (standard deviation normalized)
        if len(lengths) > 1:
            import statistics
            try:
                std_dev = statistics.stdev(lengths)
                mean = statistics.mean(lengths)
                # Coefficient of variation as variety indicator
                cv = (std_dev / mean * 100) if mean > 0 else 0
                # Score: higher CV = more variety = better (cap at 100)
                stats.sentence_length_score = min(100, cv * 2)
            except:
                stats.sentence_length_score = 50.0

    def _analyze_sticky_sentences(self, sentences: List[str], stats: WritingStats):
        """Sticky sentences, by the editor's style check; the glue index with
        the same glue words."""
        total_glue_index = 0.0
        for sentence in sentences:
            words = _style_checks._WORD_RX.findall(sentence)
            if words:
                total_glue_index += sum(1 for w in words if w.lower() in _style_checks.GLUE) / len(words)
            if any(i.kind == "sticky_sentence" for i in
                   _style_checks.analyze_paragraph(sentence, {"sticky_sentence", "long_sentence"})):
                stats.sticky_sentences.append(sentence[:100] + '...' if len(sentence) > 100 else sentence)
        stats.sticky_sentence_count = len(stats.sticky_sentences)
        stats.avg_glue_index = total_glue_index / len(sentences) if sentences else 0

    def _analyze_echoes(self, text: str, stats: WritingStats):
        """Echoes, by the editor's style check, as (word, earlier word index,
        later word index) pairs."""
        from src.utils.proofing import COMPOUND_TOKEN_RX
        tokens = [m.group(0).lower() for m in COMPOUND_TOKEN_RX.finditer(text)]
        index_at = {m.start(): i for i, m in enumerate(COMPOUND_TOKEN_RX.finditer(text))}
        for issue in self._style_of("echo"):
            later = index_at.get(issue.start)
            if later is None:
                continue
            word = tokens[later]
            earlier = next((k for k in range(later - 1, -1, -1) if tokens[k] == word), later)
            stats.echoes.append((word, earlier, later))
        stats.echo_count = len(stats.echoes)

    def _analyze_passive_voice(self, sentences: List[str], stats: WritingStats):
        """Sentences with passive voice, by the editor's style check."""
        for sentence in sentences:
            if _style_checks.analyze_paragraph(sentence, {"passive"}):
                stats.passive_sentences.append(sentence[:100] + '...' if len(sentence) > 100 else sentence)
        stats.passive_count = len(stats.passive_sentences)
        stats.passive_percentage = (stats.passive_count / len(sentences) * 100) if sentences else 0

    def _analyze_dialogue(self, text: str, sentences: List[str], stats: WritingStats):
        """Analyze dialogue and dialogue tags."""
        # Find dialogue (text in quotes)
        dialogue_matches = re.findall(r'["\u201c][^"\u201d]+["\u201d]', text)
        dialogue_words = sum(len(m.split()) for m in dialogue_matches)
        total_words = len(text.split())

        stats.dialogue_percentage = (dialogue_words / total_words * 100) if total_words > 0 else 0

        # Find dialogue tags
        tag_pattern = re.compile(
            r'["\u201d]\s*(?:,\s*)?(?:he|she|they|i|we|[A-Z][a-z]+)\s+(\w+ed?)',
            re.IGNORECASE
        )

        stats.dialogue_tags = Counter()
        for match in tag_pattern.finditer(text):
            tag = match.group(1).lower()
            if tag in self.DIALOGUE_TAGS:
                stats.dialogue_tags[tag] += 1

        # Find overused tags (>3 uses)
        stats.overused_dialogue_tags = [
            tag for tag, count in stats.dialogue_tags.items() if count > 3
        ]

    def _calculate_readability(self, text: str, words: List[str], sentences: List[str], stats: WritingStats):
        """Calculate Flesch reading ease and grade level."""
        if not words or not sentences:
            return

        # Count syllables (simple approximation)
        def count_syllables(word: str) -> int:
            word = word.lower()
            vowels = 'aeiouy'
            count = 0
            prev_vowel = False
            for char in word:
                is_vowel = char in vowels
                if is_vowel and not prev_vowel:
                    count += 1
                prev_vowel = is_vowel
            # Adjust for silent e
            if word.endswith('e') and count > 1:
                count -= 1
            return max(1, count)

        total_syllables = sum(count_syllables(w) for w in words)
        avg_syllables = total_syllables / len(words)
        avg_sentence_len = len(words) / len(sentences)

        # Flesch Reading Ease
        # 206.835 - 1.015 * (words/sentences) - 84.6 * (syllables/words)
        stats.flesch_reading_ease = 206.835 - (1.015 * avg_sentence_len) - (84.6 * avg_syllables)
        stats.flesch_reading_ease = max(0, min(100, stats.flesch_reading_ease))

        # Flesch-Kincaid Grade Level
        # 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
        stats.flesch_grade_level = (0.39 * avg_sentence_len) + (11.8 * avg_syllables) - 15.59
        stats.flesch_grade_level = max(0, stats.flesch_grade_level)

    def _analyze_adverbs(self, words: List[str], stats: WritingStats):
        """Adverbs, by the editor's style check."""
        found = self._style_of("adverb")
        for issue in found:
            word = issue.text.lower()
            if word not in stats.adverbs:
                stats.adverbs.append(word)
        stats.adverb_count = len(found)
        stats.adverb_percentage = (stats.adverb_count / len(words) * 100) if words else 0

    def _detect_cliches(self, text: str, stats: WritingStats):
        """Clichés, by the editor's style check (each one once)."""
        for issue in self._style_of("cliche"):
            phrase = issue.text.lower()
            if phrase not in stats.cliches:
                stats.cliches.append(phrase)
        stats.cliche_count = len(stats.cliches)

    def _style_of(self, kind: str) -> list:
        return [i for i in getattr(self, "_style", []) if i.kind == kind]

    def format_report(self, stats: WritingStats) -> str:
        """Format stats as an HTML report."""
        html = """
        <style>
            .stat-section { margin: 15px 0; padding: 10px; background: #f5f5f5; border-radius: 4px; }
            .stat-header { font-weight: bold; color: #374151; margin-bottom: 8px; }
            .stat-value { color: #059669; font-weight: bold; }
            .stat-warning { color: #dc2626; }
            .stat-ok { color: #059669; }
            .meter { height: 10px; background: #e5e7eb; border-radius: 5px; margin: 5px 0; }
            .meter-fill { height: 100%; border-radius: 5px; }
            .list-item { padding: 4px 0; border-bottom: 1px solid #e5e7eb; }
        </style>
        """

        # Overview
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>📊 Document Overview</div>
            <p>Words: <span class='stat-value'>{stats.word_count:,}</span> |
               Sentences: <span class='stat-value'>{stats.sentence_count:,}</span> |
               Paragraphs: <span class='stat-value'>{stats.paragraph_count:,}</span></p>
            <p>Avg sentence length: <span class='stat-value'>{stats.avg_sentence_length:.1f}</span> words |
               Avg word length: <span class='stat-value'>{stats.avg_word_length:.1f}</span> chars</p>
        </div>
        """

        # Sentence Length Variation
        variety_class = 'stat-ok' if stats.sentence_length_score > 40 else 'stat-warning'
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>📏 Sentence Length Variation</div>
            <p>Short (< 10 words): {stats.short_sentences} |
               Medium (10-20): {stats.medium_sentences} |
               Long (21-35): {stats.long_sentences} |
               Very Long (> 35): {stats.very_long_sentences}</p>
            <p>Variety Score: <span class='{variety_class}'>{stats.sentence_length_score:.0f}/100</span></p>
            <div class='meter'><div class='meter-fill' style='width: {stats.sentence_length_score}%; background: {"#059669" if stats.sentence_length_score > 40 else "#dc2626"};'></div></div>
        </div>
        """

        # Sticky Sentences
        sticky_class = 'stat-ok' if stats.sticky_sentence_count < 3 else 'stat-warning'
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>🔗 Sticky Sentences (high glue word %)</div>
            <p>Sticky sentences: <span class='{sticky_class}'>{stats.sticky_sentence_count}</span> |
               Avg glue index: {stats.avg_glue_index:.1%}</p>
        """
        if stats.sticky_sentences[:3]:
            html += "<div style='font-size: 11px; color: #666; margin-top: 5px;'>"
            for s in stats.sticky_sentences[:3]:
                html += f"<div class='list-item'>• {s}</div>"
            if len(stats.sticky_sentences) > 3:
                html += f"<div class='list-item'><em>...and {len(stats.sticky_sentences) - 3} more</em></div>"
            html += "</div>"
        html += "</div>"

        # Echoes
        echo_class = 'stat-ok' if stats.echo_count < 5 else 'stat-warning'
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>🔁 Echoes (repeated words nearby)</div>
            <p>Echoes found: <span class='{echo_class}'>{stats.echo_count}</span></p>
        """
        if stats.echoes[:5]:
            echo_words = list(set([e[0] for e in stats.echoes[:10]]))
            html += f"<p style='font-size: 11px; color: #666;'>Words: {', '.join(echo_words[:8])}</p>"
        html += "</div>"

        # Passive Voice
        passive_class = 'stat-ok' if stats.passive_percentage < 15 else 'stat-warning'
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>🔄 Passive Voice</div>
            <p>Passive sentences: <span class='{passive_class}'>{stats.passive_count}</span> ({stats.passive_percentage:.1f}%)</p>
        </div>
        """

        # Dialogue
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>💬 Dialogue Analysis</div>
            <p>Dialogue: {stats.dialogue_percentage:.1f}% of text</p>
        """
        if stats.dialogue_tags:
            top_tags = sorted(stats.dialogue_tags.items(), key=lambda x: -x[1])[:5]
            html += "<p style='font-size: 11px;'>Tags: "
            html += ', '.join([f"{tag} ({count})" for tag, count in top_tags])
            html += "</p>"
        if stats.overused_dialogue_tags:
            html += f"<p class='stat-warning' style='font-size: 11px;'>Overused: {', '.join(stats.overused_dialogue_tags)}</p>"
        html += "</div>"

        # Readability
        ease_desc = self._get_readability_description(stats.flesch_reading_ease)
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>📖 Readability</div>
            <p>Flesch Reading Ease: <span class='stat-value'>{stats.flesch_reading_ease:.1f}</span> ({ease_desc})</p>
            <p>Grade Level: <span class='stat-value'>{stats.flesch_grade_level:.1f}</span></p>
        </div>
        """

        # Adverbs
        adverb_class = 'stat-ok' if stats.adverb_percentage < 3 else 'stat-warning'
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>📝 Adverb Usage</div>
            <p>Adverbs: <span class='{adverb_class}'>{stats.adverb_count}</span> ({stats.adverb_percentage:.1f}%)</p>
        """
        if stats.adverbs[:10]:
            html += f"<p style='font-size: 11px; color: #666;'>Examples: {', '.join(stats.adverbs[:10])}</p>"
        html += "</div>"

        # Clichés
        cliche_class = 'stat-ok' if stats.cliche_count == 0 else 'stat-warning'
        html += f"""
        <div class='stat-section'>
            <div class='stat-header'>⚠️ Clichés</div>
            <p>Clichés found: <span class='{cliche_class}'>{stats.cliche_count}</span></p>
        """
        if stats.cliches:
            html += f"<p style='font-size: 11px; color: #666;'>{', '.join(stats.cliches[:5])}</p>"
        html += "</div>"

        return html

    def _get_readability_description(self, score: float) -> str:
        """Get description for Flesch reading ease score."""
        if score >= 90:
            return "Very Easy"
        elif score >= 80:
            return "Easy"
        elif score >= 70:
            return "Fairly Easy"
        elif score >= 60:
            return "Standard"
        elif score >= 50:
            return "Fairly Difficult"
        elif score >= 30:
            return "Difficult"
        else:
            return "Very Difficult"
