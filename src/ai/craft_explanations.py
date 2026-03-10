"""Static craft writing explanations for educational tips in critique results.

Each SuggestionType maps to a brief principle explanation and a
generic before/after example.  These are displayed on-demand when the
user clicks "Learn about …" in a critique card.
"""

from src.ai.chapter_analysis_agent import SuggestionType


CRAFT_EXPLANATIONS = {

    # ── Core writing craft ───────────────────────────────────────

    SuggestionType.SHOW_DONT_TELL: {
        "principle": (
            "'Show Don't Tell' means conveying emotions, states, and traits "
            "through concrete actions, sensory details, and dialogue rather "
            "than naming them directly. Important moments deserve to be "
            "experienced by the reader, not summarized."
        ),
        "before": "She was terrified of the dark room.",
        "after": (
            "Her fingers whitened on the doorframe. She counted three breaths "
            "before forcing her foot across the threshold."
        ),
    },

    SuggestionType.PACING: {
        "principle": (
            "Pacing controls how quickly or slowly the reader moves through "
            "your story. Short sentences and active verbs speed things up; "
            "longer, descriptive sentences slow things down. Match pace to "
            "emotional intensity — fast during action, slower during reflection."
        ),
        "before": (
            "He ran through the long, winding, dimly-lit corridor that seemed "
            "to stretch on forever while his heart beat faster."
        ),
        "after": "He ran. The corridor twisted. Darkness swallowed the walls ahead.",
    },

    SuggestionType.DIALOGUE: {
        "principle": (
            "Good dialogue does double duty: it reveals character and advances "
            "the story simultaneously. Each character should sound distinct. "
            "Avoid using dialogue as a vehicle to dump information the "
            "characters would already know."
        ),
        "before": (
            '"As you know, Bob, we have been partners at this firm for '
            'fifteen years and our biggest client is arriving today."'
        ),
        "after": (
            '"Client\'s here in an hour." Bob loosened his tie. '
            '"Think they\'ll buy it?" "They\'d better."'
        ),
    },

    SuggestionType.DESCRIPTION: {
        "principle": (
            "Effective description selects specific, telling details rather "
            "than cataloguing everything. One sharp image does more than a "
            "paragraph of generic adjectives. Ground description in a "
            "character's point of view so it reveals both the world and the "
            "observer."
        ),
        "before": (
            "The room was big with white walls, a brown table, four chairs, "
            "a window with blue curtains, and a vase of flowers."
        ),
        "after": (
            "Dust motes drifted through a blade of afternoon sun. The vase "
            "on the table held yesterday's lilies, their petals curling brown "
            "at the edges."
        ),
    },

    SuggestionType.CHARACTER_VOICE: {
        "principle": (
            "Every character should sound like themselves — word choice, "
            "sentence rhythm, and what they notice should differ from person "
            "to person. A child doesn't speak like a professor; a soldier "
            "doesn't observe a room the way an artist does."
        ),
        "before": (
            '"I find this situation to be quite distressing," the '
            "eight-year-old stated formally."
        ),
        "after": '"This is scary. I wanna go home." She tugged at her mother\'s sleeve.',
    },

    SuggestionType.CONSISTENCY: {
        "principle": (
            "Consistency means your facts, character traits, and world rules "
            "stay stable unless deliberately changed. If a character's eyes "
            "are blue in chapter two, they shouldn't be green in chapter "
            "eight without explanation. Readers trust you to keep track."
        ),
        "before": "She tucked the revolver into her waistband — the same revolver she'd dropped into the river two scenes ago.",
        "after": "She reached for her waistband and found nothing. Right — the river. She'd need another way.",
    },

    SuggestionType.CLARITY: {
        "principle": (
            "Clarity means the reader always knows who is speaking, what is "
            "happening, and where they are in space and time. Ambiguous "
            "pronoun references, unclear action sequences, and missing "
            "transitions break the reader's immersion."
        ),
        "before": "He told him that he thought he should leave before he got angry.",
        "after": 'Mark leaned close. "You should leave. Before I say something I regret."',
    },

    SuggestionType.GRAMMAR: {
        "principle": (
            "Grammar errors — misplaced modifiers, subject-verb disagreements, "
            "incorrect tense shifts — pull the reader out of the story. "
            "Intentional rule-breaking (fragments for emphasis, dialect) is "
            "fine when it serves a purpose; accidental errors are not."
        ),
        "before": "Running through the forest, the trees seemed to close in around him.",
        "after": "Running through the forest, he felt the trees closing in around him.",
    },

    SuggestionType.WORD_CHOICE: {
        "principle": (
            "The right word is precise and evocative; the almost-right word "
            "is flat. Avoid vague intensifiers ('very', 'really', 'quite') "
            "and choose concrete verbs and nouns. 'Sprinted' says more than "
            "'ran very fast'. 'Shack' says more than 'small building'."
        ),
        "before": "She walked slowly and sadly through the very old building.",
        "after": "She shuffled through the decrepit hall, trailing one hand along the peeling wallpaper.",
    },

    # ── Extended categories ──────────────────────────────────────

    SuggestionType.PLOT: {
        "principle": (
            "Every scene should either advance the plot, reveal character, "
            "or both. If a scene doesn't change anything — no new information, "
            "no shifted relationships, no raised stakes — it may be filler. "
            "Watch for logic gaps where characters act without motivation."
        ),
        "before": "They spent the afternoon shopping and chatting about nothing in particular.",
        "after": (
            "At the market she spotted the jacket — identical to the one in "
            "the crime-scene photos. She pulled out her phone."
        ),
    },

    SuggestionType.WORLDBUILDING: {
        "principle": (
            "Worldbuilding works best when woven into action and dialogue, "
            "not delivered in lecture form. Let the reader discover the world "
            "the way a native would experience it — through small, lived-in "
            "details rather than encyclopedia entries."
        ),
        "before": (
            "The Kingdom of Aldara was founded 300 years ago by King Toren I "
            "after the Great Unification War. Its currency is the silver crown "
            "and its primary export is ironwood timber."
        ),
        "after": (
            'She slapped two silver crowns on the counter. "Ironwood\'s '
            "doubled in a fortnight. Toren's bones, at this rate I'll be "
            'selling kindling."'
        ),
    },

    SuggestionType.STYLE: {
        "principle": (
            "Style is the pattern of your prose: sentence length, vocabulary "
            "level, figurative language, rhythm. Consistency of style creates "
            "a reading experience. Sudden shifts — from lyrical to blunt, "
            "from sparse to purple — should be intentional and motivated."
        ),
        "before": (
            "The luminescent cerulean of the twilight sky was beautiful. "
            "Then stuff happened and it got dark."
        ),
        "after": (
            "The sky deepened to indigo. Stars pricked through one by one, "
            "as if someone were poking holes in a dark curtain."
        ),
    },

    SuggestionType.TONE: {
        "principle": (
            "Tone is the emotional atmosphere of the prose — the feeling "
            "the reader absorbs from your word choices, imagery, and rhythm. "
            "A horror scene undercut by breezy, comedic narration confuses "
            "the reader. Keep tone consistent within a scene unless the "
            "shift is deliberate."
        ),
        "before": (
            "The body lay in a pool of blood, which was super gross. "
            "Anyway, Detective Mills sighed and pulled out his notebook."
        ),
        "after": (
            "The body lay in a pool of blood so dark it looked black under "
            "the fluorescents. Mills pulled out his notebook, mouth tight."
        ),
    },

    SuggestionType.VOICE: {
        "principle": (
            "Voice is the narrator's personality on the page — how they "
            "see and interpret the world. A consistent voice creates trust. "
            "If your narrator is wry and observant, they shouldn't suddenly "
            "become earnest and unobservant without reason."
        ),
        "before": (
            "He observed the mundane proceedings with sardonic detachment. "
            "Oh gosh, it was all so wonderful and exciting!"
        ),
        "after": (
            "He watched the proceedings the way one watches a microwave — "
            "technically attentive, spiritually elsewhere."
        ),
    },

    SuggestionType.CHARACTER_DEVELOPMENT: {
        "principle": (
            "Characters need to change — or meaningfully resist change — "
            "over the course of a story. Static characters feel flat. "
            "Development should be earned through conflict and decision, "
            "not announced ('She realized she had grown')."
        ),
        "before": "After the war, she realized she was a stronger person now.",
        "after": (
            "The first time someone dropped a glass, she didn't flinch. "
            "She noticed that, later, standing in the quiet kitchen."
        ),
    },

    SuggestionType.TENSION: {
        "principle": (
            "Tension is what keeps pages turning. It comes from uncertainty: "
            "the reader must want something and not know if they'll get it. "
            "Defusing tension too early, or never establishing stakes, "
            "makes scenes feel flat."
        ),
        "before": (
            "She had to defuse the bomb but she was really good at it "
            "so she knew she'd be fine."
        ),
        "after": (
            "Two wires left. Red or blue. Her instructor's voice echoed — "
            "'Fifty-fifty odds are not odds you survive.' She reached for the red."
        ),
    },

    SuggestionType.THEME: {
        "principle": (
            "Themes emerge from story events, not from characters lecturing "
            "the reader. If your theme is 'power corrupts,' show it through "
            "choices and consequences — don't have a character say 'Power "
            "corrupts, you know.' Trust the reader to draw the connection."
        ),
        "before": '"Power corrupts," she said wisely. "We must all be careful."',
        "after": (
            "She'd promised transparency. Six months in, she signed the "
            "executive order without reading it. 'Just this once,' she told herself."
        ),
    },

    # ── Publishability-specific issues ───────────────────────────

    SuggestionType.CLICHE: {
        "principle": (
            "Clichés are phrases so overused they've lost their meaning: "
            "'heart of gold', 'dead of night', 'breath she didn't know "
            "she'd been holding.' They signal that the writer reached for "
            "the first phrase that came to mind. Replace them with something "
            "specific to your character and scene."
        ),
        "before": "Her blood ran cold and her heart skipped a beat.",
        "after": "Her jaw locked. The hair on her forearms lifted.",
    },

    SuggestionType.FILTER_WORDS: {
        "principle": (
            "Filter words — 'she saw', 'he heard', 'she felt', 'he noticed' "
            "— insert the character between the reader and the experience. "
            "Removing them puts the reader directly in the scene. Instead of "
            "'She heard a crash,' write 'A crash echoed down the hall.'"
        ),
        "before": "She noticed that the sky was turning red. He felt the ground shake.",
        "after": "The sky turned red. The ground shook.",
    },

    SuggestionType.TRANSITION: {
        "principle": (
            "Smooth transitions guide the reader through time and space "
            "without calling attention to the mechanism. Avoid mechanical "
            "bridges like 'Meanwhile,' 'Suddenly,' or 'Later that day.' "
            "Instead, lead with a sensory detail or action that orients the "
            "reader naturally."
        ),
        "before": "Meanwhile, back at the castle, the queen was pacing.",
        "after": (
            "The queen's boots wore a crescent into the rug before the throne. "
            "She'd been pacing since the riders left."
        ),
    },

    SuggestionType.POV: {
        "principle": (
            "Point-of-view discipline means you only reveal what the POV "
            "character can see, hear, know, and feel. In third-person limited, "
            "you cannot describe what another character is thinking. Slipping "
            "into another character's head mid-scene is called 'head-hopping' "
            "and it disorients the reader."
        ),
        "before": (
            "Sarah felt nervous. Across the table, Mark thought she "
            "looked beautiful but couldn't find the words."
        ),
        "after": (
            "Sarah's fingers found the napkin in her lap and twisted it. "
            "Mark was staring, she realized — but at what, she couldn't tell."
        ),
    },

    SuggestionType.ADVERB: {
        "principle": (
            "Adverbs (especially '-ly' words modifying dialogue tags) often "
            "signal that the verb isn't doing enough work. 'She said angrily' "
            "is weaker than 'She snapped.' Look for a stronger verb or let "
            "the dialogue and action carry the emotion."
        ),
        "before": '"I don\'t want to go," she said sadly and reluctantly.',
        "after": '"I don\'t want to go." She turned back to the window.',
    },

    SuggestionType.PASSIVE_VOICE: {
        "principle": (
            "Passive voice ('The ball was thrown by John') hides the actor "
            "and slows the sentence. Active voice ('John threw the ball') "
            "is more direct and vivid. Passive voice has its uses — when "
            "the actor is unknown or unimportant — but defaulting to active "
            "voice makes prose more engaging."
        ),
        "before": "The door was opened by the stranger and the room was entered.",
        "after": "The stranger opened the door and stepped inside.",
    },

    SuggestionType.INFO_DUMP: {
        "principle": (
            "An info-dump is a block of exposition that halts the story to "
            "explain background, history, or mechanics. Readers absorb "
            "information best when it's delivered in small pieces, attached "
            "to action or conflict. Ask: does the reader need this now, and "
            "can I show it instead of telling it?"
        ),
        "before": (
            "The city of Varn was founded in 1042 by settlers from the north. "
            "It had a population of 50,000, a thriving fishing industry, "
            "and was governed by a council of twelve elders who each "
            "represented one of the original founding families."
        ),
        "after": (
            "The fishing boats crowded the harbor so thick you could walk "
            "across on their decks. Elder Hask watched from the quay, "
            "counting masts the way his grandfather had taught him — one "
            "mast for every family that had a voice on the council."
        ),
    },
}
