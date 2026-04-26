# CreativeOS — Design Document

CreativeOS is a desktop launcher shell that hosts a growing suite of
creative and business tools. The first tool is the **Writing Tool**
(formerly "Writer Platform"). Future plans include **Business Agents**
(marketing copy, emails, briefs) and an **Online Platform** connector
that syncs projects to a CreativeOS account.

This document captures the architecture so contributors can extend
the OS without breaking existing tools.

---

## 1. Goals

- **Single launcher, many tools.** Users open one app, pick what they
  want to do. No hunting through separate desktop apps.
- **Shared LLM configuration.** Configure your provider, model, keys,
  and local-model preferences **once** and have every tool pick them up.
- **Per-tool overrides.** A tool can deviate from the shared defaults
  when it needs to (e.g. a faster model for inline rephrase suggestions).
- **Natural-language entry point.** When the user has an LLM set up,
  the launcher exposes an "Ask CreativeOS what to do" prompt that
  dispatches to the right tool.
- **Backwards compatible.** Existing Writing Tool installs migrate
  silently; the legacy `~/.writer_platform/ai_config.json` is read once
  to seed the OS config.
- **Easy to extend.** Adding a new tool is a registration entry, an icon,
  and a launcher callback.

## 2. High-level architecture

```
┌────────────────────────────────────────────────────────────────┐
│                       main.py (entrypoint)                      │
│   • Spawns QApplication                                         │
│   • Default route → CreativeOSLauncher                          │
│   • --writer flag → MainWindow (legacy direct boot)             │
└─────┬───────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────────┐
│                    CreativeOSLauncher (QMainWindow)              │
│   • Header (title, settings ⚙)                                  │
│   • Optional "Ask CreativeOS" prompt (only when LLM configured) │
│   • Grid of _ToolTile widgets, one per registered tool           │
│   • Emits tool_selected(tool_id)                                │
└─────┬───────────────────────────────────────────────────────────┘
      │ click / ask-AI
      ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Tool launchers                             │
│   • writing      → src.ui.main_window.MainWindow                 │
│   • business_*   → (placeholder, "coming soon")                  │
│   • online_*     → (placeholder, "coming soon")                  │
└─────────────────────────────────────────────────────────────────┘
```

### Files

| File | Role |
|------|------|
| `main.py` | Process entry — spawns QApplication and shows the launcher. `--writer` skips the launcher. |
| `src/config/creativeos_config.py` | OS-level config singleton + `default_tools()` registry + `apply_shared_llm_to_tool_settings()` helper. |
| `src/ui/creative_os_launcher.py` | The launcher window, tool tiles, ask-AI prompt, keyword router. |
| `src/ui/creativeos_settings_dialog.py` | Modal for editing the shared LLM config from the launcher's ⚙ button. |
| `src/config/ai_config.py` *(updated)* | Writing Tool's existing config, now layers OS shared LLM defaults underneath its persisted overrides. |

## 3. Configuration model

### Storage layout

```
~/.creativeos/
    config.json              # OS-level shared settings (LLM keys, model, etc.)
~/.writer_platform/
    ai_config.json           # Writing Tool's persisted overrides
~/.creativeos/<future-tool>/ # Reserved for future tools
```

### Resolution order (highest priority wins)

1. **Tool-specific persisted settings** (`~/.writer_platform/ai_config.json`)
2. **Shared CreativeOS settings** (`~/.creativeos/config.json`)
3. **Hard-coded `DEFAULT_SETTINGS`** in the tool / OS module

The Writing Tool's `AIConfig._load_settings()` implements this layering:
it starts from `DEFAULT_SETTINGS`, calls
`apply_shared_llm_to_tool_settings(settings, override=True)` to push
OS-level LLM choices on top, then applies the tool's own JSON as the
final override.

### Migration

On first launch with no `~/.creativeos/config.json`, the OS config tries
to read `~/.writer_platform/ai_config.json` and copies any keys it knows
about (provider, models, API keys, local model prefs). This means existing
users see their LLM access seamlessly carry over.

### Shared LLM keys (owned by `creativeos_config.SHARED_LLM_DEFAULTS`)

- `default_llm` — claude / chatgpt / gemini
- `claude_api_key`, `chatgpt_api_key`, `gemini_api_key`
- `huggingface_token`
- `claude_model`, `openai_model`, `gemini_model`
- `enable_local_models`, `prefer_local_model`
- `local_model_id`, `local_model_device`, `local_model_quantization`
- `local_model_trust_remote_code`
- `disable_all_ai`

**Per-task model overrides** (each is the name of a registered trained
model, or empty to fall back to the global model):
- `model_for_rephrase` — writing/rephrasing
- `model_for_plot` — plot/outline generation
- `model_for_worldbuilding` — places, factions, lore
- `model_for_character` — character profiles & backstories
- `model_for_general` — chat/lookup fallback

Resolved via `CreativeOSConfig.resolve_task_model(task)`. The Per-Task
Models tab in the settings dialog drives this. Tools call
`resolve_task_model` and use the returned trained-model entry if present,
otherwise their existing logic (cloud LLM or `local_model_id`).

**Data-collection opt-ins** (each gates one source-type pipeline):
- `enable_rephrase_data_collection`, `enable_chat_data_collection`
- `enable_worldbuilding_data_collection`,
  `enable_character_data_collection`, `enable_plot_data_collection`

Tool-specific things (Writing Tool's voice settings, spell-check engine,
TTS engine, keyboard shortcuts, etc.) stay in the tool's own config and
are NOT reflected at the OS level.

## 4. Tool registry

A `CreativeOSTool` is a dataclass:

```python
CreativeOSTool(
    id="writing",
    name="Writing Tool",
    description="Long-form writing with worldbuilding, drafts, and AI.",
    icon="✍️",
    available=True,
    config_subdir="writer_platform",
    keywords=["write", "novel", "story", "manuscript", ...],
)
```

The launcher reads the registry from `default_tools()`. To add a new
tool:

1. Add a `CreativeOSTool` entry to `default_tools()`.
2. Register a launcher branch in `main.py`'s `open_tool(tool_id)` that
   constructs the tool's QMainWindow and shows it.
3. Drop in keywords so the natural-language router can dispatch to it.

The launcher itself doesn't import tool windows — that wiring lives in
`main.py` so the config module stays import-safe and free of GUI deps.

## 5. Natural-language launcher

When `CreativeOSConfig.has_llm_configured()` returns True, the
"Ask CreativeOS" panel is shown above the tool grid.

Today the dispatcher is a deterministic keyword overlap scorer
(`CreativeOSLauncher._match_tool_by_keywords`). It's instant, offline,
and predictable — good enough until we have many more tools.

**Planned upgrade:** swap in an actual LLM call when the user has
configured one. The function signature is unchanged; only the
implementation is replaced.

## 6. Per-tool launching

`MainWindow` (the Writing Tool) is unchanged from a single-tool boot.
The launcher creates an instance and `show()`s it. Multiple tools can
run simultaneously — the launcher keeps a `dict[tool_id → QMainWindow]`
in `main.py`'s closure so windows aren't garbage collected.

The launcher itself stays open. Closing the launcher only quits the app
if no tool windows are still up; closing the last tool window quits Qt.
*(Qt default behavior; no special handling needed.)*

## 7. Backwards compatibility

- **Direct boot:** `python main.py --writer` skips the launcher and goes
  straight to MainWindow. Useful for shortcuts, file associations, and
  automated tests.
- **Legacy config:** `AIConfig` now layers OS shared LLM defaults under
  the existing tool config, so the Writing Tool reads exactly the same
  settings it always did *plus* anything new from the OS layer.
- **Old projects:** Project files unchanged. CreativeOS doesn't touch
  project data; it only orchestrates tool launching and shared LLM access.

## 8. Transfer learning data flow

CreativeOS supports an opt-in **collect → train → use** loop so users
can fine-tune a model on their own writing voice without ever sending
data off their machine.

### Where the data lives

```
~/.creativeos/
    rephrase_history.db      # SQLite — accepted rephrase pairs
    trained_models.json      # Registry of locally fine-tuned models
    trained_models/<name>/   # The fine-tuned model files (LoRA adapters)
```

### Capture (unified learning database)

`src/data/rephrase_database.py` is the single learning data store for
the whole app. Every row carries a `source_type` so the training
tool can mix sources freely or pick one at a time:

| `source_type`    | Where it comes from                                        |
|------------------|------------------------------------------------------------|
| `rephrase`       | Accepted/rejected suggestions from the Rephrase tool       |
| `chat_writing`   | Chat responses in writer/critique/creative modes           |
| `chat_general`   | Chat responses in general/lookup modes                     |
| `corpus`         | Synthetic pairs derived from user-uploaded writing samples |
| `agent`          | Outputs from agents that don't fit a more specific bucket  |
| `worldbuilding`  | LLM-generated places, factions, lore (worldbuilding agent) |
| `character`      | LLM-generated character profiles, backstories, voices      |
| `plot`           | LLM-generated outlines, plot beats, chapter plans          |

Each row records: source text, output text, style/tone, **voice**,
surrounding 500-char context, character name, genre, project path, and a
**rating** (excellent / good / neutral / poor / bad — same vocabulary
as `ConversationRating`). The `voice` column lets the user later train
selectively on rows tagged `voice=jane-austen` (for example).

Logging is gated by per-source opt-ins:
- `enable_rephrase_data_collection` — covers `rephrase`
- `enable_chat_data_collection` — covers `chat_writing` + `chat_general`
- `enable_worldbuilding_data_collection` — covers `worldbuilding`
- `enable_character_data_collection` — covers `character`
- `enable_plot_data_collection` — covers `plot`
- Corpus uploads are explicit user actions in the Training Studio,
  so they don't need a separate flag.

Convenience APIs on the database:
- `log_rephrase(source, output, rating=…)` — used by Rephrase dialog
- `log_chat(prompt, response, mode=…, rating=…)` — used by the chat
  widget; routes writer-style modes to `chat_writing` and other modes
  to `chat_general`
- `log_corpus_pair(prompt, completion, title=…, voice=…, genre=…)` —
  used by the corpus uploader in the Training Studio
- `log_worldbuilding(prompt, completion, element_type=…)` — used by
  the worldbuilding agent's faction/place generators
- `log_character(prompt, completion, character_name=…)` — used by
  the worldbuilding agent's character generator
- `log_plot(prompt, completion)` — used by the chapter-planning agent
- `counts_by_source()` — feeds the Training Studio summary

Capture is funneled through `src/data/learning_capture.py` so each
agent only needs a one-line call (`capture_worldbuilding(...)`,
`capture_character(...)`, `capture_plot(...)`) and the gating logic
lives in exactly one place.

#### Rating system (positive AND negative samples)

The Rephrase dialog has four rating buttons next to the preview:
**⭐ Excellent**, **👍 Good**, **👎 Poor**, **✖ Bad**. Behavior:

- Clicking **Excellent** or **Good** sets the rating that will be
  attached when the user accepts. If the user accepts without picking
  one, "good" is implied (they liked it enough to use it).
- Clicking **Poor** or **Bad** logs the currently-previewed suggestion
  **immediately** as a rejected sample (`accepted=False`, `rating=poor/bad`)
  even if the user keeps iterating. This is the most valuable kind of
  data — examples the user explicitly disliked — and it would be lost
  if we only logged on accept.

Negative-rated rows are essential for **DPO** (Direct Preference
Optimization). They're the "rejected" side of the chosen/rejected
pair the model learns to discriminate between. They are NEVER
included in standard SFT exports — only in DPO exports.

The same rating system already exists in the AI chat
(`src.ai.conversation_store.ConversationRating`); the rephrase
database keeps its vocabulary identical so a future merge of chat +
rephrase training data is trivial.

### Export (Training Tool, step 1)

`RephraseDatabase.export_jsonl(path, fmt, min_rating)` writes the
database in one of four formats:

- **`instruction`** — Alpaca-style `{instruction, input, output, metadata}`.
  Filtered by `min_rating` (default "good"); negatives are excluded.
- **`chat`** — ShareGPT/OpenAI-style `{messages: [system, user, assistant]}`.
  Same rating filter as instruction.
- **`dpo`** — Preference pairs `{prompt, chosen, rejected, metadata}`,
  built from positive (excellent/good) and negative (poor/bad) rows.
  Pairs prefer same-source matches; fall back to cross-source negatives
  so general avoidance patterns ("don't do purple prose") still teach
  even when no same-source negative exists.
- **`raw`** — full row dump for custom pipelines.

Stats reported in step 1 of the wizard include rating counts and
"DPO pairs available" so the user knows what they can train.

Exporting lets users fine-tune on a beefier machine (Colab, server)
when their laptop can't handle it.

### Model Builder Agent

The Training Studio's first step now opens with a **"Build Training
Recipe"** flow powered by `src/ai/model_builder_agent.py`. The user
describes what they want in plain English (e.g. *"a horror novelist
in my voice"*, *"a plot generator for sci-fi screenplays"*,
*"a worldbuilding generator for my fantasy setting"*) and optionally
constrains the goal (voice / plot / both / Q&A / worldbuilding /
character) and medium (books / movies / tv / short / mixed).

The agent returns a complete `TrainingRecipe`:
- `intent` (voice / plot / both / qa / worldbuilding / character)
- `medium`
- `source_types` to combine — including `worldbuilding`, `character`,
  `plot` for the new task-specific buckets
- `recommended_corpora` (catalog ids — never hallucinated; LLM output
  is validated against the catalog)
- `export_format` (instruction / chat / dpo / plot_prompt)
- `base_model`, `epochs`, `learning_rate`, `lora_r`

For `worldbuilding` and `character` intents the agent picks a smaller
base model with a smaller LoRA rank but more epochs, since these
data buckets tend to be smaller than full-corpus voice training data.

Two layers of intelligence:
1. **Heuristic backbone** — keyword-driven. Always runs and produces
   a workable recipe even with no LLM configured.
2. **LLM refinement** — when an LLM is available, the agent passes the
   catalog and the heuristic baseline to the model and asks for a
   refined recipe in JSON. Every field is validated against the
   catalog/whitelist before being applied; any LLM failure falls back
   to the baseline.

The recipe is rendered as a card and a single **"Apply Recipe"** click
pushes every field into the wizard widgets — source-type checkboxes,
base model, hyperparameters, format. The user can then tweak any
control before hitting Train.

### Public-domain corpus library

CreativeOS ships with a curated catalog of verifiably-public-domain or
permissively-licensed text corpora users can download to enrich their
training data — Project Gutenberg classics across genres (gothic,
romance, mystery, sci-fi, fairy tales), Aristotle's *Poetics* for plot
theory, Wikisource selections.

**Copyright stance:** The catalog only points at content with verified
public-domain or CC/MIT/Apache licenses. The downloader refuses to
fetch anything outside the safelist (`LICENSE_OK` in
`corpus_catalog.py`). Users can add their own URLs through the
"Add Custom URL" form, but they must explicitly attest that they have
the right to use that source — and the entry's license is stored as
`user-attested` so it's clearly distinguishable from safelisted content.

**Files:**
- `src/data/corpus_catalog.py` — built-in entries (read-only)
- `src/data/corpus_registry.py` — user-extensible registry stored at
  `~/.creativeos/corpus_registry.json`; combines with the catalog for
  the full list shown in the UI
- `src/data/corpus_adapters.py` — pluggable parsers per format
  (plain text, markdown, Project Gutenberg with header/footer
  stripping, EPUB, **LLM-assisted** for arbitrary markup)
- `src/data/corpus_downloader.py` — coordinator: license gate →
  download → adapter parse → log into the unified learning DB as
  `corpus` rows, with attribution recorded in the `notes` column

**LLM-assisted adapter:** When the user adds a corpus in an
unfamiliar format (Wikisource MediaWiki XML, OCR'd scans, mixed
markup) and the OS has an LLM configured, the `_parse_with_llm`
adapter chunks the raw text and asks the model to clean it into
paragraph-separated prose verbatim. Falls back to the plain adapter
if no LLM is available — never silently drops the corpus.

**Multi-narrative coverage.** The catalog now spans single-author
classics (Gutenberg novels) and multi-narrative datasets pulled from
HuggingFace:
- `hf-tinystories` — 2.1M synthetic short stories (MIT)
- `hf-rocstories` — 50K five-sentence plot-structure narratives (CC-BY)
- `hf-writingprompts` — Reddit prompt→story (user-attested)
- `hf-wikipedia-movie-plots` — 35K film synopses (CC-BY-SA)
- `hf-tvstorygen` — TV episode summaries (user-attested research data)
- `hf-gutenberg-multi` — multi-author Project Gutenberg pull (PD)

**Books3 is deliberately excluded.** It contained material from a
shadow library and is widely documented as redistributing
copyrighted books without permission. Users who insist on it must
register it themselves through "Add Custom URL" — and they must
explicitly attest to permission.

Each entry carries `purpose` (voice / plot / both), `medium` (books /
movies / tv / short / mixed), and `narratives` (rough count). The
Model Builder Agent uses these tags to filter recommendations to
exactly what the user is building.

**HuggingFace adapter.** `corpus_adapters.fetch_hf_dataset()` streams
rows from `datasets.load_dataset(... streaming=True)`. For voice
corpora it splits each text on the first sentence-end (prompt = first
sentence, completion = rest). For plot corpora it uses explicit
`hf_prompt_field` / `hf_completion_field` columns. Falls back
gracefully when the `datasets` package isn't installed (raises a
clear "pip install datasets" message rather than silently failing).

**UI:** The Training Studio's step 1 has a **🌐 Open Corpus Library**
button that opens a dialog listing all entries with license badges
(`✓ pd-us`, `⚠ user-attested`, etc.). Each entry has Download &
Ingest, Add Custom URL, and Remove (user entries only). Custom URL
adds always require an attestation checkbox.

### Train (Training Studio)

`src/ui/training_tool_window.py` runs a multi-step wizard:

1. **Describe & assemble** —
   - Free-text "what kind of model are you building?" prompt. A
     keyword-driven recommender steers the source-type checkboxes and
     suggests an export format (SFT vs DPO vs Chat).
   - Source-type checkboxes: **Rephrase / Chat-writing / Chat-general /
     Corpus / Agent**. The user can deviate from the recommendation.
   - **📚 Upload Writing You Like** button — pick `.txt`/`.md` files,
     each non-trivial paragraph becomes a corpus example where the
     prompt is the first sentence and the completion is the rest.
     This teaches the model to continue prose in the source's voice.
   - Live stats: per-source counts, per-rating counts, DPO pairs
     available, top genres.
2. **Base model OR continue from previous** —
   - Editable combo of base HF ids (defaults: `gemma-2-2b-it`,
     `Qwen2.5-1.5B-Instruct`, `Llama-3.2-1B-Instruct`,
     `Phi-3-mini-4k-instruct`)
   - Second combo "Or continue from:" lists every previously-trained
     model from `~/.creativeos/trained_models.json`. Picking one
     trains a NEW LoRA on top of that model — the original is never
     touched.
3. **Hyperparams** — name, epochs, learning rate, batch size, LoRA rank,
   plus a **Train on:** filter (Excellent / Excellent+Good / All)
4. **Train** — `_TrainingWorker` runs HF Trainer + PEFT (LoRA) in a
   background thread, streams logs and progress to the UI. Auto-exports
   the dataset using the picked source types and rating filter.

**No-overwrite guarantee:** When the user starts training with a
name that's already taken, the studio auto-renames the run
(`mymodel` → `mymodel-v2`, `mymodel-v3`, …) and tells the user.
Combined with LoRA's parameter-efficient layer-on-top design, every
training run produces a brand-new entry in the trained-models
registry while leaving every prior model intact on disk.

Output goes to `~/.creativeos/trained_models/<name>/` and the model is
registered via `register_trained_model(...)` in OS config.

If `transformers`/`peft`/`datasets` isn't installed, training fails
gracefully with install instructions and a pointer to the export step
so the user can run training elsewhere.

### Test (Training Tool, step 4)

The fourth wizard page loads the just-trained model and lets the user
rephrase a sample passage to sanity-check that the fine-tune learned
their voice.

### Use (Writing Tool)

The OS settings dialog (`creativeos_settings_dialog.py`) shows a
"Trained models" picker on the Local Models tab listing every entry
in `trained_models.json`. Selecting one fills the `local_model_id`
with that path; `AIConfig._load_settings()` already inherits this OS
setting, so the Writing Tool's Rephrase / Thesaurus / Chat all use
the trained model on the next launch.

For finer control there is a **Per-Task Models** tab. Each row
(rephrase, plot, worldbuilding, character, general) is a combo box
listing every registered trained model. Empty selection means "use
the global model." At call time the writing tool resolves the right
model via `CreativeOSConfig.resolve_task_model(task)` — so a user can
have a horror-trained voice model for rephrasing while a structured
worldbuilding model handles faction generation.

### Privacy stance

- Collection is **off by default** and explicit. The user must check
  the box in CreativeOS settings.
- Data never leaves the machine unless the user explicitly exports it.
- Each row records the project path so the user can audit / scope
  deletion later.

## 9. Future hooks

- **Online Platform:** OAuth flow lives in `src/online/` (TBD); shared
  account token persisted in `creativeos_config.json` and exposed to
  tools that opt in.
- **Business Agents:** Each agent class exposed as its own
  `CreativeOSTool` entry. They share the OS LLM configuration but ship
  with their own prompt templates.
- **Plugin tools:** When external developers want to add tools, they
  publish a Python package whose entry-point registers a
  `CreativeOSTool`. The launcher would scan a known entry-point group.
- **Chat data collection:** Same database pattern as rephrase, gated
  by `enable_chat_data_collection`. Will live in `src/data/chat_database.py`.
- **Eval harness:** Tag rephrase rows with quality scores so the user
  can train on only their highest-rated edits.

## 10. Notable code conventions

- The OS config module **must not import UI**. `default_tools()` is a
  pure data factory; UI launchers live in `main.py`.
- Every tool window inherits from `QMainWindow` and exposes
  `show()` / `raise_()` / `activateWindow()`.
- LLM client construction in tools should call
  `apply_shared_llm_to_tool_settings()` so the OS-level defaults are
  respected when the tool starts.
- New top-level menus inside a tool live in that tool's window — the
  launcher has no menu bar so it stays minimal.

## 11. Open questions

- Should the launcher quit when the last tool window closes, even if
  the launcher itself is still open? *(Currently: no.)*
- Where do tool-specific telemetry/log files belong — `~/.creativeos/<tool>/`
  or stay in each tool's existing dir? *(Default: stay where they are
  to minimize disruption; reconsider when adding new tools.)*
- Should "Ask CreativeOS" gradually expand into a true AI agent that
  performs cross-tool actions (open Writing Tool **and** create chapter
  X) rather than just routing? *(Phase 2.)*
