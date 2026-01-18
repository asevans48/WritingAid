"""Thesaurus utility for synonym lookup."""

import re
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# Try to import NLTK for WordNet support
_WORDNET_AVAILABLE = False
_LEMMATIZER_AVAILABLE = False
_wordnet = None
_lemmatizer = None

try:
    from nltk.corpus import wordnet as _wordnet
    # Test if wordnet data is available
    _wordnet.synsets('test')
    _WORDNET_AVAILABLE = True

    # Try to get the lemmatizer (uses WordNet's morphy internally)
    try:
        from nltk.stem import WordNetLemmatizer
        _lemmatizer = WordNetLemmatizer()
        # Test it works
        _lemmatizer.lemmatize('testing', pos='v')
        _LEMMATIZER_AVAILABLE = True
    except (ImportError, LookupError):
        _LEMMATIZER_AVAILABLE = False
except (ImportError, LookupError):
    _WORDNET_AVAILABLE = False


@dataclass
class SynonymResult:
    """Result from a synonym lookup."""
    word: str
    synonyms: List[str]
    antonyms: List[str] = None

    def __post_init__(self):
        if self.antonyms is None:
            self.antonyms = []


class WordStemmer:
    """Simple rule-based word stemmer for English.

    Handles common suffixes to find base forms of words.
    More lightweight than full NLP stemmers but good enough for thesaurus lookup.
    """

    # Irregular verb forms -> base form
    IRREGULAR_VERBS: Dict[str, str] = {
        # be
        "am": "be", "is": "be", "are": "be", "was": "be", "were": "be", "been": "be", "being": "be",
        # have
        "has": "have", "had": "have", "having": "have",
        # do
        "does": "do", "did": "do", "done": "do", "doing": "do",
        # go
        "goes": "go", "went": "go", "gone": "go", "going": "go",
        # say
        "says": "say", "saying": "say",
        # get
        "gets": "get", "got": "get", "gotten": "get", "getting": "get",
        # make
        "makes": "make", "made": "make", "making": "make",
        # know
        "knows": "know", "knew": "know", "known": "know", "knowing": "know",
        # think
        "thinks": "think", "thought": "think", "thinking": "think",
        # take
        "takes": "take", "took": "take", "taken": "take", "taking": "take",
        # see
        "sees": "see", "saw": "see", "seen": "see", "seeing": "see",
        # come
        "comes": "come", "came": "come", "coming": "come",
        # want
        "wants": "want", "wanted": "want", "wanting": "want",
        # look
        "looks": "look", "looked": "look", "looking": "look",
        # give
        "gives": "give", "gave": "give", "given": "give", "giving": "give",
        # find
        "finds": "find", "found": "find", "finding": "find",
        # tell
        "tells": "tell", "told": "tell", "telling": "tell",
        # feel
        "feels": "feel", "felt": "feel", "feeling": "feel",
        # become
        "becomes": "become", "became": "become", "becoming": "become",
        # leave
        "leaves": "leave", "left": "leave", "leaving": "leave",
        # put
        "puts": "put", "putting": "put",
        # keep
        "keeps": "keep", "kept": "keep", "keeping": "keep",
        # begin
        "begins": "begin", "began": "begin", "begun": "begin", "beginning": "begin",
        # write
        "writes": "write", "wrote": "write", "written": "write", "writing": "write",
        # run
        "runs": "run", "ran": "run", "running": "run",
        # read
        "reads": "read", "reading": "read",
        # speak
        "speaks": "speak", "spoke": "speak", "spoken": "speak", "speaking": "speak",
        # grow
        "grows": "grow", "grew": "grow", "grown": "grow", "growing": "grow",
        # stand
        "stands": "stand", "stood": "stand", "standing": "stand",
        # fall
        "falls": "fall", "fell": "fall", "fallen": "fall", "falling": "fall",
        # hear
        "hears": "hear", "heard": "hear", "hearing": "hear",
        # sit
        "sits": "sit", "sat": "sit", "sitting": "sit",
        # hold
        "holds": "hold", "held": "hold", "holding": "hold",
        # bring
        "brings": "bring", "brought": "bring", "bringing": "bring",
        # buy
        "buys": "buy", "bought": "buy", "buying": "buy",
        # meet
        "meets": "meet", "met": "meet", "meeting": "meet",
        # lead
        "leads": "lead", "led": "lead", "leading": "lead",
        # live
        "lives": "live", "lived": "live", "living": "live",
        # die
        "dies": "die", "died": "die", "dying": "die",
        # break
        "breaks": "break", "broke": "break", "broken": "break", "breaking": "break",
        # drive
        "drives": "drive", "drove": "drive", "driven": "drive", "driving": "drive",
        # fight
        "fights": "fight", "fought": "fight", "fighting": "fight",
        # catch
        "catches": "catch", "caught": "catch", "catching": "catch",
        # throw
        "throws": "throw", "threw": "throw", "thrown": "throw", "throwing": "throw",
        # build
        "builds": "build", "built": "build", "building": "build",
        # sleep
        "sleeps": "sleep", "slept": "sleep", "sleeping": "sleep",
        # send
        "sends": "send", "sent": "send", "sending": "send",
        # spend
        "spends": "spend", "spent": "spend", "spending": "spend",
        # win
        "wins": "win", "won": "win", "winning": "win",
        # lose
        "loses": "lose", "lost": "lose", "losing": "lose",
        # eat
        "eats": "eat", "ate": "eat", "eaten": "eat", "eating": "eat",
        # drink
        "drinks": "drink", "drank": "drink", "drunk": "drink", "drinking": "drink",
        # rise
        "rises": "rise", "rose": "rise", "risen": "rise", "rising": "rise",
        # fly
        "flies": "fly", "flew": "fly", "flown": "fly", "flying": "fly",
        # draw
        "draws": "draw", "drew": "draw", "drawn": "draw", "drawing": "draw",
        # hide
        "hides": "hide", "hid": "hide", "hidden": "hide", "hiding": "hide",
        # cut
        "cuts": "cut", "cutting": "cut",
        # choose
        "chooses": "choose", "chose": "choose", "chosen": "choose", "choosing": "choose",
        # wear
        "wears": "wear", "wore": "wear", "worn": "wear", "wearing": "wear",
        # wake
        "wakes": "wake", "woke": "wake", "woken": "wake", "waking": "wake",
    }

    # Irregular plural forms -> singular
    IRREGULAR_PLURALS: Dict[str, str] = {
        "men": "man", "women": "woman", "children": "child", "teeth": "tooth",
        "feet": "foot", "mice": "mouse", "geese": "goose", "people": "person",
        "leaves": "leaf", "lives": "life", "knives": "knife", "wives": "wife",
        "halves": "half", "selves": "self", "wolves": "wolf", "thieves": "thief",
        "heroes": "hero", "potatoes": "potato", "tomatoes": "tomato",
        "analyses": "analysis", "crises": "crisis", "bases": "basis",
        "phenomena": "phenomenon", "criteria": "criterion", "data": "datum",
    }

    # Adjective comparative/superlative -> base
    ADJECTIVE_FORMS: Dict[str, str] = {
        "better": "good", "best": "good",
        "worse": "bad", "worst": "bad",
        "more": "much", "most": "much",
        "less": "little", "least": "little",
        "bigger": "big", "biggest": "big",
        "smaller": "small", "smallest": "small",
        "larger": "large", "largest": "large",
        "faster": "fast", "fastest": "fast",
        "slower": "slow", "slowest": "slow",
        "older": "old", "oldest": "old",
        "younger": "young", "youngest": "young",
        "newer": "new", "newest": "new",
        "harder": "hard", "hardest": "hard",
        "softer": "soft", "softest": "soft",
        "stronger": "strong", "strongest": "strong",
        "weaker": "weak", "weakest": "weak",
        "hotter": "hot", "hottest": "hot",
        "colder": "cold", "coldest": "cold",
        "happier": "happy", "happiest": "happy",
        "sadder": "sad", "saddest": "sad",
        "angrier": "angry", "angriest": "angry",
    }

    @classmethod
    def get_base_forms(cls, word: str) -> List[str]:
        """Get possible base forms of a word.

        Returns a list of possible base forms, ordered by likelihood.
        The original word is always included as the last fallback.

        Uses NLTK's WordNetLemmatizer when available (more accurate),
        falling back to rule-based stemming when NLTK is not installed.
        """
        word = word.lower().strip()
        if not word:
            return []

        forms = []

        # Strategy 1: Use NLTK lemmatizer if available (most accurate)
        if _LEMMATIZER_AVAILABLE and _lemmatizer:
            # Try all POS tags - noun, verb, adjective, adverb
            for pos in ['n', 'v', 'a', 'r']:
                try:
                    lemma = _lemmatizer.lemmatize(word, pos=pos)
                    if lemma != word and lemma not in forms:
                        forms.append(lemma)
                except Exception:
                    pass

            # Also try WordNet's morphy directly for more aggressive matching
            if _wordnet:
                for pos in [_wordnet.NOUN, _wordnet.VERB, _wordnet.ADJ, _wordnet.ADV]:
                    try:
                        morphy_result = _wordnet.morphy(word, pos)
                        if morphy_result and morphy_result != word and morphy_result not in forms:
                            forms.append(morphy_result)
                    except Exception:
                        pass

        # Strategy 2: Check irregular forms (always useful as backup)
        if word in cls.IRREGULAR_VERBS:
            forms.append(cls.IRREGULAR_VERBS[word])
        if word in cls.IRREGULAR_PLURALS:
            forms.append(cls.IRREGULAR_PLURALS[word])
        if word in cls.ADJECTIVE_FORMS:
            forms.append(cls.ADJECTIVE_FORMS[word])

        # Strategy 3: Apply suffix rules as supplement
        # Even with lemmatizer, suffix rules catch derivational morphology
        # that WordNet doesn't handle (e.g., surveillance -> surveil)
        suffix_forms = cls._apply_suffix_rules(word)
        forms.extend(suffix_forms)

        # Add original word as fallback
        if word not in forms:
            forms.append(word)

        # Remove duplicates while preserving order
        seen = set()
        unique_forms = []
        for form in forms:
            if form not in seen and form:
                seen.add(form)
                unique_forms.append(form)

        return unique_forms

    @classmethod
    def _apply_suffix_rules(cls, word: str) -> List[str]:
        """Apply suffix removal rules to get potential base forms."""
        forms = []

        # -ing endings (attempting -> attempt, running -> run, making -> make)
        if word.endswith('ing') and len(word) > 4:
            base = word[:-3]
            if len(base) >= 2:
                # walking -> walk, attempting -> attempt (most common)
                forms.append(base)
                # running -> run (double consonant)
                if len(base) >= 2 and base[-1] == base[-2]:
                    forms.append(base[:-1])
                # making -> make (drop e before -ing)
                forms.append(base + 'e')

        # -ed endings
        if word.endswith('ed') and len(word) > 3:
            base = word[:-2]
            if len(base) >= 2:
                # walked -> walk (most common)
                forms.append(base)
                # stopped -> stop (double consonant)
                if len(base) >= 2 and base[-1] == base[-2]:
                    forms.append(base[:-1])
                # liked -> like
                forms.append(base + 'e')
            # tried -> try (ied -> y)
            if word.endswith('ied') and len(word) > 4:
                forms.append(word[:-3] + 'y')

        # -s/-es plural endings
        if word.endswith('ies') and len(word) > 4:
            # cities -> city
            forms.append(word[:-3] + 'y')
        elif word.endswith('es') and len(word) > 3:
            # boxes -> box, watches -> watch
            forms.append(word[:-2])
            # changes -> change
            forms.append(word[:-1])
        elif word.endswith('s') and not word.endswith('ss') and len(word) > 2:
            # cats -> cat
            forms.append(word[:-1])

        # -ly adverb endings
        if word.endswith('ly') and len(word) > 4:
            # quickly -> quick
            forms.append(word[:-2])
            # happily -> happy (ily -> y)
            if word.endswith('ily'):
                forms.append(word[:-3] + 'y')

        # -er/-est comparative/superlative (but not -er as agent suffix)
        if word.endswith('er') and len(word) > 4:
            forms.append(word[:-2])
            # bigger -> big
            if len(word) > 4 and word[-3] == word[-4]:
                forms.append(word[:-3])
            # nicer -> nice
            forms.append(word[:-1])
        if word.endswith('est') and len(word) > 4:
            forms.append(word[:-3])
            # biggest -> big
            if len(word) > 5 and word[-4] == word[-5]:
                forms.append(word[:-4])
            # nicest -> nice
            forms.append(word[:-2])

        # -ness noun endings
        if word.endswith('ness') and len(word) > 5:
            # happiness -> happy
            forms.append(word[:-4])
            if word.endswith('iness'):
                forms.append(word[:-5] + 'y')

        # -ment noun endings
        if word.endswith('ment') and len(word) > 5:
            forms.append(word[:-4])

        # -tion/-sion noun endings
        if word.endswith('tion') and len(word) > 5:
            # action -> act
            forms.append(word[:-4])
            forms.append(word[:-3] + 'e')
        if word.endswith('sion') and len(word) > 5:
            forms.append(word[:-4] + 'd')
            forms.append(word[:-4] + 'de')

        # -ance/-ence noun endings (surveillance -> surveil, dependence -> depend)
        if word.endswith('ance') and len(word) > 5:
            base = word[:-4]
            # surveillance -> surveill -> surveil (double consonant before -ance)
            if len(base) >= 2 and base[-1] == base[-2]:
                forms.append(base[:-1])  # Remove double consonant
            # performance -> perform (just remove -ance)
            forms.append(base)
            # tolerance -> tolerate (ance -> ate)
            forms.append(base + 'ate')
            # reliance -> rely (iance -> y)
            if word.endswith('iance') and len(word) > 6:
                forms.append(word[:-5] + 'y')
        if word.endswith('ence') and len(word) > 5:
            # dependence -> depend
            forms.append(word[:-4])
            # reference -> refer
            forms.append(word[:-4])
            # existence -> exist
            forms.append(word[:-4])
            # preference -> prefer (ence -> )
            if word.endswith('erence') and len(word) > 7:
                forms.append(word[:-5])

        # -ant/-ent adjective/noun endings (resistant -> resist, dependent -> depend)
        if word.endswith('ant') and len(word) > 4:
            forms.append(word[:-3])
            # resistant -> resist
            forms.append(word[:-3])
        if word.endswith('ent') and len(word) > 4:
            forms.append(word[:-3])
            # dependent -> depend
            forms.append(word[:-3])

        # -ity noun endings (simplicity -> simple, activity -> active)
        if word.endswith('ity') and len(word) > 5:
            # simplicity -> simple (icity -> e)
            if word.endswith('icity'):
                forms.append(word[:-5] + 'e')
            # activity -> active (ity -> e)
            forms.append(word[:-3] + 'e')
            # clarity -> clear (ity -> )
            forms.append(word[:-3])

        # -ive adjective endings (active -> act, creative -> create)
        if word.endswith('ive') and len(word) > 4:
            # active -> act
            forms.append(word[:-3])
            # creative -> create (ive -> e)
            forms.append(word[:-3] + 'e')
            # attractive -> attract (ive -> )
            if word.endswith('ative') and len(word) > 6:
                forms.append(word[:-5] + 'e')
                forms.append(word[:-5])

        # -ful adjective endings (beautiful -> beauty, careful -> care)
        if word.endswith('ful') and len(word) > 4:
            # careful -> care
            forms.append(word[:-3])
            # beautiful -> beauty (iful -> y)
            if word.endswith('iful') and len(word) > 5:
                forms.append(word[:-4] + 'y')

        # -less adjective endings (careless -> care, hopeless -> hope)
        if word.endswith('less') and len(word) > 5:
            forms.append(word[:-4])

        # -able/-ible adjective endings (readable -> read, visible -> vision)
        if word.endswith('able') and len(word) > 5:
            # readable -> read
            forms.append(word[:-4])
            # lovable -> love (able -> e)
            forms.append(word[:-4] + 'e')
        if word.endswith('ible') and len(word) > 5:
            forms.append(word[:-4])
            forms.append(word[:-4] + 'e')

        # -ous adjective endings (famous -> fame, dangerous -> danger)
        if word.endswith('ous') and len(word) > 4:
            # dangerous -> danger
            forms.append(word[:-3])
            # famous -> fame (ous -> e)
            forms.append(word[:-3] + 'e')
            # mysterious -> mystery (ious -> y)
            if word.endswith('ious') and len(word) > 5:
                forms.append(word[:-4] + 'y')

        # -al adjective endings (musical -> music, natural -> nature)
        if word.endswith('al') and len(word) > 4 and not word.endswith('ial'):
            # musical -> music
            forms.append(word[:-2])
            # natural -> nature (al -> e)
            forms.append(word[:-2] + 'e')

        return forms


class Thesaurus:
    """
    Intelligent thesaurus for synonym lookup.

    Features:
    - WordNet integration when NLTK is available
    - Word stemming to find base forms
    - Curated fallback dictionary for creative writing
    - Caching for performance
    """

    # Curated synonym dictionary for creative writing
    # Organized by base word -> list of synonyms
    SYNONYMS: Dict[str, List[str]] = {
        # Emotions - Happy
        "happy": ["joyful", "delighted", "pleased", "content", "cheerful", "elated", "ecstatic", "gleeful", "blissful", "merry"],
        "joyful": ["happy", "delighted", "elated", "jubilant", "gleeful", "merry", "cheerful", "blissful"],
        "glad": ["happy", "pleased", "delighted", "thankful", "gratified", "relieved"],

        # Emotions - Sad
        "sad": ["unhappy", "sorrowful", "melancholy", "dejected", "downcast", "gloomy", "despondent", "forlorn", "miserable", "heartbroken"],
        "unhappy": ["sad", "miserable", "dejected", "dismal", "sorrowful", "discontented"],
        "depressed": ["sad", "despondent", "downcast", "dejected", "melancholy", "gloomy", "disheartened"],

        # Emotions - Angry
        "angry": ["furious", "enraged", "irate", "livid", "incensed", "infuriated", "outraged", "wrathful", "seething", "irritated"],
        "mad": ["angry", "furious", "irate", "enraged", "livid", "incensed", "infuriated"],
        "furious": ["angry", "enraged", "livid", "incensed", "infuriated", "outraged", "wrathful", "seething"],

        # Emotions - Fear
        "scared": ["afraid", "frightened", "terrified", "fearful", "alarmed", "panicked", "petrified", "horrified"],
        "afraid": ["scared", "frightened", "fearful", "terrified", "anxious", "apprehensive", "nervous"],
        "terrified": ["scared", "petrified", "horrified", "panic-stricken", "terror-stricken", "frightened"],

        # Emotions - Surprise
        "surprised": ["shocked", "astonished", "amazed", "startled", "stunned", "astounded", "dumbfounded", "flabbergasted"],
        "shocked": ["surprised", "stunned", "astonished", "astounded", "dumbfounded", "staggered"],

        # Actions - Movement
        "walk": ["stroll", "stride", "saunter", "amble", "pace", "march", "trudge", "wander", "roam", "meander"],
        "run": ["sprint", "dash", "race", "bolt", "hurry", "rush", "jog", "scamper", "scurry", "flee"],
        "move": ["shift", "relocate", "transfer", "proceed", "advance", "travel", "migrate", "budge"],
        "jump": ["leap", "bound", "spring", "hop", "vault", "bounce", "skip", "hurdle"],
        "fall": ["drop", "tumble", "plunge", "collapse", "descend", "topple", "crash", "plummet"],

        # Actions - Communication
        "say": ["speak", "state", "declare", "utter", "express", "articulate", "voice", "announce", "mention", "remark"],
        "said": ["spoke", "stated", "declared", "uttered", "expressed", "announced", "mentioned", "remarked", "replied", "responded"],
        "ask": ["inquire", "question", "query", "request", "demand", "probe", "interrogate"],
        "tell": ["inform", "notify", "advise", "instruct", "relate", "narrate", "recount"],
        "shout": ["yell", "scream", "cry", "holler", "bellow", "roar", "exclaim", "shriek"],
        "whisper": ["murmur", "mutter", "breathe", "hiss", "mumble", "speak softly"],

        # Actions - Looking
        "look": ["gaze", "stare", "glance", "peer", "observe", "watch", "view", "examine", "scrutinize", "survey"],
        "see": ["observe", "notice", "spot", "perceive", "witness", "view", "behold", "glimpse", "discern"],
        "watch": ["observe", "monitor", "survey", "scrutinize", "examine", "study", "view"],
        "surveil": ["watch", "monitor", "observe", "spy", "track", "follow", "scrutinize", "stake out"],

        # Actions - Thinking
        "think": ["consider", "ponder", "contemplate", "reflect", "deliberate", "muse", "meditate", "ruminate"],
        "know": ["understand", "comprehend", "realize", "recognize", "perceive", "grasp", "fathom"],
        "believe": ["think", "suppose", "assume", "presume", "trust", "accept", "consider"],
        "want": ["desire", "wish", "crave", "yearn", "long", "covet", "need", "fancy"],

        # Descriptive - Size
        "big": ["large", "huge", "enormous", "massive", "immense", "gigantic", "colossal", "vast", "substantial"],
        "small": ["tiny", "little", "miniature", "minute", "petite", "compact", "diminutive", "microscopic"],
        "large": ["big", "huge", "vast", "enormous", "substantial", "considerable", "extensive", "spacious"],
        "tiny": ["small", "minute", "miniature", "microscopic", "infinitesimal", "petite", "minuscule"],

        # Descriptive - Quality
        "good": ["excellent", "great", "fine", "wonderful", "superb", "outstanding", "exceptional", "splendid", "marvelous"],
        "bad": ["poor", "terrible", "awful", "dreadful", "horrible", "atrocious", "inferior", "substandard"],
        "beautiful": ["gorgeous", "stunning", "lovely", "attractive", "exquisite", "elegant", "radiant", "magnificent"],
        "ugly": ["hideous", "unsightly", "unattractive", "grotesque", "repulsive", "homely", "plain"],
        "nice": ["pleasant", "agreeable", "delightful", "enjoyable", "lovely", "wonderful", "charming"],

        # Descriptive - Speed
        "fast": ["quick", "rapid", "swift", "speedy", "hasty", "brisk", "fleet", "nimble"],
        "slow": ["sluggish", "unhurried", "leisurely", "gradual", "plodding", "languid", "dawdling"],
        "quick": ["fast", "rapid", "swift", "speedy", "prompt", "hasty", "brisk", "instant"],

        # Descriptive - Temperature
        "hot": ["warm", "heated", "scorching", "sweltering", "blazing", "burning", "fiery", "boiling"],
        "cold": ["chilly", "frigid", "freezing", "icy", "frosty", "cool", "wintry", "bitter"],
        "warm": ["hot", "heated", "tepid", "mild", "balmy", "toasty", "cozy"],

        # Descriptive - Light
        "bright": ["brilliant", "radiant", "luminous", "gleaming", "dazzling", "vivid", "shining", "glowing"],
        "dark": ["dim", "shadowy", "gloomy", "murky", "dusky", "obscure", "somber", "tenebrous"],
        "light": ["bright", "pale", "luminous", "radiant", "illuminated", "glowing"],

        # Descriptive - Sound
        "loud": ["noisy", "thunderous", "deafening", "booming", "blaring", "resounding", "clamorous"],
        "quiet": ["silent", "hushed", "muted", "still", "peaceful", "tranquil", "noiseless", "soundless"],
        "silent": ["quiet", "still", "hushed", "mute", "noiseless", "soundless", "speechless"],

        # Descriptive - Feeling/Texture
        "hard": ["solid", "firm", "rigid", "stiff", "tough", "dense", "unyielding"],
        "soft": ["gentle", "tender", "smooth", "supple", "plush", "fluffy", "silky", "delicate"],
        "rough": ["coarse", "rugged", "uneven", "jagged", "bumpy", "textured", "harsh"],
        "smooth": ["sleek", "even", "polished", "silky", "glossy", "flat", "level"],

        # Intensity Modifiers
        "very": ["extremely", "exceedingly", "incredibly", "remarkably", "exceptionally", "tremendously", "immensely"],
        "really": ["truly", "genuinely", "actually", "honestly", "definitely", "certainly", "absolutely"],

        # Time
        "old": ["ancient", "aged", "elderly", "antique", "vintage", "mature", "senior"],
        "new": ["fresh", "recent", "modern", "novel", "contemporary", "latest", "current"],
        "young": ["youthful", "juvenile", "adolescent", "immature", "childish"],

        # Character Traits
        "brave": ["courageous", "fearless", "bold", "valiant", "heroic", "daring", "gallant", "intrepid"],
        "smart": ["intelligent", "clever", "brilliant", "wise", "bright", "sharp", "astute", "cunning"],
        "stupid": ["foolish", "dumb", "idiotic", "dense", "slow", "dim-witted", "obtuse"],
        "kind": ["caring", "compassionate", "gentle", "generous", "benevolent", "considerate", "thoughtful"],
        "cruel": ["brutal", "harsh", "ruthless", "merciless", "heartless", "savage", "vicious"],
        "strong": ["powerful", "mighty", "robust", "sturdy", "tough", "muscular", "vigorous"],
        "weak": ["feeble", "frail", "fragile", "delicate", "powerless", "helpless", "vulnerable"],

        # Common Verbs
        "get": ["obtain", "acquire", "receive", "gain", "fetch", "retrieve", "procure", "secure"],
        "give": ["provide", "offer", "present", "grant", "bestow", "donate", "deliver", "hand"],
        "make": ["create", "produce", "construct", "build", "form", "fashion", "craft", "generate"],
        "take": ["grab", "seize", "grasp", "snatch", "capture", "claim", "acquire", "remove"],
        "put": ["place", "set", "position", "lay", "deposit", "situate", "arrange", "locate"],
        "come": ["arrive", "approach", "appear", "emerge", "reach", "enter", "advance"],
        "go": ["leave", "depart", "proceed", "travel", "move", "head", "journey", "venture"],
        "use": ["utilize", "employ", "apply", "operate", "wield", "exercise", "exploit"],
        "find": ["discover", "locate", "uncover", "detect", "spot", "identify", "encounter"],
        "keep": ["retain", "maintain", "preserve", "hold", "save", "store", "guard"],
        "let": ["allow", "permit", "enable", "authorize", "grant", "consent"],
        "begin": ["start", "commence", "initiate", "launch", "embark", "inaugurate"],
        "start": ["begin", "commence", "initiate", "launch", "embark", "kick off"],
        "end": ["finish", "conclude", "terminate", "complete", "cease", "stop", "close"],
        "stop": ["halt", "cease", "pause", "discontinue", "quit", "desist", "suspend"],
        "try": ["attempt", "endeavor", "strive", "struggle", "seek", "aim"],
        "help": ["assist", "aid", "support", "serve", "facilitate", "enable"],
        "show": ["display", "exhibit", "demonstrate", "reveal", "present", "indicate"],
        "turn": ["rotate", "spin", "revolve", "pivot", "twist", "swivel"],
        "hold": ["grasp", "grip", "clutch", "clasp", "embrace", "contain", "possess"],
        "bring": ["carry", "convey", "transport", "deliver", "fetch", "bear"],
        "happen": ["occur", "transpire", "take place", "unfold", "arise", "ensue"],
        "write": ["compose", "author", "pen", "draft", "inscribe", "record", "scribe"],
        "read": ["peruse", "scan", "study", "examine", "browse", "skim"],
        "live": ["reside", "dwell", "inhabit", "exist", "survive", "abide"],
        "die": ["perish", "expire", "pass away", "decease", "succumb"],
        "eat": ["consume", "devour", "dine", "feast", "munch", "nibble", "gobble"],
        "drink": ["sip", "gulp", "swallow", "imbibe", "quaff", "guzzle"],
        "sleep": ["slumber", "rest", "doze", "nap", "snooze", "drowse"],
        "love": ["adore", "cherish", "treasure", "worship", "idolize", "fancy"],
        "hate": ["despise", "loathe", "detest", "abhor", "dislike"],
        "like": ["enjoy", "appreciate", "fancy", "prefer", "relish", "favor"],
        "need": ["require", "want", "demand", "necessitate", "lack"],
        "seem": ["appear", "look", "sound", "feel", "come across"],
        "feel": ["sense", "experience", "perceive", "undergo", "detect"],
        "leave": ["depart", "exit", "go", "abandon", "forsake", "vacate"],
        "call": ["summon", "beckon", "shout", "cry", "yell", "name"],
        "try": ["attempt", "endeavor", "strive", "venture", "aim"],
        "meet": ["encounter", "greet", "join", "convene", "gather"],
        "wait": ["linger", "remain", "stay", "pause", "tarry", "delay"],
        "follow": ["pursue", "trail", "track", "shadow", "chase", "succeed"],
        "learn": ["discover", "study", "master", "grasp", "absorb", "acquire"],
        "change": ["alter", "modify", "transform", "convert", "shift", "vary"],
        "play": ["perform", "act", "frolic", "gambol", "sport", "recreate"],
        "work": ["labor", "toil", "operate", "function", "strive"],
        "open": ["unlock", "unfasten", "uncover", "reveal", "expose"],
        "close": ["shut", "seal", "fasten", "lock", "conclude"],
        "kill": ["slay", "murder", "execute", "destroy", "eliminate", "terminate"],
        "fight": ["battle", "combat", "struggle", "clash", "brawl", "duel"],
        "break": ["shatter", "smash", "crack", "fracture", "destroy", "rupture"],
        "build": ["construct", "create", "erect", "assemble", "establish"],
        "pull": ["drag", "tug", "draw", "haul", "yank", "extract"],
        "push": ["shove", "thrust", "press", "propel", "drive", "force"],
        "carry": ["bear", "transport", "convey", "haul", "lug", "tote"],
        "stand": ["rise", "remain", "endure", "tolerate", "withstand"],
        "sit": ["perch", "settle", "rest", "squat", "recline"],

        # Nouns - People
        "man": ["gentleman", "fellow", "guy", "male", "person", "individual"],
        "woman": ["lady", "female", "girl", "person", "individual"],
        "child": ["kid", "youngster", "youth", "minor", "juvenile", "tot"],
        "friend": ["companion", "pal", "buddy", "ally", "comrade", "confidant"],
        "enemy": ["foe", "adversary", "opponent", "rival", "antagonist"],

        # Nouns - Places
        "house": ["home", "dwelling", "residence", "abode", "domicile", "shelter"],
        "room": ["chamber", "space", "area", "quarters", "compartment"],
        "road": ["street", "path", "way", "route", "lane", "avenue", "highway"],
        "forest": ["woods", "woodland", "grove", "jungle", "thicket"],
        "mountain": ["peak", "summit", "hill", "ridge", "cliff"],
        "river": ["stream", "brook", "creek", "waterway", "tributary"],
        "city": ["town", "metropolis", "municipality", "urban area"],

        # Nouns - Things
        "thing": ["object", "item", "article", "entity", "matter"],
        "money": ["cash", "currency", "funds", "wealth", "capital"],
        "book": ["volume", "tome", "text", "publication", "novel"],
        "fire": ["flame", "blaze", "inferno", "conflagration"],
        "water": ["liquid", "fluid", "aqua", "moisture"],
        "food": ["nourishment", "sustenance", "meal", "fare", "provisions"],
        "weapon": ["arm", "armament", "tool", "implement"],

        # Nouns - Abstract
        "idea": ["thought", "concept", "notion", "theory", "belief"],
        "problem": ["issue", "difficulty", "challenge", "dilemma", "obstacle"],
        "answer": ["solution", "response", "reply", "resolution"],
        "reason": ["cause", "motive", "purpose", "explanation", "rationale"],
        "power": ["strength", "force", "authority", "control", "might"],
        "truth": ["fact", "reality", "accuracy", "veracity", "honesty"],
        "lie": ["falsehood", "untruth", "deception", "fabrication", "fib"],
        "secret": ["mystery", "enigma", "confidential", "hidden"],
        "dream": ["vision", "fantasy", "aspiration", "reverie"],
        "fear": ["terror", "dread", "fright", "horror", "anxiety", "phobia"],
        "hope": ["optimism", "expectation", "aspiration", "wish"],
        "pain": ["ache", "agony", "suffering", "torment", "discomfort"],
        "joy": ["happiness", "delight", "pleasure", "elation", "bliss"],

        # Adverbs
        "quickly": ["rapidly", "swiftly", "hastily", "speedily", "promptly", "briskly"],
        "slowly": ["gradually", "leisurely", "unhurriedly", "sluggishly"],
        "suddenly": ["abruptly", "unexpectedly", "instantly", "immediately"],
        "quietly": ["silently", "softly", "peacefully", "calmly"],
        "loudly": ["noisily", "thunderously", "boisterously"],
        "carefully": ["cautiously", "meticulously", "attentively", "gingerly"],
        "easily": ["effortlessly", "smoothly", "readily", "simply"],
        "hardly": ["barely", "scarcely", "rarely", "seldom"],
        "almost": ["nearly", "practically", "virtually", "approximately"],
        "always": ["constantly", "perpetually", "forever", "continually", "eternally"],
        "never": ["not ever", "at no time", "not once"],
        "often": ["frequently", "regularly", "commonly", "repeatedly"],
        "sometimes": ["occasionally", "periodically", "now and then", "at times"],
        "here": ["present", "nearby", "around", "in this place"],
        "there": ["yonder", "over there", "in that place"],
        "now": ["currently", "presently", "at present", "immediately", "today"],
        "then": ["afterward", "subsequently", "next", "later"],
        "again": ["once more", "anew", "afresh", "another time"],
        "together": ["jointly", "collectively", "as one", "in unison"],
        "alone": ["solitary", "isolated", "solo", "unaccompanied", "by oneself"],
    }

    # Antonyms for common words
    ANTONYMS: Dict[str, List[str]] = {
        "happy": ["sad", "unhappy", "miserable", "depressed"],
        "sad": ["happy", "joyful", "cheerful", "elated"],
        "big": ["small", "tiny", "little", "miniature"],
        "small": ["big", "large", "huge", "enormous"],
        "fast": ["slow", "sluggish", "leisurely"],
        "slow": ["fast", "quick", "rapid", "swift"],
        "hot": ["cold", "freezing", "chilly", "cool"],
        "cold": ["hot", "warm", "heated", "burning"],
        "good": ["bad", "poor", "terrible", "awful"],
        "bad": ["good", "excellent", "great", "wonderful"],
        "bright": ["dark", "dim", "gloomy", "murky"],
        "dark": ["bright", "light", "luminous", "radiant"],
        "loud": ["quiet", "silent", "soft", "hushed"],
        "quiet": ["loud", "noisy", "thunderous", "booming"],
        "hard": ["soft", "gentle", "tender", "supple"],
        "soft": ["hard", "firm", "rigid", "solid"],
        "old": ["new", "young", "fresh", "modern"],
        "new": ["old", "ancient", "aged", "antique"],
        "young": ["old", "elderly", "aged", "mature"],
        "strong": ["weak", "feeble", "frail", "fragile"],
        "weak": ["strong", "powerful", "mighty", "robust"],
        "brave": ["cowardly", "fearful", "timid", "afraid"],
        "smart": ["stupid", "foolish", "dumb", "slow"],
        "kind": ["cruel", "mean", "harsh", "unkind"],
        "cruel": ["kind", "gentle", "compassionate", "caring"],
        "love": ["hate", "despise", "loathe", "detest"],
        "hate": ["love", "adore", "cherish", "like"],
        "friend": ["enemy", "foe", "adversary", "rival"],
        "enemy": ["friend", "ally", "companion", "comrade"],
        "begin": ["end", "finish", "stop", "conclude"],
        "end": ["begin", "start", "commence", "initiate"],
        "open": ["close", "shut", "seal", "lock"],
        "close": ["open", "unlock", "unfasten", "reveal"],
        "come": ["go", "leave", "depart", "exit"],
        "go": ["come", "arrive", "stay", "remain"],
        "give": ["take", "receive", "get", "seize"],
        "take": ["give", "offer", "provide", "donate"],
        "always": ["never", "rarely", "seldom"],
        "never": ["always", "constantly", "forever"],
        "together": ["alone", "apart", "separate", "solo"],
        "alone": ["together", "accompanied", "with others"],
    }

    def __init__(self):
        """Initialize the thesaurus."""
        self._cache: Dict[str, SynonymResult] = {}
        self._use_wordnet = _WORDNET_AVAILABLE

    def refresh_wordnet(self):
        """Refresh WordNet availability status.

        Call this after downloading WordNet data to enable it without restart.
        Also clears the cache to ensure new lookups use WordNet.
        """
        self._use_wordnet = _WORDNET_AVAILABLE
        # Clear cache so new lookups will use WordNet
        self._cache.clear()

    def _clean_word(self, word: str) -> str:
        """Remove punctuation and normalize a word for lookup."""
        # Strip whitespace
        word = word.strip()
        # Remove common punctuation from start and end
        word = re.sub(r'^[^\w]+|[^\w]+$', '', word)
        # Lowercase
        return word.lower()

    def lookup(self, word: str) -> SynonymResult:
        """
        Look up synonyms for a word.

        Uses multiple strategies:
        1. Direct lookup in curated dictionary
        2. Stemming to find base form, then lookup
        3. WordNet lookup (if available)

        Args:
            word: The word to look up

        Returns:
            SynonymResult with synonyms and antonyms
        """
        # Normalize the word - strip punctuation and lowercase
        word_clean = self._clean_word(word)

        if not word_clean:
            return SynonymResult(word=word, synonyms=[], antonyms=[])

        # Check cache first
        if word_clean in self._cache:
            return self._cache[word_clean]

        # Try multiple lookup strategies
        synonyms = set()
        antonyms = set()
        base_form_used = None

        # Strategy 1: Direct lookup
        direct_synonyms = self._find_synonyms_local(word_clean)
        if direct_synonyms:
            synonyms.update(direct_synonyms)
            base_form_used = word_clean

        # Strategy 2: Try stemmed/base forms if direct lookup found nothing or few results
        if len(synonyms) < 3:
            base_forms = WordStemmer.get_base_forms(word_clean)
            for base_form in base_forms:
                if base_form != word_clean:
                    base_synonyms = self._find_synonyms_local(base_form)
                    if base_synonyms:
                        synonyms.update(base_synonyms)
                        if not base_form_used:
                            base_form_used = base_form
                        # Also check antonyms for base form
                        if base_form in self.ANTONYMS:
                            antonyms.update(self.ANTONYMS[base_form])

        # Strategy 3: WordNet lookup (if available and still need more synonyms)
        if self._use_wordnet and len(synonyms) < 5:
            wordnet_synonyms, wordnet_antonyms = self._find_synonyms_wordnet(word_clean)
            synonyms.update(wordnet_synonyms)
            antonyms.update(wordnet_antonyms)

            # Also try WordNet with base forms
            if len(synonyms) < 5:
                base_forms = WordStemmer.get_base_forms(word_clean)
                for base_form in base_forms:
                    if base_form != word_clean:
                        wn_syn, wn_ant = self._find_synonyms_wordnet(base_form)
                        synonyms.update(wn_syn)
                        antonyms.update(wn_ant)

        # Get antonyms from local dictionary
        if word_clean in self.ANTONYMS:
            antonyms.update(self.ANTONYMS[word_clean])

        # Remove the original word and its forms from results
        synonyms.discard(word_clean)
        antonyms.discard(word_clean)

        # Filter out multi-word phrases for cleaner results
        synonyms = {s for s in synonyms if ' ' not in s and '_' not in s}
        antonyms = {a for a in antonyms if ' ' not in a and '_' not in a}

        result = SynonymResult(
            word=word,
            synonyms=sorted(list(synonyms)),
            antonyms=sorted(list(antonyms))
        )

        # Cache the result
        self._cache[word_clean] = result

        return result

    def _find_synonyms_local(self, word: str) -> List[str]:
        """Find synonyms from the local curated dictionary."""
        synonyms = set()

        # Direct lookup
        if word in self.SYNONYMS:
            synonyms.update(self.SYNONYMS[word])

        # Reverse lookup - find words that have this word as a synonym
        for base_word, syn_list in self.SYNONYMS.items():
            if word in syn_list:
                synonyms.add(base_word)
                # Also add other synonyms from this group
                synonyms.update(syn_list)

        # Remove the original word from results
        synonyms.discard(word)

        return list(synonyms)

    def _find_synonyms_wordnet(self, word: str) -> Tuple[List[str], List[str]]:
        """Find synonyms and antonyms using WordNet.

        Returns:
            Tuple of (synonyms list, antonyms list)
        """
        if not self._use_wordnet or not _wordnet:
            return [], []

        synonyms = set()
        antonyms = set()

        try:
            for synset in _wordnet.synsets(word):
                # Get synonyms (lemmas in the synset)
                for lemma in synset.lemmas():
                    name = lemma.name().replace('_', ' ')
                    if name.lower() != word.lower():
                        synonyms.add(name.lower())

                    # Get antonyms from lemma
                    for antonym in lemma.antonyms():
                        ant_name = antonym.name().replace('_', ' ')
                        antonyms.add(ant_name.lower())

        except Exception:
            # If anything goes wrong with WordNet, just return empty
            pass

        return list(synonyms), list(antonyms)

    def get_synonyms(self, word: str, max_results: int = 10) -> List[str]:
        """
        Get synonyms for a word, limited to max_results.

        Args:
            word: The word to look up
            max_results: Maximum number of synonyms to return

        Returns:
            List of synonyms
        """
        result = self.lookup(word)
        return result.synonyms[:max_results]

    def get_antonyms(self, word: str, max_results: int = 5) -> List[str]:
        """
        Get antonyms for a word.

        Args:
            word: The word to look up
            max_results: Maximum number of antonyms to return

        Returns:
            List of antonyms
        """
        result = self.lookup(word)
        return result.antonyms[:max_results]

    def has_synonyms(self, word: str) -> bool:
        """Check if synonyms exist for a word."""
        result = self.lookup(word)
        return len(result.synonyms) > 0

    def clear_cache(self):
        """Clear the lookup cache."""
        self._cache.clear()


# Global thesaurus instance
_thesaurus: Optional[Thesaurus] = None


def get_thesaurus() -> Thesaurus:
    """Get the global thesaurus instance."""
    global _thesaurus
    if _thesaurus is None:
        _thesaurus = Thesaurus()
    return _thesaurus


def get_synonyms(word: str, max_results: int = 10) -> List[str]:
    """
    Convenience function to get synonyms for a word.

    Args:
        word: The word to look up
        max_results: Maximum number of results

    Returns:
        List of synonyms
    """
    return get_thesaurus().get_synonyms(word, max_results)


def get_antonyms(word: str, max_results: int = 5) -> List[str]:
    """
    Convenience function to get antonyms for a word.

    Args:
        word: The word to look up
        max_results: Maximum number of results

    Returns:
        List of antonyms
    """
    return get_thesaurus().get_antonyms(word, max_results)


def is_wordnet_available() -> bool:
    """Check if WordNet (NLTK) is available for enhanced synonym lookup."""
    return _WORDNET_AVAILABLE


def refresh_wordnet_availability() -> bool:
    """Re-check if WordNet is available (call after downloading NLTK data).

    This function should be called after downloading WordNet to enable
    its use without restarting the application.

    Returns:
        True if WordNet is now available, False otherwise
    """
    global _WORDNET_AVAILABLE, _LEMMATIZER_AVAILABLE, _wordnet, _lemmatizer

    try:
        # Try to import/reimport wordnet
        from nltk.corpus import wordnet
        # Clear any cached data to force reload
        try:
            wordnet._LazyCorpusLoader__load()
        except Exception:
            pass
        # Test if it actually works
        wordnet.synsets('test')
        _wordnet = wordnet
        _WORDNET_AVAILABLE = True

        # Also try to initialize the lemmatizer
        try:
            from nltk.stem import WordNetLemmatizer
            _lemmatizer = WordNetLemmatizer()
            _lemmatizer.lemmatize('testing', pos='v')
            _LEMMATIZER_AVAILABLE = True
        except (ImportError, LookupError):
            _LEMMATIZER_AVAILABLE = False

        # Also refresh the singleton thesaurus instance
        thesaurus = get_thesaurus()
        thesaurus.refresh_wordnet()

        return True
    except (ImportError, LookupError, Exception):
        _WORDNET_AVAILABLE = False
        _LEMMATIZER_AVAILABLE = False
        return False


def get_base_forms(word: str) -> List[str]:
    """Get possible base forms of a word using stemming rules.

    Useful for debugging or understanding what forms are being tried.

    Args:
        word: The word to analyze

    Returns:
        List of possible base forms
    """
    return WordStemmer.get_base_forms(word)
