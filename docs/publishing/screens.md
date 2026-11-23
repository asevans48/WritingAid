# Screens: the map and the clutter baseline

Written by piece 0.2. It is the baseline for rule 13: no piece may raise a count
below, and the declutter pieces (D.1 to D.4) must lower them. When U.2's
harness exists it reports these counts itself and replaces this table.

## How the counts were taken

Each screen was built offscreen at 1440 × 900, with a two-chapter sample
project, no model and `HOME` set to a scratch folder. Counts are what the writer
sees **on first open**:

- **Buttons:** visible push and tool buttons that have text or an icon.
  Buttons inside closed sections or on inner tabs that are not showing are not
  counted.
- **Menu items:** items behind the screen's drop-down buttons, with submenus
  counted item by item.
- **Sections:** collapsible sections and group boxes.

Some counts move with the project. Plot shows one "+ Add event" button per
act, and Companion section headers show counts once there are items. So treat
a difference of one or two as noise, not as a change.

## Main window

| What | Count | Detail |
|---|---|---|
| Top-level tabs | **10** | Write, Plot, Characters, World, Attributions, Visuals, Prose Profile, Critique, Video Studio, Publishing |
| Sidebar tabs | **2** | AI Assistant, Chapter Outline (the sidebar collapses to a strip; it cannot be detached) |
| Menu bar menus | **7** | File (7), Drafts (3), Edit (3), View (4), Review (3 to 8, built when opened), Export (7), Help (3) |

## Each main screen

| Screen | Buttons | Items behind menu buttons | Sections | Inner tabs |
|---|---|---|---|---|
| Write (chapter editor, panel closed) | **24** | **29** (✓ Checks ▾, 🔍 Analyze ▾, 📄 Draft ▾, 🗣 Read Aloud ▾) | 0 | manuscript bar (main + one per novella) |
| Write side panel | — | — | — | **4**: Planner, Style, Feedback, Companion |
| · Planner | 8 | 0 | 2 | 5: Events, Description, Todo List, Notes, Subplots |
| · Style | 15 | 0 | 0 | 0 |
| · Feedback | 3 | 0 | 0 | 0 |
| · Companion | 18 | 0 | **7** | 0 |
| Plot | 10 | 0 | 0 | 6: Plot Events, Subplots, Promises, Tensions, Themes, Discuss with AI |
| Characters | 3 | 0 | 0 | 0 |
| World | 6 | 0 | 0 | 0 |
| Attributions | 1 | 0 | 1 | 0 |
| Visuals | 8 | 0 | 2 | 0 |
| Prose Profile | 0 | 0 | 1 | 0 |
| Critique | 11 | 0 | 4 | results tabs, one per report run |
| Video Studio | 12 | 0 | 2 | 0 |
| Publishing | 4 | 0 | 1 | 0 |
| Sidebar: AI Assistant | 8 | 0 | 0 | 0 |
| Sidebar: Chapter Outline | 1 | 0 | 0 | 0 |

## Right-click menus in the Write tab

| Where | Top-level entries | Items in all |
|---|---|---|
| Chapter text, no selection | **6** | **12** |
| Chapter text, with a selection | **11** | **22** (plus a Synonyms submenu when one word is selected, and View Annotations when the line has some) |
| Chapter list | 8 | 8, plus a Revert to Saved Copy submenu |
| Hover card on a flagged word (left-hover, not right-click) | — | up to 5 fixes, plus Ask, Ignore, and one of Suggest in context, Rewrite with AI or Add to dictionary |

The brief's "about eighty menu actions in the manuscript editor" counts every
menu action in the file, across menus that are never open at the same time.
The right-click menu itself has 12 to 22 items.

**Two things found while counting, for D.1:**

- **Cut and Copy never appear in the right-click menu.** The menu checks for a
  selection on a fresh cursor made at the click position
  (`ChapterEditor._show_context_menu`, `src/ui/manuscript_editor.py`), and
  that cursor never has one. Keyboard cut and copy still work.
- **The editor's own flag menu cannot be reached in the Write tab.**
  `EnhancedTextEditor._show_context_menu` (Replace with, Ask, Suggest in
  context, Rewrite with AI, Ignore, Add to dictionary) is disconnected by
  `ChapterEditor` and replaced with its own menu. The hover card
  (`ErrorCard`) offers every one of those actions, so nothing is lost. The
  checks menu's tooltip still says "Right-click a word for suggestions", which
  is no longer true.

## Screens that show problems or offer fixes

| # | Screen | Opened from | What it shows | What the writer can do |
|---|---|---|---|---|
| 1 | **Highlights + hover card** (`EnhancedTextEditor`, `ErrorCard`) | always on in the text | spelling, grammar, overused words, repeated phrases, style, each in its own colour | replace with a suggestion, ✨ Suggest in context, 💬 Ask, ✨ Rewrite with AI, Add to dictionary, Ignore |
| 2 | **✓ Checks ▾** menu | Write toolbar | which checks are on (spelling, grammar, overuse, style), mode (drafting / revising / auto), focus mode | toggle checks, re-check now, open Style panel, open Consistency |
| 3 | **Style** tab (`StyleIssuesPanel`) | side panel; Checks menu | every `style_checks` issue in the chapter, counts per check, one issue at a time | toggle each of the eleven checks, step through, apply the fix, ✨ Rewrite with AI, Ignore, open Consistency |
| 4 | **Companion** tab (`CompanionPanel`), 7 sections | side panel; banner above the text | Where you left off · Notes as you write · Today's three fixes · Overly descriptive (n) · Reader's eye · Story memory · Your style sheet | find three fixes, suggest a fix, Expand…, Go to, Dismiss, read as a reader, Ask |
| 5 | **Companion banner** | one line above the text | where you left off | Details opens the Companion |
| 6 | **Rephrase** (`RephraseDialog`) | ✨ toolbar, Ctrl+R, right-click | rewrites of the selection, with voice fit | pick and edit, rate, accept |
| 7 | **Suggestions** (`PassageCritiqueDialog`) | right-click | a critique of the passage and three rewrites, with a conversation panel | pick and edit, rate, accept, talk it through |
| 8 | **Overly descriptive?** (`ExpandStatementDialog` / `OverdescriptionPanel`) | right-click; Companion Expand…; Critique | over-described statements and ways to expand them | accept and edit an expansion |
| 9 | **AI Thesaurus** (`WorldWordDialog`) | right-click | world- and voice-appropriate word choices | replace the word |
| 10 | **Ask** (`FlagChatDialog`) | hover card; Companion | a conversation about one flag or note | get a better sentence, mark it deliberate (goes to the style sheet) |
| 11 | **🔍 Analyze ▾** menu | Write bottom bar | six separate AI analyses: promises and character consistency, prose (tone, style, voice), characters, worldbuilding, plot and pacing, writing hints | each opens its own result window (`PromiseCheckDialog` or `ProseAnalysisDialog`); also "Critique this chapter" and Consistency |
| 12 | **Critique** tab (`GraderWidget`) | top-level tab; Review menu; Analyze ▾ | 11 reports (Pacing, Voice, Tension, Plot, Dialog, Style, Canon, Grammar, Characters, Worldbuilding, Continuity), plus an Overdescribed tab; the numbers come from `ProWritingAnalyzer` | choose scope (chapter, selected chapters, manuscript, custom text) and reports, run, rate each report, save, load, export, ask the assistant about a suggestion, go to the line |
| 13 | **Review** menu | menu bar | critique of the chapter, main manuscript, each novella, continuity across novellas | runs the Critique; opens Consistency; opens the Critique tab |
| 14 | **Consistency** (`ConsistencyDialog`) | Checks menu, Analyze menu, Style tab, Review menu (four ways in) | names, spellings, hyphenation, capitals, numbers and punctuation that vary across the manuscript or project | pick the form to keep, Change all, jump to each occurrence |
| 15 | **Feedback** tab (`FeedbackWidget`) | side panel | the writer's own notes from beta readers, editors and workshops, per chapter | add, edit, delete entries; Analyze (needs a model) |
| 16 | **Planner** "Check vs Chapter" | side panel, Planner | whether the chapter follows its planned events | — |
| 17 | **Attributions** tab | top-level tab | every annotation (note, attribution, recommendation) across all chapters | filter, jump to the chapter |
| 18 | **📋 annotations list** | Write toolbar | this chapter's annotations | view, jump |
| 19 | **AI Assistant** | sidebar | anything the writer asks, including critique suggestions sent from the Critique tab | conversation |
| 20 | Readability and grammar status | Write bottom bar | Flesch-Kincaid for the chapter or selection; whether LanguageTool is running | — |

### Where they overlap

- **Style issues are shown in three places:** highlights with the hover card
  (1), the Style tab (3), and the Critique's Style report (12). The first two
  use `style_checks`; the Critique uses `ProWritingAnalyzer`, so its counts
  differ (see below).
- **"What to fix in this chapter" is listed twice:** the Style tab (3) and
  Companion's Today's three fixes (4).
- **Overly descriptive statements appear in three places:** Companion's
  section (4), the Overly descriptive? window (8) and the Critique's
  Overdescribed tab (12). They share `OverdescriptionPanel`.
- **Three rewrite windows with the same layout:** Rephrase (6), Suggestions
  (7) and Overly descriptive? (8): options, an editable preview, the
  changes, a rating. AI Thesaurus (9) and Ask (10) are smaller relatives.
- **Chapter analyses are done twice:** the six Analyze ▾ items (11) cover
  the same ground as the Critique reports (12): characters, worldbuilding,
  plot, pacing, and voice and style. The Analyze items show their results in
  separate windows that offer only Copy to Clipboard and Close. Their results
  are not saved, rated or kept in critique history.
- **Consistency has four ways in** (14).
- **Notes are listed in three places:** Attributions (17), the 📋 list (18)
  and Companion's Notes as you write (4). They are not all the same notes:
  annotations are the writer's own, while Companion's notes are the app's.

## Which screens can be detached today

- **Every top-level tab**, but only with View → Multi-Window Mode switched on:
  right-click the tab, then Create New Window. The last tab cannot be detached,
  and a detached tab can be merged back. (`MainWindow._show_tab_context_menu`,
  `SecondaryWindow`, `src/ui/window_manager.py`.)
- **Drafts** open in their own window (Drafts → Open Draft in New Window).
- **Cannot be detached:** the sidebar (AI Assistant, Chapter Outline), which
  collapses instead; and the Write side panel (Planner, Style, Feedback,
  Companion), which closes with Hide ✕ and reopens with ◧ Panel.

## What the Publishing and Feedback tabs already do

For pieces 1.1, 9.2 and 9.3.

- **Publishing** (`src/ui/agent_manager_widget.py`, 281 lines) holds a list
  of literary agent contacts (`AgentContact`: name, contact information,
  notes), stored in `project.agent_contacts`. Add and Remove work. **The
  other three buttons do nothing yet:** "Compose Email to Agent", "Publish
  to Kindle Direct Publishing" and "Publish to Barnes & Noble Press" each
  show a message saying it "will be implemented soon". The working exports
  (Kindle, Barnes & Noble, publisher-ready, Word, outline, LLM context,
  project summary) live in the Export menu, not in this tab.
- **Since 1.1** the Publishing tab also asks each manuscript's publishing route
  (agent submission or self-publishing) at the top of "Publishing Actions".
- **Feedback** (`src/ui/feedback_widget.py`, 486 lines) holds per-chapter
  entries, each with a title, a source (Beta Reader, Editor, Workshop, or
  typed in) and free text. They are stored in the chapter's
  `ChapterPlanning` as `ChapterFeedback`. "Analyze" sends the entries and
  the chapter to a model for a gentle summary. **With no model it shows an
  "AI Not Available" warning,** which breaks rule 1. Whichever piece next
  touches this tab should give it a plain no-AI result instead.

## `ProWritingAnalyzer` and `style_checks`: measured twice

Input to R.4.

| Measure | `ProWritingAnalyzer` (`src/utils/writing_stats.py`, moved by R.3) | `style_checks` (`src/utils/style_checks.py`) |
|---|---|---|
| Passive voice | yes (own helper-verb list) | yes (regex plus irregular participles and adjective exceptions) |
| Adverbs | yes (own `COMMON_ADVERBS` list) | yes (`-ly` rule with exceptions) |
| Clichés | yes (own `CLICHES` set) | yes (own, different `CLICHES` list) |
| Sticky sentences | yes (own `GLUE_WORDS`) | yes (own, different `GLUE` set) |
| Echoes | yes | yes |
| Long sentences | yes (long and very long) | yes |
| Readability | Flesch, for the whole text | hard-to-read sentences, one at a time |
| Weak intensifiers, wordy phrases, repeated starts, style sheet | no | yes |
| Dialogue share and tags, sentence variety | yes | no |

**Who uses which.** `ProWritingAnalyzer` is used only by the Critique
(`ChapterAnalysisAgent._get_stats` in `src/ai/chapter_analysis_agent.py`),
for its dashboard numbers and genre comparisons. `style_checks` drives the
highlights, the Style tab, the overdescription check, rewrite checking and the
style sheet.

**They disagree.** Here are the two run on the same 158-sentence sample (made
up for this test, so the numbers only show that they differ, not which is
right):

| Measure | `ProWritingAnalyzer` | `style_checks` |
|---|---|---|
| Passive | 51 | 51 |
| Adverbs | 59 | 31 |
| Clichés | 1 | 7 |
| Sticky sentences | 158 (every sentence) | 64 |
| Echoes | 148 | 85 |
| Long sentences | 14 | 14 |

So a writer can see one count in the Style tab and a different one in the
Critique's Style report for the same chapter. R.4 should keep one of the two,
using Q.2's numbers to pick.

**Resolved in R.4:** `ProWritingAnalyzer` now calls `style_checks` for all
five measures, so the Critique and the Style tab count the same things.
