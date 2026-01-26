# WritingAid - AI-Powered Creative Writing Platform

A comprehensive desktop application for writers to organize, develop, and enhance their creative projects with AI assistance. WritingAid combines powerful worldbuilding tools, manuscript management, and integrated AI agents to streamline the entire writing process.

![Platform](https://img.shields.io/badge/Platform-Desktop-blue)
![Python](https://img.shields.io/badge/Python-3.10%2B-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## ✨ Features

### 📝 Manuscript Management
- **Rich Text Editor**: Full-featured editor with formatting, annotations, and revision history
- **Chapter Organization**: Organize your story into chapters with planning tools and story arcs
- **Word Count Tracking**: Automatic word count for chapters and entire manuscript
- **Multiple Export Formats**: Export to DOCX, PDF, EPUB, Markdown, and more
- **Version Control**: Track revisions and compare different versions of your chapters

### 🌍 Comprehensive Worldbuilding
Create and manage every aspect of your fictional world:

- **Characters**: Detailed character profiles with personality, backstory, relationships, and AI-generated portraits
- **Locations & Places**: Cities, landmarks, regions with full geographic details
- **Factions & Organizations**: Political groups, nations, corporations with leadership and allegiances
- **Historical Events**: Timeline of major events with consequences and interconnections
- **Cultures**: Customs, values, rituals, languages, and traditions
- **Mythology**: Legends, prophecies, and religious systems
- **Flora & Fauna**: Plant and animal species with habitats and ecological roles
- **Technology**: Inventions and innovations with applications and limitations
- **Planets & Star Systems**: Full astronomical details for sci-fi settings
- **Climate Presets**: Reusable climate types for consistent worldbuilding
- **Maps**: Interactive maps with places, landmarks, and events

### 🤖 AI-Powered Writing Assistance

#### Multi-Provider AI Support
- **Anthropic Claude**: Claude 3 (Opus, Sonnet, Haiku) and Claude 4 series
- **OpenAI**: GPT-4, GPT-4 Turbo, GPT-3.5
- **Google Gemini**: Gemini Pro and advanced models
- **Local Models**: Run models locally via Hugging Face Transformers (Llama, Mistral, Gemma, etc.)

#### AI Agents
- **General AI Assistant**: Conversational AI that can create worldbuilding elements, answer questions, and provide feedback
- **Chapter Analysis**: Deep analysis of pacing, character development, and consistency
- **Writing Assistant**: Helps write prose in your style with scene-by-scene guidance
- **Image Generator**: Generate character portraits and scene visualizations
- **Grammar & Style Checker**: AI-powered grammar, spelling, and style suggestions

#### Intelligent Element Creation
The AI can create worldbuilding elements directly through conversation:
- "Add a character named John, a blacksmith" → Creates character automatically
- "Add a historical event where the king was assassinated" → Creates event with details
- "Create a tropical climate preset" → Generates climate configuration
- And much more - just ask!

### 🎨 Image Generation
- **Character Portraits**: Generate AI images of characters (full body or headshot)
- **Scene Visualization**: Create images for locations and scenes
- **Multiple Backends**: Support for DALL-E 3, Stable Diffusion, FLUX, and local models
- **Apple Silicon Optimized**: Native MLX support for M-series Macs

### 📚 Story Planning
- **Plot Structure**: Organize your story with acts, beats, and narrative arcs
- **Story Events**: Track key events with positioning on the narrative arc
- **Scene Planning**: Break down chapters into individual scenes
- **Character Arcs**: Plan character development across the story
- **Themes**: Track thematic elements throughout your work

### 🔍 Advanced Text Analysis
- **Grammar Checking**: LanguageTool integration for grammar and style
- **Spell Checking**: Multiple dictionaries with contextual suggestions
- **NLP Analysis**: Part-of-speech tagging, dependency parsing, named entity recognition
- **Consistency Checking**: Find plot holes and inconsistencies across chapters
- **Readability Metrics**: Analyze reading level and complexity

### 🎯 Additional Features
- **Find & Replace**: Advanced search across entire manuscript
- **Auto-Save**: Never lose your work with automatic saving
- **Project Organization**: All project files stored in a single folder
- **Import/Export**: Import from various formats, export to multiple formats
- **Dark Mode Support**: Easy on the eyes for long writing sessions
- **Cross-Platform**: Works on Windows, macOS, and Linux

## 🚀 Installation

### Prerequisites
- **Python 3.10 - 3.13** (3.14 free-threaded builds are NOT supported for local models)
- **Git** (for cloning the repository)
- **Virtual Environment** (recommended for dependency isolation)

### Step 1: Clone the Repository
```bash
git clone https://github.com/yourusername/WritingAid.git
cd WritingAid
```

### Step 2: Create Virtual Environment
```bash
# Create virtual environment with Python 3.12 (recommended)
python3.12 -m venv venv

# Or use Python 3.10 or 3.11
python3.11 -m venv venv
```

### Step 3: Activate Virtual Environment
```bash
# On macOS/Linux:
source venv/bin/activate

# On Windows:
venv\Scripts\activate
```

### Step 4: Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5: Install NLP Models (Optional but Recommended)
```bash
# Download spaCy English model for advanced NLP features
python -m spacy download en_core_web_sm
```

### Step 6: GPU Support (Optional)

#### For NVIDIA GPU (CUDA)
If you have an NVIDIA GPU and want to use local models with GPU acceleration:

```bash
# First uninstall CPU-only PyTorch
pip uninstall torch torchvision torchaudio -y

# Install CUDA version (check your CUDA version with: nvidia-smi)
# For CUDA 12.x:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# Verify CUDA is working:
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

#### For Apple Silicon (M1/M2/M3/M4)
MLX is automatically supported for local models on Apple Silicon. For image generation:

```bash
pip install mflux mlx mlx-lm
```

### Step 7: Configure AI Providers
Create a `.env` file in the project root with your API keys:

```bash
# Anthropic Claude
ANTHROPIC_API_KEY=your_anthropic_key_here

# OpenAI
OPENAI_API_KEY=your_openai_key_here

# Google Gemini
GOOGLE_API_KEY=your_google_key_here

# Hugging Face (for model downloads)
HF_TOKEN=your_huggingface_token_here
```

You can also configure these through the Settings dialog in the application.

## 🎮 Usage

### Starting the Application

#### macOS/Linux
```bash
# Using the startup script (recommended)
./run.sh

# Or manually
source venv/bin/activate
python main.py
```

#### Windows
```bash
# Activate virtual environment
venv\Scripts\activate

# Run the application
python main.py
```

### Creating Your First Project

1. **Launch WritingAid** using one of the methods above
2. **Create a New Project**: File → New Project
3. **Set Up Your Project**:
   - Enter your project name and author information
   - Choose a save location
4. **Start Writing!**

### Using AI Features

#### Configure AI Provider
1. Go to **Settings** → **AI Settings**
2. Enter your API key for your preferred provider (Claude, OpenAI, Gemini)
3. Or select a local model from Hugging Face

#### Create Worldbuilding Elements via Chat
Open the **General AI** tab and type natural requests:

```
"Add a character named Sarah Chen, a cybersecurity expert in her 30s"
"Create a historical event: The Treaty of New Alexandria in 2157"
"Add a climate preset for a desert world with extreme temperature swings"
"Add a new chapter where the protagonist discovers the hidden laboratory"
```

The AI will create these elements automatically and add them to your project!

#### Generate Character Images
1. Go to the **Characters** tab
2. Select a character or create a new one
3. Fill in the "Physical Description" field
4. Choose image type (Portrait or Full Body)
5. Click **Generate Image**

#### Analyze Your Writing
1. Open a chapter in the **Manuscript** editor
2. Switch to **Chapter Analysis** mode in the AI chat
3. Ask questions like:
   - "Analyze the pacing of this chapter"
   - "Check for consistency issues"
   - "Suggest improvements to the dialogue"

### Managing Your Project

#### Worldbuilding
- Navigate to the **Worldbuilding** tab
- Each category (Characters, Places, Factions, etc.) has its own dedicated section
- Add elements manually or ask the AI to create them
- Elements are automatically linked and cross-referenced

#### Manuscript Editing
- Use the **Manuscript** tab for writing
- Each chapter can have:
  - Planning notes and outline
  - Story events and beats
  - Character/location assignments
  - Revision history

#### Exporting Your Work
1. **File** → **Export Manuscript**
2. Choose your format:
   - **DOCX**: For Word processors
   - **PDF**: For distribution
   - **EPUB**: For e-readers
   - **Markdown**: For version control
   - **LLM Context**: For feeding to AI systems

## 🛠️ Configuration

### AI Model Selection
- **Cloud Models**: Configured in Settings → AI Settings
- **Local Models**: Downloaded automatically on first use
- **Performance**: Adjust context length and temperature in settings

### Local Model Storage
Local models are cached in:
- **macOS/Linux**: `~/.cache/huggingface/hub/`
- **Windows**: `C:\Users\YourName\.cache\huggingface\hub\`

First-time model downloads can be 5-20GB depending on the model.

### Image Generation
Configure in Settings → Image Generation:
- **API-based**: DALL-E 3 (requires OpenAI key)
- **Local (GPU)**: Stable Diffusion/FLUX via Diffusers
- **Local (Apple Silicon)**: FLUX via MLX/mflux

## 🐛 Troubleshooting

### "Free-threaded Python" Warning
If you see this warning, you're using Python 3.14t (free-threaded build):
- **Solution**: Use Python 3.10-3.13 instead
- Create a new venv: `python3.12 -m venv venv`

### "Missing required packages" Error
```bash
# Activate virtual environment first
source venv/bin/activate  # macOS/Linux
venv\Scripts\activate     # Windows

# Then install requirements
pip install -r requirements.txt
```

### PyQt6 Not Found
```bash
pip install PyQt6 PyQt6-WebEngine
```

### CUDA Not Available (NVIDIA GPU)
```bash
# Verify CUDA installation
nvidia-smi

# Reinstall PyTorch with CUDA support
pip uninstall torch -y
pip install torch --index-url https://download.pytorch.org/whl/cu124
```

### Model Download Fails
- Check your internet connection
- Verify HuggingFace token in settings
- Some models require accepting terms on HuggingFace website first

### Grammar Checker Not Working
```bash
# LanguageTool requires Java
# macOS:
brew install java

# Ubuntu/Debian:
sudo apt-get install default-jre
```

## 📖 Documentation

### Project Structure
```
WritingAid/
├── main.py              # Application entry point
├── requirements.txt     # Python dependencies
├── run.sh              # Startup script (macOS/Linux)
├── src/
│   ├── ui/             # User interface components
│   ├── ai/             # AI agents and providers
│   ├── models/         # Data models (Pydantic)
│   ├── export/         # Export functionality
│   └── config/         # Configuration management
├── assets/             # Icons and resources
└── venv/               # Virtual environment (created during setup)
```

### Key Concepts

#### Projects
All your work is saved in a single project file (`.writer` format) along with a project folder containing:
- Chapter files (`.txt` format)
- Character images
- Generated content
- Export outputs

#### AI Modes
- **General Mode**: Conversational AI with element creation
- **Chapter Focus**: Deep analysis of current chapter
- **Writer Mode**: Prose generation assistance

#### Worldbuilding Integration
All worldbuilding elements are interconnected:
- Characters can be linked to factions, places, and events
- Events can reference characters and locations
- Cultures can be associated with factions and planets

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

### Development Setup
1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Run tests (if available)
5. Commit: `git commit -am 'Add new feature'`
6. Push: `git push origin feature/your-feature`
7. Create a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with [PyQt6](https://www.riverbankcomputing.com/software/pyqt/)
- AI powered by [Anthropic Claude](https://www.anthropic.com/), [OpenAI](https://openai.com/), and [Google Gemini](https://deepmind.google/technologies/gemini/)
- Local AI via [Hugging Face Transformers](https://huggingface.co/transformers/)
- Image generation with [DALL-E 3](https://openai.com/dall-e-3), [Stable Diffusion](https://stability.ai/), and [FLUX](https://blackforestlabs.ai/)
- NLP features powered by [spaCy](https://spacy.io/) and [LanguageTool](https://languagetool.org/)

## 📧 Support

For questions, issues, or feature requests:
- Open an issue on GitHub
- Check existing documentation
- Review troubleshooting section above

---

**Happy Writing! 📚✨**
