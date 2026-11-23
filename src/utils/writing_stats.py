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
    GLUE_WORDS = {
        'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
        'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'been',
        'be', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
        'could', 'should', 'may', 'might', 'must', 'shall', 'can', 'need',
        'it', 'its', 'this', 'that', 'these', 'those', 'i', 'you', 'he',
        'she', 'we', 'they', 'me', 'him', 'her', 'us', 'them', 'my', 'your',
        'his', 'our', 'their', 'what', 'which', 'who', 'whom', 'whose',
        'if', 'then', 'else', 'when', 'where', 'why', 'how', 'all', 'each',
        'every', 'both', 'few', 'more', 'most', 'other', 'some', 'such', 'no',
        'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
        'also', 'now', 'here', 'there', 'still', 'already', 'even', 'again',
        'into', 'through', 'during', 'before', 'after', 'above', 'below',
        'between', 'under', 'over', 'up', 'down', 'out', 'off', 'about',
        'any', 'am', 'being', 'having', 'doing', 'get', 'got', 'getting',
    }

    # Passive voice indicators
    PASSIVE_HELPERS = {'was', 'were', 'is', 'are', 'been', 'being', 'be', 'am'}

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
    CLICHES = {
        'at the end of the day', 'in the nick of time', 'all of a sudden',
        'in the blink of an eye', 'better late than never', 'as luck would have it',
        'a matter of time', 'the tip of the iceberg', 'a sigh of relief',
        'with bated breath', 'without a doubt', 'at first glance',
        'crystal clear', 'dead of night', 'in broad daylight', 'pitch black',
        'blood ran cold', 'heart skipped a beat', 'butterflies in stomach',
        'like a deer in headlights', 'like a fish out of water', 'cold as ice',
        'white as a sheet', 'red as a tomato', 'black as night', 'clear as day',
        'quiet as a mouse', 'sick as a dog', 'fit as a fiddle', 'stubborn as a mule',
        'light as a feather', 'heavy as lead', 'sharp as a tack', 'dumb as a rock',
        'needle in a haystack', 'easy as pie', 'piece of cake', 'walk in the park',
        'once upon a time', 'happily ever after', 'in the end', 'last but not least',
        'long story short', 'to make a long story short', 'bottom line',
        'at this point in time', 'going forward', 'on the same page',
        'think outside the box', 'low hanging fruit', 'push the envelope',
        'touch base', 'circle back', 'move the needle',
    }

    # Common adverbs to flag
    COMMON_ADVERBS = {
        'really', 'very', 'actually', 'basically', 'literally', 'totally',
        'absolutely', 'definitely', 'certainly', 'obviously', 'clearly',
        'simply', 'just', 'quite', 'rather', 'somewhat', 'fairly',
        'extremely', 'incredibly', 'particularly', 'especially',
        'suddenly', 'immediately', 'quickly', 'slowly', 'carefully',
        'quietly', 'loudly', 'softly', 'hardly', 'nearly', 'almost',
        'completely', 'entirely', 'perfectly', 'truly', 'honestly',
    }

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
        """Analyze sentences for high glue word percentage (sticky sentences)."""
        sticky_threshold = 0.45  # 45% glue words = sticky
        total_glue_index = 0

        for sentence in sentences:
            from src.utils.proofing import compound_tokens
            words = compound_tokens(sentence.lower())
            if len(words) < 4:
                continue

            glue_count = sum(1 for w in words if w in self.GLUE_WORDS)
            glue_index = glue_count / len(words) if words else 0
            total_glue_index += glue_index

            if glue_index >= sticky_threshold:
                stats.sticky_sentences.append(sentence[:100] + '...' if len(sentence) > 100 else sentence)

        stats.sticky_sentence_count = len(stats.sticky_sentences)
        stats.avg_glue_index = total_glue_index / len(sentences) if sentences else 0

    def _analyze_echoes(self, text: str, stats: WritingStats):
        """Find words repeated within close proximity (echoes)."""
        from src.utils.proofing import compound_tokens
        # Only words 4+ chars; contractions and compounds stay whole
        # ("didn't", "one-half") and helper-word contractions aren't echoes.
        words = [w for w in compound_tokens(text.lower())
                 if len(w) >= 4 and not w.endswith("n't")
                 and w.split("'", 1)[0] not in self.GLUE_WORDS]
        word_positions: Dict[str, List[int]] = {}

        for i, word in enumerate(words):
            if word in self.GLUE_WORDS:
                continue
            if word not in word_positions:
                word_positions[word] = []
            word_positions[word].append(i)

        # Find echoes (same word within 10 words)
        echo_distance = 10
        for word, positions in word_positions.items():
            for i in range(len(positions) - 1):
                if positions[i+1] - positions[i] <= echo_distance:
                    stats.echoes.append((word, positions[i], positions[i+1]))

        stats.echo_count = len(stats.echoes)

    def _analyze_passive_voice(self, sentences: List[str], stats: WritingStats):
        """Detect passive voice constructions."""
        # Pattern: was/were/is/are/been/being + past participle (often ends in -ed)
        passive_pattern = re.compile(
            r'\b(was|were|is|are|am|been|being|be)\s+(?:\w+\s+)?(\w+ed|written|spoken|taken|given|made|done|seen|known|found|felt)\b',
            re.IGNORECASE
        )

        for sentence in sentences:
            if passive_pattern.search(sentence):
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
        """Analyze adverb usage."""
        word_list = [w.lower() for w in words]

        # Find -ly adverbs and common adverbs
        for word in word_list:
            if word.endswith('ly') and len(word) > 3:
                if word not in stats.adverbs:
                    stats.adverbs.append(word)
            elif word in self.COMMON_ADVERBS:
                if word not in stats.adverbs:
                    stats.adverbs.append(word)

        stats.adverb_count = sum(1 for w in word_list if w in stats.adverbs or (w.endswith('ly') and len(w) > 3))
        stats.adverb_percentage = (stats.adverb_count / len(words) * 100) if words else 0

    def _detect_cliches(self, text: str, stats: WritingStats):
        """Detect clichés in text."""
        text_lower = text.lower()

        for cliche in self.CLICHES:
            if cliche in text_lower:
                stats.cliches.append(cliche)

        stats.cliche_count = len(stats.cliches)

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
