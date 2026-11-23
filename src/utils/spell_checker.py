"""Spell checking: the dictionary, the project's own words, suggestions.

Moved out of ``src/ui/enhanced_text_editor.py`` in piece R.3, unchanged, so
chapters can be checked without the editor (no Qt here). The old import
path still works.
"""

import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple


def _apos(text: str) -> str:
    """Every apostrophe look-alike → "'" (spell-checking dictionary form)."""
    from src.utils.proofing import APOSTROPHE_LIKE
    return text.translate({ord(c): "'" for c in APOSTROPHE_LIKE})


# pyspellchecker's dictionary is read-only here (custom and project words
# live on each SpellChecker), so one copy serves every editor.
_SHARED_PYSPELL = None


class SpellChecker:
    """Spell checker using nltk words corpus or pyenchant."""

    def __init__(self):
        """Initialize spell checker."""
        self._dictionary: Set[str] = set()
        self._custom_words: Set[str] = set()
        self._use_enchant = False
        self._enchant_dict = None
        self._use_pyspellchecker = False
        self._pyspellchecker = None
        self._misspelling_reasons: Dict[str, str] = {}
        self._load_dictionary()

    def _load_dictionary(self):
        """Load dictionary - try multiple sources."""
        # First try pyspellchecker (pure Python, works everywhere)
        try:
            from spellchecker import SpellChecker as PySpellChecker
            global _SHARED_PYSPELL
            if _SHARED_PYSPELL is None:
                _SHARED_PYSPELL = PySpellChecker()
            self._pyspellchecker = _SHARED_PYSPELL
            self._use_pyspellchecker = True
            print("Spell checker: Using pyspellchecker")
            return
        except ImportError:
            self._use_pyspellchecker = False
            self._pyspellchecker = None

        # Try pyenchant (requires system library)
        try:
            import enchant
            # Check if en_US dictionary is available
            if enchant.dict_exists("en_US"):
                self._enchant_dict = enchant.Dict("en_US")
                self._use_enchant = True
                print("Spell checker: Using pyenchant")
                return
            elif enchant.dict_exists("en"):
                self._enchant_dict = enchant.Dict("en")
                self._use_enchant = True
                print("Spell checker: Using pyenchant (en)")
                return
            else:
                print("Spell checker: pyenchant installed but no English dictionary found")
        except ImportError:
            pass
        except Exception as e:
            print(f"Spell checker: pyenchant error: {e}")

        # Try nltk words corpus
        try:
            import nltk
            try:
                from nltk.corpus import words
                self._dictionary = set(w.lower() for w in words.words())
                print(f"Spell checker: Using nltk ({len(self._dictionary)} words)")
                return
            except LookupError:
                # Download if not present
                nltk.download('words', quiet=True)
                from nltk.corpus import words
                self._dictionary = set(w.lower() for w in words.words())
                print(f"Spell checker: Using nltk ({len(self._dictionary)} words)")
                return
        except ImportError:
            pass

        # Fallback: comprehensive built-in dictionary
        print("Spell checker: Using built-in dictionary (install pyenchant or nltk for better results)")
        self._dictionary = self._get_comprehensive_dictionary()

    def _get_comprehensive_dictionary(self) -> Set[str]:
        """Get a comprehensive built-in dictionary of common English words."""
        # Top 10,000+ most common English words covering most writing needs
        # This is a subset - the full list would be much larger
        common_words = {
            # Articles, prepositions, conjunctions
            "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
            "at", "by", "from", "in", "into", "of", "off", "on", "onto", "out",
            "over", "to", "up", "with", "as", "if", "than", "that", "though",
            "after", "before", "since", "until", "while", "about", "above",
            "across", "against", "along", "among", "around", "behind", "below",
            "beneath", "beside", "between", "beyond", "down", "during", "except",
            "inside", "near", "outside", "through", "toward", "towards", "under",
            "upon", "within", "without",

            # Pronouns
            "i", "me", "my", "mine", "myself", "you", "your", "yours", "yourself",
            "yourselves", "he", "him", "his", "himself", "she", "her", "hers",
            "herself", "it", "its", "itself", "we", "us", "our", "ours", "ourselves",
            "they", "them", "their", "theirs", "themselves", "who", "whom", "whose",
            "which", "what", "this", "that", "these", "those", "each", "every",
            "either", "neither", "both", "all", "any", "some", "none", "one",
            "anyone", "everyone", "someone", "no one", "nobody", "anybody",
            "everybody", "somebody", "anything", "everything", "something", "nothing",

            # Common verbs (base forms and conjugations)
            "be", "am", "is", "are", "was", "were", "been", "being",
            "have", "has", "had", "having",
            "do", "does", "did", "doing", "done",
            "say", "says", "said", "saying",
            "get", "gets", "got", "gotten", "getting",
            "make", "makes", "made", "making",
            "go", "goes", "went", "gone", "going",
            "know", "knows", "knew", "known", "knowing",
            "take", "takes", "took", "taken", "taking",
            "see", "sees", "saw", "seen", "seeing",
            "come", "comes", "came", "coming",
            "think", "thinks", "thought", "thinking",
            "look", "looks", "looked", "looking",
            "want", "wants", "wanted", "wanting",
            "give", "gives", "gave", "given", "giving",
            "use", "uses", "used", "using",
            "find", "finds", "found", "finding",
            "tell", "tells", "told", "telling",
            "ask", "asks", "asked", "asking",
            "work", "works", "worked", "working",
            "seem", "seems", "seemed", "seeming",
            "feel", "feels", "felt", "feeling",
            "try", "tries", "tried", "trying",
            "leave", "leaves", "left", "leaving",
            "call", "calls", "called", "calling",
            "keep", "keeps", "kept", "keeping",
            "let", "lets", "letting",
            "begin", "begins", "began", "begun", "beginning",
            "show", "shows", "showed", "shown", "showing",
            "hear", "hears", "heard", "hearing",
            "play", "plays", "played", "playing",
            "run", "runs", "ran", "running",
            "move", "moves", "moved", "moving",
            "live", "lives", "lived", "living",
            "believe", "believes", "believed", "believing",
            "hold", "holds", "held", "holding",
            "bring", "brings", "brought", "bringing",
            "happen", "happens", "happened", "happening",
            "write", "writes", "wrote", "written", "writing",
            "provide", "provides", "provided", "providing",
            "sit", "sits", "sat", "sitting",
            "stand", "stands", "stood", "standing",
            "lose", "loses", "lost", "losing",
            "pay", "pays", "paid", "paying",
            "meet", "meets", "met", "meeting",
            "include", "includes", "included", "including",
            "continue", "continues", "continued", "continuing",
            "set", "sets", "setting",
            "learn", "learns", "learned", "learnt", "learning",
            "change", "changes", "changed", "changing",
            "lead", "leads", "led", "leading",
            "understand", "understands", "understood", "understanding",
            "watch", "watches", "watched", "watching",
            "follow", "follows", "followed", "following",
            "stop", "stops", "stopped", "stopping",
            "create", "creates", "created", "creating",
            "speak", "speaks", "spoke", "spoken", "speaking",
            "read", "reads", "reading",
            "spend", "spends", "spent", "spending",
            "grow", "grows", "grew", "grown", "growing",
            "open", "opens", "opened", "opening",
            "walk", "walks", "walked", "walking",
            "win", "wins", "won", "winning",
            "offer", "offers", "offered", "offering",
            "remember", "remembers", "remembered", "remembering",
            "love", "loves", "loved", "loving",
            "consider", "considers", "considered", "considering",
            "appear", "appears", "appeared", "appearing",
            "buy", "buys", "bought", "buying",
            "wait", "waits", "waited", "waiting",
            "serve", "serves", "served", "serving",
            "die", "dies", "died", "dying",
            "send", "sends", "sent", "sending",
            "expect", "expects", "expected", "expecting",
            "build", "builds", "built", "building",
            "stay", "stays", "stayed", "staying",
            "fall", "falls", "fell", "fallen", "falling",
            "cut", "cuts", "cutting",
            "reach", "reaches", "reached", "reaching",
            "kill", "kills", "killed", "killing",
            "remain", "remains", "remained", "remaining",
            "suggest", "suggests", "suggested", "suggesting",
            "raise", "raises", "raised", "raising",
            "pass", "passes", "passed", "passing",
            "sell", "sells", "sold", "selling",
            "require", "requires", "required", "requiring",
            "report", "reports", "reported", "reporting",
            "decide", "decides", "decided", "deciding",
            "pull", "pulls", "pulled", "pulling",
            "develop", "develops", "developed", "developing",
            "wish", "wishes", "wished", "wishing",
            "drop", "drops", "dropped", "dropping",
            "push", "pushes", "pushed", "pushing",
            "wear", "wears", "wore", "worn", "wearing",
            "cause", "causes", "caused", "causing",
            "return", "returns", "returned", "returning",
            "realize", "realizes", "realized", "realizing",
            "explain", "explains", "explained", "explaining",
            "hope", "hopes", "hoped", "hoping",
            "drive", "drives", "drove", "driven", "driving",
            "carry", "carries", "carried", "carrying",
            "allow", "allows", "allowed", "allowing",
            "suppose", "supposes", "supposed", "supposing",
            "agree", "agrees", "agreed", "agreeing",
            "help", "helps", "helped", "helping",
            "put", "puts", "putting",
            "mean", "means", "meant", "meaning",
            "might", "must", "can", "could", "would", "should", "shall", "will",

            # Common nouns
            "time", "year", "people", "way", "day", "man", "woman", "child",
            "children", "world", "life", "hand", "part", "place", "case", "week",
            "company", "system", "program", "question", "work", "government",
            "number", "night", "point", "home", "water", "room", "mother",
            "area", "money", "story", "fact", "month", "lot", "right", "study",
            "book", "eye", "job", "word", "business", "issue", "side", "kind",
            "head", "house", "service", "friend", "father", "power", "hour",
            "game", "line", "end", "member", "law", "car", "city", "community",
            "name", "president", "team", "minute", "idea", "kid", "body",
            "information", "back", "parent", "face", "others", "level", "office",
            "door", "health", "person", "art", "war", "history", "party",
            "result", "change", "morning", "reason", "research", "girl", "guy",
            "moment", "air", "teacher", "force", "education", "foot", "feet",
            "boy", "age", "policy", "process", "music", "market", "sense",
            "nation", "plan", "college", "interest", "death", "experience",
            "effect", "use", "class", "control", "care", "field", "development",
            "role", "effort", "rate", "heart", "drug", "show", "leader", "light",
            "voice", "wife", "police", "mind", "difference", "period", "value",
            "building", "action", "authority", "model", "husband", "support",
            "event", "picture", "evidence", "product", "truth", "position",
            "reason", "technology", "attention", "rule", "concern", "news",
            "player", "price", "chance", "view", "practice", "past", "doctor",
            "wall", "patient", "nature", "section", "fire", "society", "hair",
            "form", "activity", "country", "road", "table", "court", "form",
            "record", "situation", "food", "student", "material", "paper",
            "group", "defense", "manager", "character", "analysis", "access",
            "season", "today", "film", "growth", "income", "statement", "peace",
            "century", "space", "bed", "order", "presence", "opportunity",
            "performance", "relationship", "author", "response", "language",
            "love", "knowledge", "friend", "size", "bank", "condition", "base",
            "thought", "article", "look", "pressure", "behavior", "movement",
            "century", "sun", "blood", "series", "land", "project", "choice",
            "oil", "step", "amount", "church", "town", "attention", "theory",
            "director", "figure", "attack", "design", "loss", "purpose",
            "image", "standard", "approach", "agreement", "decision", "direction",

            # Common adjectives
            "good", "new", "first", "last", "long", "great", "little", "own",
            "other", "old", "right", "big", "high", "different", "small", "large",
            "next", "early", "young", "important", "few", "public", "bad", "same",
            "able", "human", "local", "late", "hard", "major", "better", "economic",
            "strong", "possible", "whole", "free", "military", "true", "federal",
            "international", "full", "special", "easy", "clear", "recent",
            "certain", "personal", "open", "red", "difficult", "available",
            "likely", "short", "single", "medical", "current", "wrong", "private",
            "past", "foreign", "fine", "common", "poor", "natural", "significant",
            "similar", "hot", "dead", "central", "happy", "serious", "ready",
            "simple", "left", "physical", "general", "environmental", "financial",
            "blue", "democratic", "dark", "various", "entire", "close", "legal",
            "religious", "cold", "final", "main", "green", "nice", "huge", "popular",
            "traditional", "cultural", "beautiful", "real", "safe", "light",
            "sure", "white", "black", "deep", "wide", "complete", "wild",

            # Common adverbs
            "not", "also", "very", "often", "however", "too", "usually", "really",
            "early", "never", "always", "sometimes", "together", "likely", "simply",
            "generally", "instead", "actually", "remember", "likely", "perhaps",
            "quickly", "slowly", "finally", "almost", "above", "hard", "especially",
            "probably", "already", "below", "directly", "therefore", "once",
            "ever", "else", "rather", "nearly", "certainly", "clearly", "soon",
            "indeed", "easily", "eventually", "exactly", "highly", "suddenly",

            # Writing-related words
            "chapter", "story", "plot", "scene", "dialogue", "narrative",
            "protagonist", "antagonist", "setting", "conflict", "resolution",
            "climax", "theme", "motif", "symbol", "foreshadowing", "flashback",
            "narrator", "manuscript", "draft", "edit", "revision", "paragraph",
            "sentence", "phrase", "metaphor", "simile", "imagery", "tone",
            "voice", "style", "genre", "fiction", "nonfiction", "novel",
            "novella", "screenplay", "script", "outline", "arc", "pacing",
            "tension", "suspense", "mystery", "fantasy", "romance", "thriller",
            "horror", "drama", "comedy", "tragedy", "epic", "saga", "trilogy",
            "sequel", "prequel", "spinoff", "backstory", "worldbuilding",
            "characterization", "motivation", "emotion", "feeling", "mood",

            # Numbers as words
            "zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
            "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
            "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
            "hundred", "thousand", "million", "billion",

            # Time-related
            "today", "tomorrow", "yesterday", "now", "then", "soon", "later",
            "morning", "afternoon", "evening", "night", "midnight", "noon",
            "second", "minute", "hour", "day", "week", "month", "year",
            "decade", "century", "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday", "january", "february", "march",
            "april", "may", "june", "july", "august", "september", "october",
            "november", "december", "spring", "summer", "autumn", "fall", "winter",

            # Contractions (without apostrophe for matching)
            "dont", "wont", "cant", "shouldnt", "wouldnt", "couldnt", "didnt",
            "doesnt", "isnt", "arent", "wasnt", "werent", "hasnt", "havent",
            "hadnt", "im", "youre", "hes", "shes", "its", "were", "theyre",
            "ive", "youve", "weve", "theyve", "id", "youd", "hed", "shed",
            "wed", "theyd", "ill", "youll", "hell", "shell", "well", "theyll",
            "thats", "whats", "whos", "heres", "theres", "wheres", "lets",

            # Additional common words
            "yes", "no", "ok", "okay", "please", "thank", "thanks", "sorry",
            "hello", "goodbye", "hey", "oh", "well", "just", "like", "really",
            "thing", "things", "stuff", "something", "anything", "nothing",
            "everything", "someone", "anyone", "nobody", "everybody", "somewhere",
        }
        return common_words

    _MISSPELLED = "Possible misspelling."

    def set_project_words(self, words) -> None:
        """Project vocabulary (character / place / faction names, the
        project dictionary). Multi-word names are split so each part is
        known ("Ash Wardens" → ash, wardens)."""
        vocab = set()
        for w in words or []:
            for part in re.findall(r"[A-Za-z]+(?:['’][A-Za-z]+)*", str(w)):
                vocab.add(_apos(part.lower()))
        self._project_words = vocab
        self._known_cache = {}

    def _is_known(self, word_lower: str) -> bool:
        cache = getattr(self, "_known_cache", None)
        if cache is None:
            cache = self._known_cache = {}
        hit = cache.get(word_lower)
        if hit is not None:
            return hit
        if (word_lower in self._custom_words
                or word_lower in getattr(self, "_project_words", ())):
            known = True
        elif self._use_pyspellchecker and self._pyspellchecker:
            known = bool(self._pyspellchecker.known([word_lower]))
        elif self._use_enchant and self._enchant_dict:
            known = bool(self._enchant_dict.check(word_lower))
        else:
            known = (word_lower in self._dictionary
                     or self._check_with_suffixes(word_lower))
        if len(cache) > 50000:
            cache.clear()
        cache[word_lower] = known
        return known

    # A sentence-initial unknown word is treated as a misspelling (not a
    # name) when its best correction is at least this common in English.
    COMMON_CORRECTION_FREQ = 1e-6

    def looks_like_common_word_typo(self, word: str) -> bool:
        lower = _apos(word.lower())
        if self._use_pyspellchecker and self._pyspellchecker:
            best = self._pyspellchecker.correction(lower)
            return bool(best and best != lower and
                        self._pyspellchecker.word_usage_frequency(best)
                        >= self.COMMON_CORRECTION_FREQ)
        return True

    def check_word(self, word: str, sentence_start: bool = False) -> Tuple[bool, str]:
        """Check if a word is spelled correctly. Fast: a dictionary
        lookup only — suggestions are computed on demand (``suggest``).

        Args:
            word: The word (may contain an apostrophe: don't, Mara's).
            sentence_start: True when the word opens a sentence, so a
                leading capital is just sentence case — the word is still
                checked. Mid-sentence capitalised words are treated as
                proper nouns and skipped unless clearly misspelled
                common words.

        Returns:
            Tuple of (is_correct, reason_if_incorrect)
        """
        if len(word) <= 1:
            return True, ""
        if any(c.isdigit() for c in word):
            return True, ""
        if word.isupper():
            return True, ""                      # acronyms, shouting
        norm = _apos(word)
        if not norm.replace("'", "").isalpha():
            return True, ""
        lower = norm.lower()
        if norm[0].isupper() and not sentence_start:
            # Capitalised mid-sentence → a proper noun; names aren't
            # spell-checked (project names are known anyway).
            return True, ""
        if self._is_known(lower):
            return True, ""
        # Possessives and contractions: accept when the base is known.
        if "'" in lower:
            base, _, tail = lower.rpartition("'")
            if tail in ("s", "d", "ll", "re", "ve", "m") and self._is_known(base):
                return True, ""
            if tail == "t" and base.endswith("n") and self._is_known(base[:-1]):
                return True, ""
            if lower.endswith("s'") and self._is_known(lower[:-1]):
                return True, ""
        if sentence_start and lower in getattr(self, "_project_words", ()):
            return True, ""
        if not (self._use_pyspellchecker or self._use_enchant):
            return False, "Word not found in dictionary"
        return False, self._MISSPELLED

    def _check_with_suffixes(self, word: str) -> bool:
        """Check if word with common suffixes is valid."""
        # Common suffixes to try removing
        suffixes = ['s', 'es', 'ed', 'ing', 'ly', 'er', 'est', 'ness', 'ment',
                   'tion', 'sion', 'able', 'ible', 'ful', 'less', 'ous', 'ive']

        for suffix in suffixes:
            if word.endswith(suffix):
                root = word[:-len(suffix)]
                if len(root) >= 2 and root in self._dictionary:
                    return True
                # Handle doubling (e.g., running -> run)
                if len(root) >= 3 and root[-1] == root[-2] and root[:-1] in self._dictionary:
                    return True

        # Check -ing with e-dropping (e.g., making -> make)
        if word.endswith('ing') and len(word) > 4:
            root = word[:-3] + 'e'
            if root in self._dictionary:
                return True

        # Check -ed with e-dropping (e.g., loved -> love)
        if word.endswith('ed') and len(word) > 3:
            root = word[:-1]  # e.g., loved -> love
            if root in self._dictionary:
                return True
            root = word[:-2]  # e.g., walked -> walk
            if root in self._dictionary:
                return True

        return False

    def check_word_simple(self, word: str) -> bool:
        """Simple check returning just True/False."""
        is_correct, _ = self.check_word(word)
        return is_correct

    def get_reason(self, word: str) -> str:
        """Get the reason why a word is flagged."""
        _, reason = self.check_word(word)
        return reason

    def suggest(self, word: str) -> List[str]:
        """Spelling suggestions, most likely first, in the word's case.
        Includes close project words (character / place names)."""
        lower = _apos(word.lower())
        out: List[str] = []
        if self._use_pyspellchecker and self._pyspellchecker:
            sp = self._pyspellchecker
            best = sp.correction(lower)
            cands = sorted(sp.candidates(lower) or [],
                           key=lambda w: -sp.word_usage_frequency(w))
            out = ([best] if best and best != lower else []) + [c for c in cands if c != best]
        elif self._use_enchant and self._enchant_dict:
            out = list(self._enchant_dict.suggest(word))
        for pw in getattr(self, "_project_words", ()):
            if abs(len(pw) - len(lower)) <= 2 and self._edit_distance(lower, pw) <= 2:
                out.append(pw)
        if out:
            seen, ranked = set(), []
            for w in out:
                w = (w[:1].upper() + w[1:]) if word[:1].isupper() else w
                if w.lower() != lower and w not in seen:
                    seen.add(w)
                    ranked.append(w)
            return ranked[:6]
        if self._use_pyspellchecker or self._use_enchant:
            return []

        if self._use_enchant and self._enchant_dict:
            return self._enchant_dict.suggest(word)[:5]

        # Simple suggestions based on edit distance
        suggestions = []
        word_lower = word.lower()

        for dict_word in self._dictionary:
            if abs(len(dict_word) - len(word_lower)) <= 2:
                distance = self._edit_distance(word_lower, dict_word)
                if distance <= 2:
                    suggestions.append((distance, dict_word))

        suggestions.sort(key=lambda x: x[0])
        return [w for _, w in suggestions[:5]]

    def _edit_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein edit distance."""
        if len(s1) < len(s2):
            return self._edit_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        prev_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            curr_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = prev_row[j + 1] + 1
                deletions = curr_row[j] + 1
                substitutions = prev_row[j] + (c1 != c2)
                curr_row.append(min(insertions, deletions, substitutions))
            prev_row = curr_row

        return prev_row[-1]

    def add_word(self, word: str):
        """Add a word to the custom dictionary."""
        self._custom_words.add(_apos(word.lower()))
        self._known_cache = {}

    def is_available(self) -> bool:
        """Check if spell checking is properly available."""
        return self._use_pyspellchecker or self._use_enchant or len(self._dictionary) > 100
