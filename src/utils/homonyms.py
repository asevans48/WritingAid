"""Homonyms (piece P.2b): a sound-alike word where the sentence wants the other.

ProWritingAid's Homonyms report lists every word that sounds like another
for the writer to confirm. Listing every "peak" and "rein" would bury the
few that are wrong, so this check flags a sound-alike only where the words
around it point to its twin: "sneak **peak**", "free **reign**", "**wreck**
havoc", "**pour** over the map", "couldn't **breath**", "walked **passed**
him". About 220 patterns, each written to leave the right use alone ("the
peak of the hill", "rain poured over the roof", "she couldn't bear it").

The words the editor's grammar rules already cover (their/there, your/you're,
its/it's, then/than, a/an, "could of") are left to them.

Each flag names the word it probably should be and offers it, so one click
fixes one place. **"Fix all" is never offered** (decision 9: the right form
depends on the sentence; ``fix_all.is_confusable`` refuses every homonym
flag). Plain patterns, no model.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

KIND = "homonym"

# A pattern names the doubtful word ``(?P<w>…)``; the fix is the right word
# for each form ("peaked" → "peeked"). ``_forms(wrong, right)`` expands a pair to
# its -s, -ed and -ing forms.
Fix = Dict[str, str]


def _s(w: str) -> str:
    return w + "es" if w.endswith(("s", "sh", "ch", "x")) else w + "s"


def _ed(w: str) -> str:
    return w + "d" if w.endswith("e") else w + "ed"


def _ing(w: str) -> str:
    if w.endswith("e") and not w.endswith(("ee", "oe")):
        return w[:-1] + "ing"
    return w + "ing"


def _forms(wrong: str, right: str) -> Dict[str, str]:
    return {wrong: right, _s(wrong): _s(right), _ed(wrong): _ed(right),
            _ing(wrong): _ing(right)}


_PRON = r"(?:I|he|she|we|they|you)"
_POSS = r"(?:my|his|her|their|our|your|its)"
_END = r"(?=\s*(?:[.,;:!?—–)\"”]|$))"          # followed by punctuation or the end

# (pattern, fix, what the right word means)
RULES: List[Tuple[str, Fix, str]] = [
    # peek / peak / pique
    (r"\bsneak (?P<w>peaks?)\b", _forms("peak", "peek"), "peek: a quick look"),
    (r"\b(?:take|took|taking|takes|steal|stole|sneak|sneaked|snuck|have|had) a (?:quick |little |"
     r"sly |furtive |brief |last |final )?(?P<w>peak)\b(?! (?:of|in|at)\b)",
     _forms("peak", "peek"), "peek: a quick look"),
    (r"\b(?P<w>peak(?:ed|ing|s)?) (?:through|inside|behind|out from|from behind|round the|"
     r"around the (?:door|corner|edge|curtain)|over (?:his|her|my|their|the) shoulder|"
     r"through the (?:keyhole|curtains?|window|door|crack|gap))\b",
     _forms("peak", "peek"), "peek: a quick look"),
    (r"\b(?P<w>peak(?:ed|ing|s)?) (?:my|his|her|their|our|your|the|its|everyone's) "
     r"(?:interest|curiosity|attention)\b", _forms("peak", "pique"), "pique: to arouse"),
    # rein / reign
    (r"\bfree (?P<w>reign)\b", {"reign": "rein"}, "rein: free rein, as with a horse"),
    (r"\b(?P<w>reign(?:ed|ing|s)?) (?:him|her|them|it|myself|himself|herself|themselves|"
     r"yourself) in\b", _forms("reign", "rein"), "rein in: to hold back"),
    (r"\b(?:tight|loose|short) (?P<w>reigns?)\b", _forms("reign", "rein"), "rein: the straps"),
    (r"\b(?:take|took|taken|taking|takes|hand|handed|hold|held|holding|grab|grabbed|pull|"
     r"pulled|seize|seized) (?:the|his|her) (?P<w>reigns)\b", {"reigns": "reins"},
     "reins: the straps (and control)"),
    (r"\b(?P<w>rein) of (?:terror|power)\b", {"rein": "reign"}, "reign: a ruler's time"),
    (r"\b(?:during|throughout) (?:the|his|her|their) (?:\w+'s )?(?P<w>rein)\b",
     {"rein": "reign"}, "reign: a ruler's time"),
    # wreak, toe, bated, throes, pore
    (r"\b(?P<w>(?:wreck|reek)(?:ed|ing|s)?) havoc\b",
     {**_forms("wreck", "wreak"), **_forms("reek", "wreak")}, "wreak havoc: to cause it"),
    (r"\b(?P<w>tow(?:ed|ing|s)?) the (?:party |company )?line\b", _forms("tow", "toe"),
     "toe the line: to conform"),
    (r"\b(?P<w>baited) breath\b", {"baited": "bated"}, "bated: held back"),
    (r"\bin the (?P<w>throws) of\b", {"throws": "throes"}, "throes: spasms, struggle"),
    (r"\b(?:death|final|last) (?P<w>throws)\b", {"throws": "throes"}, "throes: spasms, struggle"),
    (r"\b(?P<w>pour(?:ed|ing|s)?) over (?:the |his |her |their |my |a |an |every |old |"
     r"those |these )?(?:\w+ )?(?:maps?|books?|documents?|notes?|papers?|files?|letters?|"
     r"records?|pages?|details?|reports?|accounts?|ledgers?|manuscripts?|charts?|plans?|"
     r"texts?|photographs?|photos?|newspapers?|evidence|data|figures|lists?|contracts?|"
     r"diaries|diary|journals?|menus?|scriptures?|clues?|accounts)\b",
     _forms("pour", "pore"), "pore over: to study closely"),
    # lose / loose
    (r"\b(?:to|not|never|will|would|could|might|may|must|can|cannot|didn't|don't|doesn't|"
     r"won't|wouldn't|couldn't|can't|almost|nearly|I|we|you|they|'ll) (?P<w>loose) "
     r"(?:the |his |her |my |your |their |our |its |any |all )?(?:way|job|temper|mind|patience|"
     r"nerve|balance|track|footing|grip|game|match|war|battle|weight|chance|count|sight|touch|"
     r"interest|consciousness|hope|faith|control|focus|heart|courage|face|money|everything)\b",
     {"loose": "lose"}, "lose: to stop having"),
    (r"\b(?P<w>loosing) (?:the |his |her |my |your |their |our |its |any |all )?(?:way|job|"
     r"temper|mind|patience|nerve|balance|track|footing|grip|game|match|war|battle|weight|"
     r"chance|count|sight|touch|interest|consciousness|hope|faith|control|focus|heart|courage|"
     r"face|money|everything|blood|time)\b", {"loosing": "losing"}, "losing: no longer having"),
    (r"\b(?:break|broke|broken|breaking|breaks|cut|cutting|set|let|lets|letting|came|come|comes|"
     r"coming|turned|shook|shaken|worked|hung|hanging|tore|torn|wriggled|pulled) "
     r"(?P<w>lose)\b(?! (?:to|it|him|her|them|the|his|my|their|our|your|a|an|track|sight|"
     r"control|everything|anything|something|interest|face|heart|me|us|you)\b)",
     {"lose": "loose"}, "loose: free, not tight"),
    (r"\b(?P<w>lose)[- ](?:fitting|leaf|limbed|lipped|knit|ends?|change|cannon|threads?|"
     r"tooth|floorboards?|strands?|bricks?|button)\b", {"lose": "loose"},
     "loose: free, not tight"),
    # affect / effect
    (r"\b(?:an|the|no|any|little|some|side|great|full|lasting|immediate|desired|opposite|"
     r"same|strange|odd|calming|soothing|chilling|dramatic|profound|powerful|positive|negative|"
     r"real|startling|big|huge) (?P<w>affects?) (?:on|of|upon)\b",
     {"affect": "effect", "affects": "effects"}, "effect: a result"),
    (r"\b(?:in|to no|take|took|takes|taking|taken|into) (?P<w>affect)\b(?! (?:the|his|her|"
     r"their|my|your|our|its|him|them|me|us|how)\b)", {"affect": "effect"}, "effect: a result"),
    (r"\b(?:to|not|didn't|doesn't|don't|won't|wouldn't|couldn't|can't|could|would|will|might|"
     r"may|did|does|it|that|this|which|never|seemed to|seem to) (?P<w>effect(?:s|ed|ing)?) "
     r"(?:me|him|her|them|us|you|my|his|their|our|your|the way|how)\b",
     _forms("effect", "affect"), "affect: to change or move"),
    (r"\b(?:was|were|is|are|been|be|deeply|badly|greatly|not|un) (?P<w>effected) by\b",
     {"effected": "affected"}, "affected: changed or moved"),
    # breath / breathe
    (r"\b(?:to|could|couldn't|can|can't|cannot|would|will|won't|didn't|don't|did not|do not|"
     r"barely|hardly|must|let me|let him|let her|let them|tried to|began to|forgot to|"
     r"remember to|need to|needed to) (?P<w>breath)\b(?! of\b)", {"breath": "breathe"},
     "breathe: the verb"),
    (r"\b(?:a|another|deep|one|my|his|her|their|our|your|every|last|out of|catch|caught|hold|"
     r"held|holding|shaky|ragged|sharp|long|short|fresh|first|single|shallow|steadying) "
     r"(?P<w>breathe)\b", {"breathe": "breath"}, "breath: the noun"),
    # stationary / stationery
    (r"\b(?P<w>stationary) (?:shop|store|cupboard|drawer|supplies|aisle|section|order|"
     r"cabinet|set)\b", {"stationary": "stationery"}, "stationery: paper and pens"),
    (r"\b(?:remained|remain|remains|remaining|stood|standing|stayed|stay|stays|kept|perfectly|"
     r"completely|almost|utterly) (?P<w>stationery)\b", {"stationery": "stationary"},
     "stationary: not moving"),
    # principal / principle
    (r"\bin (?P<w>principal)\b(?! (?:and|amounts?|sums?|payments?|residences?)\b)",
     {"principal": "principle"}, "principle: a rule or belief"),
    (r"\b(?:matter|man|woman|people|person) of (?P<w>principal)\b",
     {"principal": "principle"}, "principle: a rule or belief"),
    (r"\b(?:school|deputy|vice|assistant|head) (?P<w>principle)\b",
     {"principle": "principal"}, "principal: the head (or main)"),
    (r"\b(?P<w>principle)'s (?:office|desk|voice|secretary)\b",
     {"principle": "principal"}, "principal: the head of a school"),
    (r"\b(?P<w>principle) (?:reason|character|characters|cause|investigator|dancer|role|source|"
     r"concern|aim|goal|suspect|witness|owner|city|street|actor|actors)\b",
     {"principle": "principal"}, "principal: main"),
    # compliment / complement
    (r"\b(?P<w>complement(?:ed|s|ing)?) (?:him|her|them|me|us|you) on\b",
     _forms("complement", "compliment"), "compliment: praise"),
    (r"\b(?:paid|pay|pays|paying|fishing for|backhanded|accept|accepted) (?:(?:him|her|me|"
     r"them|us|you) )?(?:a |the )?(?P<w>complements?)\b",
     _forms("complement", "compliment"), "compliment: praise"),
    # bear / bare
    (r"\b(?P<w>bare) (?:with (?:me|us|him|her)|in mind|the brunt|witness|fruit|a grudge|"
     r"(?:a|no|little|any) resemblance)\b", {"bare": "bear"}, "bear: to carry or endure"),
    (r"\b(?:can't|cannot|couldn't|could not|can not|could hardly|can hardly|unable to) "
     r"(?P<w>bare) (?:it|the|to|him|her|them|this|that)\b", {"bare": "bear"},
     "bear: to endure"),
    (r"\b(?P<w>bear)[- ](?:feet|foot|footed|handed|hands|chested|legs|minimum|bones|"
     r"essentials|necessities|floorboards|mattress|bulb)\b", {"bear": "bare"},
     "bare: uncovered"),
    # brake / break
    (r"\b(?:slammed|slam|slamming|jammed|stamped|pumped|pumping|released|hit|hits|hitting) "
     r"(?:on )?(?:the |his |her |their )(?P<w>breaks?)\b", _forms("break", "brake"),
     "brake: what stops a car"),
    (r"\b(?:emergency|hand|foot|parking) (?P<w>breaks?)\b", _forms("break", "brake"),
     "brake: what stops a car"),
    (r"\b(?:lunch|coffee|tea|take a|took a|taking a|need a|needed a) (?P<w>brake)\b",
     {"brake": "break"}, "break: a rest"),
    # sight / site
    (r"\b(?:out of|caught|catch|catching|lost|lose|losing|at first|a sorry|a welcome) "
     r"(?P<w>site)\b", {"site": "sight"}, "sight: seeing"),
    (r"\b(?:building|construction|camp|burial|crash|archaeological|launch|dump) (?P<w>sight)\b",
     {"sight": "site"}, "site: a place"),
    # past / passed
    (r"\b(?:walked|walk|walking|walks|ran|running|drove|driving|went|going|rode|riding|hurried|"
     r"rushed|raced|swept|slipped|pushed|brushed|shoved|squeezed|stepped|strode|marched|flew|"
     r"sailed|edged|crept|sped|glanced|looked|stared|gazed|moved|filed|wandered|limped|"
     r"staggered|stumbled|hurry|rush|race|slip|push|brush|squeeze|step|stride|march|creep|"
     r"glance|look|stare|gaze|move|wander) (?P<w>passed)\b(?! (?:away|out|on|by|over|down|"
     r"through|the (?:test|exam|ball|salt|note|message|time))\b)",
     {"passed": "past"}, "past: beyond"),
    (r"\b(?:in|for|of|during|over) the (?P<w>passed)\b", {"passed": "past"},
     "past: the time before"),
    (r"\bhalf (?P<w>passed) (?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
     r"midnight|noon|\d)", {"passed": "past"}, "past: after the hour"),
    (r"\b(?:had|has|have|having) (?P<w>past)\b(?! (?:experience|lives|life|tense|history|"
     r"mistakes|week|weeks|month|months|year|years|few|two|three|several)\b)",
     {"past": "passed"}, "passed: went by"),
    # led / lead
    (r"\b(?:was|were|been|being|is|are) (?P<w>lead) (?:by|to|into|away|astray|out|through|"
     r"down|up|along|from|off|back|around)\b", {"lead": "led"}, "led: the past of lead"),
    (r"\b(?:had|has|have) (?P<w>lead) (?:the|him|her|them|me|us|you|to|a|an|his|my|their|our|"
     r"its)\b", {"lead": "led"}, "led: the past of lead"),
    # lightning / lightening
    (r"\b(?P<w>lightening) (?:bolts?|strikes?|struck|flash(?:ed|es)?|storms?|crack(?:ed)?|"
     r"forked|split|lit)\b", {"lightening": "lightning"}, "lightning: in a storm"),
    (r"\b(?:thunder and|forked|sheet|ball of|flash of|bolt of|streak of|crack of|like greased) "
     r"(?P<w>lightening)\b", {"lightening": "lightning"}, "lightning: in a storm"),
    # whether / weather
    (r"\b(?P<w>weather) or not\b", {"weather": "whether"}, "whether: if"),
    (r"\b(?:wonder|wondered|wondering|unsure|decide|decided|deciding|doubt|doubted|asked|ask) "
     r"(?P<w>weather) (?:he|she|they|I|we|it|to|or|there|anyone|you|his|her|their|the)\b",
     {"weather": "whether"}, "whether: if"),
    # wonder / wander
    (r"\b(?P<w>wander(?:ed|ing|s)?) (?:if|whether|why|how|what|who|aloud|about (?:it|that|"
     r"this|what|whether|why|how))\b", _forms("wander", "wonder"), "wonder: to ask oneself"),
    (r"\b(?P<w>wonder(?:ed|ing|s)?) (?:off|around the|round the|aimlessly|the streets|"
     r"the halls|the corridors|away from|along the|into the (?:woods|forest|street|kitchen|"
     r"garden|crowd|hall))\b", _forms("wonder", "wander"), "wander: to roam"),
    # aloud / allowed
    (r"\b(?:read|reads|reading|said|say|says|saying|spoke|speak|speaking|thought|think|"
     r"thinking|wondered|wonder|wondering|laughed|laugh|laughing|counted|count|counting|"
     r"mused|muse|musing|prayed|sighed|groaned|cursed|swore) (?P<w>allowed)\b(?! (?:to|in|on|"
     r"into|out|him|her|them|me|us|you|it|the|a|an|any|no|for|by|that|myself|himself|"
     r"herself|themselves)\b)", {"allowed": "aloud"}, "aloud: out loud"),
    # vain / vein / vane
    (r"\bin (?P<w>vein)\b(?=\s*[.,;!?—]|$| (?:hope|attempt|effort|search)\b)",
     {"vein": "vain"}, "in vain: for nothing"),
    (r"\bweather[- ]?(?P<w>vain|vein)\b", {"vain": "vane", "vein": "vane"},
     "vane: it turns in the wind"),
    # horde / hoard
    (r"\b(?:a|the|whole|entire|huge|vast) (?P<w>hoards?) of (?:\w+ )?(?:people|zombies|men|"
     r"women|soldiers|tourists|children|kids|reporters|journalists|fans|students|shoppers|orcs|"
     r"goblins|warriors|barbarians|invaders|enemies|locusts|rats|flies|guests|relatives|"
     r"admirers|onlookers|protesters|refugees|demons|undead|savages|rioters)\b",
     {"hoard": "horde", "hoards": "hordes"}, "horde: a crowd"),
    # palate / palette
    (r"\b(?P<w>palette|pallet)[- ]cleanser\b", {"palette": "palate", "pallet": "palate"},
     "palate: taste"),
    (r"\b(?:cleanse|cleansed|cleansing) (?:the |his |her |my |your |their )?"
     r"(?P<w>palette|pallet)\b", {"palette": "palate", "pallet": "palate"}, "palate: taste"),
    (r"\b(?:colou?r|painter's|artist's) (?P<w>pallet|palate)\b",
     {"pallet": "palette", "palate": "palette"}, "palette: a painter's colours"),
    # role / roll
    (r"\b(?P<w>roll) (?:models?|reversals?|playing|played)\b", {"roll": "role"},
     "role: a part played"),
    (r"\b(?:title|leading|starring|supporting|lead) (?P<w>roll)\b", {"roll": "role"},
     "role: a part played"),
    (r"\b(?P<w>role) call\b", {"role": "roll"}, "roll call: the list read out"),
    (r"\brock (?:and|'n'|n|&) (?P<w>role)\b", {"role": "roll"}, "rock and roll"),
    (r"\bon a (?P<w>role)\b", {"role": "roll"}, "on a roll: doing well"),
    (r"\b(?:egg|spring|sausage|bread|toilet) (?P<w>roles?)\b", {"role": "roll", "roles": "rolls"},
     "roll: the food (or paper)"),
    # faze / phase
    (r"\b(?:didn't|doesn't|don't|did not|does not|do not|never|wouldn't|won't|hadn't|can't|"
     r"couldn't|barely|hardly|not|seemed to) (?P<w>phased?|phases)\b(?! (?:out|in|into|of|"
     r"one|two|three)\b)", {"phase": "faze", "phased": "fazed", "phases": "fazes"},
     "faze: to unsettle"),
    # sheer / shear
    (r"\b(?P<w>shear) (?:luck|will|willpower|terror|size|number|numbers|panic|joy|"
     r"determination|weight|scale|volume|bulk|exhaustion|fright|horror|chance|madness|"
     r"stupidity|beauty|drop|cliff|delight|relief|bliss|fury|rage|audacity|nerve|speed|"
     r"coincidence|desperation|willpower)\b", {"shear": "sheer"}, "sheer: pure, utter, steep"),
    (r"\bby (?P<w>shear) (?:force|strength)\b", {"shear": "sheer"}, "sheer: pure, utter"),
    (r"\b(?P<w>slight) of hand\b", {"slight": "sleight"}, "sleight: skill, trickery"),
    # stakes / steak
    (r"\bhigh[- ](?P<w>steaks)\b", {"steaks": "stakes"}, "stakes: what is at risk"),
    (r"\b(?:raise|raised|raising|upped|up) the (?P<w>steaks)\b", {"steaks": "stakes"},
     "stakes: what is at risk"),
    (r"\b(?:burned|burnt|burn|burning) at the (?P<w>steak)\b", {"steak": "stake"},
     "stake: a post"),
    (r"\b(?:drive|drove|driven|driving|drives) a (?P<w>steak) (?:through|into)\b",
     {"steak": "stake"}, "stake: a pointed post"),
    (r"\bdire (?P<w>straights)\b", {"straights": "straits"}, "straits: trouble"),
    (r"\b(?:core|basic|central|fundamental|key|main) (?P<w>tenants)\b", {"tenants": "tenets"},
     "tenets: beliefs"),
    (r"\b(?P<w>tenants?) of (?:the |his |her |their |our )?(?:faith|belief|beliefs|religion|"
     r"doctrine|philosophy|creed|ideology|theory)\b", {"tenant": "tenet", "tenants": "tenets"},
     "tenet: a belief"),
    (r"\begg (?P<w>yokes?)\b", {"yoke": "yolk", "yokes": "yolks"}, "yolk: the yellow"),
    (r"\b(?P<w>wet(?:ted|ting|s)?) (?:my|his|her|your|their|our|the|its|everyone's) appetite\b",
     {"wet": "whet", "wetted": "whetted", "wetting": "whetting", "wets": "whets"},
     "whet: to sharpen"),
    (r"\b(?:coal|gold|silver|tin|copper|diamond) (?P<w>minors?)\b",
     {"minor": "miner", "minors": "miners"}, "miner: digs in a mine"),
    (r"\b(?P<w>boarder) (?:guards?|patrol|crossing|control|town|post|police|checkpoint|"
     r"dispute|wall|fence)\b", {"boarder": "border"}, "border: a frontier"),
    (r"\bwide (?P<w>birth)\b", {"birth": "berth"}, "berth: room to pass"),
    (r"\b(?P<w>cereal) (?:killers?|killings?|numbers?|murderers?|rapist|offender|port)\b",
     {"cereal": "serial"}, "serial: one after another"),
    (r"\b(?P<w>serial) (?:bowls?|box|boxes|packet)\b", {"serial": "cereal"},
     "cereal: breakfast grain"),
    (r"\bof (?P<w>coarse)\b(?=\s*(?:[,.!?;—–]|$|\s(?:not|he|she|I|it|they|we|you|there|that|"
     r"this|i)\b))", {"coarse": "course"}, "of course"),
    (r"\b(?:golf|race|obstacle|main|crash|due|collision|matter of|change|changed|plotted|"
     r"stay the|stayed the|off) (?P<w>coarse)\b", {"coarse": "course"}, "course: a route or part"),
    (r"\bup the (?P<w>creak)\b", {"creak": "creek"}, "creek: a stream"),
    (r"\b(?:fought|fight|fighting|challenged (?:him|her|them|me) to) a (?P<w>dual)\b",
     {"dual": "duel"}, "duel: a fight"),
    (r"\b(?P<w>duel) (?:citizenship|carriageway|purpose|roles?|nationality|personality|"
     r"identity|nature|meaning|controls?|wielding)\b", {"duel": "dual"}, "dual: two"),
    (r"\b(?P<w>flee) (?:market|markets|bites?|bitten|collar|circus|ridden|infested|powder)\b",
     {"flee": "flea"}, "flea: the insect"),
    (r"\b(?:to|must|had to|forced to|tried to|would|could|didn't|they|we|I|he|she) "
     r"(?P<w>flea)\b(?= (?:the|from|into|for|across|town|home|abroad|north|south|east|west)\b)",
     {"flea": "flee"}, "flee: to run away"),
    (r"\b(?:look|looks|looking|looked|step|steps|stepping|stepped|lean|leans|leaning|leaned|"
     r"leant|move|moving|moved|came|come|coming|went|go|going|pushed|lurched|surged|bent|"
     r"rushed|ran|walked|fast|edged|inched|pitched|tipped|fell|stumbled|leapt|jumped|sprang|"
     r"straight) (?P<w>foreword)\b", {"foreword": "forward"}, "forward: ahead"),
    (r"\b(?P<w>hair)[- ]?brained\b", {"hair": "hare"}, "hare-brained: like a hare"),
    (r"\bfor the long (?P<w>hall)\b", {"hall": "haul"}, "the long haul"),
    (r"\ball (?P<w>manor) of\b", {"manor": "manner"}, "manner: kind, way"),
    (r"\b(?P<w>manor) of (?:speaking|dress|death)\b", {"manor": "manner"}, "manner: way"),
    (r"\b(?P<w>marshall?) (?:law|arts?|artists?)\b", {"marshal": "martial", "marshall": "martial"},
     "martial: of war"),
    (r"\bcourt[- ](?P<w>marshall?(?:l?ed)?)\b",
     {"marshal": "martial", "marshall": "martial", "marshaled": "martialed",
      "marshalled": "martialled"}, "court-martial"),
    (r"\b(?:test|tested|testing|prove|proved|proven|proving|show|showed|shown|showing) "
     r"(?:his|her|their|my|your|our) (?P<w>metal|medal)\b",
     {"metal": "mettle", "medal": "mettle"}, "mettle: courage"),
    (r"\b(?:won|win|wins|winning|awarded|earned|earn|received) (?:a |the |an |his |her |their )?"
     r"(?:gold |silver |bronze |olympic |Olympic )?(?P<w>metal)\b(?=\s*(?:[.,;!?]|$|\s(?:for|"
     r"in|at|and|from)\b))", {"metal": "medal"}, "medal: an award"),
    (r"\bin (?P<w>morning) (?:for|black|clothes|band)\b", {"morning": "mourning"},
     "mourning: grief"),
    (r"\b(?:period|time|days|year|weeks|months) of (?P<w>morning)\b", {"morning": "mourning"},
     "mourning: grief"),
    (r"\b(?:window|glass|plate[- ]glass) (?P<w>pains?)\b", {"pain": "pane", "pains": "panes"},
     "pane: a sheet of glass"),
    (r"\b(?P<w>piece) (?:and|&) quiet\b", {"piece": "peace"}, "peace: calm"),
    (r"\brest in (?P<w>piece)\b", {"piece": "peace"}, "peace: calm"),
    (r"\b(?:make|made|making|at|world|inner|disturbed|disturbing|disturb) (?P<w>piece)\b"
     r"(?! (?:of|by|together|after|for|in|on|to|with)\b)", {"piece": "peace"}, "peace: calm"),
    (r"\b(?P<w>piece) of mind\b", {"piece": "peace"}, "peace of mind"),
    (r"\b(?:a|one|another|each|every|that|this|the|last|small|big|large|tiny) (?P<w>peace) of "
     r"(?:cake|paper|bread|wood|meat|furniture|evidence|advice|information|land|work|music|art|"
     r"string|glass|cloth|metal|pie|news|jewelry|jewellery|toast|chocolate|fruit|equipment|"
     r"junk|luggage|chalk|tape|candy|gum|clothing|pottery|rope|wire|fabric|cheese|the puzzle)\b",
     {"peace": "piece"}, "piece: a part"),
    (r"\b(?P<w>wrapped) (?:attention|audience|expression|gaze|silence)\b", {"wrapped": "rapt"},
     "rapt: absorbed"),
    (r"\b(?:days|times|years|tales) of (?P<w>your|you're)" + _END,
     {"your": "yore", "you're": "yore"}, "yore: long ago"),
    (r"\b(?:suits?|suited|fits?|fitted) (?:\w+ )?to a (?P<w>tea)\b", {"tea": "tee"},
     "to a tee: exactly"),
    (r"\b(?:a|what a|such a|complete|total|utter) (?P<w>waist) of\b", {"waist": "waste"},
     "waste: something squandered"),
    (r"\b(?P<w>waist) of (?:time|money|energy|effort|space|breath|talent|life|resources)\b",
     {"waist": "waste"}, "waste: something squandered"),
    (r"\b(?P<w>waste)[- ](?:deep|high|length|band|coat)\b", {"waste": "waist"},
     "waist: the middle of the body"),
    (r"\b(?:around|round) (?:his|her|my|their|your) (?P<w>waste)\b", {"waste": "waist"},
     "waist: the middle of the body"),
    (r"\b(?:his|her|my|their|your) (?:slim|slender|narrow|thick|thin|tiny|small) (?P<w>waste)\b",
     {"waste": "waist"}, "waist: the middle of the body"),
    (r"\b(?:lose|lost|losing|loses|gain|gained|gaining|gains|put on|carry|carried|carrying|"
     r"shift|shifted|shifting) (?:his|her|my|their|your|our|some|the|its|any|much|more|full) "
     r"(?P<w>wait)\b", {"wait": "weight"}, "weight: heaviness"),
    (r"\b(?:I'll|we'll|you'll|he'll|she'll|they'll|can't|couldn't|could|would|will|should|must|"
     r"please|just|let's) (?P<w>weight)\b(?= (?:for|until|till|a minute|a moment|a second|"
     r"a bit|here|there|outside)\b|\s*[.,;!?])", {"weight": "wait"}, "wait: to stay"),
    (r"\bworse for (?:the )?(?P<w>where|ware)\b", {"where": "wear", "ware": "wear"},
     "wear: use"),
    (r"\b(?P<w>where|ware) and tear\b", {"where": "wear", "ware": "wear"}, "wear and tear"),
    (r"\b(?P<w>wear) (?:are|were|did|do|does|have|had|has) (?:you|we|they|he|she|I)\b(?! wear)",
     {"wear": "where"}, "where: what place"),
    (r"\b(?P<w>weigh) to go\b", {"weigh": "way"}, "way to go"),
    (r"\b(?:a|one|last|next|this|that) (?P<w>weak) (?:ago|later|before|after|earlier|"
     r"from now|or two|and a half)\b", {"weak": "week"}, "week: seven days"),
    (r"\b(?:felt|feel|feels|feeling|grew|growing|looked|seemed|sounded|so|too|very) "
     r"(?P<w>week)\b(?! (?:of|later|ago|before|after|earlier|or|and|in|three|two|four|five|six|"
     r"one|by)\b)", {"week": "weak"}, "weak: without strength"),
    (r"\b(?:was|were|am|felt|feel|feeling|so|get|got|getting|being|been|looked|seemed|grew|"
     r"very|too|utterly|completely) (?P<w>board)\b(?!-| (?:up|meeting|members?|certified|"
     r"games?|room|of|the|a|an|with|by|for|on|and|over|her|his|their|our|ship|train|plane|bus)\b)",
     {"board": "bored"}, "bored: weary"),
    (r"\b(?P<w>board) out of (?:my|his|her|their|our|your) (?:mind|minds|skull|skulls|wits)\b",
     {"board": "bored"}, "bored: weary"),
    (r"\b(?P<w>bored) (?:meeting|room|members?|games?|of directors|of governors|of trustees|"
     r"of education)\b", {"bored": "board"}, "board: a committee (or game board)"),
    (r"\b(?:a|the|whole) (?P<w>heard) of\b", {"heard": "herd"}, "herd: a group of animals"),
    (r"\b(?:had|have|has|haven't|hadn't|hasn't|never) (?P<w>herd)\b", {"herd": "heard"},
     "heard: the past of hear"),
    (r"\b" + _PRON + r" (?P<w>herd) (?:that|someone|something|nothing|anything|footsteps|voices|"
     r"a (?:noise|sound|voice|knock|scream|shout|cry|crash|bang|thud))\b", {"herd": "heard"},
     "heard: the past of hear"),
    (r"\b(?:voice|throat) (?:was |sounded |went |grew |had gone |turned |came out )?"
     r"(?P<w>horse)\b", {"horse": "hoarse"}, "hoarse: rough-voiced"),
    (r"\b(?:a|his|her|in a) (?P<w>horse) (?:whisper|voice|croak|cough|rasp)\b",
     {"horse": "hoarse"}, "hoarse: rough-voiced"),
    (r"\b(?:shouted|screamed|yelled|cheered|sang|talked|cried) (?:himself|herself|themselves|"
     r"myself|ourselves|yourself) (?P<w>horse)\b", {"horse": "hoarse"}, "hoarse: rough-voiced"),
    (r"\b(?P<w>hoarse)(?=[- ]?(?:back|drawn|races?|racing|riding|riders?|shoes?|power|play|"
     r"whisperer|box|trailer|stables?|cart|carriage|thie(?:f|ves)|blanket|meat|manure|dung|"
     r"trough|sense)\b)", {"hoarse": "horse"}, "horse: the animal"),
    (r"\b(?:a|the) (?P<w>loan) (?:wolf|figure|survivor|gunman|rider|star|ranger|voice|tree|"
     r"soldier|traveller|traveler|horseman)\b", {"loan": "lone"}, "lone: alone"),
    (r"\b(?:I|he|she|we|they|you|had|has|have) (?P<w>maid) (?:a|an|the|it|him|her|me|them|us|"
     r"up|sure|sense|way|his|my|their)\b", {"maid": "made"}, "made: the past of make"),
    (r"\b(?:his|her|my|their|your|own|belly) (?P<w>naval)\b(?=\s*(?:[.,;!?]|$|\s(?:ring|"
     r"piercing|lint|area|button)\b))", {"naval": "navel"}, "navel: the belly button"),
    (r"\b(?P<w>naval)[- ]gazing\b", {"naval": "navel"}, "navel-gazing"),
    (r"(?<!\ba )(?<!\bthe )\b(?P<w>pair|paired|pairing|pear|peared) down\b",
     {"pair": "pare", "paired": "pared", "pairing": "paring", "pear": "pare", "peared": "pared"},
     "pare down: to trim"),
    (r"\bbeyond the (?P<w>pail)\b", {"pail": "pale"}, "beyond the pale"),
    (r"\b(?:went|turned|grew|looked|face|faces|skin|cheeks|lips) (?:very |deathly |ashen |"
     r"slightly |)(?P<w>pail)\b(?!-| of\b)", {"pail": "pale"}, "pale: without colour"),
    (r"\b(?P<w>peddl(?:e|ed|ing|es)) (?:his|her|my|their|the|a) (?:bike|bicycle|cycle|"
     r"tricycle)\b", {"peddle": "pedal", "peddled": "pedalled", "peddling": "pedalling",
                      "peddles": "pedals"}, "pedal: to push the pedals"),
    (r"\bback[- ]?(?P<w>peddl(?:e|ed|ing|es))\b", {"peddle": "pedal", "peddled": "pedalled",
                                                   "peddling": "pedalling", "peddles": "pedals"},
     "backpedal"),
    (r"\b(?P<w>pier) (?:pressure|group|groups|review|reviewed)\b", {"pier": "peer"},
     "peer: an equal"),
    (r"\b" + _PRON + r" (?P<w>pier(?:ed|s)?) (?:at|into|through|over|around|down|out|up|"
     r"closer)\b", _forms("pier", "peer"), "peer: to look closely"),
    (r"\b(?:in|into|within) (?P<w>plane) (?:sight|view)\b", {"plane": "plain"},
     "plain sight: openly"),
    (r"\b(?:the|a|his|her|their|our) (?P<w>plain) (?:crashed|landed|took off|taxied|"
     r"touched down|tickets?|crash)\b", {"plain": "plane"}, "plane: an aircraft"),
    (r"\b(?:boarded|boarding|caught|catch) (?:the |a |his |her |our )(?P<w>plain)\b",
     {"plain": "plane"}, "plane: an aircraft"),
    (r"\b(?:fall|falls|fell|falling|fallen|easy|became|become|becomes|birds? of) "
     r"(?P<w>pray)\b", {"pray": "prey"}, "prey: the hunted"),
    (r"\b(?:I|we|let us|let's|they|knelt to|knelt and) (?P<w>prey)\b(?! (?:on|upon)\b)",
     {"prey": "pray"}, "pray: to ask God"),
    (r"\b(?P<w>right|write) of passage\b", {"right": "rite", "write": "rite"},
     "rite of passage"),
    (r"\b(?P<w>ring(?:ing|s)?|rung) (?:her|his|my|their|our|your) (?:hands|neck)\b",
     {"ring": "wring", "ringing": "wringing", "rings": "wrings", "rung": "wrung"},
     "wring: to twist"),
    (r"\b(?P<w>ring(?:ing|s)?|rung)(?: out)? (?:the |a |her |his )?(?:towel|cloth|rag|washing|"
     r"flannel|dishcloth|sponge|mop)\b",
     {"ring": "wring", "ringing": "wringing", "rings": "wrings", "rung": "wrung"},
     "wring: to squeeze out"),
    (r"\b" + _PRON + r" (?P<w>road) (?:a|an|the|his|her|my|their|our|home|away|off|out|up|"
     r"down|on|in|into|through|past|back|hard|fast|slowly|alongside|beside|behind|ahead|toward|"
     r"towards)\b", {"road": "rode"}, "rode: the past of ride"),
    (r"\bever (?P<w>sense)\b", {"sense": "since"}, "since: from then"),
    (r"\b(?:make|makes|made|making|common) (?P<w>cents)\b", {"cents": "sense"}, "sense: meaning"),
    (r"\b(?:to|would|could|will|must|I|he|she|we|they|had to) (?P<w>sleigh(?:ed)?) (?:the|a|"
     r"his|her|their|him|them|dragons?|monsters?|beasts?|giants?|vampires?|demons?|enemies)\b",
     {"sleigh": "slay", "sleighed": "slew"}, "slay: to kill"),
    (r"\b(?P<w>slay) (?:bells?|ride|rides|runners)\b", {"slay": "sleigh"}, "sleigh: a sledge"),
    (r"\b(?P<w>soar) (?:throat|throats|feet|foot|losers?|point|muscles?|eyes|head|arm|arms|"
     r"legs?|spot|knees?|ribs|jaw|neck|shoulders?|wrist|ankle|hands?|thumb|subject|tooth|"
     r"teeth|gums)\b", {"soar": "sore"}, "sore: aching"),
    (r"\b(?P<w>sore(?:d|ing)?) (?:above|into the (?:sky|air|clouds)|high|upward|upwards|"
     r"skyward|skywards|overhead|aloft)\b",
     {"sore": "soar", "sored": "soared", "soring": "soaring"}, "soar: to fly high"),
    (r"\b(?:heart and|body and|kindred|lost|bless (?:his|her|my|your|their)|not a (?:living )?|"
     r"every living|immortal|tortured|troubled) (?P<w>soles?)\b(?! of\b)",
     {"sole": "soul", "soles": "souls"}, "soul: the spirit"),
    (r"\b(?:the|his|her|my|their|our|its) (?P<w>soul) (?:survivors?|purpose|reason|heir|"
     r"heiress|owner|responsibility|aim|exception|occupant|provider|beneficiary|breadwinner|"
     r"custody|focus|means|remaining)\b", {"soul": "sole"}, "sole: only"),
    (r"\b(?:I|he|she|we|they|you|would|could|n't) (?P<w>stair(?:s|ed|ing)?) (?:at|into|"
     r"down at|back at|out at|up at|blankly|intently)\b", _forms("stair", "stare"),
     "stare: to look hard"),
    (r"\b(?P<w>steal(?:ing|s)?) (?:himself|herself|myself|themselves|ourselves|yourself|"
     r"yourselves)\b", _forms("steal", "steel"), "steel oneself: to brace"),
    (r"\bnerves? of (?P<w>steal)\b", {"steal": "steel"}, "nerves of steel"),
    (r"\b(?P<w>steel(?:s|ing)?) (?:a|the|his|her|my|their|your) (?:car|money|kiss|glance|"
     r"look|show|horse|purse|wallet|jewels|necklace|bread|food|limelight|spotlight|thunder|"
     r"scene|secrets?|identity)\b", _forms("steel", "steal"), "steal: to take"),
    (r"\b(?:hotel|bridal|honeymoon|presidential|executive|penthouse|en) (?P<w>sweet)\b",
     {"sweet": "suite"}, "suite: a set of rooms"),
    (r"\b(?P<w>team(?:ed|ing|s)?) with (?:life|fish|rain|insects|bugs|wildlife|vermin|rats|"
     r"flies|activity|maggots|ants)\b", _forms("team", "teem"), "teem: to swarm"),
    (r"\b(?:was|were|been|be|being|get|got|gets|getting|had|have|has) (?P<w>throne)\b",
     {"throne": "thrown"}, "thrown: the past of throw"),
    (r"\b(?:the|a|his|her|their|its) (?P<w>thrown)\b(?=\s*(?:[.,;!?]|$|\s(?:of|room)\b))",
     {"thrown": "throne"}, "throne: a royal seat"),
    (r"\b(?:walked|walk|walking|went|go|going|ran|run|running|came|come|coming|looked|look|"
     r"looking|broke|break|breaking|pushed|push|pushing|drove|drive|driving|climbed|climb|"
     r"crawled|crawl|stared|staring|peered|peering|cut|cutting|sliced|waded|wading|made it|"
     r"flipped|leafed|sifted|halfway|all the way|straight) (?P<w>threw)\b",
     {"threw": "through"}, "through: from one side to the other"),
    (r"\b(?:I|he|she|we|they|you) (?P<w>through) (?:a|an|the|his|her|my|their|our|it|them|"
     r"him|me|up|open|down|away|off)\b(?! (?:the |a |)(?:door|doorway|window|gate|crowd|"
     r"room|hall|tunnel|woods|forest|night|years|streets?)\b)", {"through": "threw"},
     "threw: the past of throw"),
    (r"\b(?P<w>wave(?:d|s)?) (?:the|his|her|their|my|any|all) (?:rights?(?! (?:hand|arm|fist|"
     r"foot|leg|palm))|fees?|requirements?|charges?|penalty|immunity|privilege|claims?|fine)\b",
     {"wave": "waive", "waved": "waived", "waves": "waives"}, "waive: to give up"),
    (r"\b(?P<w>waive(?:d|s)?) (?:goodbye|good-bye|good bye|at (?:him|her|them|me|us)|"
     r"(?:his|her|a) hand|farewell|them off|him off|her off|me off)\b",
     {"waive": "wave", "waived": "waved", "waives": "waves"}, "wave: to move the hand"),
    (r"\b(?:red|white|sparkling|mulled|glass of|bottle of|bottles of|glasses of|cup of|sip of|"
     r"sipped|sipping|poured|drank) (?P<w>whine)\b", {"whine": "wine"}, "wine: the drink"),
    (r"\b(?:can|could|couldn't|can't|cannot|didn't|to|will|would|won't|wouldn't|I|we|they) "
     r"(?P<w>here) (?:the|a|an|his|her|their|my|your|our|them|him|me|us|what|that|you|"
     r"someone|something|anything|nothing|voices|footsteps|music|everything)\b",
     {"here": "hear"}, "hear: with the ears"),
    (r"\b(?:right|come|came|in|out|up|down|from|around) (?P<w>hear)" + _END,
     {"hear": "here"}, "here: this place"),
    (r"\bthe (?P<w>hole) (?:time|thing|day|night|week|year|world|story|truth|family|town|"
     r"village|lot|point)\b", {"hole": "whole"}, "whole: all of it"),
    (r"\ba (?P<w>whole) in (?:the|his|her|my|their|its|our)\b", {"whole": "hole"},
     "hole: an opening"),
    (r"\b(?:I|we|they|you|didn't|don't|doesn't|did not|do not|wouldn't|couldn't|might|would|"
     r"will|won't) (?P<w>no) (?:that|what|how|why|who|whether|if)\b", {"no": "know"},
     "know: to be aware"),
    (r"\bon (?P<w>queue)\b(?! (?:for|to|at|in|behind)\b)", {"queue": "cue"}, "on cue: at the signal"),
    (r"\bdown the (?P<w>isle)\b", {"isle": "aisle"}, "aisle: a passage"),
    (r"\b(?P<w>isle) seat\b", {"isle": "aisle"}, "aisle: a passage"),
    (r"\b(?:at|to|before|approached|knelt at|knelt before) the (?P<w>alter)\b(?! ego)",
     {"alter": "altar"}, "altar: in a church"),
    (r"\b(?P<w>alter) (?:boys?|girls?|rail|cloth|server|candles?)\b", {"alter": "altar"},
     "altar: in a church"),
    (r"\b(?P<w>flare) for (?:the dramatic|drama|languages|fashion|style|design|words|business|"
     r"cooking|music|comedy|theatre|theater|numbers|the theatrical)\b", {"flare": "flair"},
     "flair: a talent"),
    (r"\b(?:fairy|cautionary|old wives'?|tall|morality) (?P<w>tails?)\b",
     {"tail": "tale", "tails": "tales"}, "tale: a story"),
    (r"\btell[- ](?P<w>tail)\b", {"tail": "tale"}, "telltale"),
    (r"\b(?P<w>bridle) (?:shower|party|gown|suite|veil|dress|magazine|shop|bouquet|march|"
     r"registry)\b", {"bridle": "bridal"}, "bridal: of a bride"),
    (r"\b(?:struck|strike|strikes|striking|touched|touch) a (?:\w+ )?(?P<w>cord)\b",
     {"cord": "chord"}, "chord: notes together"),
    (r"\b(?:vocal|spinal|umbilical) (?P<w>chords?)\b", {"chord": "cord", "chords": "cords"},
     "cord: a string"),
    (r"\b(?:marine|press|peace|army|medical|officer|diplomatic|ballet|cadet) (?P<w>core)\b",
     {"core": "corps"}, "corps: a body of people"),
    (r"\b(?:shaken|shook|rotten|chilled|frightened|scared) to (?:the |his |her |my |their )"
     r"(?P<w>corps)\b", {"corps": "core"}, "core: the centre"),
    (r"\b(?P<w>gorillas?) (?:warfare|war|wars|fighters?|tactics|campaign|attacks?|army|"
     r"armies|band|bands|forces|leader|movement)\b",
     {"gorilla": "guerrilla", "gorillas": "guerrilla"}, "guerrilla: irregular fighting"),
    (r"\b(?:teen|pop|matinee|matinée|childhood|false|screen|sporting|football|golden) "
     r"(?P<w>idles?)\b(?=\s*(?:[.,;!?]|$|\s(?:of|and|was|had|who)\b))",
     {"idle": "idol", "idles": "idols"}, "idol: someone adored"),
    (r"\b(?:sat|sit|sitting|stood|stand|standing|lay|lying|remained|stayed|left) "
     r"(?P<w>idol)\b(?=\s*(?:[.,;!?]|$|\s(?:for|while|in|on|at|and)\b))", {"idol": "idle"},
     "idle: doing nothing"),
    (r"\b(?P<w>meet(?:ing|s)?|meat) out (?:justice|punishments?|retribution|vengeance|"
     r"discipline|revenge|sentences?|penalties)\b",
     {"meet": "mete", "meeting": "meting", "meets": "metes", "meat": "mete"},
     "mete out: to hand out"),
    (r"\b(?:chocolate|hair|salmon|mango|lemon|raspberry|strawberry|styling) (?P<w>moose)\b",
     {"moose": "mousse"}, "mousse: a foam"),
    (r"\b(?:iron|copper|uranium|zinc|nickel) (?P<w>oar)\b", {"oar": "ore"}, "ore: rock with metal"),
    (r"\b(?P<w>sew(?:ed|n|ing|s)?) (?:the |a |his |her |their |some )?(?:seeds?|discord|"
     r"dissent|doubt|confusion|chaos|wild oats|crops?|wheat|barley|mistrust|distrust|division)\b",
     {"sew": "sow", "sewed": "sowed", "sewn": "sown", "sewing": "sowing", "sews": "sows"},
     "sow: to plant"),
    (r"\b(?P<w>sow(?:ed|n|ing)?) (?:up )?(?:the |a |his |her |their )?(?:buttons?|seams?|hems?|"
     r"patch|patches|quilt|stitches|wound|gash|sleeve|collar|pocket)\b",
     {"sow": "sew", "sowed": "sewed", "sown": "sewn", "sowing": "sewing"}, "sew: to stitch"),
    (r"\b(?:pulled|drawn|stretched|held|wire|rope|line|cord|string|muscles|skin|nerves|jaw|"
     r"voice|smile|lips) (?:was |were |had been |pulled |drawn |stretched |)(?P<w>taught)"
     r"(?=\s*(?:[.,;!?—–]|$|\s(?:and|as|with|against|across|between|like|under|beneath)\b))",
     {"taught": "taut"}, "taut: pulled tight"),
    (r"\b(?:a|the|his|her|their|its) (?P<w>taught) (?:rope|line|wire|cord|string|muscles?|skin|"
     r"face|jaw|smile|voice|expression|body|silence|thread|sails?|nerves|stomach|belly|frame|"
     r"thriller|drum|canvas)\b", {"taught": "taut"}, "taut: pulled tight"),
    (r"\bloose (?P<w>canon)\b", {"canon": "cannon"}, "loose cannon"),
    (r"\b(?P<w>cannon) law\b", {"cannon": "canon"}, "canon law"),
    (r"\b(?:keep|kept|keeping|keeps) (?:his|her|my|their|our|your) own (?P<w>council)\b",
     {"council": "counsel"}, "counsel: advice"),
    (r"\blegal (?P<w>council)\b", {"council": "counsel"}, "counsel: a lawyer"),
    (r"\b(?P<w>illicit(?:ed|s|ing)?) (?:a|an|the|his|her|their|my|some|no) (?:response|"
     r"reaction|smile|laugh|gasp|groan|confession|information|answer|cry|sigh|sympathy|giggle|"
     r"chuckle|nod|shrug)\b", _forms("illicit", "elicit"), "elicit: to draw out"),
    (r"\b(?:aircraft|plane|airplane|aeroplane|zeppelin|airship|jet|helicopter) "
     r"(?P<w>hangers?)\b", {"hanger": "hangar", "hangers": "hangars"}, "hangar: for aircraft"),
    (r"\b(?:brought|bring|brings|bringing) to (?P<w>heal)" + _END, {"heal": "heel"},
     "brought to heel"),
    (r"\b(?:Achilles'?|Achilles's|head over|high|stiletto|kitten|dig (?:his|her|their|my|our|"
     r"your|in (?:his|her|their|my|our|your))) (?P<w>heals?)\b", {"heal": "heel", "heals": "heels"},
     "heel: the back of the foot"),
    (r"\bon (?:his|her|their|my|your|our) (?P<w>heals)\b", {"heals": "heels"},
     "heels: the backs of the feet"),
    (r"\b(?:was|were|am|is|are|felt|be|been|seemed|remained) (?P<w>loathe) to\b",
     {"loathe": "loath"}, "loath: unwilling"),
    (r"\b(?P<w>fowl) (?:play|mood|language|smell|odour|odor|weather|temper|stench|mouth|"
     r"mouthed|deed|deeds)\b", {"fowl": "foul"}, "foul: bad"),
    (r"\b(?:wild|water|domestic|guinea) (?P<w>foul)\b", {"foul": "fowl"}, "fowl: birds"),
    (r"\b(?P<w>died|dying|dies|die) (?:her|his|my|their|your|our) (?:hair|beard|eyebrows|"
     r"clothes|shirt|dress|jeans)\b",
     {"died": "dyed", "dying": "dyeing", "dies": "dyes", "die": "dye"}, "dye: to colour"),
    (r"\b(?:was|is|were|are|be|been|it's|that's) (?P<w>dew) to\b", {"dew": "due"},
     "due to: because of"),
    (r"\b(?P<w>dew) (?:date|diligence)\b", {"dew": "due"}, "due: owed"),
    (r"\b(?:caught|catch|catching|got|getting|bout of) (?:the )?(?P<w>flue)" + _END,
     {"flue": "flu"}, "flu: the illness"),
    (r"\b(?:back and|so on and so|and so|from that day|from this day|bring|brought|bringing|"
     r"sallied|sally|issued|poured|burst|bursting|sprang|sent) (?P<w>fourth)\b(?! (?:place|"
     r"position|seat|spot|class|grade|floor|time)\b)", {"fourth": "forth"}, "forth: onward"),
    (r"\b(?:the|his|her|its|a|their|my|our) (?P<w>forth) (?:time|floor|day|year|grade|place|"
     r"quarter|of July|son|daughter|child|wife|husband|attempt|try|round|chapter|book|century|"
     r"row|storey|wall|week|month|night|generation|birthday|cup|glass|drink|shot|game|lap)\b",
     {"forth": "fourth"}, "fourth: number four"),
    (r"\b(?P<w>grizzly) (?:murders?|scenes?|crimes?|deaths?|details|discovery|remains|"
     r"killings?|end|business|task|aftermath|injuries|wounds?|photographs?|evidence|tale)\b",
     {"grizzly": "grisly"}, "grisly: gruesome"),
    (r"\b(?P<w>gilt)[- ](?:trip|tripped|tripping|ridden|stricken)\b", {"gilt": "guilt"},
     "guilt: blame"),
    (r"(?<!the )\b(?P<w>real(?:ed|ing|s)?) (?:him|her|them|it|me|us) in\b",
     {"real": "reel", "realed": "reeled", "realing": "reeling", "reals": "reels"},
     "reel in: to wind in"),
    (r"\b(?:have|has|had|haven't|hasn't|hadn't|never|ever|I've|you've|we've|they've|I'd|you'd|"
     r"we'd|they'd|he'd|she'd) (?P<w>scene)\b(?! (?:one|two|three|four|five|six|seven|eight|"
     r"nine|ten|after|of)\b|\s*\d)", {"scene": "seen"}, "seen: the past of see"),
    (r"\b(?:crime|murder|accident) (?P<w>seen)\b(?=\s*(?:[.,;!?]|$|\s(?:tape|investigators?|"
     r"photographers?|photos?|photographs?|cleaners?|cleanup)\b))", {"seen": "scene"},
     "scene: a place"),
]

_COMPILED = [(re.compile(rx, re.I), fix, note) for rx, fix, note in RULES]


def _match_case(original: str, word: str) -> str:
    if original.isupper() and len(original) > 1:
        return word.upper()
    if original[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def _starts_sentence(text: str, pos: int) -> bool:
    before = text[:pos].rstrip(" \t\"“‘'(")
    return not before or before[-1] in ".!?…:;—\n"


def find(text: str) -> List[Tuple[int, int, str, str, str]]:
    """(start, end, word, right word, note) for each sound-alike that the
    words around it say is probably the wrong one."""
    out: Dict[Tuple[int, int], Tuple[int, int, str, str, str]] = {}
    for rx, fix, note in _COMPILED:
        for m in rx.finditer(text):
            s, e = m.span("w")
            word = m.group("w")
            if word[:1].isupper() and not word.isupper() and not _starts_sentence(text, s):
                continue                             # a name ("Free Reign Stables")
            right = fix.get(word.lower()) if isinstance(fix, dict) else None
            if not right:
                continue
            out.setdefault((s, e), (s, e, word, _match_case(word, right), note))
    return sorted(out.values())


def analyze(text: str, add) -> None:
    from src.utils.style_checks import StyleIssue
    for s, e, word, right, note in find(text):
        add(StyleIssue(KIND, s, e, word,
                       f"“{word}” sounds like “{right}”, which fits here better ({note}). "
                       f"Check which you meant.", suggestions=[right]))
