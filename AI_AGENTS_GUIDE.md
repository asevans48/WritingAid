# WritingAid AI Agents Guide

This guide covers all AI agents and modes in WritingAid, with example queries and best practices for each.

---

## 📚 Table of Contents

- [Overview](#overview)
- [General AI Mode](#general-ai-mode)
- [Chapter Focus Mode](#chapter-focus-mode)
- [Writer Mode](#writer-mode)
- [Chapter Planning Assistant](#chapter-planning-assistant)
- [Text-to-Speech (TTS)](#text-to-speech-tts)
- [Cost Optimization](#cost-optimization)
- [Best Practices](#best-practices)

---

## Overview

WritingAid includes multiple specialized AI agents that work together to assist with every aspect of your writing:

- **General AI**: Conversational assistant that creates worldbuilding elements
- **Chapter Focus**: Deep chapter analysis and improvement suggestions
- **Writer Mode**: AI prose generation based on your outline and style
- **Chapter Planning**: Helps structure and organize chapters
- **TTS**: Multi-voice text-to-speech for manuscript narration

All agents have access to your full project context (characters, worldbuilding, plot, etc.) to provide consistent, contextual assistance.

---

## General AI Mode

**Purpose**: Create worldbuilding elements, answer questions, and manage your project through natural conversation.

**Access**: Main AI chat tab (default mode)

### What It Can Do

The General AI can **create and add** elements to your project by simply asking:

- ✅ Characters
- ✅ Places/Locations
- ✅ Factions/Organizations
- ✅ Cultures
- ✅ Myths & Legends
- ✅ Historical Events
- ✅ Technologies
- ✅ Flora (plants)
- ✅ Fauna (animals)
- ✅ Climate Presets
- ✅ Planets
- ✅ Star Systems
- ✅ New Chapters

### Example Queries

#### Creating Characters

```
"Add a character named Elena Martinez, a cybersecurity expert in her mid-30s.
She's brilliant but socially awkward, with a dry sense of humor."

"Create a villain named Lord Varken, ruler of the Shadow Realm.
Make him charismatic but ruthless."

"We need a comic relief character - a clumsy apprentice wizard"
```

**What the AI does:**
- Wraps your details in a `<create_character>` block
- Generates the character automatically
- Adds it to your Characters tab
- Confirms creation briefly, then stops

#### Creating Places

```
"Add a location called The Crimson Marketplace - a bustling bazaar
in the lower district where illegal goods are traded"

"Create a planet named Kepler-442c, Earth-like but with two suns
and massive oceans covering 90% of the surface"

"I need a fortress called Ironwatch Keep on the northern border"
```

#### Creating Historical Events

```
"Add a historical event: The Treaty of Broken Swords in year 1547.
It ended the century-long war between House Valen and House Kross,
but neither side truly won. The treaty is still contested today."

"Create an event where the fabricator was discovered by Dr. Chen
in 2157, changing humanity forever"

"Let's add the formation of the Blums dynasty - Werner Blum defeated
Robert Traust by controlling the fabricator and cutting off supplies
to Traust's faction"
```

#### Creating Worldbuilding Elements

```
"Add a climate preset for tropical coastal regions - hot, humid,
with monsoon seasons and frequent hurricanes"

"Create a technology called Neural Link - allows direct brain-to-computer
interface but has addiction risks"

"Add a medicinal plant called Silverleaf that cures infections
but is extremely rare"

"Create a predator species called Shadow Wolves - pack hunters
that can blend into darkness, highly intelligent"
```

#### Creating Chapters

```
"Add a new chapter where Sarah discovers the hidden laboratory
beneath the old factory"

"Create Chapter 12: The Betrayal - where Marcus realizes his
mentor has been working for the enemy"
```

#### Asking Questions

```
"What characters do I have in the resistance faction?"

"Tell me about the history of the Valen Empire"

"Which chapters mention the fabricator?"

"What factions are at war with each other?"

"Summarize the worldbuilding for my sci-fi setting"
```

### Response Style

The General AI is configured to be **concise and focused**:

✅ **Good Response:**
```
User: "Add a character named John, a blacksmith"
AI: "I've added John the blacksmith to your characters.
<create_character>
{
  "name": "John",
  "character_type": "minor",
  "personality": "Skilled craftsman with a gruff exterior",
  ...
}
</create_character>"
```

❌ **Bad Response (what it WON'T do):**
```
User: "Add a character named John, a blacksmith"
AI: "I've added John... Blacksmiths are interesting because historically
they played a crucial role... By the way, I noticed your Act 1 pacing
needs work, and Chapter 3 has character development issues..."
```

### Intent Detection

The AI recognizes when you want to **create** vs. just **discuss**:

**Will CREATE:**
- "Add a character named..."
- "Create a faction called..."
- "We need a villain who..."
- "Let's add a historical event..."
- "I want a new chapter where..."

**Will only DISCUSS:**
- "What kind of character would work here?"
- "Should I have a mentor?"
- "Maybe a corrupt merchant?" (use "yes, add them" to confirm)
- "Give me some ideas for..."

---

## Chapter Focus Mode

**Purpose**: Deep analysis of a specific chapter for pacing, consistency, character development, and prose quality.

**Access**: AI chat → Switch to "Chapter Focus" mode

### What It Can Do

- Analyze chapter pacing and structure
- Identify character voice issues
- Check consistency with established lore
- Suggest improvements to specific passages
- Review dialogue quality
- Check scene transitions
- Identify plot holes within the chapter

### Example Queries

#### Pacing Analysis

```
"Analyze the pacing of this chapter"

"Does this chapter feel too slow? Where does it drag?"

"The action scene feels rushed - how can I improve it?"

"Should I cut any of these scenes?"
```

#### Character Analysis

```
"Does Sarah's dialogue sound consistent with her character?"

"Is Marcus acting out of character here?"

"Check if the character voices are distinct in this conversation"

"Does Elena's reaction to the betrayal make sense given her backstory?"
```

#### Consistency Checking

```
"Check this chapter for inconsistencies with the established worldbuilding"

"Does this contradict anything from Chapter 3?"

"Verify that the technology use here matches what we established earlier"

"Is the timeline consistent with previous chapters?"
```

#### Prose Improvement

```
"This paragraph feels clunky - how can I improve it?"

"The opening is weak. Suggest a stronger hook."

"Are there any overused words or phrases?"

"How can I make this scene more vivid and immersive?"
```

#### Dialogue Review

```
"Is the dialogue here too on-the-nose?"

"Does this conversation sound natural?"

"The argument between Marcus and Elena feels flat - how do I fix it?"

"Should I use more dialogue tags or rely on action beats?"
```

#### Scene Transitions

```
"The transition from the marketplace to the fortress is jarring - fix it?"

"How do I smoothly move from this action scene to the quiet aftermath?"

"Should I add a scene break here or keep it flowing?"
```

### Analysis Depth Options

**Quick Review** (~$0.01):
```
"Give me a quick review of this chapter"
```
- Overall impression
- Top 3 strengths
- Top 3 areas to improve
- Few specific suggestions

**Detailed Analysis** (~$0.05-0.10):
```
"Give me a detailed analysis of this chapter"
```
- Comprehensive assessment
- 5-7 line-item suggestions with explanations
- Pacing and character consistency notes
- Paragraph-level feedback
- Specific examples with line references

---

## Writer Mode

**Purpose**: Generate actual prose for your chapters based on your outline, world, and style.

**Access**: AI chat → Switch to "Writer" mode

### What It Can Do

- Write complete scenes from your outline
- Continue from your cursor position
- Match your established writing style and voice
- Maintain character voices and POV
- Follow scene-by-scene structure
- Create smooth scene transitions
- Write in specified tone/mood

### Configuration

Before writing, configure:

1. **POV Settings**:
   - Character POV (whose perspective)
   - Narrative POV (first person, third person limited, omniscient)

2. **Chapter Planning** (in Story Planning tab):
   - Outline with scene list
   - Description of what happens
   - Tone (dark, lighthearted, tense, etc.)
   - Voice (lyrical, matter-of-fact, sardonic, etc.)
   - Pacing (slow build, rapid-fire, contemplative, etc.)

3. **Insert Mode**:
   - Insert at cursor
   - Replace selection
   - Append to chapter
   - Replace entire chapter

### Example Queries

#### Scene-by-Scene Writing

```
"Write the next scene from my outline"

"Continue writing scene 3 from the chapter plan"

"Write the opening scene - Sarah arriving at the abandoned factory"

"Generate the confrontation scene between Marcus and the villain"
```

**The AI will:**
- Look at your chapter outline
- Write the scene in order
- Match your specified tone/voice
- Continue from where you left off

#### Continuing from Cursor

```
"Continue from here"

"Keep writing this scene"

"Write the next 500 words continuing from my cursor"

"Finish this paragraph and continue the scene"
```

**The AI will:**
- Read text before your cursor for context
- Continue seamlessly in your style
- Maintain narrative flow
- Match established character voices

#### Specific Scene Requests

```
"Write an action scene where Elena fights off three attackers
in the narrow alley. Keep it fast-paced and visceral."

"Write a quiet moment where Marcus reflects on his father's death.
Make it introspective but not melodramatic."

"Generate dialogue between Sarah and Dr. Chen where she confronts
him about the lies. Sarah is angry but controlled; Chen is defensive."

"Write the reveal scene where the audience learns Marcus was
the traitor all along. Make it shocking but foreshadowed."
```

#### Stylistic Instructions

```
"Write this scene but make it darker and more ominous"

"Rewrite this passage with shorter, punchier sentences"

"Make this dialogue more natural and less expository"

"Add more sensory details to this scene"

"Write this in first person from Elena's POV instead"
```

### Important Notes

**Writer Mode vs. Other Modes:**
- Writer mode **generates prose** you can insert directly
- Chapter Focus mode **analyzes and suggests** but doesn't write
- General mode **creates project elements** but doesn't write scenes

**Scene-by-Scene Writing:**
If you provide a chapter outline with scenes:
```
Scene 1: Sarah arrives at the factory
Scene 2: She discovers the hidden door
Scene 3: Confrontation with the guard
Scene 4: Escape through the tunnels
```

The AI will:
1. Write Scene 1 completely
2. Then Scene 2, 3, 4 in order
3. Create smooth transitions between scenes
4. Follow your outline structure

**Continuity:**
- Writer mode reads the text before your cursor to continue smoothly
- It references your chapter outline to stay on track
- It maintains character voices and world consistency
- It follows your specified tone/voice/pacing

---

## Chapter Planning Assistant

**Purpose**: Help structure and organize your chapters before writing.

**Access**: Story Planning tab → Chapter Planning section → AI assistance

### What It Can Do

- Create chapter outlines that fit your story arc
- Suggest scenes and plot points
- Identify what needs to happen for story consistency
- Break complex chapters into manageable tasks
- Ensure character arcs progress appropriately
- Check for plot consistency
- Generate writing tasks (todos)

### Example Queries

#### Creating Outlines

```
"Help me outline Chapter 7 - this is where Sarah discovers
the truth about the fabricator"

"Create a chapter plan for the big confrontation between
Marcus and the Council"

"What scenes should I include in the chapter where Elena
infiltrates the compound?"

"Outline the final chapter - the climactic battle and resolution"
```

#### Scene Suggestions

```
"What scenes do I need to set up the betrayal reveal?"

"Suggest scenes that show Marcus's internal conflict"

"What should happen in this chapter to advance the romance subplot?"

"I need to get Sarah from the city to the mountains -
what scenes would work?"
```

#### Story Consistency

```
"What needs to happen in this chapter for the plot to make sense?"

"Check if this chapter plan contradicts anything from earlier"

"What unresolved threads from Chapter 3 should I address here?"

"Does this chapter advance the main plot or is it just filler?"
```

#### Task Breakdown

```
"Break this chapter down into writing tasks I can tackle"

"What research do I need to do before writing this chapter?"

"Create a checklist of scenes to write for this chapter"

"What character moments need to happen here?"
```

#### Character Arcs

```
"How should Elena's character develop in this chapter?"

"What character arc moment should Marcus have here?"

"This chapter feels like it's ignoring Sarah's emotional state -
what should I add?"

"Check that all POV characters get development this chapter"
```

### Response Format

The Chapter Planning AI provides **actionable suggestions**:

```
"For Chapter 7 (Sarah discovers the truth), here's a suggested structure:

Scene 1: Sarah investigates the old factory records
- TODO: Research 1940s industrial record-keeping
- TODO: Show Sarah's detective skills

Scene 2: She finds the hidden ledger
- TODO: Create tension - someone is watching
- TODO: Reveal first clue about the fabricator's origin

Scene 3: Confrontation with Dr. Chen
- TODO: Write dialogue where Sarah confronts him
- TODO: Chen's reaction reveals his complicity

Scene 4: Sarah's decision point
- TODO: Internal monologue - what to do with this information?
- TODO: Sets up the conflict for Chapter 8

Key Character Moments:
- Sarah must show her determination despite fear
- Foreshadow her breaking point in Chapter 10
- Show her growth from passive observer to active investigator

Consistency Checks:
- Verify the fabricator timeline matches Chapter 2
- Confirm Dr. Chen's position in the company
- Check Sarah's knowledge level - what should she know by now?"
```

---

## Text-to-Speech (TTS)

**Purpose**: Convert your manuscript to audio for listening/reviewing, or generate multi-speaker scripts for narration.

**Access**:
- Read button (🔊) in chapter toolbar
- Right-click → Text to Speech
- AI chat → ask TTS-related questions

### Features

1. **Simple Read Aloud**: Click Read button or select text and right-click
2. **Multi-Speaker TTS Documents**: Generate formatted scripts with speaker assignments
3. **Multiple TTS Engines**: pyttsx3 (offline), edge-tts (online), VibeVoice (multi-speaker)

### AI Queries for TTS

#### Getting Help

```
"How do I use text-to-speech?"

"tts help"

"What TTS voices are available?"

"Explain how VibeVoice works"
```

#### Checking Status

```
"tts status"

"Is text-to-speech available?"

"What TTS engine is active?"

"Check if VibeVoice is installed"
```

#### Voice Configuration

```
"Show me available voices"

"What voices can I use for narration?"

"tts voices"

"How do I configure different speakers?"
```

#### Generating TTS Documents

```
"Generate a TTS document for this chapter"

"Convert this chapter to a multi-speaker script"

"Create a TTS doc with speaker assignments"

"How do I generate audio with different voices for each character?"
```

#### Playback Control

```
"Stop TTS"

"Stop reading"

"Pause the narration"
```

### TTS Document Format

When you generate a TTS document, it creates speaker-assigned text:

```
Speaker 1 (Narrator): Sarah walked into the abandoned factory,
her footsteps echoing in the vast empty space.

Speaker 2 (Sarah): "Hello? Is anyone here?"

Speaker 1 (Narrator): A shadow moved in the corner. She spun around,
heart pounding.

Speaker 3 (Marcus): "I've been waiting for you."
```

**Output Location**: `~/.writer_platform/tts_output/{chapter_name}_tts.txt`

### VibeVoice Multi-Speaker Synthesis

For professional multi-voice narration:

1. Generate TTS document with speaker assignments
2. Install VibeVoice from Settings → TTS Settings
3. Run the generated document through VibeVoice
4. Get professional-quality multi-voice audio

**Available VibeVoice Voices:**
- **Carter**: Deep, authoritative male
- **Davis**: Warm, friendly male
- **Emma**: Clear, professional female
- **Frank**: Mature, steady male
- **Grace**: Soft, gentle female
- **Mike**: Energetic, youthful male
- **Samuel**: Distinguished, formal male

---

## Cost Optimization

WritingAid includes intelligent cost optimization features:

### Local Models

For cost-effective operation, enable local models:

**Settings → AI Configuration → Use Local Model**

- **Apple Silicon (M1/M2/M3/M4)**: Automatic MLX optimization
  - Default: `mlx-community/Qwen2.5-7B-Instruct-4bit`
  - Fast inference with 4-bit quantization

- **NVIDIA GPU**: PyTorch with CUDA
  - Default: `microsoft/Phi-3.5-mini-instruct`
  - Requires CUDA setup (see main README)

- **CPU**: Runs but slower
  - Recommend smaller models for better performance

### Hybrid Cloud/Local Strategy

The agent suite automatically routes requests:

**Local Model Used For:**
- Short questions (<300 characters)
- Worldbuilding recommendations
- Quick suggestions
- Chapter planning assistance
- Approximate cost: **$0.00** (free, but slower)

**Cloud Model Used For:**
- Element creation (ensures quality)
- Long-form writing (Writer mode)
- Deep chapter analysis
- Complex reasoning tasks
- Approximate cost: **$0.01-0.10** per request

### Cost Tracking

View cost summary:
```
Session cost tracking shows:
- Total session cost
- Breakdown by agent type
- Which model was used for each request
```

**Approximate Costs:**
- **General AI (element creation)**: $0.001-0.01 per element
- **Chapter Focus (quick review)**: $0.01
- **Chapter Focus (detailed)**: $0.05-0.10
- **Writer Mode (500 words)**: $0.02-0.05
- **Chapter Planning**: $0.005-0.02 (often uses local model)

---

## Best Practices

### General AI

✅ **Do:**
- Be specific with names and details
- Provide context about how elements fit your world
- Ask follow-up questions to refine elements
- Use confirmation ("yes, add it") for discussed ideas

❌ **Don't:**
- Ask vague questions like "give me ideas" if you want creation
- Forget to check the created elements in their respective tabs
- Create duplicate elements (check first: "what characters do I have?")

### Chapter Focus

✅ **Do:**
- Ask specific questions about issues you're noticing
- Request targeted feedback on problem areas
- Use quick reviews first, then detailed if needed
- Cite specific paragraphs or scenes for review

❌ **Don't:**
- Ask it to write new content (use Writer mode)
- Submit multiple chapters at once (do one at a time)
- Ignore consistency warnings about worldbuilding

### Writer Mode

✅ **Do:**
- Create a detailed chapter outline first
- Specify tone, voice, and pacing in chapter planning
- Set POV clearly before generating
- Review and edit generated prose (AI is a co-writer, not replacement)
- Use "continue from here" for seamless flow

❌ **Don't:**
- Expect perfect prose without any editing
- Generate without an outline (results will be unfocused)
- Forget to set insert mode (you might overwrite content)
- Use for brainstorming (use General AI instead)

### Chapter Planning

✅ **Do:**
- Include story context (what happened before)
- Ask for task breakdowns for complex chapters
- Request consistency checks with earlier chapters
- Use planning before writing in Writer mode

❌ **Don't:**
- Ask it to write the chapter (use Writer mode)
- Skip planning for important story moments
- Ignore character arc suggestions

### TTS

✅ **Do:**
- Use TTS to catch awkward phrasing when editing
- Generate multi-speaker docs for dramatic dialogue
- Configure different voices for character dialogue vs narration
- Save TTS docs for later processing with VibeVoice

❌ **Don't:**
- Expect perfect pronunciation of fantasy names
- Run TTS on entire manuscript at once (do chapter by chapter)
- Forget that TTS is for review, not publication

---

## Troubleshooting

### "Element not created"

**Problem**: You asked to create something but it only showed up as text.

**Solution**: The AI must wrap JSON in XML tags. Example:
```
✅ Correct:
<create_character>
{ "name": "John", ... }
</create_character>

❌ Wrong:
{ "name": "John", ... }  // No tags = won't be created
```

If this happens, tell the AI: "Please use the creation tags to add it to the project"

### "AI is rambling"

**Problem**: AI gives long responses when you just wanted element creation.

**Solution**: The prompt is configured to be concise. If rambling occurs:
- Say "keep responses brief"
- Report if it persists (may need prompt adjustment)

### "Writer mode ignoring my style"

**Problem**: Generated prose doesn't match your voice.

**Solution**:
1. Fill in tone/voice/style in Chapter Planning
2. Provide examples of your prose in chapter content
3. Give explicit style instructions in your prompt
4. Tell it to "match the style of the existing chapter content"

### "Local model is slow"

**Problem**: Local model taking too long to respond.

**Solution**:
1. Enable 4-bit quantization (Settings → AI Config)
2. Use smaller models (Phi-3.5-mini vs larger models)
3. On Apple Silicon, ensure MLX is being used
4. Consider disabling local model for faster cloud-only operation

### "Chapter Focus not seeing my edits"

**Problem**: AI references old version of chapter.

**Solution**:
- Auto-save should update, but manually save if needed (Ctrl/Cmd+S)
- Close and reopen chapter if context seems stale

---

## Advanced Features

### RAG (Semantic Search)

The agent suite includes a RAG (Retrieval-Augmented Generation) system that:
- Automatically finds relevant context for your questions
- Searches across all chapters, characters, worldbuilding
- Uses hybrid semantic + keyword search
- Reduces hallucinations by grounding AI in your content

**You don't need to do anything** - it works automatically when asking questions.

### Conversation Export

Export AI conversations for reference:
- **File** → **Export Conversation**
- Saves as JSON with timestamps and cost summary
- Useful for tracking creative decisions

### Multi-Window Workflow

For intensive writing sessions:
1. Open Writer mode in one window
2. Open Chapter Focus in another
3. Write → Review → Iterate quickly

---

## Quick Reference

| Task | AI Mode | Example Query |
|------|---------|---------------|
| Create character | General | "Add a character named..." |
| Create location | General | "Create a place called..." |
| Create event | General | "Add a historical event..." |
| Analyze chapter | Chapter Focus | "Analyze the pacing" |
| Check consistency | Chapter Focus | "Does this contradict Chapter 3?" |
| Write scene | Writer | "Write the next scene from my outline" |
| Continue writing | Writer | "Continue from here" |
| Plan chapter | Chapter Planning | "Outline Chapter 7" |
| Read aloud | TTS Button | Click 🔊 button |
| Multi-speaker TTS | TTS AI | "Generate TTS document" |

---

## Support

For issues or questions:
- Check this guide first
- Review main [README.md](README.md) for installation/setup
- Open GitHub issue for bugs or feature requests
- Check Settings → AI Configuration for API key issues

---

**Happy Writing with AI! 🤖✍️**
