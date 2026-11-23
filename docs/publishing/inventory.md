# What already exists

Most checks are a new view over code that is already there. This list comes from
reading module summaries, not every function. Piece 0.1 confirms it.

| Need | Already in the app |
|---|---|
| Spelling, grammar and style flags, judged by a model | the editor's highlighter, `src/ai/flag_judge.py` |
| Grammar engines (LanguageTool plus built-in rules), readability | `src/utils/proofing.py` |
| Eleven style checks: passive voice, adverbs, weak intensifiers, wordy phrases, clichés, repeated sentence starts, echoes, style sheet, long, hard-to-read and sticky sentences | `src/utils/style_checks.py`, `src/ui/style_panel.py` |
| Writing statistics: sentence variety, dialogue share and tags, overused words | `ProWritingAnalyzer` and `OveruseDetector` in `src/ui/enhanced_text_editor.py` |
| Consistency logic | `src/utils/consistency_checks.py` |
| Overly descriptive statements | `src/ai/overdescription.py` |
| Repetition | `src/ai/repetition_judge.py` |
| Dialogue problems, each character's way of speaking | `src/ai/dialogue_craft.py`, `src/ai/dialogue_speakers.py` |
| Pacing compared with published books by genre | `src/ai/pacing_analyzer.py` (`compare_to_genre`) |
| Continuity across the manuscript | `src/ai/continuity_analysis.py` |
| Names, spellings, hyphenation, numbers | `src/ui/consistency_dialog.py` |
| Order of events | `src/ai/event_order.py` |
| Settled story decisions, personal style rules | `src/ai/story_memory.py`, `src/ai/style_sheet.py` |
| Promises made to the reader, subplots, themes | `StoryPlanning` in `src/models/project.py` |
| Chapter critique and its history over time | `src/ui/grader_widget.py`, `src/data/critique_history.py` |
| Genre, tone and voice targets | `ProseProfile` in `src/models/project.py`, `src/data/genres.py` (includes comp titles) |
| Snapshots and per-chapter revisions | `src/services/project_checkpoint.py`, `ChapterRevision`, `src/ui/revision_dialog.py` |
| Export (Word, Kindle, Barnes & Noble, publisher-ready) | `src/export/manuscript_exporter.py` |
| Literary agent contacts, emails to agents, publish buttons | the Publishing tab, `src/ui/agent_manager_widget.py` |
| Detachable tabs and secondary windows | `src/ui/window_manager.py`, `src/ui/secondary_window.py` |
| The AI assistant's modes and actions | `src/ui/chat_widget.py`, `src/ai/chat_actions.py`; described in `docs/AI_AGENTS_GUIDE.md` |
| Read aloud | `src/services/tts_service.py` |
| Reader and editor feedback on a chapter | `ChapterFeedback` in `ChapterPlanning` |
| Daily fixes, notes, reader's eye | `src/ai/companion.py`, `src/ui/companion_panel.py` |

_Piece 0.1 corrects this file. Later pieces rely on it._
