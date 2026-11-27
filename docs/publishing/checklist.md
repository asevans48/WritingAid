# Checklist: how to proceed from here

Written 24 November 2026. It covers what is built and waiting for you, the
decisions that block later work, and the order of the remaining pieces. The
plan, rules and tracker are in [README.md](README.md); this file is only the
order of work. Tick items here as you go.

**Keeping this file current.** Every session that does a piece updates this
file before it stops (the README's *How to work through this plan*, step 3,
and each brief's *When you finish* say the same):

- tick the piece in section 5;
- add to section 1 what the writer should try, as tick boxes under a heading
  with the piece's number;
- add to section 3 any decision it needs;
- correct "Where things stand" below.

The writer ticks sections 1 to 3. A session never ticks those for them.

**Where things stand** (26 November): everything up to and including
H.1, D.4, D.5, P.2b, 4.3 and the chapter's prose profile is **committed**
(d0d347e and 58226e9, after 0733233). **Built since, not committed:**

- **Round 1.** P.6 (LanguageTool's n-gram data, installed, Download /
  Remove in Settings ▸ Language: harder confused words caught 13% → 38%,
  no new false alarms; and a fix: the LanguageTool server now stops when
  the app, a script or a test run ends). P.8 (character analysis: "Across
  the book" on each character, and a scan in the Critique's Character
  check). V.1 (a voice fingerprint on every rating). V.2 (voice groups,
  thresholds calibrated on 64 published books: Born in Blood and Teller
  County form two groups; Tempest has too few ratings yet).
- **Round 2.** V.3 (the model names each new or merged group in the
  background; untried with a real model). V.4 (rewrites learn from rated
  examples in the passage's voice group; "keep this project's ratings to
  itself"). V.5 (managing the groups: Training Studio ▸ Browse rows ▸
  "rated rewrites, by voice"). 6.1 (Read Aloud ▾ → Listen and mark: M
  marks a sentence). 6.2 (marks become 👂 notes and Next-fix cards).
- **Round 3.** D.9's second session (67 more "nothing to do" boxes now a
  status-bar line; 116 in all). D.8's second session (one coloured main
  button and the kit's colours on Plot, Characters, World, Visuals, Video
  Studio, Publishing, Drafts and Print). 0.3's screen check (the safety
  check also opens every screen on a copy, saves it from the window and
  compares). The D.2a design for the One Improve window (reviewed 25
  November: decision 16).
- **Two fixes you asked for** (25 November): Listen and mark reads only
  the highlighted text (the whole chapter when nothing is highlighted);
  pause no longer stutters (the player is stopped and resumed from the
  place, a quarter-second back).
- **D.2b** (25 November): the One Improve window. Suggestions and Overly
  descriptive? open one window with tabs 💡 Suggestions · 📝 Critique ·
  🔍 Expand; the old windows are one tick away (Settings ▸ Features ▸
  Improve window, ticked by default). The right-click is counted 7 / 11
  (was 9 / 13), as decision 16 says; the baseline was lowered to match.
- **D.2c** (26 November): Rephrase joins as the third tab (✨ Rephrase,
  Ctrl+3). Ctrl+R, ✨, the right-click, a style flag's ✨ Rewrite with AI
  and the draft window's Rephrase open the Improve window on it; its 25
  options sit behind ▸ Change options; no "Discard your edit?". Rating
  rows are the same as the old window's (tested column by column). The
  old Rephrase window is behind the same switch. Every D.2 piece is done.
- **8.1a** (26 November): the job-queue design is written (no code) and
  reviewed: its eight questions answered as recommended (decision 17).
- **4.2** (26 November): **dropped at its gate.** The voice measure tells a
  different human author apart (74% of chapters) but not a model's
  rewrites of your own passages (0 of 14 sets caught; they move it about
  0.25, your own chapters differ by up to 0.6). Nothing built; the proof
  is `scripts/voice_drift_gate.py` and the numbers are in the brief's
  *Outcome*. You agreed to drop it (section 3).
- **9.3** (26 November): the submission package, in Publish ▸ Publishing
  (the list's first entry, 📦 Submission package): synopsis, query letter,
  blurb, and readers and comps with where the book sits. Filled in from the
  story without a model; drafts in your voice with one (untried with a real
  model). Drafts kept in `<project>.submission.json` beside the project,
  earlier versions kept. Its four questions are answered (section 3).
- **A fix** (26 November): Expand (Overly descriptive?) showed nothing until
  the model had answered, after the whole Suggestions run when that ran
  first. The word scan (no model, milliseconds) now shows at once, and the
  AI's review takes its place when it comes.
- **Your section 3 answers** (26 November): every open question answered
  (the recommendations, with your changes: retire the old screens only
  once everything is checked; the shared-folder warning should exist).
  The agreed figures are in `screens_baseline.json`.
- **Round 6** (26 November): three small pieces from those answers.
  The grammar check's results no longer reach an editor that is being
  torn down (the abort seen only in tests). Rephrase ratings carry the
  style of the option you rated, and "Auto-detect from text" is back in
  the character-voice list. Save As warns when the folder already holds
  another project and offers a new subfolder.
- **D.10, your request** (26 November, round 7): **built.** One tree in
  the Write screen's left panel holds the main manuscript and every novella
  with their chapters, always shown. Chapters move by drag-and-drop or
  right-click ▸ Move to ▸ (main → novella, between novellas, and back),
  with Undo. The top row of manuscript tabs and Novellas ▾ are gone, one
  switch away (Settings ▸ Features ▸ Manuscript tree). The Write screen
  went from 19 buttons and 29 menu items to 18 and 28; the baseline was
  lowered to match. Its section 3 items are answered.
- **Other formats: planned** (26 November, your request; README decision
  18). The app is to work for video story scripts, podcasts, editorial
  series and journalism as well as novels, keeping every story feature.
  A new phase, **F**, of sixteen pieces is written
  (`pieces/70-…` to `pieces/85-…`) and starts after the final sweep; F.0 is
  a design for your review. The sweep briefs (U.3a, U.3b, 9.1) and rule 11
  have notes so the remaining work does not make it harder. Your answers
  are recorded in section 3, "Other formats".
- **Round 8** (26 November): **U.3a** (the fit-and-scroll sweep of the
  screens used most) is built. Write, the side panel (Companion, Planner,
  Feedback), the Critique in its own window, the stage chooser, the
  manuscript tree and Settings now fit at 1024 × 600 and at 150%. The side
  panel needed 1,094 px and now needs 713: the line under the text no
  longer refuses to shrink. "Add Hierarch" reads "Add Hierarchy". No count
  rose. Left for U.3b: Video Studio (1,407 px wide), which keeps the main
  window from fitting, and World's height. **F.0** (the other-formats
  design) is written and reviewed: its seven questions, the Studio-card
  bug and U.3a's two things were answered on 26 November (section 3).

- **Round 9** (26 November): **the Studio cards fix** (a moved chapter's
  cards, decks and chosen chapter follow its new id after a clash; Undo
  puts them back) and **U.3b** (the fit-and-scroll sweep of the remaining
  screens). The whole main window, Write included, fits 1024 × 600 again:
  Video Studio needed 1,407 px and now 216; the main window 1,415 × 641,
  now 508 × 472; World 677 × 545, now 401 × 170. All 58 screens the
  harness draws pass at all four sizes. Narrow rows now shorten, then wrap
  (your rule): 💡 Fix, ✓ Beat, ✕ in the Companion; ⭐ Best and Save on the
  rating bar; 🎤 Slides, 📑 Export, ✨ Refine in the Studio; ➕ Add in World.
  No count rose. About 80 windows the harness cannot open yet (the Studio's
  editors, the Training Studio's run dialogs) are listed in U.3b's Outcome.

- **Round 10** (26 November): **D.11, the old screens retired** (your
  answer: the four groups work). Gone: the ten-tab mode and Settings ▸ Main
  tabs; the two old analysis windows and "Show in a window (old)"; the old
  Rephrase, Suggestions and Overly descriptive? paths and Settings ▸
  Features ▸ Improve window; the manuscript tab row, Novellas ▾ and
  Settings ▸ Features ▸ Manuscript tree. Every action has a home (the
  capability checklist is in D.11's Outcome). "Move main chapters into
  this novella" now goes through D.10's move: renamed in place, with Undo.
  Your stored settings stay in the file, unread. No count rose; about 1,170
  lines fewer. Then the model queue started (the V.4 real trial, then 7.2).

- **Round 11** (26–27 November): **the model queue** (the app closed, the
  on-device Gemma model, one job at a time; resumed once after the session
  stopped). **V.4's real trial:** 16 of your rated passages, 2 rewrites
  each, with today's examples and with V.4's. Examples in the passage's own
  voice rose from 66% to 83%; voice fit 0.912 → 0.919, which is within
  chance (better 6, same 5, worse 5): V.4 does no harm and does what it was
  built for, but a real gain would need about 100 pairs or your own blind
  ratings. **7.2 built:** tension rated twice per chapter agreed 25 of 25
  (bar: 90% within one point and kappa 0.6), so the Critique's scene
  outline now shows the model's scenes (who, what happens, what it is for)
  and "Tension N of 5: why", and the chart's tension line is joined up. A
  fix to 8.2's outline reader came with it (the model sometimes returned
  the prompt's field names as a fake scene).

- **Round 12** (27 November): **7.2 on Cydonia** (fails the bar on
  readable answers; Gemma passes; section 3) and **7.4, scene markers kept
  beside the text**: right-click a paragraph ▸ More ▸ 📝 Note or scene
  break ▸ Scene break here; a dashed line in the margin; "Use the model's
  scenes" in the Critique's Scene outline; ✕ and Undo; markers follow edits
  and moves; the outline, tension and chart use them; export unchanged
  unless you tick "Mark scene breaks". Your text and its saved files are
  never touched. Then the tension follow-ups started (the app closed).

- **Round 13** (27 November): **the tension follow-ups.** An unreadable
  tension answer is remembered (with the chapter's text, markers, model and
  prompt), so that model isn't asked again until one of them changes. A
  firmer prompt: **Cydonia now passes** (readable 29% → 100%; kappa 0.85 at
  the app's setting), and Gemma still does (kappa 1.00). Gemma is steadier,
  uses more of the scale and is about 6× faster (about 11 s a chapter
  against 70 s); Cydonia reads scenes more finely. The outlines did not
  change. Choose the Critique's model in Settings (section 3).

Tests: 2,088 pass in one run, none fail (after the tension follow-ups' 8).

- **Tried 27 November:** you tried U.3b, D.11, 7.4, the tension follow-ups
  with your chosen model and V.4's addendum: all pass (noted under each in
  section 1; the boxes are yours to tick).

What is waiting for you:

- **Try it (section 1).** Nothing there is ticked yet. The newest items,
  from the end: the fit-and-scroll sweep (U.3a), the manuscript tree (D.10), round 6 (the shared-folder
  warning, the two Rephrase fixes), Expand no longer keeps you waiting (26 Nov fix), the
  submission package (9.3), voice drift's numbers (4.2), Rephrase in the
  Improve window (D.2c), the One Improve
  window (D.2b), the screen check (0.3; run it on both projects), D.9's
  other screens, the model naming groups (V.3), managing groups (V.5),
  rewrites in the same voice (V.4), marks becoming notes (6.2), listen
  and mark (6.1), LanguageTool in full (P.6), voice groups (V.2), character
  analysis (P.8) and the voice fingerprint (V.1); also the two fixes of
  25 November (listen and mark with a highlight; pause). Before them: the
  chapter's prose profile and everything earlier. **Checking all of
  section 1 is what lets the old screens be retired** (section 5).
- **Run the genre script (P.3)** with the app closed:
  `venv/bin/python scripts/genre_baseline.py`, then `--show`.
- **D.2b and D.2c are built** on the reviewed D.2a design (decision 16);
  try them (section 1). Their figures are now the window's baseline.
- **Run the measurement (section 2)** when you can: P.5 waits for it.
- **Decide (section 3).** Every question is answered (26 November),
  recorded under each item (round 6's test-only weak spots: fixed in
  9.1). The boxes are yours to tick.
- **Commit** when you are happy: rounds 1, 2 and 3, the two fixes of 25
  November, D.2b, D.2c, 4.2, 9.3, the Expand fix, the section 3 answers,
  round 6, D.10, the phase F docs, U.3a, F.0's design, the Studio cards fix and U.3b (the commit lines are at the end of
  section 1).
- **Next pieces (section 5): what remains.**
  - Optional, if you want them: more one-look sessions for the Training
    Studio, the assistant and Video Studio's editors (D.8). D.9's boxes in
    separate windows stay as boxes (section 3).
  - Checks: P.5 after section 2's measurement (now that P.2 and P.6 are
    in).
  - Done in round 11 (the app closed, the model): V.4's real trial and 7.2.
    The app can be opened again.
  - Needs a model, for you to judge in the app: try 8.2; try 9.3's model
    tier (section 1); V.3's group names. (4.2 was dropped at its gate.)
  - When the server is connected: 8.1b (8.1a is reviewed: decision 17),
    P.7, 8.3.
  - Done in round 9: the Studio cards fix and U.3b. Optional, no model:
    a second U.3b session for the windows the harness cannot open yet
    (U.3b's Outcome). Also free to run: the query letter addressed to the
    chosen agent (9.3, agreed), and more D.8 sessions (optional).
    The old screens are retired (D.11, round 10). Next for novels: the
    rest of section 1 checked, then 9.1, the last piece for novels.
  - After 9.1: phase F, other formats (section 5, group H). F.0, its
    design, is reviewed: its seven questions are answered (26 Nov,
    README decision 18), so F.1 can start after 9.1.

## 1. Try what is built

Do this in the app, on a real project. Restart the app first.

**The crash fix (0.5)**
- [ ] In Critique ▸ Readiness check, double-click a cell, a chapter name and a
      check name, in the main manuscript and in a novella. No crash.
- [ ] If it crashes: copy the end of `~/.creativeos/crash.log` and say what
      you double-clicked.

**Fix all (3.4)**
- [ ] Hover over a misspelling that appears several times. Tick "Fix all N
      like this" (click the box or its text). The card stays open.
- [ ] Click a fix. Every place changes; the status bar says how many.
- [ ] One Ctrl+Z puts them all back.
- [ ] With the box unticked, a fix changes one place only.
- [ ] "See all N…" lists each place and lets you untick some.

**Chapter stages (3.1)**
- [ ] The Companion's chapter header shows "Stage: … · change". Change it;
      it is still set after a restart.
- [ ] In the scorecard, right-click a chapter name ▸ Move to…; move several
      chapters at once.
- [ ] Tell the assistant "move chapters 3 and 4 to copyedit". Ask for a
      chapter that does not exist: it says "Nothing was moved".

**The next-fix queue (3.2) and Not a problem (3.3)**
- [ ] The Companion's Next fixes shows one fix at a time, and only fixes for
      the chapter's stage.
- [ ] Accept changes the text and shows the next fix; Ctrl+Z undoes it.
- [ ] Skip sends a fix to the back; Back returns to the last one.
- [ ] Shortcuts: accept Ctrl+Shift+Enter, skip Ctrl+Shift+], back
      Ctrl+Shift+[, not a problem Ctrl+Shift+Backspace.
- [ ] Not a problem: the pattern stops appearing in every chapter, and after
      a restart. Undo, or "take that back" in the Critique, brings it back.
- [ ] "Today's three fixes ▸" still opens the old list.

**Style checks in the queue and the menu (D.3)**
- [ ] Repeated sentence starts and long or hard sentences appear in the queue
      at the line stage. "More options" opens the rewrite window.
- [ ] Write menu ▸ Style checks: switching a check on or off keeps the Style
      tab's boxes in step.

**Critique links and its own window (2.5)**
- [ ] In the Critique's issue list, click a flagged word: the chapter opens
      with the passage selected.
- [ ] A repeated finding shows "Each place: 1 2 3 …"; each number goes to its
      own place.
- [ ] A failing check shows "What it looks for: …".
- [ ] Click "⧉ Own window". The Critique opens beside the main window, which
      shows Write. A link in the Critique selects the passage in Write.
      *(Since D.4 the button is gone: use Critique ▸ Critique in Its Own
      Window, or right-click the Critique's tab. See "Fewer top-level tabs
      (D.4)" below.)*
- [ ] Close the Critique window: it is back in its tab, as it was.

**One state file per project (R.7)**
- [ ] Open Teller County and save. Beside `Teller County.writerproj` there
      are now `Teller County.readiness.json` and
      `Teller County.companion_state.json`; the old `readiness.json` and
      `companion_state.json` are still there, unchanged.
- [ ] Chapter stages, dismissed patterns, the scorecard's results and the
      Companion's notes are all as they were.

**The right-click menu (D.1)**
- [ ] Right-click a red-underlined word in Write: its fixes are at the top,
      with the "Fix all N like this" box.
- [ ] Select a sentence and right-click: Cut and Copy are there; "✨ Improve
      this" holds Rephrase, Suggestions and Overly descriptive?.
- [ ] More ▸ holds Add Annotation, Heading Style and Text to Speech.
- [ ] Right-click in a sentence without selecting anything: "✨ Improve this
      sentence" is the first entry (after a flagged word's fixes), with
      Rephrase, Suggestions and Overly descriptive?; choosing one selects
      the sentence and opens the tool.

**Export and import (9.2)**
- [ ] Export ▸ Export Publisher Ready on Teller County. Open it in Pages or
      Word: title page with "about N words", the header "Surname / Title / 1"
      on the first page of text, each chapter on a new page, italics as
      italics (no asterisks), "#" at scene breaks.
- [ ] Export ▸ Export for Kindle; open it in Books. Italics, no asterisks,
      every chapter in the contents.
- [ ] In a scratch chapter with some text, Draft ▾ ▸ Import from Word: it
      asks first; after importing, Ctrl+Z brings the old text back.
- [ ] Import a Word file with italics, save, reopen: the italics are still
      there.

**Scene outline (7.1)**
- [ ] In the Critique, click a chapter's row. Under its stage, click "Scene
      outline (N scenes) ▸": each scene with its length, dialogue share and
      speakers. Click a scene's first words: Write opens there.
- [ ] If a chapter shows one scene but has several, its breaks are not
      marked with a line of *** (or * * *, #) or two blank lines; say how
      you mark them and the splitter can learn it.

**Show less at once (D.7)**
- [ ] Write: the novella buttons are one "Novellas ▾"; the manuscript-draft
      ＋, 🗑 and ↗ are one "Drafts ▾" beside "Editing:"; 📝 adds an
      annotation and its arrow lists them. Ctrl+Shift+N still adds one.
- [ ] Hover a flagged word: fixes, the Fix-all box and Ignore in view;
      "More ▾" shows Ask, Suggest in context and See all on the card.
- [ ] Set a chapter to Copyedit: the Companion opens "Your style sheet" and
      closes Reader's eye and Story memory. Open one by hand: it stays open
      when you come back to the chapter.
- [ ] File ▸ Drafts holds the four items the Drafts menu had.

**Fewer interruptions (D.9, first session: Write, Companion, Critique, main window)**
- [ ] Right-click a blank line ▸ More ▸ … or press Rephrase with nothing
      selected: "Select some text first" appears at the bottom of the
      window, no box to close.
- [ ] Export a chapter or the manuscript: the bottom line says where, with
      **Show file** beside it (opens Finder at the file).
- [ ] Help ▸ Recent messages lists every quiet message of the session.
- [ ] Settings ▸ Features ▸ Messages ▸ "Show a box for every message" on:
      the boxes come back. Off again: quiet.
- [ ] Anything about deleting, moving, replacing or an error still opens a
      box (for example Drafts ▾ ▸ Drop this draft).

**One look (D.8, first session: Write, side panel, Companion, Critique, Settings)**
- [ ] Write: no coloured buttons; ◀ Prev, Next ▶, ＋ ↑ ↓, ⇅ Split View,
      Analyze ▾, Draft ▾ and ◧ Panel are white with a thin border, in the
      same places. With the panel open, ◧ Panel shows a pale tint.
- [ ] Side panel ▸ Style: the counts beside each check are readable blue
      numbers; clicking one still filters the list.
- [ ] Side panel ▸ Companion: "🎯 Find the next fixes" is the one coloured
      button; with a fix showing, ✓ Accept is.
- [ ] Side panel ▸ Planner: with AI set up, "🤖 AI Assistant ▶" is the one
      coloured button; with AI off in Settings, "+ Add" (chapter events)
      is. "Check vs Chapter" is plain;
      "Clear Plot Arc" still stands out in red. Feedback ▸ "▼ Analysis" is
      readable.
- [ ] Critique: "Run Critique" is the one coloured button (your choice);
      Check readiness is plain but the same size. Run a critique: the
      report reads as before.
- [ ] Settings (not drawn by the harness yet, so look closely): "💾 Save" is
      the one coloured button; every page opens and its notes are coloured
      as before (green for good, amber for warnings, red for errors).
- [ ] Open the side-by-side draft view (⇅ Split View): its labels and
      buttons look calm and work as before.

**The app-wide tidy (D.8, your answer: all screens at once)**
- [ ] Plot, Characters, World, the assistant and the other screens: buttons
      that had no style of their own are now white with a thin border
      instead of indigo, at the same size and in the same places.
- [ ] In a dialog, the OK/Save button (the one Enter presses) is still
      coloured.
- [ ] Buttons that set their own colours (red for removing, a few green
      ones) are unchanged; D.8's later sessions go through those.

**Missing reports (P.2a)**
- [ ] Write ▸ ✓ Checks ▸ Style checks: four new switches, unticked: Few
      transitions, Pronouns, Alliteration, Acronyms. The Style tab has the
      same four, with no count beside them until ticked.
- [ ] Tick each (with Style highlighting on) on a chapter you know: are the
      flags ones you would want to see? Note any that are wrong under
      P.2a's *Review notes*.
- [ ] Few transitions ticked: the Style tab's summary shows "transitions
      in N% of sentences".
- [ ] Acronyms: one written two ways (F.B.I. and FBI) offers the form you
      use most; "Fix all N" makes the chapter consistent. An acronym you
      spelled out earlier in the chapter is not flagged.
- [ ] Companion ▸ Find the next fixes, with a chapter at the line stage:
      flags of a ticked new check are in the queue; unticked, they are not.
- [ ] Restart the app: the four are off again (no style switch is
      remembered; see section 3).
- [ ] With the app closed, run
      `venv/bin/python scripts/score_checks.py --languagetool` to add the
      four rows to check_scores.md.

**Mark as intentional (4.1)** (run the safety check from 0.3 first: this
writes the readiness file and adds style sheet rules)
- [ ] In Write, right-click a flagged word you meant (a fragment, dialect, a
      repeated word): "📌 This is intentional" is after Ignore. Choose it:
      the underline goes, and the status line says what went into your style
      sheet.
- [ ] Open another chapter with the same word or phrase: not flagged there
      either. Restart the app: still not flagged.
- [ ] Side panel ▸ Companion ▸ Your style sheet: the line is there.
      Double-click it to reword it. Delete it: the flag comes back.
- [ ] Critique ▸ a chapter with a query (point-of-view slip, plot jump):
      "That's intended" now also adds a line to your style sheet; "take that
      back" removes both.
- [ ] Companion ▸ Find the next fixes ▸ Not a problem: the status line now
      also offers "It's intentional: add it to my style sheet". Undo after it
      takes back both.
- [ ] Save the editor's brief: each quirk is listed once under "Deliberate
      choices", and your own notes appear with their text.

**Draft beside plan (7.3)** (no model; run the safety check from 0.3 first:
a correction writes the readiness file)
- [ ] Critique ▸ a chapter whose outline in the side panel has planned
      events. The closed "Scene outline (N scenes) ▸" line now says how many
      planned events are not drafted and how many scenes are not in the plan.
- [ ] Open it: under each scene, "Plan: … (suggested)" or "Not in the
      plan". Below the scenes, "Planned, not found in the draft". Are the
      suggestions right? It matches by shared names and words, so a plan
      worded very differently from the draft gets fewer matches (it should
      not get wrong ones); say which it got wrong.
- [ ] Click "change" beside a scene: tick the events it holds, or "Not in
      the plan". It now says "(yours)". Restart the app: still yours. "Use
      the suggestion" in the same menu goes back.
- [ ] The small chart under it: every scene of the book, the chapter shown
      in colour, bars for words per scene and a line for dialogue share.
      Without a model it is pacing, not tension (tension waits for 7.2).
- [ ] A chapter with no planned events says so and still shows the chart.

**Every measure compared with the genre (P.3)** (no model; nothing
changes until you build the figures, and building them reads only the
books already downloaded)
- [ ] Before building anything: Critique ▸ Check readiness gives the same
      cells as before (the fixed figures are unchanged without genre data).
- [ ] With the app closed, run `venv/bin/python scripts/genre_baseline.py`.
      It lists each genre with its book count; a genre with fewer than five
      books says "too little data". Most genres list 5 to 15 Gutenberg books
      in the Training Studio, but only the ones you have downloaded count
      (fantasy lists only 3, so it can never qualify as things stand).
      `--show` prints what is stored.
- [ ] Set the Prose Profile's genre to one with enough books. Check
      readiness: the scorecard's note says once, that day, "Now compared
      with published … (N books) rather than fixed figures", and names any
      check that is now stricter.
- [ ] Click an Adverbs or Passive voice cell: the issue list says "Adverbs
      18 per 1,000 words; published thrillers 6 to 15 per 1,000 words
      (12 books)". Pacing shows sentences, dialogue and readability beside
      the genre; Chapter length and Sentence variety use the genre's range.
- [ ] A genre with too few books: the same cells say "too little data to
      compare (N books; 5 needed)" and keep the old figure.
- [ ] Do the ranges look right for your genre? They come from
      public-domain books (19th and early 20th century), not contemporary ones; say if a
      figure is off for books like yours.

**Retire the trial screens (D.6)** (no model needed; nothing stored changes)
- [ ] Open a chapter and the side panel: three tabs, Planner, Feedback,
      Companion. No Style tab.
- [ ] ✓ Checks ▾ → Style issues panel…: the Companion opens on Next fixes,
      and the card steps through **every style issue in the chapter**, in
      order, whatever the chapter's stage. The first time only, a line says
      where the Style tab went. Accept is the old Fix, 💡 More options… the
      old ✨ Rewrite with AI, Not a problem the old Ignore (Undo puts it back).
- [ ] On a card, "Only Adverbs" (or whichever check) steps through that
      check's issues alone, as clicking a count in the Style tab did.
      "Check again" goes back to the chapter's queue.
- [ ] ✓ Checks ▾ → Style checks: the first line is the old tab's summary
      ("12 issues · 4.1/1,000 words", and the transitions share when Few
      transitions is ticked); below it the switches, each with its count.
- [ ] Ticking Style in ✓ Checks ▾ opens the same style list, as it used to
      open the Style tab.
- [ ] With a model set up: "The three that matter most" (a link on the
      card's status line) shows the model's three picks on the card, with
      rewrites in your voice. Without one the link is not shown.
- [ ] On any card, "✎ edit" (after the before-and-after) lets you change
      the suggestion, or the sentence when there is none, before Accept.
- [ ] Critique ▸ a scorecard cell ▸ work through them in the Companion: the
      fixes now show on the card ("From the scorecard: …"), the first one
      selected in the text.
- [ ] A rewrite with a warning ("⚠ This rewrite …") shows the warning on
      the card, as the old list did.

**Contact details on the title page** (9.2 addendum; no model needed; stored once for all your books)
- [ ] Publishing tab ▸ Publishing Actions: beside the publishing route,
      "Your details for the title page": Name, Pen name, Phone, Email,
      Address. Type in them; there is no Save button, each is kept as you type.
- [ ] Settings ▸ 👤 Your Details shows the same fields (not the pen name,
      which belongs to the book). Change one there and press Save; the
      Publishing tab shows the change. Cancel leaves it as it was.
- [ ] Export ▸ Export Publisher Ready. Top left of the title page, single
      spaced: your name, each address line, phone, email. The title is still
      about halfway down.
- [ ] With a pen name: "A Novel by <pen name>" and the header "Pen-surname /
      Title / 1"; your real name stays top left. With no pen name, the byline
      is your name.
- [ ] Leave a field empty (say phone): it is simply left out, no blank line.
- [ ] The other project: the contact details are already there (they are
      yours, not the book's); its pen name is its own.

**Remembered style switches** (P.2a addendum; no model needed; per project)
- [ ] Open an existing project: ✓ Checks ▾ ▸ Style checks shows the same
      ticks as before (Few transitions, Pronouns, Alliteration, Acronyms
      unticked), Style highlighting off.
- [ ] Tick Pronouns, untick Adverbs, switch Style on. Quit and reopen the
      app (or switch chapters): the ticks and Style are as you left them,
      and the highlighting shows them.
- [ ] Open the other project: its ticks are its own, untouched by the first.
- [ ] File ▸ New Project, then a chapter: under Style checks, only the
      checks that meet four in five are ticked (Weak intensifiers, Wordy
      phrases, Hard-to-read sentences, Pronouns, Acronyms, Your style
      sheet); Spelling, Grammar and Overused words are on. Save it, quit,
      reopen: still the same. Your existing projects keep their ticks.
- [ ] Spelling, Grammar and Overused words are remembered the same way.
      Show highlights, Re-check as I type, Mode and Focus are not (they
      start as before).

**CONLIT sentence length (P.3)** (no model; nothing changes until you re-run the script)
- [ ] Check CONLIT is where the app looks: `~/.creativeos/conlit/CONLIT_META.csv`
      (or the path written in `~/.creativeos/conlit_path.txt`). If it is
      elsewhere, add `--conlit /path/to/CONLIT_META.csv` to the next command.
- [ ] With the app closed, re-run `venv/bin/python scripts/genre_baseline.py`.
      Near the top it says "CONLIT: N books from …" (not "not found").
- [ ] Then `venv/bin/python scripts/genre_baseline.py --show`. Each genre
      ends "sentence length from: …". Mystery, science fiction and romance
      should say "CONLIT (contemporary, CONLIT, … books)", literary
      "CONLIT (contemporary historical fiction, CONLIT, … books)"; the rest
      "Gutenberg books measured by the app". Do the CONLIT ranges (in the
      app's words per sentence) look right for books like yours?
- [ ] In the same output, the "Check:" line: median characters per token
      near 4.5 (and word length near 3.7) means CONLIT counts punctuation as
      tokens, as assumed. Near 5.3 (and 4.2) means it does not: tell the next
      session, and the conversion (÷ 1.12) should be dropped.
- [ ] A project whose genre is mystery, science fiction, romance or literary:
      Critique ▸ Check readiness ▸ Pacing for the genre says "Sentences …
      words; published mysteries … to … words (contemporary, CONLIT, …
      books)". The other measures still give their Gutenberg book counts.
- [ ] The first check that day says once, in the grey line under the
      verdict, that sentence length is now compared with contemporary books.

**The writing habit (H.1)** (no model; nothing changes until you set a goal,
apart from one link; the record is new, `~/.creativeos/writing_habit.json`,
so run the safety check from 0.3 first and take a checkpoint)
- [ ] Open a chapter with no goal set. "Where you left off" in the
      Companion shows what it did before, plus one link, "Set a daily goal…".
- [ ] Click it, set words a day and/or words a week, OK. The line now reads
      "Today: N of GOAL words · this week N of GOAL · N days in a row", and
      the link becomes "Your writing record…".
- [ ] Your days from before H.1 are there: open "Your writing record…" and
      check that the days you wrote in recent weeks are shaded (only words
      added were kept before H.1, so a cutting-only day from before will not
      show).
- [ ] Type a few sentences and save (or switch chapter). The line's
      numbers go up after the save.
- [ ] Delete a paragraph and save. The streak still counts today (cutting
      is writing); in the record window, today shows the words cut.
- [ ] Paste a long passage (over 300 words) and save. In the record window
      it is listed as "pasted or imported", not as words added, and does not
      count toward the goal. On a day with only a paste, the streak does not
      grow.
- [ ] Reach a goal: one line in the status bar, "Daily goal met: … words"
      (or the weekly one). No box.
- [ ] Write in both projects on the same day. The streak counts the day
      once, and today's words are the two projects' together; clicking
      today in the record window lists both projects and their chapters.
- [ ] In the record window: the 12 weeks run left to right, Monday at the
      top; clicking a day lists what you worked on; "Goals…" changes the
      goals; it fits at your smallest screen.
- [ ] Settings ▸ ✨ AI Features ▸ Writing habit shows the same goals and
      the nudge switch. Setting a goal to "No goal" there takes the line
      away again.
- [ ] The nudge appears only after 7 writing days of revising with almost no
      new words on an unfinished novel or novella (no chapter given a
      stage). If you see it: "Keep revising" closes it for at least 7 more
      writing days; "Stop these nudges" turns it off and the Settings switch
      turns it back on; "Go to the next chapter" opens the chapter after the
      one you last worked on.

**Fewer top-level tabs (D.4)** (no model; nothing in your projects
changes; three new window settings, all in the file that already keeps
window positions)
*Your note, 26 Nov: you have been testing and using the five tabs and they
work well. Tick the items below as you confirm each; then the old ten tabs
can go in "Retire the old screens".*
*Needed before the old screens retire (26 Nov). Your answer, 26 Nov: "everything is working" (all of this group), so retirement can start; the boxes stay yours to tick.*
- [ ] The main window has five tabs: Write · Story · Revise · Publish ·
      Studio. Write and Publish look exactly as before (no second row of
      tabs). Hovering Story, Revise or Studio lists the screens inside.
- [ ] Story holds Plot, Characters and World; Revise holds Critique, Prose
      Profile and Attributions; Studio holds Visuals and Video Studio, each
      under its old name. Every screen works as it did.
- [ ] Open Characters, then Write, then Story again: Story opens on
      Characters. Restart: the app opens on Write, and Story still opens on
      Characters.
- [ ] Each way in still lands on the right screen: Critique ▸ Open Critique
      Tab and Critique Current Chapter (Revise ▸ Critique); a Critique
      link, Go to line, an assistant passage link, an annotation in
      Attributions, and "📝 Open in writer" in Video Studio (all to Write).
- [ ] Right-click a group's tab, e.g. Story ▸ "Open “Story” in Its Own
      Window" (Multi-Window Mode does not need to be on). The first time it
      sits beside the main window; the Story tab says "Story is open in its
      own window. Show it · Bring it back here". Both links work.
- [ ] In that window, right-click Characters ▸ "Open “Characters” in Its
      Own Window": Characters gets a window of its own. Right-click another
      of its tabs ▸ "Bring “Story” Back to the Main Window".
- [ ] Right-click a screen's tab inside a group (e.g. Revise ▸ Attributions)
      ▸ Open in Its Own Window. Choosing Attributions again from the main
      window raises its window. Close it: it is back in its tab.
- [ ] Move a window somewhere, close it, open it again: it comes back
      where you left it (also after a restart).
- [ ] The Critique: Critique ▸ "Critique in Its Own Window" works as
      before (it opens where you last left it), and the menu entry then
      reads "Bring the Critique Back to Its Tab". The "⧉ Own window" button
      on the scorecard is gone.
- [ ] View ▸ Multi-Window Mode: switching it on says to right-click a tab;
      switching it off brings every window back.
- [ ] Settings ▸ ✨ AI Features ▸ Main tabs: untick "Group the tabs into
      five" and Save. The ten tabs are back at once, in the old order,
      still showing the screen you were on. Tick it and Save to return.
- [ ] At your smallest screen, a grouped screen (e.g. Story ▸ Plot) still
      fits: the second row of tabs takes about 28 px.

**Analyses as Critique reports (D.5)** (run the safety check from 0.3 first:
critique history and saved critiques gain new keys; nothing in your
projects changes. With a model, run it with the app's model as usual.)
*Needed before the old screens retire (26 Nov). Your answer, 26 Nov: "everything is working" (all of this group), so retirement can start; the boxes stay yours to tick.*
- [ ] Write ▸ 🔍 Analyze ▾ still lists the same entries. Choose "Prose —
      tone, style && voice": the app switches to Revise ▸ Critique (or
      raises the Critique's own window if it is out), runs, and opens on the
      "Prose profile fit" tab with the same sections the old window had.
- [ ] Do the same for Promises, Characters (two tabs: Character check and
      Characters), Worldbuilding, and Plot && pacing (Plot vs plan, Plot,
      Pacing). Each result is as good as the old window's, or better; say
      which is weaker if one is.
- [ ] "Writing hints" now gives hints (what works, quoted hints, one thing
      to try) instead of "will be integrated soon".
- [ ] Rate a report (the rating bar, a chapter's rating, 👍/👎 on a
      finding); Save Critique, then Load Critique: it comes back.
- [ ] Click a "↗" after a quote: Write opens with the passage selected.
- [ ] On the tab: "Copy" copies the report; "Run again" runs it again;
      "Show in a window (old)" opens the old window (during the trial).
- [ ] Run the same analysis twice: the second shows "Progress since the
      last critique"; a full "Critique this chapter" is not mixed with it.
- [ ] With AI switched off (or no model), each entry says so in one line
      on its tab and shows the scan; no empty window.
- [ ] While a critique runs, an Analyze ▾ entry says to wait or press Stop.

**More missing reports (P.2b)** (no model needed; nothing stored changes
except the ticks you make, as with P.2a)
- [ ] Write ▸ ✓ Checks ▾ ▸ Style checks: four more switches, unticked in
      your two projects: Homonyms, Sensory detail, Sentence structure,
      Vague words. Each shows its count for the chapter even while off.
- [ ] Homonyms ticked (with Style highlighting on): type "She took a sneak
      peak" and "He gave the horse free reign". Each is flagged, and the
      card offers "peek" / "rein" for that one place. There is **no** "Fix
      all N like this" box on a homonym, even when it appears twice.
- [ ] Homonyms on a chapter you know: does it flag anything that is right?
      (It should leave "the peak of the hill", "rain poured over the roof",
      "couldn't bear it" alone.) Note any wrong flag under P.2b's *Review
      notes*.
- [ ] Sensory detail ticked: the Style checks summary at the top of the
      submenu adds "senses: sight N%, sound N%, …" for the chapter. A long
      paragraph of pure telling is tinted; a summary you meant as summary
      may be too (that is why it is off).
- [ ] Sentence structure ticked: four or more sentences in a row of about
      the same length, or three in a row opening with an -ing phrase
      ("Turning, she …"), a "when / as" clause, a preposition or an -ly
      word, are tinted. Are they ones you would change?
- [ ] Vague words ticked: "stuff", "kind of", "all sorts of things", "or
      something", "nice", "aspect" … are marked in narration, never inside
      quotation marks. A first-person narrator's voice will draw some you
      meant.
- [ ] A **new** project starts with Homonyms ticked; the other
      three are unticked. Your two projects keep their ticks.
- [ ] Each ticked check's flags reach the Companion's next-fix queue at the
      line stage and its list of every style issue.

**Checks earn their place (4.3)** (run the safety check from 0.3 first:
each project's readiness file gains an `"outcomes"` key; nothing else
changes. No model needed.)
- [ ] Work through a chapter on the Companion's Next fixes card: Accept,
      Skip, Not a problem. Then Revise ▸ Critique, hover a check's column
      heading: it ends "Fixes accepted here: N of M (x%) …" for this book.
      Your other project shows its own figures, not these.
- [ ] Not a problem, then Undo at once: the answer is not counted (the
      figure does not move).
- [ ] "Fix all N like this" on a misspelling counts as N accepts under
      Spelling and grammar left.
- [ ] Right-click a flag ▸ 📌 This is intentional, or That's intended in
      the Critique: counted once, as "not a problem or intended".
- [ ] Turn down a check's fixes about 20 times, accepting few (Weak
      intensifiers is the quickest). At the answer that tips it, the card
      says it is toned down and offers "Switch it off · Keep it as it was".
      Nothing is switched off until you click: ✓ Checks ▾ ▸ Style checks
      still has it ticked.
- [ ] Toned down: its findings come after the others of the stage on the
      card ("toned down for this book: bring it back"); its Critique column
      is fainter, and the tooltip says why; its details below the grid say
      why, with "Bring it back". ✓ Checks ▾ ▸ Style checks shows
      "· toned down" after its name, and each switch's tooltip gives its
      rate.
- [ ] Bring it back (card or Critique): it is drawn as before and back in
      its place; the tooltip still has its counts.
- [ ] Switch it off from the card: the check's tick goes in ✓ Checks ▾ ▸
      Style checks, stays off after a restart, and can be ticked again.
      Spelling and overused words are never offered off.

**The chapter's prose profile (your request, 25 November)**
- [ ] Open a chapter in Write, then the Prose Profile tab (📊 Revise). Below
      the targets, "This chapter: …" lists sentence length and variety,
      dialogue, adverbs, passive voice, readability and length, each beside
      its target for your genre (published books where the app has figures,
      else its genre guide), with ✓, ▲ or ▼.
- [ ] Change the Genre field: the measures follow a moment later, before you
      save. Open another chapter and come back: it shows that one.
- [ ] "Full review in the Critique" runs the Prose profile fit report on the
      chapter (tone, style and voice; needs a model). "Send the summary to the
      chat" puts the same summary in the AI chat.
- [ ] In the AI chat, type "prose profile" (or "summarise my prose", "how
      does this chapter compare to the genre?"): the summary comes at once,
      with no model. "Review my prose" gives the summary and starts the full
      report in the Critique. "Critique this chapter" still runs the full
      critique, as before.
- [ ] Ask the chat about your sentence length or dialogue: it now knows the
      chapter's figures.
- [ ] On a small window, the Prose Profile tab scrolls.

**A voice fingerprint on every rating (V.1)**
- [ ] Open the app and wait about a minute: a one-time copy of your ratings
      store appears beside it, `~/.creativeos/rephrase_history.db.before-voice`
      (about 1.9 GB), and the terminal says "[voice fingerprint] … rating(s)
      fingerprinted".
- [ ] Run `venv/bin/python scripts/check_project_safety.py --stores-compare
      before.json`: "stores intact", with one new table, `voice_fingerprints`.
- [ ] Rate a rewrite in Rephrase: it saves as before, with no delay.
- [ ] Quit within a minute of opening and reopen: nothing is lost, and the
      fingerprinting finishes on a later start.

**Character analysis (P.8)**
- [ ] Story ▸ Characters → a main character → open **Across the book**
      (under Personality Arc). The chapters listed are the ones they appear
      in; coming back to that character, it opens at once.
- [ ] A character who disappears for a stretch: "⚠ Away for N chapters"
      names the right chapters; clicking a chapter opens it in Write at the
      passage.
- [ ] A character with a lot of dialogue: if a chapter is marked as a
      change in their speech, is it a real one, or a line the scan gave to
      the wrong speaker?
- [ ] Restart: the section is open or closed as you left it.
- [ ] With a model: "Ask the model how … changes across the book" answers
      in the section while you keep working. With AI off, it says the arc
      needs a model.
- [ ] Write → 🔍 Analyze ▾ → Characters on a chapter where someone returns
      after an absence: the Character check report shows "Across the book
      (a scan)", and its ↗ links open the passages.

**LanguageTool in full (P.6)**
- [ ] Settings ▸ Language: "LanguageTool Extra Data" shows "~9.0 GB
      download, ~15.4 GB on disk", "✓ Installed" and **Remove**.
- [ ] In a chapter, type "Don't forget to put on the breaks." and "She was
      quiet happy.": both are flagged, offering brakes and quite.
- [ ] Grammar flags work as before, and "Fix all" is never offered for
      confused words.
- [ ] Optional: Remove (confirm): the button becomes Download and those two
      sentences are no longer flagged. Download again (2–3 minutes) and
      watch the progress bar; it carries on if Settings is closed.
- [ ] Quit the app, then run `ps aux | grep languagetool-server`: no
      server is left from that run.

**Voice groups (V.2)** (nothing to see on screen until V.5)
- [ ] Start the app and wait about a minute (V.1 copies and fingerprints
      first): `~/.creativeos/voice_groups.json` appears, with two groups,
      Born in Blood and Teller County.
- [ ] `venv/bin/python scripts/voice_thresholds.py --writer` prints the
      calibration table and your two projects' separation (about 1.40,
      well apart), and says a second rebuild gives the same groups.
- [ ] The app opens at its usual speed; the grouping runs in the
      background.

**Listen and mark (6.1)**
- [ ] Write → 🗣 Read Aloud ▾ → 👂 Listen and mark: the chapter is read
      sentence by sentence, the one being read highlighted in yellow.
- [ ] Space pauses and resumes (or click the Read Aloud button); it carries
      on from the same sentence.
- [ ] M marks the sentence being read (violet, underlined; the button says
      "1 marked"); M again on it unmarks it.
- [ ] Esc or ⏹ Stop reading stops it; the highlight goes, and M and Space
      type normally again.
- [ ] Highlight a few sentences, then Listen and mark: only those are read
      and only those can be marked; it stops at the end of the highlight,
      and your highlight comes back. With nothing highlighted, the whole
      chapter is read from the top. *(Fixed 25 Nov: a highlight used to be
      ignored.)*
- [ ] Read Aloud ▾ → Marks in this chapter: each mark listed; choosing one
      selects its sentence. Edit a marked sentence: the list says "(the
      text has changed)" and keeps the mark.
- [ ] With a neural voice (Kokoro, Chatterbox, VibeVoice): is the pause
      between sentences acceptable?
- [ ] After listening, the text and Undo are unchanged.

**Marks become notes (6.2)**
- [ ] Listen and mark two or three sentences, then stop: each is a 👂 note
      in Companion › Notes as you write ("Marked while listening: …").
- [ ] Select one ▸ 💡 Suggest fix: Suggestions opens on that sentence.
      Accept a rewrite: the note goes, and stays gone after reopening.
      Suggest fix again and cancel: the mark stays.
- [ ] Chapter at Line stage ▸ 🎯 Find the next fixes: the marks are near
      the front. Skip one: it comes back at the end. More options… or ✎
      edit and Accept: cleared from both places.
- [ ] Not a problem on a mark: only that mark goes; similar sentences are
      still flagged elsewhere.
- [ ] Edit a marked sentence by hand: the note says "(the text has
      changed)" and stays until Dismiss.
- [ ] At Copyedit stage, the marks aren't in the queue but are still in
      the notes.

**Rewrites learn from the same voice (V.4)** (after V.2's groups exist:
start the app once and wait a minute)
- [ ] Rephrase a passage in Teller County, then hover the options list: it
      says the examples came "from your voice group …" (the first-person
      one). In Born in Blood it names the third-person group.
- [ ] Rephrase in Tempest: "from all your ratings" (too few ratings yet).
- [ ] Suggestions: after a result, hover a rating button; its last line
      says where the examples came from.
- [ ] With V.5's switch: turn on "Keep this project's ratings to itself"
      for Teller County, rephrase in Tempest, and check the console's
      `[examples]` line uses none of Teller County's. Turn it off again.
- [ ] With a model (app closed for sessions): rewrite the same few
      passages before and after, and compare the voice fit.

**Manage ratings by voice (V.5)**
- [ ] Training Studio ▸ 🔎 Browse rows… ▸ Source "rated rewrites, by
      voice": your groups, each with its projects, "one project" or how
      alike, and rating counts; Tempest under Unsorted with how many more
      rated passages it needs.
- [ ] Type a phrase from a rewrite in Search: only that rating shows.
- [ ] Right-click a group ▸ Rename…, then Rebuild the groups: the name
      stays.
- [ ] Right-click a project ▸ Move to another group (📌 appears); Rebuild;
      it stays. Ctrl+Z puts it back.
- [ ] Select two groups ▸ Merge: if the voices differ it asks first; Undo
      splits them back.
- [ ] Right-click a project ▸ Keep this project's ratings to itself: 🔒
      appears; untick it or Undo.
- [ ] Open a project, right-click a rating ▸ Change rating, then Remove
      this rating… (asks first; only that one goes).
- [ ] Switch Source back to "All": the table and its buttons are as before.
- [ ] Rule 15: run the safety check on both projects and the stores
      comparison before and after trying these.

**The screen check (0.3)**
*Needed before the old screens retire (26 Nov). Your answer, 26 Nov: "everything is working" (all of this group), so retirement can start; the boxes stay yours to tick.*
- [ ] `venv/bin/python scripts/check_project_safety.py "<path to Adelphus -
      Born in Blood.writerproj>"`: ends "RESULT: safe", with a line
      "screens: opened N on the copy …" and "original untouched".
- [ ] The same on Teller County: 2 manuscripts (the empty main one and
      the novella), no PROBLEM lines.
- [ ] Note each project's screen count and result in the table at the end
      of piece 0.3's Outcome.
- [ ] Open the app as usual: chat input size, Plot's collapsed sections and
      window sizes are as you left them.

**Fewer interruptions, the other screens (D.9, second session)**
- [ ] Video Studio: Deck or Stitch on a scene with nothing yet: a
      status-bar line, not a box.
- [ ] Characters: Strengthen with no project open: a status-bar line; the
      Strengthen report itself is still a box.
- [ ] Worldbuilding builders: Edit or Remove with nothing selected: a
      status-bar line.
- [ ] Chapter editor: Read aloud on an empty chapter: a status-bar line;
      Help ▸ Recent messages lists it.
- [ ] Training Studio and any editor dialog: messages still open a box.

**One look, the other screens (D.8, second session)**
- [ ] Story ▸ Plot: "➕ Add Event" is the only coloured button; each other
      tab has its own coloured ➕ Add; Discuss with AI has a coloured Ask.
- [ ] Story ▸ Characters: "Add" coloured, Generate plain; with nothing
      selected, the right side shows one quiet line.
- [ ] Story ▸ World: in Factions, Star Systems, Power Hierarchies and Maps,
      only the Add button is coloured.
- [ ] Studio ▸ Visuals: "Generate Image" coloured (scroll down to it).
- [ ] Studio ▸ Video Studio: "➕ Add" coloured; in a card's conversation,
      Send coloured, Apply Last plain.
- [ ] Publish: "Add" coloured; the empty right side reads "Add or select
      an agent/publisher", centred.
- [ ] Write ▸ Drafts ▾ (the Drafts panel): 💾 Save coloured, Close plain.

**The model names the groups (V.3)**
- [ ] With your on-device model loaded (use Rephrase once first), open
      Training Studio ▸ 🔎 Browse rows… ▸ "rated rewrites, by voice":
      within a minute or so each group shows "Name — one line"; hovering
      shows the measured description.
- [ ] Rename a group, then Rebuild the groups: your name stays.
- [ ] Merge two groups the model named: the result is named afresh
      shortly after. Merge one you named: it keeps your name.
- [ ] Rephrase while the groups view is open: Rephrase isn't slowed;
      naming waits its turn.
- [ ] With no model (or AI off): plain descriptions, no errors.
- [ ] If "The model reads … as one voice. Merge them?" appears: Decline
      and it stays gone; Accept merges (with the usual warning if the
      voices differ).

**Two fixes you asked for (25 November)**
- [ ] **Listen and mark with a highlight:** highlight a few sentences, then
      Read Aloud ▾ → 👂 Listen and mark. Only those sentences are read and
      can be marked, it stops at the end of the highlight, and your
      highlight comes back. With nothing highlighted, the whole chapter is
      read from the top.
- [ ] **Pause no longer stutters** (Kokoro, and every voice that plays a
      sound file: Chatterbox, VibeVoice, Edge, the basic Mac voices). Read
      Aloud, then ⏸ Pause: silence, with no looping scrap of sound.
      ▶ Resume carries on from where it stopped, a quarter-second earlier
      so no word is clipped. Also try Space while listening and marking,
      and pausing in the short gap between paragraphs.

**The One Improve window (D.2b)**
*Needed before the old screens retire (26 Nov). Your answer, 26 Nov: "everything is working" (all of this group), so retirement can start; the boxes stay yours to tick.*
- [ ] Highlight a sentence or two, right-click ▸ ✨ Improve this ▸ 💡
      Suggestions…: one window, "Improve — …", with tabs 💡 Suggestions ·
      📝 Critique · 🔍 Expand. Suggestions runs at once; the versions list,
      Your version, the changes and the rating row are below the tabs.
- [ ] Click 📝 Critique: the critique is there with no second wait (same
      model call). Click 🔍 Expand: the overly descriptive statements are
      there too, also without a new wait.
- [ ] Right-click ▸ 🔍 Overly descriptive?…: the same window opens on
      Expand. Apply an expansion with **Apply to passage**: "Your text,
      expanded" appears at the top of the versions. Rate it (it can be
      rated now), then ✓ Accept: the passage changes in the chapter, and
      Ctrl+Z undoes it.
- [ ] Edit a version in Your version (✏ edited shows), pick another
      version, come back: your edit is still there, with no question.
      ↺ Reset brings the original back.
- [ ] Rate a suggestion, use 🚫 Avoid a phrase… on a selected phrase, and
      Talk it through ("make it darker"): new versions go to the top.
- [ ] From the Companion: the next-fix card's 💡 More options… and a
      note's 💡 Suggest fix open the window on Suggestions with Focus
      filled; accept from any tab and the note or fix clears. The
      Companion's Expand… and the Critique's "Ways to expand it…" open it
      on Expand.
- [ ] Keys: Ctrl+1 / Ctrl+2 / Ctrl+4 switch tabs, Ctrl+Return accepts,
      Esc closes, Return in Focus regenerates (and does not accept).
- [ ] On the small laptop screen (1024 × 600): the window fits, the middle
      scrolls, Close and ✓ Accept stay in view. Talk it through is a
      closed section there; on a wide window (drag it past 1,200 px) it is
      a column beside Your version.
- [ ] With AI off: Suggestions says there is no model and links to
      🔍 Expand, which shows the word scan.
- [ ] Settings ▸ Features ▸ Improve window: untick it, and the old
      Suggestions and Overly descriptive? windows open exactly as before;
      tick it again for the new one. Rephrase (Ctrl+R, ✨) is unchanged
      until D.2c.

**The One Improve window: Rephrase joins (D.2c)**
*Needed before the old screens retire (26 Nov). Your answer, 26 Nov: "everything is working" (all of this group), so retirement can start; the boxes stay yours to tick.*
- [ ] Highlight a phrase and press Ctrl+R (or ✨ on the toolbar): the
      Improve window opens on ✨ Rephrase, the third of four tabs. The
      line under the tabs says it works on exactly what you highlighted;
      the summary line shows your styles, tone, point of view and Cloud or
      Local.
- [ ] Open ▸ Change options: genre, the seven styles, point of view,
      character voice, the twelve tones with Custom, Cloud / Local are all
      there. Change a few: the summary line follows. Close the window and
      reopen it: the section is open or closed as you left it.
- [ ] Check the Scene (↻ Refresh rebuilds it), then Generate Options: the
      options come in as "Rephrase · concise", "Rephrase · clearer", … in
      the versions list, with Why and the changes from your highlight.
- [ ] Edit one option in Your version, pick another, come back: your edit
      is still there and no "Discard your edit?" question appears.
      ↺ Reset brings the option back.
- [ ] Rate an option and keep editing: the status says "Saving as … after
      you finish editing…", then "✓ Saved as … (edited) for training".
      Rate another Poor, then ✓ Accept it anyway.
- [ ] ✓ Accept: exactly your highlighted text is replaced (not the whole
      sentence), and Ctrl+Z undoes it.
- [ ] Talk it through on the Rephrase tab ("make it darker"): new versions
      go to the top; edits on the earlier ones stay.
- [ ] Switch to 💡 Suggestions in the same window: it runs on the whole
      sentence. Pick a suggestion or a rephrase and accept either.
- [ ] A style flag's hover card ▸ ✨ Rewrite with AI, and the next-fix
      card's 💡 More options… on a style flag: the window opens on
      Rephrase with the flag's hint at the top of Scene.
- [ ] Right-click ▸ ✨ Improve this ▸ ✨ Rephrase with AI…: the same.
- [ ] In a draft window, right-click ▸ ✨ Rephrase with AI…: the whole
      Improve window opens over the draft window (Suggestions and Expand
      work there too); Accept changes the draft and marks it unsaved.
- [ ] ▾ context beside the passage shows the text around it.
- [ ] With AI off: Rephrase says it uses the Python libraries, and
      Suggestions' no-model line links to ✨ Rephrase and 🔍 Expand.
- [ ] Settings ▸ Features ▸ Improve window: untick it, and Ctrl+R opens
      the old Rephrase window exactly as before (with its question); tick
      it again.
- [ ] If you train on your ratings: rate and accept a few rephrases, and
      check they appear in Training Studio ▸ Browse rows as before.

**Voice drift (4.2)** (dropped at its gate: nothing in the app changed)
- [ ] Read the 4.2 brief's *Outcome*: the table, and "Why it fails". Do you
      agree the piece should be dropped (section 3, "4.2: voice drift")?
- [ ] If you want to see the numbers yourself, with the app closed (it only
      reads; about 10 s):
      `venv/bin/python scripts/voice_drift_gate.py --writer --earlier-drafts
      "/Volumes/USB321FD/writing/Adelphus/Adelphus - The Fall/chapters"`.
      Section 4 a) is the test that failed: the model's versions of your
      passages score about the same as your own.
- [ ] Critique ▸ Check readiness: the scorecard has the same columns as
      before (no Voice drift column), and the Improve window's versions
      show their voice fit as before.

**The submission package (9.3)**
- [ ] Publish ▸ Publishing: the list's first entry is 📦 Submission
      package. Choose it: the synopsis is filled in from your plot,
      characters and story memory, with [brackets] where something is
      missing. Is anything in it wrong, or taken from the wrong place?
- [ ] Look at the Query letter, Blurb and Readers and comps the same way.
      The blurb and query should keep the ending back; the synopsis gives it.
- [ ] Readers and comps: tick one or two candidates and type a title of
      your own; then Fill in from the story (More ▾). Both appear, and the
      query letter's "It will appeal to readers of …" uses them once you
      fill it in again.
- [ ] Edit a draft, choose an agent, come back: your edit is there. Then
      Fill in from the story: the new text arrives and More ▾ › Earlier
      versions has your edit; restore it.
- [ ] The status line says where the drafts are kept: beside the project,
      `<project>.submission.json`. Check it is there and that nothing changed
      in the chapters.
- [ ] More ▾ › Export this document… and Export the whole package… (Word):
      open them in Pages or Word.
- [ ] If the book has a novella: the manuscript picker shows, and each has
      its own package.
- [ ] At 1024 × 600 (or a small window): the page scrolls, and Draft and
      More ▾ stay reachable.
- [ ] **The real model trial, with the app closed or the model not otherwise
      in use** (nothing else generating; the on-device model crashed the
      app once when used by two things at a time): with a model set up,
      choose each document and press ✍ Draft in my voice. Does it read like
      you? Does the query name only the comps you ticked, and no sales or
      awards? Is "Where it sits" still the app's figures? Does your earlier
      text appear under Earlier versions?

**A fix you asked for (26 November): Expand no longer keeps you waiting**
- [ ] Right-click ▸ 🔍 Overly descriptive?… (or the 🔍 Expand tab): the word
      scan's statements are listed and highlighted at once, with "The AI is
      checking them…" (or "…once Suggestions is done", when Suggestions ran
      first). When the AI answers, its list takes their place. More ideas
      waits for the AI.
- [ ] Apply one of the word scan's expansions before the AI answers: it is
      kept when the AI answers, and More ideas then works.
- [ ] With the old windows (Settings ▸ Features ▸ Improve window unticked),
      Overly descriptive? shows the word scan at once too.

**Round 6 (26 November)**
- [ ] **Shared-folder warning:** File ▸ Save As, and choose a folder that
      already holds another project's `.writerproj` file. One box: "Another
      project is in this folder", with **Save in New Folder** (the default),
      **Save Here Anyway** and Cancel. Save in New Folder puts the project in
      a new folder named after it (a number is added if that name is taken)
      and leaves the other project alone. An ordinary Save never asks.
- [ ] **Rephrase ratings carry the right style:** in Rephrase (the Improve
      window's tab, or the old window), rate the second or third option.
      In Training Studio ▸ Browse rows, the new row's style is that
      option's ("clearer/…", "elaborate/…"), not always "concise/…". Rows
      from before keep what they had.
- [ ] **Auto-detect from text:** Rephrase ▸ Change options ▸ character
      voice: "Auto-detect from text" is the first entry. Choose it on a
      line of dialogue: the summary reads "Voice: auto-detect" and the
      rephrase is in the speaker's voice.
- [ ] Nothing to try for the grammar fix: it only stops a late result from
      reaching an editor that is being closed. Grammar underlines should
      appear as before.

**The manuscript tree (D.10)**
*Needed before the old screens retire (26 Nov). Your answer, 26 Nov: "everything is working" (all of this group), so retirement can start; the boxes stay yours to tick.*
- [ ] Write: the top row of manuscript tabs and Novellas ▾ are gone. The
      left panel shows 📖 Main Manuscript with its chapters under it, each
      novella as 📘 with its chapter count, and "＋ New novella…" at the end.
      With no novellas, the chapters are still under Main Manuscript.
- [ ] Click a novella's row: it opens, as its tab did. Click a chapter
      under another manuscript: the app switches to it and opens the
      chapter. Arrow keys move through the rows; Enter opens.
- [ ] Right-click a manuscript row: everything the tab's menu had (critique,
      continuity, rename, description, turn main into a novella, drop
      novella, new novella). Right-click a chapter: its old menu, plus
      **Move to ▸**.
- [ ] **On a copy of a project first:** drag a chapter up or down inside
      its manuscript (the same as ↑ ↓). Drag a chapter from the main
      manuscript onto a novella, from one novella to another, and back to
      the main manuscript. Select several and drag them together. Drop one
      on "＋ New novella…".
- [ ] After a move, the status bar says "Moved “…” to …" with **Undo** for
      30 seconds. Press Undo: the chapter is back where it was, with its
      drafts, saved copies, notes and marks.
- [ ] Move a chapter with Move to ▸ too, and check its drafts (right-click ▸
      Drafts…) and its notes in the Companion came with it.
- [ ] While "Editing:" shows a draft, a move is refused with a message
      (section 3 asks whether it should switch back by itself).
- [ ] At 1024 × 600: the tree fits and scrolls, and long names are
      shortened with "…".
- [ ] Settings ▸ Features ▸ Manuscript tree: untick it, and the tab row,
      Novellas ▾ and the chapter list are back exactly as before; tick it
      again.

**Fit and scroll on the screens used most (U.3a)**
- [ ] On the small laptop screen (1024 × 600), or the window made that
      small: Write with the side panel open (Companion, Planner, Feedback)
      fits beside the text with nothing cut off. The line under the text
      ("Words: …", the reading level, the grammar status) shortens with
      "…"; hover for the full text.
- [ ] The Chapter Title box grows to two or three lines for a long title
      and shrinks back.
- [ ] The toolbar's font size shows "12" whole, and the heading box shows
      "Normal" whole.
- [ ] The Companion's note buttons (Go to, Suggest fix, Ask, Dismiss) and
      the scorecard's legend wrap onto a second line in a narrow panel,
      instead of making it wider.
- [ ] World ▸ Hierarchies: the button reads "➕ Add Hierarchy".
- [ ] The Critique in its own window, narrow: "Check the book with the
      model…" wraps, a long manuscript name shortens, and the page scrolls
      sideways instead of cutting things off.
- [ ] A chapter's stage chooser with a long novella name: the heading and
      chapter names wrap.
- [ ] Settings opens within the screen at 1024 × 600, with every page
      whole.
- [ ] At exactly 1024 px with the side panel closed: is 🗣 Read Aloud behind
      the toolbar's ››? (Section 3 asks whether to narrow the chapter
      list to bring it back.)

**Studio cards follow a moved chapter (the small fix, 26 Nov)**
- [ ] Rare to see: it needs two chapters with the same id, one in the
      main manuscript and one in a novella (a chapter copied between
      them). Move the main one into that novella. Its Video Studio cards,
      chapter deck and slide deck still belong to it (Studio ▸ the
      chapter list), and ↶ Undo moves them back with it. Without a clash
      nothing in the Studio changes.

**Fit and scroll on the remaining screens (U.3b)**
- [ ] At 1024 × 600, all five tabs fit, and no window is wider than the
      screen.
- [ ] Video Studio narrow (or in its own window): the toolbar wraps and
      reads 🎤 Slides, 📑 Export, ✨ Refine; widen it and the full words come
      back. Hover the Backends line to read all of it.
- [ ] World ▸ History & Timeline on a small screen scrolls. World in its
      own window: the search, filter and sort row and the Factions buttons
      wrap.
- [ ] A narrow Companion: 💡 Fix, ✓ Beat, ✕; hover each for the full name.
      Wide: Suggest fix, Mark beat done, Dismiss as before.
- [ ] The rating bar, narrow: ⭐ Best and Save (hover: Excellent, Save for
      training).
- [ ] Video Studio: Save and Load on the toolbar, and "+" beside them
      opens Arrange, Clear and Fit (each does what its button did).
- [ ] World ▸ Hierarchies: "➕ Add Hierarchy" reads whole again.
- [ ] Video Studio opens without its side panel: the canvas has the whole
      width. Right-click empty canvas: **Backend status…** and **Hints…**
      each open a small window. ▶◀ brings the panel back; reopen the app
      and it is still open (and stays closed once you close it).
- [ ] The Critique in its own window at 150 %: the verdict's words sit
      under the verdict.
- [ ] The World editors (map event, place, landmark, star system,
      military, magic), the Import guide, Import AI data, the CreativeOS
      launcher and Model Hub open within the screen, with Save / Close
      visible; Model Hub's ☆ stars show.
      *27 Nov: you tried these and they pass.*

**The old screens retired (D.11)** (try on a copy of a project first)
- [ ] Open the app: five tabs, the manuscript tree, no tab row above
      Write; Settings has no Main tabs, Improve window or Manuscript tree
      boxes. Nothing asks a question at start.
- [ ] Ctrl+R, ✨, the right-click ✨ Improve this ▸ entries and a draft
      window's Rephrase all open the Improve window.
- [ ] Analyze ▾ ▸ any entry: the report shows "Run again · Copy" (no
      "Show in a window (old)").
- [ ] Right-click a novella in the tree ▸ "Move main chapters into this
      novella": it asks first (mentioning Undo), moves every main chapter
      with its drafts, and the status bar offers Undo; Undo puts everything
      back.
      *27 Nov: you tried these and they pass.*

**The reverse outline with a model (7.2)** (run the safety check from 0.3
first; one more request per chapter when the book is checked with the
model, about 2–6 seconds on the on-device model)
- [ ] Revise ▸ Critique ▸ "Check the book with the model…", then open a
      chapter's Scene outline ▸: under each scene, the model's scenes (who,
      what happens → what it is for, or "changes nothing?") and "Tension N
      of 5: why". The chart's tension line runs through the chapters.
- [ ] Do the scene readings and tension numbers match your sense of the
      chapters? (On Born in Blood ch. 1 the trial model called all four
      scenes "changes nothing": a misreading; see section 3.)
- [ ] Change a chapter and check it again: its readings are redone; an
      unchanged chapter keeps its stored ones.

**Scene markers (7.4)** (try on a copy of a project first; nothing in
your text changes)
- [ ] Right-click a paragraph ▸ More ▸ 📝 Note or scene break ▸ Scene break
      here: a thin dashed line appears above it; hover for "Scene 2". The
      status bar offers Undo. Right-click it again ▸ Remove scene break.
- [ ] Type or cut text above a marked paragraph: the line follows it.
- [ ] Revise ▸ Critique ▸ a chapter's Scene outline ▸: marked scenes read
      "· marked ✕"; ✕ removes one; the Undo link and Cmd+Z put it back. On a
      chapter checked with the model, "Use the model's scenes" lists the
      paragraphs first, then "Mark these N".
- [ ] The tension chart and the outline show one entry per marked scene.
- [ ] Move a marked chapter to a novella and Undo: the markers go and
      come back with it.
- [ ] File ▸ Export Chapter: "Mark scene breaks" shows only when markers
      exist. Unticked, the export is as before; ticked, a centred "#" at
      each marker in the exported copy.
- [ ] Add Annotation is now under More ▸ 📝 Note or scene break ▸ on the
      right-click (still one click on the toolbar's 📝, and Ctrl+Shift+N).
      *27 Nov: you tried these and they pass.*

**Tension with your chosen model (round 13)** (the app's model, as usual)
- [ ] Settings ▸ the Critique's model: choose Gemma or Cydonia. Then
      "Check the book with the model…": tension lines and the chart's curve
      appear for each chapter.
- [ ] Check again without changing anything: no chapter is rated again
      (fast). Change one chapter: only it is asked again.
      *27 Nov: you tried these and they pass.*

**V.4's real trial (information; nothing changed in the app)**
- [ ] Read the addendum in V.4's Outcome: the side-by-side rewrites, and
      whether "more examples in your own voice" matches what you see when
      you rephrase.
      *27 Nov: you read it.*

**Other formats (planned; nothing built)**
- [ ] Read README decision 18 and the list of phase F pieces (section 5,
      group H). Is anything missing or wrong for the videos, podcasts and
      series you have in mind?

**When you are happy**
Already committed by you: phase 3, D.3, 2.5 and 0.5 (7e48893); R.7, D.1,
9.2, 7.1 (206300a); D.7 and D.9 (ccc779b); D.8, P.2a, 4.1, 7.3, P.3, D.6,
the contact details, the remembered style switches, CONLIT sentence length
and decisions 3 and 9 (0733233); H.1, D.4, D.5, P.2b, 4.3 and the
chapter's prose profile (d0d347e, 58226e9).
- [ ] Commit round 1: V.1, P.8, P.6 and V.2.
- [ ] Commit round 2: 6.1, 6.2, V.3, V.4 and V.5.
- [ ] Commit round 3: D.9's and D.8's second sessions, the D.2a design
      and 0.3's screen check.
- [ ] Commit the two fixes: Listen and mark reads only the highlight
      (`src/ui/listen_mark.py`), and pause without the stutter
      (`src/services/tts_service.py`, `tests/test_tts_pause.py`). The D.2a
      answers (decision 16) are in the docs.
- [ ] Commit D.2b: the One Improve window with Suggestions, Critique and
      Expand (`src/ui/improve.py`, `improve_window.py`, `improve_tabs.py`,
      the helpers moved in `passage_critique_dialog.py`, call lines in
      `manuscript_editor.py` and `settings_dialog.py`, the harness and
      baseline (right-click 7 / 11), `tests/test_improve_window.py` and the
      test changes named in D.2b's *Outcome*), and two old Expand glitches
      fixed after review ("can't" shown as code; "very, very cold" cut to
      "very, cold": `overdescription_panel.py`, `src/ai/overdescription.py`).
- [ ] Commit D.2c: Rephrase joins the Improve window
      (`src/ui/improve_rephrase.py`, `tests/test_improve_rephrase.py`; changes
      in `improve.py`, `improve_window.py`, `improve_tabs.py`,
      `rephrase_dialog.py` (`hosted`, two signals); call lines in
      `manuscript_editor.py` and `draft_editor_window.py`; the harness's
      `improve_rephrase` screen; `tests/test_improve_window.py` and
      `tests/test_one_look.py` as D.2c's *Outcome* says; the docs).
- [ ] Commit 4.2: voice drift, dropped at its gate (`scripts/voice_drift_gate.py`,
      `tests/test_voice_drift_gate.py`; the 4.2 brief's Status and *Outcome*,
      the README tracker, `cut.md`, `inventory.md`, this file).
- [ ] Commit 9.3: the submission package (`src/ai/submission_package.py`,
      `src/data/submission_store.py`, `src/ui/submission_package_view.py`,
      the list entry and scroll in `src/ui/agent_manager_widget.py`, the
      harness's `publishing_package` screen, `tests/test_submission_package.py`;
      the 9.3 brief's Status and *Outcome*, the README tracker, this file).
- [ ] Commit the Expand fix: the word scan shows at once while the AI checks
      (`src/ui/improve_tabs.py`, `src/ui/overdescription_panel.py`, four tests
      in `tests/test_improve_window.py` and `tests/test_overdescription.py`).
- [ ] Commit round 6: the grammar results (`src/ui/grammar_results.py`, two
      call lines in `enhanced_text_editor.py`, `tests/test_grammar_results.py`);
      the Rephrase slips (`src/ui/rephrase_dialog.py`,
      `tests/test_rephrase_slips.py`, one assertion in
      `tests/test_improve_rephrase.py`); the shared-folder warning
      (`src/ui/save_location.py`, two call lines in `main_window.py`,
      `tests/test_save_location.py`).
- [ ] Commit D.10: the manuscript tree (`src/ui/manuscript_tree.py`,
      `src/data/chapter_move.py`, two call lines in `manuscript_editor.py`,
      three in `settings_dialog.py`, `tests/test_manuscript_tree.py`,
      `tests/test_chapter_move.py`, the change in `tests/test_show_less.py`,
      the "write" figures in `screens_baseline.json`, the D.10 brief).
- [ ] Commit the phase F docs: the sixteen briefs (`pieces/70-…` to
      `pieces/85-…`), README decision 18, the tracker and rule 11's note,
      the notes in the U.3a, U.3b and 9.1 briefs, this file.
- [ ] Commit U.3a: the fit-and-scroll sweep (`src/ui/ui_kit.py`'s
      `ElidedLabel`, `FlowLayout` and `grow_with_text`; changes in
      `companion_panel.py`, `scorecard_widget.py`, `rating_bar.py`,
      `chapter_stage_ui.py`, `worldbuilding/hierarchy_builder.py`,
      `grader_widget.py`; call lines in `manuscript_editor.py` and
      `settings_dialog.py`; the harness's new screens and cut-off check;
      `tests/test_fit_sweep_u3a.py`; the U.3a and U.3b briefs).
- [ ] Commit F.0's design (the F.0 brief) and the notes it added to the
      other phase F briefs.
- [ ] Commit round 13: the tension follow-ups (`src/ai/scene_tension.py`,
      `tests/test_scene_tension.py`, `tests/test_readiness_judge.py`, 7.2's
      second addendum).
- [ ] Commit round 12: 7.4 (`src/data/scene_marks.py`,
      `src/ui/scene_marks_ui.py`, `tests/test_scene_marks.py`;
      `reverse_outline.py`, `scene_tension.py`, `plan_match.py`,
      `outline_section.py`, `plan_section.py`, `readiness_issues.py`,
      `write_menu.py`, `export_document_dialog.py`,
      `manuscript_exporter.py`, `chapter_move.py`; call lines in
      `manuscript_editor.py` and `main_window.py`; `tests/test_one_look.py`;
      the 7.4 brief and notes in 9.1 and F.6) and the Cydonia trial
      (`scripts/tension_repeat_trial.py`, 7.2's addendum).
- [ ] Commit round 11: 7.2 (`src/ai/scene_tension.py`,
      `src/ai/scene_reading.py`, `src/ui/outline_section.py`,
      `src/ai/readiness_checks/editor.py`, `src/ai/chapter_digest.py`,
      `tests/test_scene_tension.py`, `tests/test_scene_reading.py`,
      `tests/test_readiness_judge.py`, `scripts/tension_repeat_trial.py`,
      the 7.2 brief and notes in 7.3, 8.1b, 8.3, F.6) and V.4's trial
      (`scripts/voice_examples_model_trial.py`, the V.4 brief's addendum).
- [ ] Commit D.11 (the old screens retired): `src/ui/secondary_window.py`
      and `tests/test_promise_check_dialog.py` deleted; `screen_groups.py`,
      `main_window.py`, `settings_dialog.py`, `manuscript_editor.py`,
      `manuscript_tree.py`, `write_toolbar.py`, `analysis_menu.py`,
      `src/ai/analysis_reports.py`, `improve.py`, `draft_editor_window.py`,
      `scripts/screen_harness.py`; `tests/test_retire_old_screens.py` and
      the changed tests; the D.11 brief and notes in 9.1 and U.3b.
- [ ] Commit the Studio cards fix (`src/data/chapter_move.py`,
      `tests/test_chapter_move_studio.py`, the note in the F.0 and F.10
      briefs).
- [ ] Commit U.3b (`src/ui/ui_kit.py`; `scripts/screen_harness.py`; the
      Companion, rating bar, World, scorecard and test-history widgets;
      call lines in Characters, Visuals, the World editors, the import
      dialogs, Model Hub, the launcher, `studio_widget.py` and
      `training_tool_window.py`; `tests/test_fit_sweep_u3b.py` and the
      U.3a test's one change; the U.3b brief and notes in F.10, F.15, 9.1;
      then your three U.3b answers: `ui_kit.fold_into_menu`, the Studio's
      "+" call line, World's 290 px cap, the harness's "+" group and
      `screens_baseline.json`); and the Studio side panel dropped by
      default (`src/ui/video_studio/studio_side_panel.py`, one call line
      in `studio_widget.py`, the right-click hook in `scene_canvas.py`,
      `tests/test_studio_side_panel.py`).
- [ ] Commit the second round of section 3 answers (26 Nov): F.0's seven,
      the Studio-card fix, U.3a's two (this file, README decision 18 and
      the tracker, the F.0 brief's *Review notes*, the U.3b brief's notes).
- [ ] Commit the section 3 answers (26 Nov): the new figures in
      `screens_baseline.json` and the harness's comments
      (`scripts/screen_harness.py`), the answers in this file, the 8.1a
      brief's *Review notes*, and README decision 17 and the tracker.
- [ ] For anything you reject, untick it in the README tracker and write why
      under the piece's *Review notes*.

## 2. Run the measurement

- [ ] **Close the app first.** A model run while the app uses the on-device
      model crashed it once.
- [ ] Run:
      `venv/bin/python scripts/measure_misses.py --model --editor --limit 3 --cases 4`
- [ ] Read [miss_rates.md](miss_rates.md). Two things to look for: whether
      agreement mistakes are caught again with the model, and the new list
      of example flags on clean passages.
- [ ] Keep the report; P.5 works from it.

## 3. Decide

Write each answer in the README under *Decisions*, or tell the session.

- [x] **8. Shared state files.** Decided 24 November: a file per project
      ([R.7](pieces/22b-R.7-one-state-file-per-project.md)).
- [x] **13. The Write screen's buttons.** Decided: group by row, 24 to 18 (D.7).
- [x] **14. Book-wide fixes.** Decided: chapter by chapter, each with its own undo (9.1).
- [x] **15. Where the reverse outline shows.** Decided: in the Critique (7.1).
- [ ] **9. Fix all for every kind of flag.** Confirm, or name kinds to leave
      out (their/there, for example). *Answered 24 Nov: leave out confused
      words. Done (`fix_all.is_confusable`).*
- [ ] **10. Two ways to detach the Critique.** Merge them in D.4 (the plan),
      or drop one entry now. *Answered 24 Nov: merge in D.4.*
- [ ] **11. What to retire.** After using them: may the old three-fixes list
      and the Style tab go? Does a submenu count as one menu entry?
      *Answered 24 Nov: both may go (D.6 can start). A submenu counts as
      one when its items are one closely related group; different actions
      (Rephrase, Suggestions, Critique) count separately.*
- [ ] **12. The on-device model.** Accept that model measurements run with
      the app closed until 8.1. *Answered 24 Nov: yes.*
- [ ] **Still open from before:** 2 (what is left out of parity), 3 (the
      four-in-five quality target), 5 (voice groups), 6 (whether you want
      P.1). *Answered 24 Nov: 2, parity to put the app on a par with others
      (plagiarism stays out; integrations such as YouTube, KDP and Barnes &
      Noble come after the first working product; the writing habit is in
      and important, it needs a brief; community comes after the first
      working product, on its own web page); 6, P.1 is dropped; 3, style checks must meet 4 in 5, spelling and
      overused words stay on (built for new projects). 5 answered 25 Nov:
      broad = shared across projects, manageable = you manage the groups;
      the number of groups is never chosen: it is how many strong, distinct
      voices there is evidence for (projects and narrators are grouped, the
      most alike merging while the group stays strong; "square root of n"
      was an example only, the method left to the session); a per-project switch keeps
      a project's ratings to itself (off by default). Then: groups grow and
      shrink with the data (yours are proposed, never changed silently); you
      can set starting groups and combine groups; the model names each new
      or merged group (yours keep their names); at most 8 groups made by the
      app, and a merge suggested above 8 in all. And groups stay strong:
      a project or narrator with too few ratings waits in Unsorted, the app never makes a
      loose group to hit a count, and merging loose voices asks you first. In README decision 5
      and the V.1 to V.5 briefs.*
- [ ] **The new counts (D.1, D.7).** The harness counts every menu item as
      clutter. What changed:
      *Answered 24 Nov: agreed, with the new counting. `screens_baseline.json` now holds the new figures (the 0.2 ones kept inside it).*

      | Menu or screen | Before | Now | Baseline |
      |---|---|---|---|
      | Right-click, with a selection | 22 | 26 | 22 |
      | Right-click, without one | 12 | 15 | 12 |
      | Write, visible buttons | 24 | 19 | 24 |
      | Write, items behind menu buttons | 40 | 48 | 29 |

      - The top levels of the right-click menus are 9 (was 11) and 6.
      - The right-click rise is entries that were hidden by a bug, the two
        group headings, and Improve without a selection.
      - Write's 8 new menu items are the 8 buttons now in Novellas ▾,
        Drafts ▾ and 📝 ▾.
      - Agree the new figures and a session updates `screens_baseline.json`,
        which makes the one failing test pass.

      **Counted by decision 11 (D.6, 24 Nov; information, nothing to tick
      here).** A submenu or menu button of one closely related group counts
      as one entry (the list is in [screens.md](screens.md)). With that
      rule, and the Style tab retired, every count is at or under the
      baseline and the harness test passes without a new baseline:

      | Menu or screen | Every item (old rule) | Grouped (decision 11) | Baseline |
      |---|---|---|---|
      | Right-click, with a selection | 26 | 13 | 22 |
      | Right-click, without one | 15 | 9 | 12 |
      | Write, visible buttons | 19 | 19 | 24 |
      | Write, items behind menu buttons | 53 | 29 | 29 |
      | Style tab, buttons | 15 | retired: 0 | 15 |
      | Companion, buttons and sections | 15 and 7 | 15 and 7 | 18 and 7 |
      | Critique, buttons | 6 | 6 | 11 |

      Write's 53 includes one new line, the Style checks summary. Lowering
      the baseline to these figures is still yours to agree.
- [ ] **Contact details for the title page (9.2).** Standard manuscript format
      puts your address, phone and email under your name. The app has nowhere
      to keep them. Add a place (Publishing tab), or keep adding them by hand?
      *Answered 24 Nov: one place to update name, phone, email and address. Built: try it in section 1 ("Contact details on the title page").*
- [ ] **Saving into a shared folder.** Two projects saved in one folder could
      also collide over chapter folders (found in R.7; neither of your
      projects is set up that way). Want a warning when saving a project into
      a folder that already holds another project file? That would be a
      small piece of its own, since it touches saving.
      *Answered 26 Nov: yes, the warning should exist. A small piece of its own, since it touches saving ("Shared-folder warning", section 5).*
- [ ] **D.9: did a quiet message go somewhere you'd rather keep a box?**
      You said you'd likely have notes once you see it. Each moved message
      is one word to move back (``notify.done``/``notify.empty`` →
      ``QMessageBox.information``); name it under D.9's *Review notes*. Also
      still open: "Draft #N saved" and "Created draft …" stay boxes unless
      you say move them.
      *Answered 24 Nov: "Draft #N saved" and "Created draft …" are visible but no box: a bold, tinted status-bar line for 20 seconds. Done.*

      *Answered 26 Nov (the recommendations): no; keep them quiet.*
- *(Answered 24 Nov: you said go; left here for reference.)* **D.9's list has arrived.** Read the table in
      [D.9's Outcome](pieces/48e-D.9-fewer-interruptions.md#outcome). It
      sorts 68 message boxes:
      - 9 "done" messages become a status-bar line;
      - 40 "nothing to do" messages become a quiet line;
      - 19 stay boxes.

      Two of the boxes could also move if you agree: "Draft #N saved" and
      "Created draft …". Mark changes under its *Review notes* and say go.

- [ ] **D.8: the app-wide button colour.** Every button that sets no style
      of its own is indigo, from the app-wide style in `styles.py`. D.8
      made the screens above plain one by one. Changing the app-wide rule to
      plain would make every other screen calm at once (Plot, Characters,
      World, the assistant…), but changes all of them in one go, before
      each is looked at. Do it now, or screen by screen as D.8 repeats?
      *Answered 24 Nov: "do a tidy without losing features, in one go".
      Done: see "The app-wide tidy" in section 1.*
- [ ] **D.8: the main button on two screens.** The Critique's coloured
      button is now "Check readiness" (Run Critique is plain, same size);
      the Planner has none (its candidates are "+ Add" and "AI Generate").
      Say if you want either the other way.
      *Answered 24 Nov: the Critique's is Run Critique; on the Planner the
      plan comes first, and with AI set up the conversation is the
      centrepiece. Done: Run Critique is coloured, Check readiness plain;
      the Planner colours "+ Add" without AI and "🤖 AI Assistant" with it.*

- [ ] **P.2a: remember the style switches?** No style check's tick is kept
      between sessions today (Style on/off included), so the four new
      checks must be ticked again after each restart. Keep it that way, or
      remember the ticks per project (a small stored-data change, its own
      piece)? If remembered, should Pronouns and Acronyms, which meet the 4
      in 5 target on the marked set, start on for new projects? Few
      transitions and Alliteration do not (they flag deliberate choices) and
      would stay off.
      *Answered 24 Nov: yes, remember them per project, and Pronouns and Acronyms start on for new projects. Built (P.2a addendum); try it in section 1, "Remembered style switches".*
- [ ] **P.2a: Write's menu count.** The four switches take Write's menu
      items from 48 to 52 (baseline 29). Part of decision 11 (does a submenu
      count as one entry?).
      *Answered 24 Nov: settled by the new counting (29).*
- [ ] **4.1: one more entry on a flagged word's right-click menu.**
      "📌 This is intentional" is added to the flag section, after Ignore;
      nothing was folded into it, because Ignore lasts only the session and
      Add to Dictionary only covers spelling. The harness right-clicks plain
      text, so its counts do not change. Keep it as an entry of its own?
      *Answered 24 Nov: keep it.*
- [ ] **4.1: should Not a problem also hide the underline?** Today the
      card's Not a problem stops a pattern in the report and the queue, but
      the editor still underlines it; "This is intentional" hides it
      everywhere. Keep that difference, or make Not a problem hide the
      underline too (a one-word change in `intentional.intended_keys`)?
      *Answered 24 Nov: yes. Done (`intentional.intended_keys`).*

- [ ] **P.3: use CONLIT for sentence length?** CONLIT (the Training
      Studio's download: statistics for about 2,750 contemporary books) has sentence
      length for mystery, science fiction, romance and historical fiction, from
      many books each, but it is counted with a different tokenizer
      (it likely counts punctuation as words), so its figures would not
      compare with the app's own count and could mislead. P.3 leaves it out
      and uses only books measured by the app's own checks. Keep it out, or
      add it once the two counts have been compared on the same books?
      *Answered 24 Nov: CONLIT works; use it. Built: its tokens per sentence are divided by
      1.12 to give the app's words per sentence (measured on the benchmark prose), and it
      sets sentence length for genres it has five or more books for. Try it in section 1
      ("CONLIT sentence length (P.3)").*
- [ ] **P.3: five books before a genre is used.** With fewer, a range is
      so narrow that published chapters fail it (shown on the benchmark in
      P.3's *Outcome*). Keep five, or ask for more?
      *Answered 24 Nov: five is fine.*
- [ ] **H.1: the nudge's numbers.** The nudge asks when a project's last
      7 writing days grew the manuscript by under 200 words in all (words
      added minus words cut). Keep 7 and 200, or change them (two constants,
      `NUDGE_DAYS` and `NUDGE_MIN_NEW` in `src/data/writing_habit.py`)?
      *Answered 24 Nov: keep the nudges as they are unless you turn them off.*
- [ ] **H.1: does pasted or imported text keep the streak?** A day whose
      only change was a paste or an import of more than 300 words counts as
      a writing day today (the words are listed as "pasted or imported", not
      written, and never count toward a goal). Keep that, or count only
      typing, cutting and revising?
      *Answered 24 Nov: a paste or an import alone does not count. Done:
      such a day is still recorded and shown, but is not a writing day.*
- [ ] **D.4: the new top-level tab count.** The harness now counts the
      main window's top-level tabs: 5, against 10 in
      `screens_baseline.json` (`main_window.top_level_tabs`). Agree 5 as
      the new baseline and a session writes it in. Every other count is
      unchanged. One count the harness does not keep rose: right-clicking a
      top-level tab offers one entry ("Open … in Its Own Window") without
      Multi-Window Mode switched on (before, the menu was empty unless it
      was on); the brief asked for this.
      *Answered 26 Nov (the recommendations): agreed. Written into `screens_baseline.json` (top_level_tabs 5).*
- [ ] **D.4: when to retire the old ten tabs.** During the trial, Settings ▸
      ✨ AI Features ▸ Main tabs switches back to the ten (rule 11). When
      you have used the five groups on both projects and agree, a small
      step removes that switch, and the old `SecondaryWindow` (no longer
      used) with it; the stored setting is left in place, unread. Say when,
      or keep the switch for good.
      *Answered 26 Nov: Retire once everything in section 1 is checked, in one piece with the other old screens, so nothing is there twice ("Retire the old screens", section 5).*
      *Changed 26 Nov: retirement waits only on the four groups for the old screens (D.4, D.5, the One Improve window D.2b and D.2c, the manuscript tree D.10) and the 0.3 safety check; the rest of section 1 is checked before 9.1.*
- [ ] **D.4: reopen windows at start-up?** A screen left in its own window
      comes back into its tab when the app restarts (as the Critique's
      window always has: 2.5 recorded it but nothing reopened it). Keep
      that, or reopen whatever was out (a small change to what the app
      shows at start)?
      *Answered 26 Nov (the recommendations): keep as built: a screen comes back into its tab.*

- [ ] **D.5: when to retire the old analysis windows.** During the trial,
      each analysis's tab has "Show in a window (old)". When you have used
      the reports on both projects and agree, a small step removes the two
      old windows (`ProseAnalysisDialog`, `PromiseCheckDialog`) and that
      link. Say when.
      *Answered 26 Nov: Retire once everything in section 1 is checked, in one piece with the other old screens, so nothing is there twice ("Retire the old screens", section 5).*
      *Changed 26 Nov: retirement waits only on the four groups for the old screens (D.4, D.5, the One Improve window D.2b and D.2c, the manuscript tree D.10) and the 0.3 safety check; the rest of section 1 is checked before 9.1.*
- [ ] **D.5: the new reports in the full critique?** Promises, Prose
      profile fit, Character check, Plot vs plan and Writing hints run only
      from Analyze ▾ (and "Run again"). Adding them as tick boxes in
      Detailed critique would add five controls to the Critique. Keep them
      out, or add them (and to which runs: "Critique this chapter (all
      reports)" too)?
      *Answered 26 Nov (the recommendations): keep them out (no new controls).*

- [ ] **4.3: when is a check toned down?** Built: after at least 20
      answers to its fixes (Accept, Not a problem, intended; Skip does not
      count) with fewer than two in five accepted, since it was last
      brought back. Keep these figures, or name others (a later or earlier
      point, or a different share).
      *Answered 26 Nov (the recommendations): keep these figures.*

- [ ] **The chapter's prose profile: the Companion's chat too?** "Prose
      profile" and "review my prose" work in the AI Assistant chat (side
      panel). The Companion's chat doesn't know them yet. Add them there
      (a few call lines, no new controls), or keep one place for them?
      *Answered 26 Nov (the recommendations): keep one place (the AI Assistant chat).*

- [ ] **V.1: the one-time copy of the ratings store.** Before it adds the
      fingerprints, V.1 copies the whole store aside once (rule 15):
      `rephrase_history.db.before-voice`, about 1.9 GB, because the store
      also holds about 200,000 downloaded corpus rows. Your own ratings are
      about 6,000 rows. Keep the full copy (safest; needs 1.9 GB once), or
      copy only your own rows (a few MB; the corpus rows can be downloaded
      again)? Nothing is copied until the app next opens.
      *Answered 26 Nov: keep the full copy (safest, rule 15); confirmed by you. Note: your own rated rewrites are 398 rows, not about 6,000 as written above.*
- [ ] **V.1/V.2: which ratings shape the voice groups.** Only Rephrase
      ratings get a fingerprint. The 250 rows made from downloaded corpora,
      and rows with no project, are left out of the grouping (they aren't
      your voice) and keep working as today. Say if you want any kept in.
      *Answered 26 Nov (the recommendations): as built: corpus rows and rows with no project stay out of the grouping.*
- [ ] **P.8: where it shows.** Built in both places: the full section on
      each character (Story ▸ Characters), and a scan of the chapter's
      characters in the Critique's Character check (no controls added).
      Keep both?
      *Answered 26 Nov (the recommendations): keep both.*
- [ ] **P.8: how sensitive.** An absence counts from 3 chapters. Speech is
      compared only in chapters where the character has 5 or more lines,
      against 8 or more elsewhere; a change is marked when line length
      doubles (and differs by 5+ words) or contractions, formality or
      swearing flip. Keep these, or name others after trying it?
      *Answered 26 Nov (the recommendations): keep these figures.*
- [ ] **P.8: two limits.** Novellas are analysed one manuscript at a time,
      not across all of them; the model's arc answer isn't saved (asked
      again after reopening). Worth more work, or fine as is?
      *Answered 26 Nov (the recommendations): fine as is.*
- [ ] **P.6: keep the n-gram data?** It uses 15.4 GB. Harder confused
      words caught went from 13% to 38% (all seeded mistakes 71% → 75%),
      with no new false alarms on clean prose; the Q.2 table didn't move
      (its three misses, to/too and it is/its, aren't pairs the data
      covers). Remove in Settings ▸ Language deletes it.
      *Answered 26 Nov (the recommendations): keep it.*
- [ ] **Old LanguageTool servers still running.** About 40 were left by
      earlier app, script and test runs (24 and 25 November) before the
      fix; each holds memory. The session wasn't allowed to stop them.
      With the app closed: `pkill -f languagetool-server`.
      *Answered 26 Nov (the recommendations): done; none are left from before the fix (only the running app's own).*
- [ ] **V.2: two calibration choices (technical; confirm or ask).**
      "Same voice" was measured as the first half of a book against its
      second half (ratings come from different chapters), giving "alike"
      at 0.45 and "different" at 0.67, and 30 distinct passages before a
      project counts. And one source is split into two voices only at a
      higher bar (1.25): at the ordinary one, 29 of 55 single books split
      wrongly; at 1.25, 1 of 55. Naming narrators makes them separate
      sources anyway.
      *Answered 26 Nov (the recommendations): confirmed.*
- [ ] **V.2: a group with one project** reads "very alike" (nothing to
      compare). V.5 will show "one project" instead, unless you prefer
      otherwise.
      *Answered 26 Nov (the recommendations): show "one project".*
- [ ] **6.1: listening choices.** Built: with text highlighted, only the
      highlight is read and marked; otherwise the whole chapter from the top
      (*answered 25 Nov: your fix*); Space, M and Esc
      are taken over only while listening; M toggles a mark. With a neural
      voice each sentence is made separately, so there may be a pause
      between sentences: acceptable, or use the system voice for Listen?
      Listening across several chapters with marks is left out ("Read
      chapters…" is unchanged).
      *Answered 26 Nov (the recommendations): the pause between sentences with a neural voice is acceptable; several chapters stay left out.*
- [ ] **V.4: order of examples within a group.** Built: your "excellent"
      ratings first, then this project's, as today, and closest in voice
      within each. Measured without a model on 87 rated passages: voice
      fit 0.894, against 0.885 today and 0.871 for closest-in-voice alone
      (so that wasn't used). The big gain is a new book in a known voice:
      all its examples come from its own voice, against about half today.
      The real test, new rewrites with a model, is still to run.
      *Answered 26 Nov (the recommendations): keep as built.*
- [ ] **V.4: a kept-to-itself project and the groups.** Its ratings are
      never used as examples elsewhere, but still help decide the voice
      groups. Leave them out of the grouping too?
      *Answered 26 Nov (the recommendations): keep as built (still helps decide the groups).*
- [ ] **V.4: where the switch is kept.** In a small file beside the
      project, `<project>.ratings.json`. If you rename or move a project,
      its old ratings keep the old path, so the switch no longer covers
      them. Fine, or worth handling?
      *Answered 26 Nov (the recommendations): fine as is.*
- [ ] **V.5: where it lives.** In the Training Studio's Browse rows, the
      one screen that already lists and removes ratings, so you leave the
      writing app to reach it. A shortcut in the writing app would add a
      menu entry (rule 13). Add one, or keep it in the Studio?
      *Answered 26 Nov (the recommendations): keep it in the Studio (no new menu entry).*
- [ ] **V.5: changing a rating to Poor or Bad** leaves its "accepted" flag
      as it was (as rating changes always have). Should it also mark the
      rewrite as not accepted?
      *Answered 26 Nov (the recommendations): keep as built (the accepted flag is left as it was).*
- [ ] **6.2: marks and stages.** Marks are line-stage fixes (they show in
      Next fixes at Line, always in the notes). The brief said "unless you
      say otherwise", but a control for it would add to a count. Keep as
      built, have marks follow the chapter's stage, or add a stage choice
      to Read Aloud ▾ → Marks in this chapter?
      *Answered 26 Nov (the recommendations): keep as built (line-stage fixes).*
- [ ] **V.3: naming with only the on-device model.** The model is never
      loaded just to name groups, so names appear after something else
      (Rephrase) has loaded it. Right, or should opening the groups view
      load it?
      *Answered 26 Nov (the recommendations): right as built (never loaded just to name groups).*
- [ ] **V.3: the description shown.** The model's one line replaces the
      measured description in the tree (the measured one moves to the
      tooltip). Keep, or show both?
      *Answered 26 Nov (the recommendations): keep (the measured line in the tooltip).*
- [ ] **D.2a: review the One Improve window design** (its brief, section
      *Design*). In short: one window, "Improve", with four tabs:
      💡 Suggestions · ✨ Rephrase · 🔍 Expand · 📝 Critique (Critique is
      Suggestions' what-works/what-doesn't, moved to its own tab, same
      model call). Each tab's options on top (Rephrase's 25 options behind
      "▸ Change options"); below, shared by all tabs: the versions (each
      labelled with its tab), your version (editable, ↺ Reset), the
      changes and why, ratings, Talk it through, and Close / ✓ Accept,
      which never scroll away. All 12 ways in land there; ratings, models
      and voice-group examples work exactly as today; old windows stay
      behind a trial switch. One tab shows 9–11 buttons, against 24 across
      the three windows now. Mock-ups at 1024×600 and 1440×900 are in the
      brief. Then answer:
      1. Critique last (as built) or second?
      2. Count right-click ✨ Improve this ▸ as one group (9/13 → 7/11;
         nothing on screen changes)? Recommended: yes.
      3. Tab name "Expand" (old name in its tooltip) or "Overly
         descriptive?"? Recommended: Expand.
      4. Trial switch starts on? Recommended: on, as D.4's five tabs.
      5. Allow rating a version made in Expand? Recommended: yes.
      6. Drop Rephrase's "Discard your edit?" question (edits now stay with
         their version)?
      7. The draft window's Rephrase opens the whole window (Suggestions and
         Expand work on drafts too)? Recommended: yes.

      *Answered 25 Nov:*
      1. Critique is second.
      2. Yes, one group.
      3. Expand.
      4. On.
      5. Yes, it can be rated.
      6. Drop the question: selecting the rephrased text replaces the
         highlighted text.
      7. Yes, the whole window.

      *Recorded in the D.2a, D.2b and D.2c briefs and README decision 16.*
- [ ] **0.3: the screen check's lines.** (a) A section that was empty and
      that the window fills with defaults (the Video Studio always does)
      is a note, not a problem: right? (b) The screen step runs on every
      safety check (`--no-screens` leaves it out): keep, or make it
      opt-in? (c) Each manuscript opens one chapter, the first with text:
      enough, or every chapter (slower)?
      *Answered 26 Nov (the recommendations): (a) yes, a note; (b) keep it on every safety check; (c) one chapter is enough.*
- [ ] **D.8: main buttons and two small things.** (a) Where a screen had
      a choice, "Add" was made the main button (the plan first, as on the
      Planner): Video Studio Add over Stitch, Publishing Add over Publish,
      Characters Add over Generate. Should any switch to the AI action
      when AI is set up, like the Planner? (b) The Plot screen and the
      Planner use slightly different greens and oranges for the arc
      stages: make them one set? (c) "➕ Add Hierarchy" reads "Add
      Hierarch" at 1024×600 (as before): shorten the label or widen the
      list?
      *Answered 26 Nov (the recommendations): (a) keep Add as the main button; (b) leave the two sets of colours as they are; (c) fix it in the U.3 sweep (confirmed by you).*
- [ ] **D.9: four kinds of box left on purpose.** Say which to make quiet:
      (a) "Image saved to …" and the chapter-deck exports (4): a status
      line with Show file, like other exports? (b) "Open a project before
      saving / loading a storyboard" (2)? (c) the map tool's instructions
      (3): a status line lasts only 8 seconds, so keep them as boxes?
      (d) 165 boxes in separate windows (Training Studio 47, Video Studio's
      editors 74, Settings 10, others): give those windows a status line
      so they can go quiet too?
      *Answered 26 Nov (the recommendations): keep all four kinds as boxes.*
- [ ] **D.2b: the Improve window's figures and Talk it through.**
      (a) Agree the window's counts as its baseline: Suggestions tab 10
      buttons, Critique 9, Expand 12; 1 section; 3 tabs (4 after D.2c).
      Recommended: agree (the three old windows had 24 buttons between
      them). (b) Talk it through is a column only when the window is
      1,200 px wide or more (the app's rule for "narrow"); the window opens
      1,100 wide, so it starts as a closed section until you widen it.
      Keep that, or open the window wider (about 1,250) where the screen
      allows, so the column shows at once? Recommended: keep; the window
      remembers its size once you widen it.
      *Answered 26 Nov (the recommendations): (a) agreed, written into `screens_baseline.json`; (b) keep (a closed section below 1,200 px).*
- [ ] **D.2c: the Rephrase tab's figures.** Agree them as part of the
      window's baseline: 12 buttons, 2 sections (▸ Change options, Talk it
      through), 4 tabs, the 25 options out of view until opened (the old
      window: 9 buttons and the 25 options in view). Recommended: agree.
      *Answered 26 Nov (the recommendations): agreed, written into `screens_baseline.json` (`improve_rephrase`).*
- [ ] **D.2c: two old Rephrase slips, found while building (not changed,
      so the rows stay the same as before).** (a) Every Rephrase rating
      row is stamped with the *first* option's style ("concise/neutral"),
      whichever option you rated, so the training data cannot tell styles
      apart. Fix it, as a small piece of its own (new rows only; old rows
      stay as they are)? Recommended: yes. (b) "Auto-detect from text" never
      shows in the character-voice list, so speaker detection never runs
      from it. Fix it in the same small piece? Recommended: yes.
      *Answered 26 Nov (the recommendations): fix both, as a small piece of its own (new rows only).*
- [ ] **D.2c: when to retire the three old windows.** Once you have used
      the Improve window on both projects, retiring the old Rephrase,
      Suggestions and Overly descriptive? windows (and the switch) is its
      own small step (rule 11). Recommended: after a week of use on both
      projects.
      *Answered 26 Nov: Retire once everything in section 1 is checked, in one piece with the other old screens, so nothing is there twice ("Retire the old screens", section 5).*
      *Changed 26 Nov: retirement waits only on the four groups for the old screens (D.4, D.5, the One Improve window D.2b and D.2c, the manuscript tree D.10) and the 0.3 safety check; the rest of section 1 is checked before 9.1.*
- [ ] **6.2: order and undo.** Marks come before other line fixes of the
      same standing. Clearing a mark has no undo (like Dismiss on notes
      today). Both fine?
      *Answered 26 Nov (the recommendations): both fine.*
- [ ] **8.1a: review the job-queue design** (its brief, section
      *Design*). In short: "Check the book with the model…" becomes a
      job that belongs to the app, not the Critique screen, so it keeps
      going while you write, with the Critique closed. A small file beside
      the project (`<project>.jobs.json`) remembers an unfinished check;
      results stay in the readiness file as today, so resuming simply
      carries on from the first chapter not yet judged. If the model
      server stops answering part-way, the job pauses with a plain
      message, tries again every 5 minutes and carries on by itself. One
      job at a time, always inside the app, giving way to you between
      requests, so the on-device model is never run twice at once. The
      Check readiness button reads Pause / Resume while a job exists; one
      line at the right of the status bar shows "📖 Book check · 12 of
      40" on any screen. A job never changes your text, only adds
      results. No new window, no new button. Then answer:
      1. Carry on by itself two minutes after the project opens, with no
         question when you quit? Recommended: yes.
      2. Server gone: retry every 5 minutes for up to 12 hours, then stay
         paused? Recommended: yes (refused keys are never retried).
      3. Keep the Mac awake while a check runs (the screen still sleeps)?
         Recommended: yes.
      4. Allow jobs on the on-device model, taking turns with you?
         Recommended: yes (or: server and cloud only).
      5. Rename the button "Stop" to "Pause" / "Resume"? Recommended: yes.
      6. Show the status-bar line on every screen while a job exists?
         Recommended: yes.
      7. A later small piece so measurement scripts refuse to start while
         the app holds the on-device model (what crashed it)?
         Recommended: yes, after 8.1b; decision 12 stands until then.
      8. Switching project pauses the job until you reopen that project?
         Recommended: yes.
      *Answered 26 Nov (the recommendations): yes to all eight. 8.1b can start (needs the server).*
- [ ] **4.2: voice drift** (dropped at its gate; the brief's *Outcome*).
      1. **Drop it, as the brief says?** The measure catches 74% of
         chapters by another author, but none of the 14 sets of a model's
         rewrites of your passages, and the rewrite mark caught only 1 in 5
         model rewrites. Thresholds tried: a chapter has moved at **0.70**
         (4.4% of untouched published chapters reach it; 2 of your 46
         untouched chapters, both earlier drafts of Born in Blood); a
         lower bar of 0.40 would still miss the tone rewrites and would
         mark one untouched chapter in five. Recommended: **drop it** (done;
         it is in `cut.md`, and the script stays so it can be rerun).
      2. **Try again later with a word-based measure?** Rates of common
         words saw the 74 plain rewrites (0.44 against 0.00 for your own
         text) but not the tone rewrites (0.28), and 74 rewrites are too
         few to set a bar on. Recommended: **not now**; rerun the script
         when there are a few hundred plain rewrites rated, and reopen 4.2
         only if section 4 a) then separates (most sets over the bar, your
         own sets under it).
      *Answered 26 Nov (the recommendations): 1. drop it; 2. not now.*
- [ ] **9.3: the submission package** (the brief's *Outcome*).
      1. **Its screen counts.** With nothing chosen, the Publishing tab is
         as in the baseline (4 buttons, 1 section). With the package open
         it shows 6 buttons and 4 menu items (Draft and More ▾ added), as
         an agent's page adds Compose Email. Make those figures the
         package's own baseline (`publishing_package`)? Recommended: yes.
      2. **Comparable titles.** The genre list holds only public-domain
         classics, so the candidates are old books, and the screen says
         agents want recent ones. Keep candidates from the genre list as
         built, or show none and leave only your own line?
         Recommended: keep them, with the note (they are honest and help
         with "who it's for").
      3. **Opening an empty document fills it in by itself** (from the
         story, no model, saved to the drafts file). Keep, or wait for a
         click? Recommended: keep (an empty page says nothing).
      4. **The query letter and the agent list.** Address the query to the
         agent chosen in the list, and make Compose Email open it?
         Recommended: yes, as a small later step (not built here).
      *Answered 26 Nov (the recommendations): 1. yes, written into `screens_baseline.json` (`publishing_package`); 2. keep the candidates with the note; 3. keep; 4. yes, as a small later step.*
- [ ] **A crash seen only in tests: the grammar check's results.** Found
      while 9.3 was built. Five test files run together without the rest
      of the suite (publishing goal, writer contact, one look, screen
      harness, fewer top-level tabs) abort in
      `enhanced_text_editor._on_grammar_results`. They did the same before
      9.3. The full suite passes, and your `crash.log` shows no crash.
      Since the app sets no exception hook, an error raised there in the
      app would close it. Track it down as a small fix of its own? That
      file is over 3,000 lines, so the fix goes in a new module with only
      call lines in the editor. Recommended: yes, before the U.3 sweep.
      *Answered 26 Nov (the recommendations): yes, a small fix before the U.3 sweep.*
- [ ] **Round 6: two test-only weak spots, found while fixing the grammar
      abort (not changed).** (a) The editor's typing timer has no parent
      (`QTimer()` in `enhanced_text_editor.py`), so an editor being closed
      can lose it first; the new check covers grammar results, but giving
      the timer a parent (`QTimer(self)`) removes the cause. (b) The one-look
      test starts a real LanguageTool server and leaves a half-closed editor
      behind; and six tests in `tests/test_next_fixes.py` fail when run after
      the other editor tests (they pass alone and in the full suite).
      Recommended: fix both in 9.1's final sweep (a one-line change in the
      editor and test set-up only).
      *Answered 26 Nov: fix both in 9.1's final sweep.*
- [ ] **D.10: two things.** (a) **A stray folder.** If a move needs a
      folder name that an unused folder already has, that folder is kept
      beside it as `chapter_NNN_2` (never deleted), and Undo gives it its
      name back. Keep that, or move such folders somewhere else?
      Recommended: keep. (b) **Moving while a draft is open.** While
      "Editing:" shows a draft, a move is refused with a message. Keep, or
      have the app switch back to the manuscript by itself and then move?
      Recommended: keep (a move changes the manuscript, not the draft, and
      switching by itself could surprise). The old tab row is retired with
      the other old screens, as you said.
      *Answered 26 Nov: (a) keep the numbered folder; (b) keep the refusal.*
- [ ] **D.10: the older whole-manuscript move.** "Move main chapters into
      this novella" (from before D.10) copies, checks, then deletes, where
      D.10's chapter move renames in place and can be undone. Bring the
      older one onto the new move, as a small piece? Recommended: yes,
      with the "Retire the old screens" piece.
      *Answered 26 Nov: yes.*
- [ ] **Other formats (phase F).** *Answered 26 Nov, recorded in README
      decision 18 and the F.0 brief:* a kind per project (Novel, Video
      series, Podcast, Editorial series, Journalism); the words set by the
      kind and editable; an uploaded video goes to the Studio for the
      selected chapter and becomes a card refined there; spoken kinds gain
      a runtime estimate, hook and retention checks, checks for the ear,
      speakers and cues; nonfiction gains a sources list, an
      unsourced-claim check, real people and a timeline, with fiction
      checks off; publishing prepares a video package, a podcast package,
      an article export, a series page, a compilation of a project with
      its novellas, and one novella on its own as a novel, story or short
      story; a new phase after the final sweep. A video stands for a
      chapter in a novel, novella or story, and for an episode in a video
      series or podcast (confirmed 26 Nov). **Still to answer, in
      F.0's design:** the exact words for each kind; how a true story is
      marked; where a video file is kept (copied or linked).
      *Answered 26 Nov in F.0's seven questions below.*
- [ ] **F.0: review the project-kinds design** (its brief, section
      *Design*). In short: the kind is one key in the project file, written
      only when the kind is not Novel, so **a Novel project's file never
      changes**. One module holds the kinds and their words; for a Novel
      every screen shows exactly today's text. Kind-only data (minutes,
      targets, series status, People, dates, which card is a chapter's
      video) goes in a new `<project>.kind.json`, and sources in a private
      `<project>.sources.json`, each made only when first used. Changing
      kind deletes nothing and offers Undo. New Project gains a Kind field;
      the kind is changed in Revise ▸ Prose Profile ▸ Project Targets.
      Build order: F.1, F.14, F.2, F.3, then spoken (F.4, F.10, F.5, F.6,
      F.11, F.13), then nonfiction (F.7, F.8, F.9, F.12), then F.15. Then
      answer:
      1. **The words.** Main manuscript: Main channel (Video series), Main
         feed (Podcast), Main column (Editorial series), Main collection
         (Journalism); Novella: Series, Season, Series, Series; Chapter:
         Video, Episode, Part, Article; a heading inside one: Section or
         Segment; "Project" stays. Recommended: as listed.
      2. **A true story** is a tick, not a sixth kind; not shown for
         Editorial series or Journalism (always true); also offered for a
         Novel (memoir). Recommended: yes.
      3. **A chapter's video is copied into the project** (the Studio's
         rule today), with its size and the free space shown first for
         files over 1 GB. Recommended: yes.
      4. **The one visible change in a Novel project** is the Kind row in
         Prose Profile and in New Project. Recommended: accept.
      5. **Marking in a script:** `## Heading` for sections (they become
         timestamps), `[B-ROLL: …]`, `[MUSIC: …]`, `[AD BREAK]` for cues,
         `HOST: …` for a speaker (only known names count). Recommended:
         accept.
      6. **Each kind's export takes Publisher Ready's place** in its
         Export menu (Script, Transcript, Article), so no menu grows.
         Recommended: yes.
      7. **Series status:** drafted and revised come from the chapter
         stages; only planned, recorded (or filed) and published are
         stored. Recommended: yes.
      *Answered 26 Nov (the recommendations, all seven): 1. the words as
      listed; 2. a tick, not a sixth kind; 3. copied into the project;
      4. accepted; 5. accepted; 6. yes, it takes Publisher Ready's place;
      7. yes. Recorded in README decision 18 and the F.0 brief. F.1 can
      start after 9.1.*
- [ ] **A bug the design found, already affecting novels: moving a chapter
      can lose its Studio cards.** When D.10's move has to give a chapter a
      new id (another chapter in the target has the same one), it updates
      the characters' readings but not the Studio's cards and decks, which
      keep the old id. The cards stay in the Studio, but no longer belong
      to the chapter. Rare (ids are random; it needs a chapter copied
      between manuscripts), but it should not happen. Fix it as a small
      piece now (the Studio's chapter ids join the move and its Undo)?
      Recommended: yes, next.
      *Answered 26 Nov: yes, next ("Studio cards follow a moved chapter",
      section 5).*
- [ ] **Three more things the design found (no action now; for the
      pieces named).** (a) Saving writes every field of the project with
      its default, so any new field on a project, chapter, character or
      card would change every Novel project's file; phase F adds no field
      to them (F.1 tests it). (b) The Studio stores full paths to its
      media, so a moved project folder loses them (F.10 looks in the
      project's own folder first). (c) The export uses the open
      manuscript only; a novella is exported by opening it first (F.14
      fixes this).
- [ ] **U.3a: two things.** (a) **Read Aloud at exactly 1024 px.** With
      the side panel closed, 🗣 Read Aloud now sits behind the toolbar's
      ››, because the chapter list takes its natural 250 px (before, the
      editor's oversized minimum squeezed it to 228). Narrow the list to
      about 220 px on every screen to bring Read Aloud back, or keep it?
      Recommended: keep (it is one click away, and the list's names are
      easier to read). (b) **Wrapping rows.** The Companion's note buttons
      and the scorecard legend now wrap onto a second line in a narrow
      panel, instead of making the panel wider. Keep? Recommended: keep.
      *Answered 26 Nov: (a) keep. (b) Wrap only where it doesn't look odd:
      **shorten, then wrap.** Details (the legend, notes text) wrap freely.
      Titles and headings never wrap: they shorten with … and show the full
      text on hover. Buttons first switch to shorter words, icon kept, full
      name in the tooltip (💡 Suggest fix → 💡 Fix, Mark beat done → ✓ Beat,
      Dismiss → ✕), and wrap only if that still doesn't fit. Icon-only
      buttons stay only where they already are (🗑️). Applied in U.3b, to
      U.3a's rows too (the U.3b brief).* Built in U.3b (section 1).
- [ ] **7.2: three things.** (a) **Which model the Critique uses.** With
      no Critique model chosen, it falls back to your Plot model
      (`model_for_plot`: Cydonia 24B, in `~/.creativeos/config.json`); the
      tension proof ran on Gemma 4 26B (your main local model). Choose
      Gemma for the Critique (Settings, one choice), or have a session rerun
      the proof on Cydonia (app closed)? Recommended: rerun on Cydonia, so
      the proof holds for the model you actually use.
      *Answered 27 Nov: try Cydonia as well.* **Done 27 Nov: Cydonia fails
      the bar, Gemma passes** (7.2's Outcome, addendum). Cydonia's tension
      answers could be read only 29% of the time (it rates beats in its own
      format and runs out of room); its judgement itself is steady. Its
      scene outline is better (finer scenes, no fake scenes, Born in Blood
      ch. 1 read correctly: 0 of 4 "changes nothing" against Gemma's 4 of
      4), but it is about 7 times slower (about 80 s a chapter against 12).
      With Cydonia today the app shows no tension and no check is affected,
      but it asks the unreadable tension question again on every check
      (about 19 s a chapter). Nothing changed. **Three answers needed:**
      1. **Stop the wasted request:** remember "couldn't be read" with the
         chapter's text, so a model that fails isn't asked again until the
         chapter changes. Recommended: yes, a small fix.
      2. **The Critique's model:** Gemma (tension works, about 7× faster)
         or Cydonia (better scene reading, no tension). One model does both
         (rule 2: no per-request model setting). Recommended: Gemma if the
         tension curve matters to you; Cydonia if the outline matters more.
      3. **A firmer tension prompt** (pre-filled answer line), then rerun
         the proof on both models: later, optional. Recommended: yes, as a
         small piece after 1, since it could give Cydonia tension too.
      For (c), "changes nothing": with Cydonia it reads as plausible quiet
      beats; Gemma's misreading caused the over-flagging. Recommended: keep
      it on.
      *Answered 27 Nov: 1. yes, stop the wasted request. 2. Tension
      matters more, and the better substantive model matters; the model
      stays yours to choose in Settings (the Critique's model; nothing
      hard-wired). Until step 3 says otherwise, choose Gemma as the
      Critique's local model there. 3. yes, a firmer prompt and a rerun on
      both models. Queued after 7.4 (1 needs no model; 3 runs with the app
      closed).* **Done 27 Nov (round 13):** 1 built; 3: both pass with the
      new prompt (Gemma kappa 1.00 / 0.96, Cydonia 0.85 / 0.78; Cydonia only
      uses 3 to 5, Gemma 2 to 5). **Your choice in Settings ▸ the Critique's
      model:** Gemma (recommended: steadier, fuller curve, about 6× faster)
      or Cydonia (finer scenes, no false "changes nothing"). Note: chapters
      rated with the old prompt keep those ratings until they change, so a
      book can mix the two (all within one point on Gemma).
      (b) **Scene breaks.**
      Your chapters have no break lines, so the outline and the chart see
      one scene per chapter (the model found 1 to 6). Adding `***` between
      scenes gives the chart a point per scene and plan matching more to go
      on. Your call as the writer; nothing changes if you don't.
      *Answered 27 Nov: add markers for scenes, but not in the text. Brief
      written: [7.4 Scene markers](pieces/59b-7.4-scene-markers.md) (kept
      beside the chapter; added from the outline's "Use the model's scenes"
      or the right-click; shown as a margin line; exports unchanged unless
      you tick "Mark scene breaks"). Built after the Cydonia run.*
      (c) **"Scenes that change nothing"** over-flags on this model (all
      four of Born in Blood ch. 1). Keep the check on, turn it off by
      default, or decide after (a)? Recommended: decide after the Cydonia
      rerun.
- [ ] **7.4: four things.** (a) **Where "Scene break here" sits.** To keep
      the right-click count at 7 / 11, More ▸ 📝 Add Annotation became a
      submenu, More ▸ 📝 Note or scene break ▸ (Add Annotation, View
      Annotations, Scene break here), counted as one 📝 group, as the
      toolbar's 📝 is. Add Annotation is one level deeper on the right-click
      (still one click on the toolbar and Ctrl+Shift+N). Keep that, or put
      the scene entry straight in More ▸ and raise the baseline by one?
      Recommended: keep. (b) **Publisher Ready** ignores markers (it has no
      dialog). Always mark them there, or never? Recommended: always, since
      a publisher-ready file should show scene changes. (c) **The export
      tick** starts off each time. Remember your last choice? Recommended:
      yes, per project. (d) **Older tension ratings** stay hidden for a
      chapter once it is marked, until the next check with the model rates
      the marked scenes. Fine? Recommended: fine.
- [ ] **V.4: the real trial (information).** No measurable gain and no
      harm (+0.007, within chance on 16 pairs). Keep V.4 as built?
      Recommended: keep (it does what it was built for); revisit with your
      own blind ratings later if you want proof.
      *Answered 27 Nov: keep as built.*
- [ ] **D.11: three things found while retiring.** (a) **Two old
      windows kept in the code, with no way in:** the old Suggestions
      (`PassageCritiqueDialog`) and Overly descriptive? (`ExpandStatementDialog`)
      windows. The Improve window uses parts of their modules and about a
      dozen tests check features through them. Delete them too (moving those
      tests onto the Improve window)? Recommended: yes, in 9.1's sweep.
      (b) **"Turn main manuscript into a novella…"** still uses the older
      copy, check and delete move. Bring it onto D.10's move with Undo, like
      "Move main chapters into this novella"? Recommended: yes, a small
      piece. (c) **A bug that predates this:** a chapter's saved copies
      (`backup_*.md`) are named to the second, so two saves in the same
      second write the same file (the earlier copy of that second is lost;
      rule 15). Fix it as a small piece (a unique name, nothing else
      changes)? Recommended: yes, next.
      *Answered 27 Nov: (a) delete every old window that can no longer be
      reached (not waiting for 9.1). (b) yes, use the undoable move, and
      warn people plainly about anything that cannot be undone. (c) yes,
      fix the backup bug. Built as one piece, D.12 (round 14).*
- [ ] **U.3b: three things.** (a) **The short words.** ⭐ Excellent →
      ⭐ Best, Save for training → Save, and in the Studio 🎤 Slides,
      📑 Export, ✨ Refine (the full words return when there is room and
      always head the tooltip). Right, or name others? (b) **"➕ Add
      Hierarchy" always reads "➕ Add"**, because World's hierarchy column is
      capped at 250 px on every screen. Keep, or widen the cap to about
      290 px so the full words show on larger screens? Recommended: widen
      (one number; nothing else moves). (c) **The Studio toolbar at
      420 px** takes five lines, about half the height. Folding Save,
      Load, Arrange, Clear and Fit into one "Board ▾" menu would make it
      three, but that is a declutter piece (it changes what is on
      screen), not a sweep. Do it as a small piece, or leave it?
      Recommended: a small piece, with the next D.8 session.
      *Answered 26 Nov: (a) the short words are fine. (b) widen: the cap is
      290 px, so "➕ Add Hierarchy" reads whole. (c) show Save and Load and
      fold the rest into a "+" menu: done (Arrange, Clear, Fit behind "+";
      `video_studio` in `screens_baseline.json` is now 10 buttons and 1
      grouped menu entry, was 12 and 0).*

## 4. For every piece from here on

The routine from the README, as a checklist:

- [ ] Read the brief, including *What has changed since this brief was
      written* and *Build notes*. Write any changes under *Review notes*.
- [ ] Start a fresh session: "Do the piece in docs/publishing/pieces/NN-….md.
      Read docs/publishing/README.md first."
- [ ] The session ends with: its tests passing, the full suite run once,
      screenshots for a piece with a screen, the *Outcome* filled in, the
      tracker ticked, **this checklist updated**, nothing committed.
- [ ] For a piece that changes a screen: the capability checklist is ticked,
      and the before-and-after test shows chapter text unchanged (rule 11,
      *Updating the app*).
- [ ] Try it on a real project. Commit if you are happy.
- [ ] If the piece changed something a later brief assumes, check that
      brief's *What has changed* section was updated.

## 5. The remaining pieces, in order

**A. Simplify the interface** (no model needed; display only unless noted)
- [x] [R.7](pieces/22b-R.7-one-state-file-per-project.md) One state file per project — built, for review
- [x] [D.6](pieces/48b-D.6-retire-the-trial-screens.md) Retire the trial screens — built, for review
- [x] [D.1](pieces/44-D.1-tidy-the-right-click-menu.md) Tidy the right-click menu — built, for review
- [x] [D.7](pieces/48c-D.7-show-less-at-once.md) Show less at once — built, for review
- [x] [D.9](pieces/48e-D.9-fewer-interruptions.md) Fewer interruptions — both sessions built, for review (116 boxes quiet across every screen in the main window; boxes in separate windows stay, see section 3)
- [x] [D.8](pieces/48d-D.8-one-look.md) One look — two sessions built, for review (Write, Companion, Critique, Settings; then Plot, Characters, World, Visuals, Video Studio, Publishing, Drafts, Print). Left for a later session if wanted: Training Studio, the assistant, Video Studio's editors
- [x] [D.4](pieces/49-D.4-fewer-top-level-tabs.md) Fewer top-level tabs (reads saved window layouts) — built, for review
- [x] [D.2a](pieces/45-D.2a-one-improve-window-design.md) One Improve window: design — written and reviewed 25 Nov; the seven questions are answered (README open decision 16). D.2b can start.
- [x] [D.2b](pieces/46-D.2b-one-improve-window-build-with-suggestions-and-ex.md) — built 25 Nov, for review (section 1, "The One Improve window (D.2b)")
- [x] then [D.2c](pieces/47-D.2c-one-improve-window-rephrase-joins.md) — built 26 Nov, for review (section 1, "The One Improve window: Rephrase joins (D.2c)"). Every D.2 piece is done.
- [x] [D.5](pieces/49b-D.5-analyses-run-as-critique-reports.md) Analyses run as Critique reports (adds kinds to critique history) — built, for review
- [x] Two small fixes before the sweep (answered 26 Nov, section 3) — built 26 Nov, round 6: the grammar check's results handler that aborts in tests (a new module, call lines only in `enhanced_text_editor.py`); and the two old Rephrase slips (each rating stamped with the option you rated; "Auto-detect from text" back in the character-voice list; new rows only)
- [x] Shared-folder warning (answered 26 Nov, section 3) — built 26 Nov, round 6 (Save As and a new project's first save; ordinary saves never ask): warn when a project is saved into a folder that already holds another project file, since the two could collide over chapter folders. Touches saving, so a small piece of its own (rule 15: nothing overwritten)
- [x] [D.10](pieces/48f-D.10-manuscript-tree.md) — built 26 Nov, for review (section 1, "The manuscript tree (D.10)"). One manuscript tree on the left (your request, 26 Nov): manuscripts and novellas with their chapters in the left panel; chapters moved by drag-and-drop or right-click; the top row of manuscript tabs and Novellas ▾ go (behind a switch until retired). Before U.3, so the sweep sees the final Write screen
- [x] [U.3a](pieces/50-U.3a-fit-and-scroll-sweep-the-screens-used-most.md) — built 26 Nov, for review (section 1, "Fit and scroll on the screens used most (U.3a)"); ("➕ Add Hierarchy" fixed there, section 3 D.8 (c)); then [U.3b](pieces/51-U.3b-fit-and-scroll-sweep-the-remaining-screens.md) — built 26 Nov, round 9, reviewed 27 Nov (section 1, "Fit and scroll on the remaining screens (U.3b)"): the main window fits 1024 × 600 again; 58 screens pass at all sizes; narrow rows shorten, then wrap. Left for an optional second session: about 80 windows the harness cannot open yet (its Outcome)
- [x] Studio cards follow a moved chapter (answered 26 Nov, section 3) — built 26 Nov, round 9, for review (section 1, "Studio cards follow a moved chapter"; `chapter_move._retarget_studio`, `tests/test_chapter_move_studio.py`): when D.10's move gives a chapter a new id, the Studio's cards and decks for it take the new id too, and Undo puts them back. Small; touches the Studio's saved data, so rule 15 (nothing lost)
- [x] [D.11](pieces/48g-D.11-retire-the-old-screens.md) Retire the old screens — built 26 Nov, round 10, reviewed 27 Nov (you tried it: it passes) (section 1, "The old screens retired (D.11)"). once the four groups for them in section 1 are checked (D.4, D.5, D.2b and D.2c, D.10) and the 0.3 safety check has run on both projects (answered 26 Nov: avoid redundancy; the gate narrowed to those groups the same day): the old manuscript tab row (D.10); the old ten tabs and Settings ▸ Main tabs (D.4); the older whole-manuscript move brought onto D.10's undoable chapter move (answered 26 Nov); the old analysis windows and "Show in a window (old)" (D.5); the old Rephrase, Suggestions and Overly descriptive? windows and Settings ▸ Features ▸ Improve window (D.2c). One piece; stored settings left in place, unread (rule 11); counts go down, never up

**B. Better checks** (can run alongside A; no model needed)
- [ ] [P.5](pieces/30-P.5-fix-or-hide-the-worst-checks.md) Fix or hide the worst checks (after step 2's report)
- [x] [P.2a](pieces/31-P.2a-missing-reports-transitions-pronouns-alliteratio.md) Missing reports: transitions, pronouns, alliteration, acronyms — built, for review
- [x] [P.2b](pieces/32-P.2b-missing-reports-homonyms-sensory-detail-sentence.md) Missing reports: homonyms, sensory detail, sentence structure, diction — built, for review
- [x] [P.3](pieces/33-P.3-every-measure-compared-with-the-genre.md) Every measure compared with the genre — built, for review
- [x] [P.6](pieces/35-P.6-languagetool-in-full-with-its-larger-data-as-a-d.md) LanguageTool in full — built, for review (data installed: 15.4 GB in `~/.cache/language_tool_python/ngrams`)
- [ ] P.5 again, since the table changes after P.2 and P.6

**C. After the path** (no model needed)
- [x] [4.1](pieces/52-4.1-mark-as-intentional.md) Mark as intentional — built, for review
- [x] [4.3](pieces/54-4.3-checks-earn-their-place.md) Checks earn their place — built, for review
- [x] [7.1](pieces/57-7.1-reverse-outline-without-a-model.md) Reverse outline without a model — built, for review
- [x] [7.3](pieces/59-7.3-draft-beside-plan-and-the-tension-curve.md) Draft beside plan — built, for review (no-model tier)
- [x] [6.1](pieces/55-6.1-listen-and-mark.md) Listen and mark — built, for review (untried with a real voice)
- [x] [6.2](pieces/56-6.2-marks-become-notes.md) Marks become notes — built, for review
- [ ] [9.1](pieces/60-9.1-final-sweep.md) Final sweep (last: after the old screens are retired, U.3, and the rest of section 1 checked)
- [x] [9.2](pieces/61-9.2-export-and-import-check.md) Export and import check — built, for review
- [x] [P.8](pieces/36-P.8-character-analysis.md) Character analysis — built, for review (the arc part asks a model only when you click)

**D. Ratings by voice** (in order; V.1 copies the ratings database aside first)
- [x] [V.1](pieces/39-V.1-a-voice-fingerprint-on-every-rating.md) A voice fingerprint on every rating — built, for review
- [x] [V.2](pieces/40-V.2-voice-groups-without-a-model.md) Voice groups without a model — built, for review (thresholds calibrated on 64 published books)
- [x] [V.4](pieces/42-V.4-suggestions-learn-from-the-same-voice.md) Suggestions learn from the same voice — built, for review (the real gate needs a model)
- [x] [V.5](pieces/43-V.5-manage-ratings-by-voice.md) Manage ratings by voice — built, for review (Training Studio ▸ Browse rows ▸ "rated rewrites, by voice")
- [x] [V.3](pieces/41-V.3-a-model-names-and-refines-the-groups.md) A model names and refines the groups — built, for review (untried with a real model)

**D2. The writing habit** (no model needed)
- [x] [H.1](pieces/67-H.1-the-writing-habit.md) Daily and weekly goals, a streak shared across projects (cutting and revising count), a nudge to move on that you can turn off — built, for review

**E. Needs a model** (run with the app closed, or on the server)
- [ ] Try [8.2](pieces/65-8.2-editorial-letter.md) Editorial letter with a real model; it is built but untried
- [x] [7.4](pieces/59b-7.4-scene-markers.md) Scene markers kept beside the text — built 27 Nov, round 12, reviewed 27 Nov (section 1, "Scene markers (7.4)")
- [x] Tension follow-ups — built 27 Nov, round 13, reviewed 27 Nov (7.2's Outcome, second addendum; Cydonia now passes with the firmer prompt): remember an unreadable tension answer per chapter text so it isn't asked again; a firmer tension prompt; rerun the proof on Gemma and Cydonia (app closed)
- [x] [7.2](pieces/58-7.2-reverse-outline-with-a-model.md) Reverse outline with a model — built 26–27 Nov, round 11, for review (section 1, "The reverse outline with a model (7.2)"): tension proven (25 of 25 repeat ratings identical); scene readings and tension in the Critique's outline; the two checks were already on the scorecard. V.4's real trial ran in the same round (V.4's Outcome)
- [x] [4.2](pieces/53-4.2-voice-drift.md) Voice drift (prove the measure first; drop it if it fails) — dropped 26 Nov at its gate: the measure cannot tell a model's rewrites from your prose; proof in `scripts/voice_drift_gate.py`
- [x] [9.3](pieces/62-9.3-submission-package-and-marketability.md) Submission package and marketability — built 26 Nov, for review (untried with a real model; section 1, "The submission package (9.3)")

**F. When the server is connected**
- [x] [8.1a](pieces/63-8.1a-job-queue-design.md) Job queue: design — written and reviewed 26 Nov; the eight questions answered as recommended (README decision 17). 8.1b can start once the server is connected.
- [ ] [8.1b](pieces/64-8.1b-job-queue-build.md) Job queue: build
- [ ] [P.7](pieces/37-P.7-reader-s-eye-for-the-whole-book.md) Reader's eye for the whole book
- [ ] [8.3](pieces/66-8.3-server-prompts.md) Server prompts

**G. Optional and loose ends**
- ~~[P.1](pieces/38-P.1-side-by-side-comparison.md) Side-by-side comparison~~ dropped (decision 6, 24 Nov)
- [x] [0.3](pieces/03-0.3-safety-net-for-your-two-projects.md) The screen check that was left to follow — built, for review (run it on both projects: section 1)
- [x] The 4 old failures in `tests/test_overuse_context.py`: the test setup hid the WordNet data; fixed in `tests/conftest.py`
- [x] Your request (25 Nov): the chapter's prose profile — the Prose Profile tab measures the chapter open in Write (`src/ai/prose_snapshot.py`, `src/ui/prose_profile_chapter.py`); the AI chat answers "prose profile" at once and "review my prose" with the full report (`src/ai/prose_chat.py`) — built, for review

**H. Other formats: phase F** (after 9.1; your request, 26 Nov; README decision 18)
- [x] [F.0](pieces/70-F.0-project-kinds-design.md) Project kinds: design (no code) — written and reviewed 26 Nov: the seven questions answered as recommended (README decision 18). F.1 can start after 9.1.
- [ ] [F.1](pieces/71-F.1-project-kind-and-its-words.md) Project kind and its words (everything else needs it)
- [ ] [F.2](pieces/72-F.2-checks-by-kind.md) Checks by kind
- [ ] [F.10](pieces/80-F.10-a-chapters-video-in-the-studio.md) A chapter's video in the Studio (needs only F.1; can come early)
- [ ] [F.14](pieces/84-F.14-export-a-compilation-or-one-novella.md) Export a compilation, or one novella on its own (needs only 9.2; can come early)
- [ ] Spoken: [F.3](pieces/73-F.3-runtime-and-targets.md) Runtime and targets, [F.4](pieces/74-F.4-speakers-and-cues.md) Speakers and cues, [F.5](pieces/75-F.5-written-for-the-ear.md) Checks for the ear, [F.6](pieces/76-F.6-hook-and-retention.md) Hook and retention (a model adds to it)
- [ ] Nonfiction: [F.7](pieces/77-F.7-sources-list.md) Sources list, [F.8](pieces/78-F.8-unsourced-claims.md) Unsourced claims (a model adds to it), [F.9](pieces/79-F.9-people-and-timeline.md) Real people and the timeline
- [ ] Publishing: [F.11](pieces/81-F.11-video-and-podcast-packages.md) Video and podcast packages (a model adds to it), [F.12](pieces/82-F.12-article-export.md) Article export, [F.13](pieces/83-F.13-series-page.md) The series page
- [ ] [F.15](pieces/85-F.15-sweep-for-the-new-kinds.md) Sweep for the new kinds (last)

## 6. Finished when

- [ ] Every box in the README tracker is ticked or deliberately cut (the plan for novels ends at 9.1; phase F, other formats, follows it).
- [ ] Every check that is on by default meets the quality target (P.5).
- [ ] The harness counts are at or under `screens_baseline.json` on every
      screen.
- [ ] Both of your projects pass the safety check from 0.3, and open in the
      version of the app from before this plan with nothing missing.
