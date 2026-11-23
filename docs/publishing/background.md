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
| Writing reports | 27 named reports | About 19 of them in some form | Close. Six are missing (P.2). |
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
| Sentence Structure | Partly: repeated sentence starts (`style_checks`), and sentence-length variety in the Critique (`ProWritingAnalyzer`) |
| Diction | Partly: wordy phrases only |
| Transition, Sensory | **Missing as scans.** The Critique's model prompts ask about forced transitions and scenes with no sensory grounding, but nothing counts them. |
| Pronoun, Alliteration, Homonym, Acronym | **Missing** |
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
