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

**Where things stand** (25 November): everything up to and including
H.1, D.4, D.5, P.2b, 4.3 and the chapter's prose profile is **committed**
(d0d347e and 58226e9, after 0733233). **Built since, not committed, in
three rounds:**

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
  compares). The D.2a design for the One Improve window (for your
  review).

Tests: 1,834 pass in one run, none fail. No screen count rose above
`screens_baseline.json` in any of these (D.4's 5 top-level tabs, against
10 in the baseline, is still yours to agree).

What is waiting for you:

- **Try it (section 1).** Nothing there is ticked yet. The newest items,
  from the end: the screen check (0.3; run it on both projects), D.9's
  other screens, the model naming groups (V.3), managing groups (V.5),
  rewrites in the same voice (V.4), marks becoming notes (6.2), listen
  and mark (6.1), LanguageTool in full (P.6), voice groups (V.2), character
  analysis (P.8) and the voice fingerprint (V.1). Before them: the
  chapter's prose profile and everything earlier.
- **Stop the old LanguageTool servers** (about 40, left before the fix),
  with the app closed: `pkill -f languagetool-server`.
- **Run the genre script (P.3)** with the app closed:
  `venv/bin/python scripts/genre_baseline.py`, then `--show`.
- **The D.2a design is reviewed** (25 Nov). Its seven questions are
  answered (README decision 16), so D.2b can start when you say go.
- **Decide (section 3).** Open: D.4 (three), D.5 (two), 4.3, the
  Companion's chat, V.1 (the 1.9 GB copy; which rows shape groups), P.8
  (three), P.6 (keep the data), V.2 (two calibration choices), 6.1, V.4
  (three), V.5 (two), 6.2 (two), V.3 (two), D.9 (four
  kinds of box), D.8 (three), 0.3 (three). The rest are answered and
  marked so; their boxes are yours to tick.
- **Commit rounds 1, 2 and 3** when you are happy with them (end of
  section 1).
- **Next pieces (section 5): what remains.**
  - D.2b, then D.2c (D.2a is reviewed).
  - More one-look and fewer-interruptions sessions if you want them:
    Training Studio, the assistant, Video Studio's editors (D.8); boxes in
    separate windows (D.9, section 3).
  - Checks: P.5 after section 2's measurement (now that P.2 and P.6 are
    in).
  - Needs a model (run with the app closed): try 8.2; 7.2; 4.2; 9.3; and
    the real tests of V.3 and V.4.
  - When the server is connected: 8.1a (review the design), 8.1b, P.7,
    8.3.
  - Last: U.3a, then U.3b; then 9.1.

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
- [ ] With the cursor mid-chapter, listening starts at that sentence.
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
- [ ] **D.9: did a quiet message go somewhere you'd rather keep a box?**
      You said you'd likely have notes once you see it. Each moved message
      is one word to move back (``notify.done``/``notify.empty`` →
      ``QMessageBox.information``); name it under D.9's *Review notes*. Also
      still open: "Draft #N saved" and "Created draft …" stay boxes unless
      you say move them.
      *Answered 24 Nov: "Draft #N saved" and "Created draft …" are visible but no box: a bold, tinted status-bar line for 20 seconds. Done.*
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
- [ ] **D.4: when to retire the old ten tabs.** During the trial, Settings ▸
      ✨ AI Features ▸ Main tabs switches back to the ten (rule 11). When
      you have used the five groups on both projects and agree, a small
      step removes that switch, and the old `SecondaryWindow` (no longer
      used) with it; the stored setting is left in place, unread. Say when,
      or keep the switch for good.
- [ ] **D.4: reopen windows at start-up?** A screen left in its own window
      comes back into its tab when the app restarts (as the Critique's
      window always has: 2.5 recorded it but nothing reopened it). Keep
      that, or reopen whatever was out (a small change to what the app
      shows at start)?

- [ ] **D.5: when to retire the old analysis windows.** During the trial,
      each analysis's tab has "Show in a window (old)". When you have used
      the reports on both projects and agree, a small step removes the two
      old windows (`ProseAnalysisDialog`, `PromiseCheckDialog`) and that
      link. Say when.
- [ ] **D.5: the new reports in the full critique?** Promises, Prose
      profile fit, Character check, Plot vs plan and Writing hints run only
      from Analyze ▾ (and "Run again"). Adding them as tick boxes in
      Detailed critique would add five controls to the Critique. Keep them
      out, or add them (and to which runs: "Critique this chapter (all
      reports)" too)?

- [ ] **4.3: when is a check toned down?** Built: after at least 20
      answers to its fixes (Accept, Not a problem, intended; Skip does not
      count) with fewer than two in five accepted, since it was last
      brought back. Keep these figures, or name others (a later or earlier
      point, or a different share).

- [ ] **The chapter's prose profile: the Companion's chat too?** "Prose
      profile" and "review my prose" work in the AI Assistant chat (side
      panel). The Companion's chat doesn't know them yet. Add them there
      (a few call lines, no new controls), or keep one place for them?

- [ ] **V.1: the one-time copy of the ratings store.** Before it adds the
      fingerprints, V.1 copies the whole store aside once (rule 15):
      `rephrase_history.db.before-voice`, about 1.9 GB, because the store
      also holds about 200,000 downloaded corpus rows. Your own ratings are
      about 6,000 rows. Keep the full copy (safest; needs 1.9 GB once), or
      copy only your own rows (a few MB; the corpus rows can be downloaded
      again)? Nothing is copied until the app next opens.
- [ ] **V.1/V.2: which ratings shape the voice groups.** Only Rephrase
      ratings get a fingerprint. The 250 rows made from downloaded corpora,
      and rows with no project, are left out of the grouping (they aren't
      your voice) and keep working as today. Say if you want any kept in.
- [ ] **P.8: where it shows.** Built in both places: the full section on
      each character (Story ▸ Characters), and a scan of the chapter's
      characters in the Critique's Character check (no controls added).
      Keep both?
- [ ] **P.8: how sensitive.** An absence counts from 3 chapters. Speech is
      compared only in chapters where the character has 5 or more lines,
      against 8 or more elsewhere; a change is marked when line length
      doubles (and differs by 5+ words) or contractions, formality or
      swearing flip. Keep these, or name others after trying it?
- [ ] **P.8: two limits.** Novellas are analysed one manuscript at a time,
      not across all of them; the model's arc answer isn't saved (asked
      again after reopening). Worth more work, or fine as is?
- [ ] **P.6: keep the n-gram data?** It uses 15.4 GB. Harder confused
      words caught went from 13% to 38% (all seeded mistakes 71% → 75%),
      with no new false alarms on clean prose; the Q.2 table didn't move
      (its three misses, to/too and it is/its, aren't pairs the data
      covers). Remove in Settings ▸ Language deletes it.
- [ ] **Old LanguageTool servers still running.** About 40 were left by
      earlier app, script and test runs (24 and 25 November) before the
      fix; each holds memory. The session wasn't allowed to stop them.
      With the app closed: `pkill -f languagetool-server`.
- [ ] **V.2: two calibration choices (technical; confirm or ask).**
      "Same voice" was measured as the first half of a book against its
      second half (ratings come from different chapters), giving "alike"
      at 0.45 and "different" at 0.67, and 30 distinct passages before a
      project counts. And one source is split into two voices only at a
      higher bar (1.25): at the ordinary one, 29 of 55 single books split
      wrongly; at 1.25, 1 of 55. Naming narrators makes them separate
      sources anyway.
- [ ] **V.2: a group with one project** reads "very alike" (nothing to
      compare). V.5 will show "one project" instead, unless you prefer
      otherwise.
- [ ] **6.1: listening choices.** Built: it starts at the cursor's
      sentence (the top when the cursor is at the top); Space, M and Esc
      are taken over only while listening; M toggles a mark. With a neural
      voice each sentence is made separately, so there may be a pause
      between sentences: acceptable, or use the system voice for Listen?
      Listening across several chapters with marks is left out ("Read
      chapters…" is unchanged).
- [ ] **V.4: order of examples within a group.** Built: your "excellent"
      ratings first, then this project's, as today, and closest in voice
      within each. Measured without a model on 87 rated passages: voice
      fit 0.894, against 0.885 today and 0.871 for closest-in-voice alone
      (so that wasn't used). The big gain is a new book in a known voice:
      all its examples come from its own voice, against about half today.
      The real test, new rewrites with a model, is still to run.
- [ ] **V.4: a kept-to-itself project and the groups.** Its ratings are
      never used as examples elsewhere, but still help decide the voice
      groups. Leave them out of the grouping too?
- [ ] **V.4: where the switch is kept.** In a small file beside the
      project, `<project>.ratings.json`. If you rename or move a project,
      its old ratings keep the old path, so the switch no longer covers
      them. Fine, or worth handling?
- [ ] **V.5: where it lives.** In the Training Studio's Browse rows, the
      one screen that already lists and removes ratings, so you leave the
      writing app to reach it. A shortcut in the writing app would add a
      menu entry (rule 13). Add one, or keep it in the Studio?
- [ ] **V.5: changing a rating to Poor or Bad** leaves its "accepted" flag
      as it was (as rating changes always have). Should it also mark the
      rewrite as not accepted?
- [ ] **6.2: marks and stages.** Marks are line-stage fixes (they show in
      Next fixes at Line, always in the notes). The brief said "unless you
      say otherwise", but a control for it would add to a count. Keep as
      built, have marks follow the chapter's stage, or add a stage choice
      to Read Aloud ▾ → Marks in this chapter?
- [ ] **V.3: naming with only the on-device model.** The model is never
      loaded just to name groups, so names appear after something else
      (Rephrase) has loaded it. Right, or should opening the groups view
      load it?
- [ ] **V.3: the description shown.** The model's one line replaces the
      measured description in the tree (the measured one moves to the
      tooltip). Keep, or show both?
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
- [ ] **D.8: main buttons and two small things.** (a) Where a screen had
      a choice, "Add" was made the main button (the plan first, as on the
      Planner): Video Studio Add over Stitch, Publishing Add over Publish,
      Characters Add over Generate. Should any switch to the AI action
      when AI is set up, like the Planner? (b) The Plot screen and the
      Planner use slightly different greens and oranges for the arc
      stages: make them one set? (c) "➕ Add Hierarchy" reads "Add
      Hierarch" at 1024×600 (as before): shorten the label or widen the
      list?
- [ ] **D.9: four kinds of box left on purpose.** Say which to make quiet:
      (a) "Image saved to …" and the chapter-deck exports (4): a status
      line with Show file, like other exports? (b) "Open a project before
      saving / loading a storyboard" (2)? (c) the map tool's instructions
      (3): a status line lasts only 8 seconds, so keep them as boxes?
      (d) 165 boxes in separate windows (Training Studio 47, Video Studio's
      editors 74, Settings 10, others): give those windows a status line
      so they can go quiet too?
- [ ] **6.2: order and undo.** Marks come before other line fixes of the
      same standing. Clearing a mark has no undo (like Dismiss on notes
      today). Both fine?

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
- [ ] [D.2b](pieces/46-D.2b-one-improve-window-build-with-suggestions-and-ex.md), then [D.2c](pieces/47-D.2c-one-improve-window-rephrase-joins.md)
- [x] [D.5](pieces/49b-D.5-analyses-run-as-critique-reports.md) Analyses run as Critique reports (adds kinds to critique history) — built, for review
- [ ] [U.3a](pieces/50-U.3a-fit-and-scroll-sweep-the-screens-used-most.md), then [U.3b](pieces/51-U.3b-fit-and-scroll-sweep-the-remaining-screens.md) Fit-and-scroll sweep (last, so it sweeps the final screens)

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
- [ ] [9.1](pieces/60-9.1-final-sweep.md) Final sweep
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
- [ ] [7.2](pieces/58-7.2-reverse-outline-with-a-model.md) Reverse outline with a model (its two checks already exist)
- [ ] [4.2](pieces/53-4.2-voice-drift.md) Voice drift (prove the measure first; drop it if it fails)
- [ ] [9.3](pieces/62-9.3-submission-package-and-marketability.md) Submission package and marketability

**F. When the server is connected**
- [ ] [8.1a](pieces/63-8.1a-job-queue-design.md) Job queue: design. **Review the design before 8.1b.**
- [ ] [8.1b](pieces/64-8.1b-job-queue-build.md) Job queue: build
- [ ] [P.7](pieces/37-P.7-reader-s-eye-for-the-whole-book.md) Reader's eye for the whole book
- [ ] [8.3](pieces/66-8.3-server-prompts.md) Server prompts

**G. Optional and loose ends**
- ~~[P.1](pieces/38-P.1-side-by-side-comparison.md) Side-by-side comparison~~ dropped (decision 6, 24 Nov)
- [x] [0.3](pieces/03-0.3-safety-net-for-your-two-projects.md) The screen check that was left to follow — built, for review (run it on both projects: section 1)
- [x] The 4 old failures in `tests/test_overuse_context.py`: the test setup hid the WordNet data; fixed in `tests/conftest.py`
- [x] Your request (25 Nov): the chapter's prose profile — the Prose Profile tab measures the chapter open in Write (`src/ai/prose_snapshot.py`, `src/ui/prose_profile_chapter.py`); the AI chat answers "prose profile" at once and "review my prose" with the full report (`src/ai/prose_chat.py`) — built, for review

## 6. Finished when

- [ ] Every box in the README tracker is ticked or deliberately cut.
- [ ] Every check that is on by default meets the quality target (P.5).
- [ ] The harness counts are at or under `screens_baseline.json` on every
      screen.
- [ ] Both of your projects pass the safety check from 0.3, and open in the
      version of the app from before this plan with nothing missing.
