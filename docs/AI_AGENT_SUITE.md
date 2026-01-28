# AI Agent Suite - Cost-Effective Worldbuilding Assistant

## Overview

The AI Agent Suite provides intelligent assistance for worldbuilding, character development, and chapter analysis without writing your content for you. It uses a hybrid architecture to minimize costs while maintaining quality.

## Key Features

### 1. **Cost-Effective Hybrid Architecture**
- **Local Small Language Models (SLMs)** for simple tasks (free)
- **Cloud LLMs** for complex reasoning (paid, but optimized)
- Automatic routing based on task complexity
- Real-time cost tracking

### 2. **Worldbuilding Agent**
Helps create and develop worldbuilding elements:
- **Characters**: Suggest personality traits, backstory ideas, character arcs
- **Factions**: Develop goals, structure, conflicts, and relationships
- **Places/Locations**: Generate descriptions, key features, atmosphere
- **Consistency Checking**: Identify contradictions and logical issues
- **Map Suggestions**: Recommend interesting locations and features

### 3. **Chapter Analysis Agent**
Provides line-item editing suggestions:
- **Quick Review** (~$0.01): Overall impressions and top issues
- **Detailed Analysis** (~$0.05-0.10): Comprehensive feedback with line-item suggestions
- **Paragraph Analysis**: Specific feedback on pacing, show-don't-tell, dialogue
- **Consistency Checking**: Character voice and plot consistency

### 4. **Conversational Interface**
Natural conversation for all tasks:
- Create elements by describing what you want
- Ask for recommendations and ideas
- Request consistency checks
- Get feedback on specific aspects

## Cost Optimization Strategies

### Using Local Models

**Recommended Local Models** (ordered by performance/size):

1. **Microsoft Phi-3.5-mini-instruct** (3.8B parameters)
   - Best balance of quality and speed
   - ~4GB RAM required
   - Good for suggestions and simple analysis

2. **Qwen2.5-3B-Instruct** (3B parameters)
   - Excellent for creative tasks
   - ~3.5GB RAM required
   - Strong multilingual support

3. **Llama-3.2-3B-Instruct** (3B parameters)
   - Good general performance
   - ~3.5GB RAM required
   - Solid for recommendations

**When Local Models Are Used:**
- Simple suggestions (name ideas, basic recommendations)
- Quick reviews of short text
- Paragraph-level feedback
- Map element suggestions
- Initial brainstorming

**Requirements:**
- 8GB+ RAM recommended
- GPU optional but speeds up inference 10x
- First run downloads model (~2-4GB)
- Models cached locally for future use

### When Cloud LLMs Are Used

The system automatically routes to cloud LLMs for:
- Detailed chapter analysis
- Complex consistency checking across multiple elements
- Nuanced character development
- Plot structure analysis
- Long-form feedback

### Cost Comparison

**Example Tasks (approximate costs):**

| Task | Local Model | Cloud Model | Savings |
|------|-------------|-------------|---------|
| Name suggestions | $0.00 | $0.002 | 100% |
| Quick character ideas | $0.00 | $0.01 | 100% |
| Paragraph feedback | $0.00 | $0.005 | 100% |
| Quick chapter review | $0.00-0.005 | $0.01 | 50-100% |
| Detailed chapter analysis | $0.01 | $0.05-0.10 | 80-90% |
| Consistency check | $0.005 | $0.02 | 75% |

**Typical Session Costs:**
- **Light use** (10 interactions): $0.00-0.05
- **Moderate use** (30 interactions): $0.05-0.20
- **Heavy use** (100 interactions): $0.20-0.80

Compare to writing services:
- Professional editor: $50-200/hour
- AI agent session: $0.00-1.00/hour

## Usage Guide

### Setting Up

1. **Configure API Keys** (Settings > AI Configuration)
   - Add your Claude, ChatGPT, or Gemini API key
   - Select default provider

2. **Enable Local Model** (optional but recommended)
   - Check "Use Local Model (Cost Savings)"
   - Select preferred local model
   - First use will download model (~2-4GB)

### Creating Worldbuilding Elements

#### Characters

**Example conversation:**
```
You: Create a character who is a reluctant hero from a farming background

AI: I've drafted some character suggestions...
    Name: [suggests name fitting your world]
    Type: Protagonist

    Personality Ideas:
    - Practical and grounded from farm life
    - Initially resistant to adventure
    - Strong sense of duty to family

    Would you like me to:
    1. Add this character to your project
    2. Refine any aspect
    3. Generate additional ideas
```

#### Factions

```
You: I need a religious faction that secretly controls trade routes

AI: Here are some faction ideas...
    [Provides structure, goals, conflicts, and secrets]

    I can help you:
    1. Add this faction to your project
    2. Develop conflicts with existing factions
    3. Create key faction members
```

#### Places

```
You: Create a neutral city where different factions meet for trade

AI: Here are some ideas for this place...
    [Suggests name, key features, atmosphere, story relevance]

    I can help you:
    1. Add this place to your project
    2. Add it to a map
    3. Connect it to existing locations
```

### Analyzing Chapters

#### Quick Review (Cost-Effective)

```
You: Quick review of chapter 3

AI: **Quick Review of Chapter 3**

    Overall: Strong opening but pacing drags in middle section.

    Top Strengths:
    - Compelling dialogue between main characters
    - Vivid sensory descriptions
    - Clear chapter goal

    Areas to Improve:
    - Middle section (paragraphs 8-12) slows significantly
    - Too much internal monologue
    - Final scene feels rushed

    Cost: $0.01
```

#### Detailed Analysis

```
You: Detailed analysis of chapter 3

AI: **Comprehensive Chapter Analysis**

    [Provides overall assessment, strengths, improvements]

    **Line-Item Suggestions:**

    1. Paragraph 3
       Quote: "She felt sad about leaving."
       Type: Show Don't Tell
       Suggestion: Consider showing her sadness through actions
       Why: Stronger emotional impact
       Priority: High

    [4-6 more specific suggestions]

    Cost: $0.08
```

### Getting Recommendations

```
You: Suggest some interesting locations for my desert planet

AI: Here are 5 location ideas for your desert world:

    1. The Glass Sea - Ancient battlefield where sand
       was fused into glass by weapons
    2. Spiral Oasis - Water source protected by...
    [etc.]

    Cost: $0.002 (local model)
```

### Consistency Checking

```
You: Check if my new character contradicts existing worldbuilding

AI: **Consistency Check**

    Found 2 potential issues:

    1. Character's age conflicts with established timeline
       - Says born 20 years ago but event was 15 years ago

    2. Faction affiliation unclear
       - Worldbuilding says faction only accepts nobles
       - Character described as commoner

    Cost: $0.02
```

## Best Practices

### Maximizing Cost Efficiency

1. **Enable Local Model** for 50-100% cost savings on simple tasks
2. **Start with Quick Reviews** before detailed analysis
3. **Be Specific** in requests to get targeted responses
4. **Batch Similar Requests** rather than one-at-a-time
5. **Use Recommendations** for brainstorming (very cheap)

### Getting Better Suggestions

1. **Provide Context**: Share relevant worldbuilding before asking
2. **Be Specific**: "Suggest names for a water-based faction" vs "suggest names"
3. **Iterate**: Refine suggestions through conversation
4. **Ask Questions**: Agent asks clarifying questions when needed

### What AI Won't Do

The agent is designed to ASSIST, not WRITE:
- ✅ Suggests improvements
- ✅ Provides ideas and recommendations
- ✅ Points out issues
- ✅ Asks clarifying questions
- ❌ Doesn't rewrite your prose
- ❌ Doesn't generate full chapters
- ❌ Doesn't make changes automatically

## Technical Details

### Supported LLM Providers

**Cloud LLMs:**
- **Claude** (Anthropic): Best for creative writing tasks
- **ChatGPT** (OpenAI): Strong general performance
- **Gemini** (Google): Free tier available

**Local LLMs:**
- **Phi-3.5** (Microsoft): Recommended for balance
- **Qwen2.5** (Alibaba): Strong creative performance
- **Llama 3.2** (Meta): Solid general model

### System Requirements

**Minimum (Cloud Only):**
- Any modern computer
- Internet connection
- API key for chosen provider

**Recommended (Hybrid with Local Model):**
- 8GB+ RAM
- 10GB free disk space
- GPU optional but recommended
- Internet connection for cloud fallback

**With GPU:**
- NVIDIA GPU with 4GB+ VRAM
- 10-20x faster local inference
- Better experience with larger models

### Privacy & Data

**Local Model:**
- Runs entirely on your computer
- No data sent to external servers
- Completely private

**Cloud LLM:**
- Requests sent to provider's API
- Subject to provider's privacy policy
- Anthropic, OpenAI, Google have strong privacy practices
- Conversation logging optional

**Rated Conversations:**
- Stored locally in `~/.writer_platform/training_data/`
- Can be exported for fine-tuning your own models
- Never sent anywhere without explicit export

## Troubleshooting

### Local Model Issues

**"Failed to load local model"**
- Check RAM availability (need 4-8GB free)
- Ensure disk space for model download
- Try different model from dropdown
- Check internet for first-time download

**Slow Local Model Performance**
- First run is slower (model loading)
- Consider GPU acceleration
- Try smaller model (Phi-3.5 recommended)
- Reduce max_tokens in config

### API Issues

**"No API key configured"**
- Go to Settings > AI Configuration
- Add API key for your chosen provider
- Verify key is correct

**"API rate limit exceeded"**
- You've hit provider's rate limit
- Wait a few minutes
- Consider enabling local model
- Switch to different provider

### General Issues

**Agent gives generic responses**
- Ensure project is loaded for context
- Provide more specific requests
- Share relevant worldbuilding details

**Costs higher than expected**
- Check if local model is enabled
- Verify local model is actually loading
- Use "View Cost Stats" to see breakdown
- Consider using "Quick Review" mode

## Advanced: Fine-Tuning Your Own Model

The system can save high-quality conversations for fine-tuning:

1. **Rate Conversations** after agent interactions
2. **Export Training Data** from conversation store
3. **Use Export for Fine-Tuning** your own local model
4. **Train on Your Writing Style** for personalized assistance

This creates a model that understands YOUR worldbuilding and writing style, further reducing costs.

## Support

For issues or questions:
- Check troubleshooting section above
- Review AI configuration in Settings
- Ensure API keys are valid and have credits
- For local models, check system resources

## Future Enhancements

Planned features:
- Map generation assistance
- Plot outline development
- Character relationship mapping
- Multi-agent collaboration
- Voice input/output
- Integration with writing timeline
