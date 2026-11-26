# Background to the plan

Why the plan is shaped the way it is. A coding session does not need this file.

## Critical review: can this match ProWritingAid?

**Short answer.** On the range of reports, the app is already close and can
reach parity cheaply. On grammar accuracy and overall polish, it is behind, and
nobody knows by how much because nothing measures it. On integrations (Word,
Google Docs, browser) it will not match and should not try. Where it knows the
story, the characters and the writer's voice, it can be better than
ProWritingAid, which sees only the text in front of it.

The comparison below uses ProWritingAid's own features and reports pages, read
on 22 November 2026. This app's side comes from module summaries and is
confirmed in piece 0.1.

| Area | ProWritingAid | This app today | Verdict |
|---|---|---|---|
| Writing reports | 27 named reports | Every one but plagiarism, since P.2a and P.2b (Combo only partly) | Close. Of the eight P.2 checks, Pronouns, Acronyms and Homonyms meet four in five and are on for new projects; the other five are one tick away. |
| Grammar | Its own engine | LanguageTool's open rules plus built-in rules | Behind. Narrowed by P.4 and P.6. |
| False alarms | Tuned over years | Unknown. No check has a measured accuracy. | The real risk. Fixed by phase Q. |
| Chapter critique | Yes | Yes, with story memory, characters, plot and voice | Ahead where the story matters. |
| Manuscript analysis | Editor-style overview of plot, pacing, next steps | Not yet | Piece 8.2. |
| Virtual beta reader | Hook points, drop-off points, emotional impact | Reader's eye, one chapter at a time | Piece P.7 extends it to the book. |
| Character and plot analysis | Yes | Parts exist (speech profiles, pacing audit) | Pieces P.8 and 7.3. |
| Marketability and agent materials | Yes | Not yet | Piece 9.3. |
| Rewrites | Rephrase, Sparks Edit | Rephrase, Suggestions, Expand, in the writer's own voice, learning from ratings | Ahead. |
| Privacy | Text goes to their servers | Can run entirely on the writer's machine or own server | Ahead. |
| Integrations | Word, Google Docs, Scrivener, browsers | A standalone app | Out of scope. Good import and export instead (9.2). |
| Plagiarism check | Yes | No | Out of scope: it needs a web-scale index. |
| Writing habits and community | Sprints, challenges, nudges, critique groups, workshops, mobile app | No | Out of scope: not part of getting a manuscript ready. |

**Report by report.** Confirmed in 0.1 against the code (see the
[inventory](inventory.md)).

| ProWritingAid report | Here today |
|---|---|
| Realtime, Grammar, Style | Yes |
| Rephrase, Chapter Critique, Thesaurus | Yes |
| Overused Words, All Repeats, Echoes | Yes. Repeated phrases: **yes**, from `OveruseDetector.analyze_phrases`, shown in the editor as "Repeated phrase" |
| Sentence Length, Readability, Sticky Sentences, Clichés | Yes |
| Consistency, House Style | Yes (consistency checks, style sheet) |
| Dialogue, Pacing | Yes |
| Combo | **Partly.** The editor's highlights show all four families together (spelling, grammar, overuse, style), but no single report lists them together. The Style panel lists the eleven style checks only. |
| Sentence Structure | Yes, since P.2b: style check "Sentence structure" (four or more sentences in a row of about the same length; three in a row opening the same way: an -ing phrase, a "when / as" clause, a preposition, an -ly word), beside repeated sentence starts and the Critique's sentence-length variety. Off until ticked. |
| Diction | Yes, since P.2b: style check "Vague words" (stuff, kind of, all sorts of things, or something, nice, aspect …, in narration only) beside wordy phrases. Off until ticked. |
| Transition | Yes, since P.2a: style check "Few transitions" (long paragraphs with no linking word) and the share of sentences with one in the Style tab's summary. Off until ticked. |
| Pronoun, Alliteration, Acronym | Yes, since P.2a: style checks "Pronouns", "Alliteration" and "Acronyms". Off until ticked. |
| Sensory | Yes, since P.2b: style check "Sensory detail" (a long stretch of narration with no sense at all) and the chapter's mix of senses (sight, sound, touch, smell, taste) in the Style checks summary. Off until ticked. |
| Homonym | Yes, since P.2b: style check "Homonyms", a sound-alike where the words around it want its twin (sneak peak, free reign, wreck havoc …), with the twin as a one-place fix and no "Fix all". On for new projects (meets four in five). |
| Plagiarism | Out of scope |

### What is wrong with the first version of this plan

1. **It measured nothing.** It added checks and a readiness figure without ever
   asking whether the checks are right. ProWritingAid's advantage is
   calibration more than the number of reports. A check that is wrong one time
   in three teaches the writer to ignore the whole tool. The benchmark (phase Q)
   is now the first code written.
2. **It rebuilt things that exist.** The editor already contains a style
   analyser, eleven style checks and a style panel. The old piece 1.3 would
   have written a second copy. It now reuses them.
3. **It added screens and removed none.** The app has a style panel, the critique
   tab, the Companion, Suggestions, Rephrase and the consistency dialog. A
   scorecard and a queue on top make it harder to use, not easier, unless
   something is merged or retired. Rule 13 now forbids adding without taking
   away, and phase D removes a tab, two windows and most of a menu.
4. **A readiness figure can mislead.** Clearing every flag does not make a book
   publishable; ProWritingAid's users still need editors and readers. The
   figure is now called "ready for readers", the scorecard says plainly what it
   does and does not measure, and no screen uses the word "publishable" for a
   number.
5. **The writer waited too long to see anything.** Sixteen sessions passed before
   the queue appeared. A thin scorecard now follows straight after the engine
   (2.1 before the remaining checks), so each later check appears on screen as
   it is added.
6. **Model time was ignored.** Judging four stages across forty chapters is about
   160 model calls. On a local or home-server model that is hours. The
   background check (2.3) must be resumable from the start, not only when the
   job queue arrives.
7. **Some pieces rest on unproven ideas.** Voice drift (4.2) and tension ratings
   (7.2) may turn out to be noise. They are now marked experimental: each has
   to pass a test on real chapters before it is shown to the writer.
8. **The editor file is 5,700 lines.** Pieces that change how the editor draws
   text (phase 5) carry the most risk of breaking something else. Phase 5 has
   been cut.

### What will actually get there

In order of effect:

1. **Measure the checks** (Q.1, Q.2), then fix or hide the worst ones (P.5).
2. **Compare side by side with ProWritingAid** on the same chapters (P.1), and
   let that list, not guesswork, decide what to add.
3. **Deeper proofreading with a model** (P.4), shown only when the change is
   small and can be verified.
4. **Compare every measure with published books in the genre** (P.3).
5. **Fewer, clearer screens** (0.2).
6. **The path itself**: scorecard, stages and queue (phases 1 to 3).

### Cut from the plan

Six pieces have been cut to keep the app uncluttered. Each added a view or a
convenience without a new ability, or did not change the manuscript. Their
write-ups stay in this document, marked *cut*, so any can be restored.

- **5.1 and 5.2, changes shown in the text.** The style panel and right-click
  menu already apply fixes in one click.
- **U.4, issue strip.** The highlights and the scorecard already show where
  problems are.
- **U.5, pop-out panels.** A convenience for several screens only. Rule 12
  still requires every window to work across screens.
- **9.4, beta readers,** and **10.1, revision checklist.** Neither changes the
  manuscript.

Cutting these removes nothing that exists today, so it cannot affect
backwards compatibility.

The tension curve (7.3) and the submission package (9.3) stay: they are needed
for parity with ProWritingAid's plot analysis and marketability features.

## What "publishable" means here

A tool cannot certify a book. What it can do is take the manuscript through
the same stages a professional edit would, in the same order, and say honestly
which of them it has checked. The stages below follow the published
definitions of the Editorial Freelancers Association and Editors Canada.

| Stage in this app | Professional equivalent | What it covers, per those definitions |
|---|---|---|
| Structure | Developmental or structural editing | Content, organisation and genre; revising, reordering, cutting, expanding; clarifying plot, characterisation and theme |
| Scene | Part of the same stage; closest to a manuscript evaluation | Characterisation, dialogue, setting, plot, structure, voice, tone |
| Line | Line or stylistic editing | Language and style at sentence and paragraph level; meaning, coherence and flow; clichés, sentence and paragraph length, tone and voice |
| Copyedit | Copyediting | Spelling, grammar, usage, punctuation; consistency of mechanics and facts, including character names; the style sheet |
| Proof | Proofreading | Typographical and formatting errors in the final format. Editors Canada: proofreading "is not a substitute for editing." |

**How the plan uses this**

- The five stages and their order are kept, and each readiness check is filed
  under the stage whose definition covers it.
- The editorial letter (8.2) reports on the seven elements Editors Canada lists
  for a manuscript evaluation.
- The style sheet is treated as a copyediting deliverable, which is how the EFA
  describes it, and the final sweep (9.1) checks the book against it.
- The scorecard's wording says which stages have been checked, never that the
  book is publishable.

**Opening pages.** Agents and editors who write about rejections most often
name the same things: sample pages that do not hook, a story that takes too
long to reach its inciting incident, and an unpolished draft. They say the
decision is usually made within the first five to ten pages. These are
practitioners' accounts, not studies, so the plan treats them as a strong
convention: piece 1.8 gives the opening pages a stricter check of their own.

**Length is information, not a target.** Good writing at an unusual length is
still good, and a manuscript at the "right" length can still be poor. The app
shows length beside what is typical for the genre and route. It never counts
toward readiness.

**Format.** For agent submissions, piece 9.2 checks export against William
Shunn's manuscript format: a title page with contact details, title and an
approximate word count; a running header of surname, short title and page
number; each chapter starting on its own page; scene breaks marked with "#".
Font, spacing, margin and indent rules are read from his novel guide in that
piece; I could not confirm them from the pages I read. An agent's or
publisher's own guidelines always override.

**Sources**
- Editorial Freelancers Association, editorial services definitions:
  https://www.the-efa.org/editorial-services-definitions/
- Editors Canada, definitions of editorial skills: https://editors.ca/hire/skills
- William Shunn, proper manuscript format (novel): https://www.shunn.net/format/novel/
- ProWritingAid features and reports: https://prowritingaid.com/features and
  https://prowritingaid.com/features/writing-reports
- On opening pages (practitioner opinion): Renee Fountain, "The Science of
  Rejection: How Agents Decide In the First Ten Pages",
  https://reneefountain.substack.com/p/the-science-of-rejection-how-agents ;
  Hallie Ephron, "7 Reasons Why Your Work May Be Rejected", Writer's Digest,
  https://writersdigest.com/publishing-insights/7-reasons-why-your-work-may-be-rejected-by-hallie-ephron

## How publishers acquire and edit novels

Researched 23 November 2026 to ground the verdict and the Critique. Each claim
is marked by how strong its evidence is: **[R]** scholarly research, **[P]**
professional-body guidance, **[O]** practitioner opinion. Claims marked
*(review)* were read in a review or summary, not in the book itself.

**Acquisition turns mostly on things outside the text.**
- Editors weigh the author's sales record, comparable titles, the author's
  platform and trade buzz; there is no formula, and many bestsellers
  surprised their publishers (Thompson, *Merchants of Culture* [R],
  *(review)*).
- UK commissioning editors describe buying on "love", often "from the first
  page, or the first chapter", in meetings that are "half book club, half
  commercial assessment". Many books are bought for their potential, with the
  author's readiness to be edited part of the decision (Squires 2020 [R], 19
  interviews).
- Publisher and author history predict sales; text quality was not a modelled
  input (Wang et al. 2019 [R]).

**The order of edits rests on professional guidance, not research.**
- The developmental edit comes first and is delivered as a letter that
  "outlines the big-picture issues"; line editing follows "after big-picture
  issues have been addressed"; then copyediting and proofreading (EFA [P]).
- No scholarly study was found that maps the sequence of edits inside a
  publisher; structural editing is deliberately kept out of view (Squires
  [R]).

**How editors deliver feedback** (Editors Canada, *Professional Editorial
Standards* 2024 [P]): queries and letters are clear, succinct and actionable;
query where intent is unclear and keep queries few; explain changes; never
alter the intended meaning; keep the author's voice.

**What the evidence does not support.**
- No peer-reviewed study of agents' decisions or of opening pages deciding
  acceptance was found. The "first pages" convention is interview and
  practitioner evidence.
- Readability scores barely differ between more and less successful novels,
  and simpler syntax correlated with *less* success in one study of
  public-domain books (Ashok et al. 2013 [R], correlational).
- Bestseller-prediction claims (*The Bestseller Code*) are weak.

**What the app does with this**

1. **Macro before micro.** The verdict names stages in editing order, and
   tells the writer to start with structure.
2. **Major issues come first, then other factors, then polish** (revised;
   see the next section). Major: spelling and grammar, character
   disconnects, plot jumps, continuity. A major check at "problem" gives
   "Needs a revision pass". Line-level style checks are polish and never
   block.
3. **The opening checks are a convention.** They count like any other scene
   or structure check; they no longer force a verdict alone, and chapter 1's
   stricter bar was eased (0.75 agent, 0.9 self).
4. **No prediction of acceptance.** The scorecard says it cannot tell whether
   an agent or publisher will take the book.
5. **A model's verdict is one reader's view,** and the scorecard says so.
6. **No readability targets.** Hard-to-read sentences stay an editor aid;
   readability is not a readiness check.
7. **For later pieces** (8.2 editorial letter, P.4 proofreading): a short
   prioritised letter plus passage-anchored notes; queries where intent is
   unclear; every finding actionable, with its evidence.

**Not verified:** Thompson's own text on editing practice; the Chicago Manual
of Style sections on queries and author letters (paywalled); CIEP's fiction
guidance (members only); Greenberg's books on editing (cited via Squires).

**Sources**
- Thompson, J.B. *Merchants of Culture*. Polity, 2010; 2nd ed. 2012. Review:
  https://www.timeshighereducation.com/books/book-of-the-week-merchants-of-culture-the-publishing-business-in-the-twenty-first-century/413351.article
- Childress, C. *Under the Cover*. Princeton UP, 2017. https://muse.jhu.edu/book/56270
- Squires, C. "Sensing the Novel/Seeing the Book/Selling the Goods", in *The
  Novel as Network*, Palgrave, 2020.
  https://www.storre.stir.ac.uk/bitstream/1893/31484/1/Squires%20Sensing%20the%20Novel%20_accepted.pdf
- Wang et al., "Success in books: predicting book sales before publication",
  *EPJ Data Science* 8:31, 2019. https://link.springer.com/10.1140/epjds/s13688-019-0208-6
- Ashok, Feng & Choi, "Success with Style", EMNLP 2013. https://aclanthology.org/D13-1181/
- Editors Canada, *Professional Editorial Standards* 2024.
  https://editors.ca/publications/professional-editorial-standards/fundamentals-editing/
- EFA, editorial services definitions: https://www.the-efa.org/editorial-services-definitions/

## What readers stumble on: the major issues

Researched and verified 23 November 2026, to define the major issues the
scorecard puts first (spelling and grammar, character disconnects, plot
jumps, continuity). Same marks as above. Each source says how it was read,
because several support a narrower claim than they are usually cited for.

**Readers track a few dimensions, and breaks in some cost more than others.**
- Readers follow time, space, causation, the protagonist and their goals
  (the event-indexing model: Zwaan, Langston & Graesser 1995 [R]; reviewed in
  Zwaan & Radvansky 1998 [R], read in full). The 1995 paper's own evidence
  is a task of grouping verbs, not reading times, and the review says the
  five dimensions are not "exhaustive or fixed".
- The reading-time evidence: breaks in time and in cause slow readers
  (Zwaan, Magliano & Graesser 1995 [R], via the review, "partial support");
  shifts of protagonist and time slow readers and lower how coherent the
  text is rated, while the effect of a change of place is weak (Rinck &
  Weber 2003 [R], abstract only).
- Stories are remembered and judged coherent through their causal links
  (Trabasso & van den Broek 1985 [R], secondary sources only).

**A character inconsistency is a conflict with something specific.**
- Readers slow at an action that contradicts a trait stated earlier, even
  several sentences back (Albrecht & O'Brien 1993 [R], secondary sources
  only). Whether an outdated fact still interferes after the text has
  explained the change (O'Brien et al. 1998) is contested (Zwaan & Madden
  2004), so the app only says: check whether the text shows a reason.
- Readers form expectations from specific traits, not general impressions
  (Rapp, Gerrig & Prentice 2001 [R], abstract only).

**A gap is not an error by itself.** Narrative theory treats ellipsis and
withheld information as ordinary, often deliberate devices (Genette;
Sternberg; Malcolm 2018, read in full) [R, theory, not experiment].

**Spelling and grammar errors lower how the writer is judged, in studies of
short texts.** Typos lowered ratings of the writer, more for some readers
than others (Boland & Queen 2016 [R], read in full; emails, not fiction). A
few errors had no effect on judgements of the writer; many did (Kreiner et
al. 2002 [R], abstract). No study of errors in novels was found.

**Continuity is the copyeditor's job, done with a style sheet and
queries.** A fiction style sheet records characters, places and the timeline
(Schneider, *The Chicago Guide to Copyediting Fiction*, 2023 [P], publisher's
description only). The copyeditor checks internal consistency and must
"correct or query" (Editors Canada, *Professional Editorial Standards* 2024,
D2–D3 [P]); fiction may break usual rules on purpose (D1.2).

**Not supported, so not claimed.** That one error "breaks immersion":
Busselle & Bilandzic 2008 propose that perceived inconsistency *may* disrupt
engagement; it is a theoretical paper. That a count of errors predicts how
readers or publishers receive a novel. That a change of place alone is a
problem.

**What the app does with this**

1. **A finding is an instance, never a verdict on the writer.** It quotes
   the passage.
2. **A character disconnect or continuity break quotes both sides**: the
   words in the chapter and the earlier words (or the record) they
   contradict. If either quote can't be found in what the model was shown,
   the finding is dropped.
3. **A plot jump names what broke**: time, cause and effect, or whom we
   follow. A change of place alone is not counted; a marked scene break or
   a gap the reader can fill is not a jump.
4. **Findings are queries.** "Earlier: “…”. … Which is intended?" The app
   doesn't rule on which passage is right, and asks whether a gap is
   intended.
5. **Dialogue and dialect are the writer's choice**; British and period
   spellings can be accepted in Settings.
6. **Spelling and grammar are a major issue only at the "problem" level**
   (many errors), matching Kreiner et al.; a handful doesn't block.
7. **A book-wide style sheet** (`src/ai/story_ledger.py`). As the model
   reads each chapter it also lists the facts that chapter establishes
   (about characters, places, things and the timeline), each with the words
   that establish it. Every later chapter is read against the facts recorded
   before it about the people and things it mentions, so a contradiction
   many chapters apart can be seen. The writer can read the style sheet from
   the Whole manuscript row of the scorecard.
8. **Every Critique report puts findings the same way**
   (`src/ai/editorial_standards.py`): passage, effect, option; a question
   where the author may have meant it; meaning and voice are the author's;
   few, well-chosen points; about the text, never the writer.
9. **Misses are measured, not assumed** (`scripts/measure_misses.py`,
   results in `miss_rates.md`): known mistakes and contradictions are
   inserted and counted as caught or missed, with the rules alone and with
   a model.

**Sources**
- Zwaan & Radvansky, "Situation models in language comprehension and
  memory", *Psychological Bulletin* 123, 1998.
  https://sites.ualberta.ca/~dmiall/Cognitive/Readings/Zwaan_Radvansky_1998.pdf
- Zwaan, Langston & Graesser, "The construction of situation models in
  narrative comprehension", *Psychological Science* 6, 1995.
  https://www.psychologicalscience.org/journals/psychological-science/j.1467-9280.1995.tb00513.x/
- Zwaan, Magliano & Graesser, *JEP: Learning, Memory, and Cognition* 21,
  386–397, 1995.
- Rinck & Weber, *Memory & Cognition* 31(8), 1284–1292, 2003.
  https://link.springer.com/article/10.3758/BF03195811
- Albrecht & O'Brien, *JEP: LMC* 19, 1993. https://doi.org/10.1037/0278-7393.19.5.1061
- Rapp, Gerrig & Prentice, "Readers' trait-based models of characters in
  narrative comprehension", *Journal of Memory and Language*, 2001.
  https://collaborate.princeton.edu/en/publications/readers-trait-based-models-of-characters-in-narrative-comprehensi/
- Trabasso & van den Broek, *Journal of Memory and Language* 24, 1985.
- Busselle & Bilandzic, *Communication Theory* 18, 2008.
  https://doi.org/10.1111/j.1468-2885.2008.00322.x
- Boland & Queen, *PLOS ONE*, 2016. https://pmc.ncbi.nlm.nih.gov/articles/PMC4784893
- Kreiner et al., *Journal of General Psychology* 129, 2002.
  https://doi.org/10.1080/00221300209602029
- Schneider, *The Chicago Guide to Copyediting Fiction*, 2023.
  https://www.press.uchicago.edu/ucp/books/book/chicago/C/bo183690033.html
- Editors Canada, *Professional Editorial Standards* 2024, copy editing.
  https://editors.ca/publications/professional-editorial-standards/copy-editing/
- Malcolm, "Ellipsis, narrative gaps…", *Tekstualia*, 2018.
  https://tekstualia.pl/files/2db2274d/malcolm_d._-_ellipsis_narrative_gaps....pdf

## What a developmental editor's read rests on

Researched and verified 23 November 2026, for the chapter outline, the
editor's whole-book checks, the reader's pull and the editorial letter. Same
marks as above; each source says how it was read. Much of the older
psychology is paywalled: where only the citation was confirmed, the finding
comes from secondary sources and is marked so.

**What a manuscript evaluation is** [P].
- Editors Canada (*Professional Editorial Standards* 2024, appendix, read in
  full): "a systematic examination of the strengths and weaknesses", a
  "detailed memo to help a writer revise", following "a set of headings",
  with "specific guidance about how to revise". For fiction it lists
  characterization, dialogue, setting, plot, structure and believability;
  voice and tone are among what it "can also involve".
- The structural-editing standard itself (Section B) has **no fiction
  checklist**: it speaks of narrative flow, cutting superfluous material and
  filling gaps.
- EFA (read in full): a developmental editor may deliver a manuscript
  evaluation or an editorial letter on big-picture issues and ways to
  address them. CIEP (read in full): a critique covers story, plot and
  structure, character, tension, theme and point of view, as general
  analysis, not every instance.
- Norton, *Developmental Editing*, 2nd ed. (Chicago, 2023; contents page
  only): summarising the content comes before planning the edit. The book
  is mainly about nonfiction; its fiction chapter was not read.

**Outlining what the draft contains.**
- Events with more causal connections are recalled better and judged more
  important than dead ends (Trabasso & Sperry 1985; Trabasso & van den
  Broek 1985 [R], secondary sources only; short simple stories, not novels).
  This does **not** show that a scene with no consequences is bad craft.
- Reverse outlining as a revision technique: writing-centre handouts only
  [O]. No controlled study was found.
- Genette (scene and summary, focalization) and Labov & Waletzky (the parts
  of an oral anecdote) give vocabulary, not evidence about readers.

**Point of view, character, setups.**
- Sentences that keep the established point of view are read faster and
  remembered better than ones that shift it (Black, Turner & Bower 1979 [R],
  secondary sources; sentence-level stimuli, not novels).
- Readers slow at behaviour inconsistent with a character's traits (Rapp,
  Gerrig & Prentice 2001 [R], abstract). Nothing empirical was found on
  character arcs or on characters who drop out.
- Suspense rises when readers believe the paths to a solution are narrowing
  (Gerrig & Bernardo 1994 [R], abstract). **Setup and payoff ("Chekhov's
  gun") is practitioner lore** [O]: no research was found.

**Where readers are held or lost.**
- Transportation and narrative engagement are measured by asking readers
  (Green & Brock 2000; Busselle & Bilandzic 2009 [R], abstracts; the second
  was validated on film and television). Neither can be computed from text.
- Suspense, curiosity and surprise come from the order in which events are
  revealed (Brewer & Lichtenstein 1982 [R], secondary).
- Reading data from one company: readers who stop mostly stop in the first
  chapters (Jellybooks [O], industry data from volunteer readers). The
  often-repeated "90% quit after five chapters" described one title.
- Story-shape studies do not support predicting a novel's success: Reagan
  et al. 2016 measured word sentiment in Gutenberg texts; Toubia et al. 2021
  studied films, television and papers, not novels.

**What models can and can't do with a whole book** [R], as of the models
tested in 2024–25 (newer ones are probably better; not verified):
- Summarising a book in pieces and merging gives coherent summaries (Chang
  et al., BooookScore, ICLR 2024, read in full), but coherent is not
  accurate: 69–91% of claims in such summaries were faithful, the errors
  were mostly about characters' states and events, key events were missing
  from a third to two thirds of summaries, and a model checking its own
  claims did poorly (Kim et al., FABLES, 2024, read in full).
- Judging claims that need the whole novel: the best model got 56% of
  claim pairs right (chance 25%), worse on reasoning across the book and in
  speculative fiction (Karpinska et al., NoCha, EMNLP 2024, read in full).
- Finding planted plot holes: equal to people on very short stories,
  markedly worse on longer ones, and summaries introduced errors of their
  own (Ahuja, Sclar & Tsvetkov 2025, read in full).
- Feedback on flawed short stories was mostly accurate, but "models often
  fail to identify the biggest writing issue" and call flawed stories fine
  (Rashkin et al., ACL 2025, read in full).
- No study compares a model's developmental feedback on a whole novel with
  a human editor's.

**What the app does with this**

1. **The letter follows the evaluation's shape**: what works, the three to
   five most important issues in order, each with where it shows, its
   effect and one option, under the elements Editors Canada and CIEP list
   (`src/ai/editorial_letter.py`).
2. **An outline per chapter, then the whole** (`src/ai/chapter_digest.py`),
   every line tied to words in the chapter; an issue in the letter that
   names no real chapter is dropped.
3. **Every structural finding is a question.** A scene that changes
   nothing, a shift of point of view, an open thread or a character who
   leaves can all be deliberate, and the research is on short texts.
4. **The reader's pull is one model reader's rating**, weighted to the
   first three chapters, and never called a prediction.
5. **The letter says what it can't judge**: the prose itself; whole-book
   judgements as its least reliable part; that finding nothing is not a
   clean bill of health; acceptance, sales, and where real readers stop.
7. **The handover to a human editor is the goal** (`src/ai/editor_pass.py`):
   mechanical work cleared first, queries answered or marked intended, and
   a brief with the style sheet, open questions and deliberate choices.
   Editors Canada's copyediting standard has the editor build a style
   sheet and query the author; the brief hands both over at the start.
6. **Measured, not assumed**: `scripts/measure_misses.py --model --editor`
   runs the checks and the letter on short books with one planted flaw.

**Not claimed:** that the letter equals a developmental edit; that setup
and payoff or reverse outlining are research-backed; that Editors Canada's
structural standard prescribes these checks; anything from the *Chicago
Manual of Style* or from Norton's fiction chapter (not read).

**Sources**
- Editors Canada, *Professional Editorial Standards* 2024: appendix
  https://editors.ca/publications/professional-editorial-standards/appendix/
  and structural editing
  https://editors.ca/publications/professional-editorial-standards/structural-editing/
- EFA, editorial service definitions: https://www.the-efa.org/editorial-services-definitions/
- CIEP, manuscript critique: https://www.ciep.uk/resource/manuscript-critique.html
- Norton, *Developmental Editing*, 2nd ed., 2023.
  https://press.uchicago.edu/ucp/books/book/chicago/D/bo201563215.html
- Trabasso & Sperry; Trabasso & van den Broek, *Journal of Memory and
  Language* 24(5), 1985. doi:10.1016/0749-596X(85)90049-X
- Black, Turner & Bower, *Journal of Verbal Learning and Verbal Behavior*
  18, 187–198, 1979.
- Gerrig & Bernardo, *Poetics* 22(6), 459–472, 1994.
- Green & Brock, *JPSP* 79(5), 701–721, 2000. Busselle & Bilandzic, *Media
  Psychology* 12(4), 321–347, 2009. Brewer & Lichtenstein, *Journal of
  Pragmatics* 6, 473–486, 1982.
- Reagan et al., *EPJ Data Science* 5:31, 2016 (arXiv:1606.07772). Toubia,
  Berger & Eliashberg, *PNAS* 118(26), 2021.
- Jellybooks: https://www.jellybooks.com/about/publishers/completion-rate
- Chang et al., BooookScore, arXiv:2310.00785. Kim et al., FABLES,
  arXiv:2404.01261. Karpinska et al., NoCha, arXiv:2406.16264. Ahuja, Sclar
  & Tsvetkov, arXiv:2504.11900. Rashkin et al., arXiv:2507.16007.

## Outstanding issues

Open as of this version of the plan. Each is handled by the piece or decision
named.

1. **The plan conflicted with itself on removing things.** The declutter pieces
   retired the Style tab, two windows and two Companion sections, including
   sections added recently because they helped. Decluttering now means
   *reorganising*: nothing a writer can do today is taken away, and nothing is
   retired until you have used its replacement on both projects and said so.
   (Rule 11, "Features stay"; pieces 3.2, D.2, D.3, D.4.)
2. **Two live projects were not protected.** No piece said how the two projects
   in use are kept safe while stored data changes. Piece 0.3 adds a safety
   check that runs against a copy of each project and never writes to the
   original. (Rule 11, "Two live projects"; piece 0.3.)
3. **"Not a problem" would not have lasted.** Piece 3.3 relied on the store of
   flag verdicts, which is held in memory only: it is lost when the app closes
   and is not separated by project. Dismissals now get their own per-project
   file. (Piece 3.3.)
4. **Ratings are shared between projects, with nothing to keep voices apart.**
   Rated rewrites are kept in one database for all projects. With two books in
   different voices, one can colour the other's suggestions. Decided: ratings
   stay broad (shared across projects) and are grouped by voice, so a rewrite
   learns from ratings given to writing that sounds like it, whichever
   project they came from. (Phase V.)
5. **Hiding a weak check could change a project you are working in.** P.5 turned
   poor checks off by default. It now changes the default for new projects
   only, and offers the change in existing ones. (Piece P.5.)
6. **Per-project learning.** Acceptance rates, the revision checklist, chapter
   stages, dismissals and readiness results are all kept per project, so the
   two books never share them. (Pieces 1.2, 3.1, 3.3, 4.3.)
7. **The model server is untested against a real server.** It passes its tests
   against a stand-in. To be connected when the machine arrives this week;
   needed before 8.1. The rest of the recent work has been used in the running
   app and works.
8. **The inventory is unverified.** It comes from module summaries. (Piece 0.1.)
9. **Novellas were not mentioned.** A project can hold a main manuscript and
   novellas. Every piece that works per chapter or per book now works per
   manuscript, and nothing may drop a novella. (Rule 11; pieces 1.1, 1.2, 2.1,
   3.1.)
10. **Open decisions** are listed at the end, after the ones now settled.
