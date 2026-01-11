"""Import Guide Dialog - Comprehensive prompts for building project data with external LLMs."""

import os
from pathlib import Path
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QTextEdit, QPushButton, QLabel, QScrollArea, QFrame,
    QComboBox, QGroupBox, QSplitter, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


# Platform-specific instructions and prompt adaptations
PLATFORM_INFO = {
    "claude": {
        "name": "Claude (Anthropic)",
        "file_prefix": "claude",
        "context_window": "200K tokens",
        "tips": """## Tips for Using with Claude

- **Context Window**: Claude has a 200K token context window - you can paste large manuscript excerpts
- **Artifacts**: Claude can create artifacts (documents, code) - ask it to format output as artifacts for easy copying
- **XML Tags**: Claude responds well to XML-style tags like <manuscript>, <characters>, etc.
- **Projects**: Consider creating a Claude Project to maintain context across conversations
- **Best For**: Long manuscript analysis, detailed character development, complex worldbuilding

## Recommended Workflow

1. Start a new conversation or Project in Claude
2. Paste the system context prompt first to set up the assistant
3. Then paste individual prompts with your content
4. Use "create an artifact" to get formatted, copyable output
5. Claude excels at maintaining consistency across long conversations
""",
        "system_context": """You are a creative writing assistant helping an author build a project in Writer Platform, a comprehensive writing organization tool. Your goal is to help extract, analyze, and structure story elements.

When generating content:
- Be thorough and detailed in your analysis
- Use the exact JSON formats when asked for structured data
- Maintain consistency with previously established elements
- Ask clarifying questions if information is ambiguous
- Format output clearly for easy copying

The user will provide manuscript excerpts, notes, or descriptions. Help them populate their Writer Platform project with organized, consistent data."""
    },
    "chatgpt": {
        "name": "ChatGPT (OpenAI)",
        "file_prefix": "chatgpt",
        "context_window": "128K tokens (GPT-4)",
        "tips": """## Tips for Using with ChatGPT

- **Context Window**: GPT-4 has 128K context - good for most excerpts, break up very long manuscripts
- **Custom GPTs**: Consider creating a Custom GPT with these prompts pre-loaded
- **Code Interpreter**: Enable Code Interpreter for JSON validation and formatting
- **Memory**: ChatGPT can remember context within a conversation - work in one session when possible
- **Best For**: Quick analysis, brainstorming, iterative refinement

## Recommended Workflow

1. Start with the system context in "Custom Instructions" or as your first message
2. Work through prompts one section at a time
3. Use "format this as a code block" to get copyable JSON
4. Ask ChatGPT to validate JSON before copying
5. Good for quick iterations and brainstorming sessions
""",
        "system_context": """You are a creative writing assistant helping an author build a project in Writer Platform. Your goal is to extract, analyze, and structure story elements into organized data.

Guidelines:
- Provide thorough, detailed analysis
- Use exact JSON formats when requested (validate before outputting)
- Keep consistency with established elements
- Format all output for easy copying
- When generating JSON, use code blocks for easy copying

Help the user organize their story's characters, plot, worldbuilding, and other elements."""
    },
    "gemini": {
        "name": "Gemini (Google)",
        "file_prefix": "gemini",
        "context_window": "1M tokens (Gemini 1.5)",
        "tips": """## Tips for Using with Gemini

- **Context Window**: Gemini 1.5 Pro has 1M token context - excellent for entire manuscripts
- **Google Docs**: Gemini integrates with Google Docs - you can reference documents directly
- **Multimodal**: Gemini can analyze images - useful for character reference images or maps
- **Grounding**: Gemini can search for real-world information to enrich worldbuilding
- **Best For**: Very long manuscripts, multimodal content, research-integrated worldbuilding

## Recommended Workflow

1. Upload your entire manuscript as a file or Google Doc for reference
2. Start with the system context to establish the task
3. Reference specific sections: "Looking at Chapter 3..."
4. Ask Gemini to format JSON in code blocks
5. Excellent for analyzing entire manuscripts at once
""",
        "system_context": """You are a creative writing assistant helping an author organize their work in Writer Platform. Analyze story content and generate structured data for characters, plot, worldbuilding, and other elements.

When working:
- Provide comprehensive analysis
- Generate properly formatted JSON when requested
- Maintain consistency across all generated content
- Format output clearly in code blocks for copying
- You can reference uploaded documents or images

Help transform the author's creative work into an organized project structure."""
    }
}


def adapt_prompt_for_platform(prompt: str, platform: str) -> str:
    """Adapt a prompt for a specific platform's strengths."""
    if platform == "claude":
        # Claude works well with explicit structure requests
        if "JSON" in prompt or "json" in prompt:
            prompt += "\n\nPlease create an artifact containing the JSON output for easy copying."
    elif platform == "chatgpt":
        # ChatGPT benefits from explicit formatting requests
        if "JSON" in prompt or "json" in prompt:
            prompt += "\n\nFormat the JSON in a code block and validate it before outputting."
    elif platform == "gemini":
        # Gemini can handle larger context
        if "[PASTE" in prompt:
            prompt = prompt.replace(
                "[PASTE YOUR MANUSCRIPT EXCERPT - UP TO 5000 WORDS]",
                "[PASTE YOUR MANUSCRIPT EXCERPT - you can include large sections or reference uploaded files]"
            )
            prompt = prompt.replace(
                "[PASTE YOUR STORY EXCERPT OR SUMMARY]",
                "[PASTE YOUR STORY EXCERPT OR SUMMARY - or reference an uploaded document]"
            )
    return prompt


class ImportGuideDialog(QDialog):
    """Dialog with comprehensive prompts for importing/creating project data with external LLMs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project Import & Setup Guide")
        self.setMinimumSize(900, 700)
        self.resize(1000, 800)
        self._prompts = {}  # Store prompts for export
        self._init_ui()

    def _init_ui(self):
        """Initialize the UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Header
        header = QLabel("Build Your Project with AI Assistance")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #6366f1; padding: 8px;")
        layout.addWidget(header)

        intro = QLabel(
            "Use these prompts with ChatGPT, Claude, or other AI assistants to analyze your existing work "
            "and generate structured data for Writer Platform. Copy prompts, paste responses, and build your project step by step."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #666; padding: 0 8px 8px 8px;")
        layout.addWidget(intro)

        # Main content with tabs
        tabs = QTabWidget()
        tabs.addTab(self._create_getting_started_tab(), "Getting Started")
        tabs.addTab(self._create_characters_tab(), "Characters")
        tabs.addTab(self._create_plot_tab(), "Plot & Structure")
        tabs.addTab(self._create_worldbuilding_tab(), "Worldbuilding")
        tabs.addTab(self._create_factions_tab(), "Factions & Politics")
        tabs.addTab(self._create_analysis_tab(), "Manuscript Analysis")
        tabs.addTab(self._create_json_export_tab(), "JSON Export")

        layout.addWidget(tabs)

        # Bottom button row
        button_layout = QHBoxLayout()

        # Export button with platform selector
        export_layout = QHBoxLayout()
        export_layout.setSpacing(8)

        export_label = QLabel("Export for:")
        export_layout.addWidget(export_label)

        self.platform_combo = QComboBox()
        self.platform_combo.addItem("Claude (Anthropic)", "claude")
        self.platform_combo.addItem("ChatGPT (OpenAI)", "chatgpt")
        self.platform_combo.addItem("Gemini (Google)", "gemini")
        self.platform_combo.addItem("All Platforms", "all")
        self.platform_combo.setMinimumWidth(150)
        export_layout.addWidget(self.platform_combo)

        export_btn = QPushButton("Export Prompts")
        export_btn.setProperty("secondary", True)
        export_btn.clicked.connect(self._export_prompts)
        export_layout.addWidget(export_btn)

        button_layout.addLayout(export_layout)
        button_layout.addStretch()

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setMaximumWidth(100)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

    def _create_prompt_widget(self, title: str, prompt: str, notes: str = "", category: str = "") -> QWidget:
        """Create a widget displaying a copyable prompt."""
        # Store prompt for export
        if category not in self._prompts:
            self._prompts[category] = []
        self._prompts[category].append({
            "title": title,
            "prompt": prompt,
            "notes": notes
        })

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 12)

        # Title
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #1a1a1a;")
        layout.addWidget(title_label)

        # Notes if provided
        if notes:
            notes_label = QLabel(notes)
            notes_label.setWordWrap(True)
            notes_label.setStyleSheet("color: #666; font-style: italic; padding: 4px 0;")
            layout.addWidget(notes_label)

        # Prompt text area
        prompt_edit = QTextEdit()
        prompt_edit.setPlainText(prompt)
        prompt_edit.setReadOnly(True)
        prompt_edit.setMinimumHeight(150)
        prompt_edit.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #e5e7eb;
                border-radius: 6px;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 12px;
            }
        """)
        layout.addWidget(prompt_edit)

        # Copy button
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setMaximumWidth(150)
        copy_btn.clicked.connect(lambda: self._copy_to_clipboard(prompt))
        layout.addWidget(copy_btn)

        return widget

    def _copy_to_clipboard(self, text: str):
        """Copy text to clipboard."""
        from PyQt6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        clipboard.setText(text)

    def _export_prompts(self):
        """Export prompts as a package of files for the selected platform."""
        platform = self.platform_combo.currentData()

        # Ask user for export directory
        export_dir = QFileDialog.getExistingDirectory(
            self,
            "Select Export Directory",
            "",
            QFileDialog.Option.ShowDirsOnly
        )

        if not export_dir:
            return

        try:
            if platform == "all":
                # Export for all platforms
                for plat in ["claude", "chatgpt", "gemini"]:
                    self._export_for_platform(export_dir, plat)
                msg = "Exported prompts for all platforms (Claude, ChatGPT, Gemini)"
            else:
                self._export_for_platform(export_dir, platform)
                msg = f"Exported prompts for {PLATFORM_INFO[platform]['name']}"

            QMessageBox.information(
                self,
                "Export Complete",
                f"{msg}\n\nLocation: {export_dir}"
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Error",
                f"Failed to export prompts:\n{str(e)}"
            )

    def _export_for_platform(self, base_dir: str, platform: str):
        """Export prompts for a specific platform."""
        info = PLATFORM_INFO[platform]
        platform_dir = Path(base_dir) / f"writer_platform_prompts_{info['file_prefix']}"
        platform_dir.mkdir(exist_ok=True)

        # Create README with instructions
        readme_content = self._generate_readme(platform)
        (platform_dir / "README.md").write_text(readme_content, encoding="utf-8")

        # Create system context file
        context_file = platform_dir / "00_SYSTEM_CONTEXT.txt"
        context_file.write_text(info["system_context"], encoding="utf-8")

        # Export prompts by category
        category_order = [
            ("Getting Started", "01_getting_started"),
            ("Characters", "02_characters"),
            ("Plot & Structure", "03_plot_structure"),
            ("Worldbuilding", "04_worldbuilding"),
            ("Factions & Politics", "05_factions_politics"),
            ("Manuscript Analysis", "06_manuscript_analysis"),
            ("JSON Export", "07_json_export")
        ]

        for category_name, folder_name in category_order:
            if category_name in self._prompts:
                category_dir = platform_dir / folder_name
                category_dir.mkdir(exist_ok=True)

                for i, prompt_data in enumerate(self._prompts[category_name], 1):
                    # Create safe filename from title
                    safe_title = "".join(
                        c if c.isalnum() or c in " -_" else ""
                        for c in prompt_data["title"]
                    ).strip().replace(" ", "_").lower()

                    filename = f"{i:02d}_{safe_title}.txt"

                    # Adapt prompt for platform
                    adapted_prompt = adapt_prompt_for_platform(
                        prompt_data["prompt"], platform
                    )

                    # Build file content
                    content = f"# {prompt_data['title']}\n\n"
                    if prompt_data["notes"]:
                        content += f"## Notes\n{prompt_data['notes']}\n\n"
                    content += f"## Prompt\n\n{adapted_prompt}\n"

                    (category_dir / filename).write_text(content, encoding="utf-8")

    def _generate_readme(self, platform: str) -> str:
        """Generate the README file for a platform export."""
        info = PLATFORM_INFO[platform]

        readme = f"""# Writer Platform - AI Prompt Guide for {info['name']}

This package contains prompts to help you build a Writer Platform project using {info['name']}.

## About Writer Platform

Writer Platform is a comprehensive tool for writers to organize books, short stories, and media.
These prompts help you extract and structure information from your existing work or brainstorm
new story elements using AI assistance.

## Platform Information

- **AI Assistant**: {info['name']}
- **Context Window**: {info['context_window']}

{info['tips']}

## File Structure

```
{info['file_prefix']}_prompts/
├── README.md                    (This file)
├── 00_SYSTEM_CONTEXT.txt        (Paste this first to set up the assistant)
├── 01_getting_started/          (Initial setup prompts)
├── 02_characters/               (Character development prompts)
├── 03_plot_structure/           (Plot and story structure prompts)
├── 04_worldbuilding/            (World creation prompts)
├── 05_factions_politics/        (Organizations and politics prompts)
├── 06_manuscript_analysis/      (Analyze existing writing)
└── 07_json_export/              (Generate importable JSON data)
```

## How to Use

1. **Start a new conversation** with {info['name']}

2. **Paste the system context** from `00_SYSTEM_CONTEXT.txt` as your first message
   (or add it to Custom Instructions if supported)

3. **Choose a category** based on what you want to build:
   - Starting fresh? Begin with `01_getting_started`
   - Have a manuscript? Use `06_manuscript_analysis` to extract elements
   - Building characters? Use `02_characters`

4. **Open a prompt file** and copy the prompt text

5. **Paste the prompt** into the chat along with your manuscript excerpt or notes

6. **Copy the AI's response** back into Writer Platform

## Importing JSON Data

For prompts in `07_json_export/`:

1. Generate the JSON using the prompts
2. Save your Writer Platform project and close it
3. Open the `.writerproj` file in a text editor
4. Carefully merge the generated JSON into the appropriate section
5. Reopen the project in Writer Platform

**Always back up your project before manual JSON editing!**

## Tips for Best Results

- Work through one category at a time
- Provide context from your story when using prompts
- Review and refine AI-generated content
- Maintain a single conversation to keep context
- Ask the AI to clarify or expand on any responses

## Questions or Issues?

Visit the Writer Platform repository for documentation and support.

---
Generated by Writer Platform Import Guide
"""
        return readme

    def _create_scrollable_content(self, widgets: list) -> QScrollArea:
        """Create a scrollable area containing the given widgets."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(16)

        for widget in widgets:
            layout.addWidget(widget)

        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _create_getting_started_tab(self) -> QWidget:
        """Create the getting started tab."""
        widgets = []

        # Introduction
        intro = QLabel("""
<h3>Welcome to the Project Import Guide</h3>
<p>This guide helps you build a complete Writer Platform project using AI assistants like ChatGPT or Claude.
You can either:</p>
<ul>
<li><b>Import an existing work:</b> Analyze your manuscript to extract characters, plot, and worldbuilding</li>
<li><b>Start fresh:</b> Build your project from scratch with AI-guided brainstorming</li>
</ul>
<p><b>How to use this guide:</b></p>
<ol>
<li>Choose a section (Characters, Plot, Worldbuilding, etc.)</li>
<li>Copy the relevant prompt</li>
<li>Paste it into your AI assistant along with your manuscript excerpt or notes</li>
<li>Copy the AI's response back into Writer Platform</li>
</ol>
<p><b>Tips for best results:</b></p>
<ul>
<li>Work section by section - don't try to do everything at once</li>
<li>Provide context from your story when using prompts</li>
<li>Review and refine AI-generated content to match your vision</li>
<li>Use the JSON Export tab to get data you can directly import</li>
</ul>
        """)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        widgets.append(intro)

        widgets.append(self._create_prompt_widget(
            "Initial Project Setup Prompt",
            """I'm setting up a writing project in a tool called Writer Platform. I need help organizing my story's elements.

Here's a brief summary of my story:
[PASTE YOUR STORY SUMMARY HERE - 2-3 paragraphs describing the premise, setting, and main conflict]

Please help me identify and list:
1. The main characters (protagonists, antagonists, and major supporting characters)
2. The primary setting(s) and time period
3. The central conflict and main plot arc
4. Key themes the story explores
5. Any unique worldbuilding elements (magic systems, technology, cultures, etc.)

Format your response as organized lists that I can use to populate my project.""",
            "Start here! This prompt gives you an overview of all the elements you'll need to build.",
            "Getting Started"
        ))

        widgets.append(self._create_prompt_widget(
            "Story Genre & Tone Analysis",
            """Based on the following story summary/excerpt, please analyze:

[PASTE YOUR STORY EXCERPT OR SUMMARY]

1. Primary genre and any subgenres
2. Overall tone (dark, lighthearted, serious, comedic, etc.)
3. Point of view and narrative style
4. Pacing (fast, slow, variable)
5. Target audience (age group, interests)
6. Comparable published works (for positioning)

This will help me maintain consistency throughout my project.""",
            "Understanding your story's identity helps maintain consistency.",
            "Getting Started"
        ))

        return self._create_scrollable_content(widgets)

    def _create_characters_tab(self) -> QWidget:
        """Create the characters tab."""
        widgets = []

        widgets.append(self._create_prompt_widget(
            "Character Extraction from Manuscript",
            """Please analyze the following manuscript excerpt and extract all characters mentioned:

[PASTE YOUR MANUSCRIPT EXCERPT - UP TO 5000 WORDS]

For each character, provide:
1. Name (and any aliases/nicknames)
2. Role: protagonist, antagonist, major supporting, or minor
3. Physical description (if mentioned)
4. Personality traits demonstrated
5. Relationships to other characters
6. Goals/motivations (if apparent)
7. Key scenes they appear in

Format as a structured list I can use to build character profiles.""",
            "Paste a chapter or section of your manuscript to extract characters.",
            "Characters"
        ))

        widgets.append(self._create_prompt_widget(
            "Deep Character Profile Builder",
            """Help me build a comprehensive character profile for: [CHARACTER NAME]

Context about this character:
[PASTE ANY NOTES YOU HAVE ABOUT THIS CHARACTER]

Please develop:

**Basic Information:**
- Full name and any titles/aliases
- Age, birth date (if known)
- Physical appearance (height, build, distinguishing features)
- Voice and mannerisms

**Background:**
- Birthplace and upbringing
- Family relationships
- Formative experiences
- Education/training
- Current occupation/role

**Psychology:**
- Core personality traits (use specific descriptors, not just "nice" or "mean")
- Deepest fear
- Greatest desire
- Internal conflict
- How they handle stress
- Their fatal flaw
- Their greatest strength

**Relationships:**
- Key relationships and dynamics
- How they interact with authority
- How they treat strangers vs. friends
- Romantic history/orientation

**Character Arc:**
- Where do they start emotionally?
- What needs to change?
- What catalyst drives change?
- Where do they end up?

Format this as a detailed profile I can paste into my writing tool.""",
            "Use this for your main characters to create rich, detailed profiles.",
            "Characters"
        ))

        widgets.append(self._create_prompt_widget(
            "Character Relationship Web",
            """I have the following characters in my story:

[LIST YOUR CHARACTERS WITH BRIEF DESCRIPTIONS]

Please create a relationship web showing:
1. The relationship between each pair of characters
2. The nature of each relationship (family, friends, enemies, romantic, professional, etc.)
3. The dynamic (one-sided, mutual, complicated, etc.)
4. Any tension or conflict between them
5. How relationships might evolve during the story

Format as a relationship map I can reference while writing.""",
            "Understanding how characters connect helps with consistent interactions.",
            "Characters"
        ))

        widgets.append(self._create_prompt_widget(
            "Character Voice Development",
            """Help me develop a distinct voice for this character:

Name: [CHARACTER NAME]
Background: [BRIEF BACKGROUND]
Personality: [KEY TRAITS]
Education level: [EDUCATION]
Region/culture: [WHERE THEY'RE FROM]

Please provide:
1. Speech patterns and vocabulary level
2. Common phrases or expressions they'd use
3. Topics they'd talk about enthusiastically
4. Topics they'd avoid
5. How their speech changes when emotional
6. Sample dialogue lines showing their voice

Include 5-10 example lines of dialogue in different situations.""",
            "",
            "Characters"
        ))

        return self._create_scrollable_content(widgets)

    def _create_plot_tab(self) -> QWidget:
        """Create the plot and structure tab."""
        widgets = []

        widgets.append(self._create_prompt_widget(
            "Freytag's Pyramid Analysis",
            """Please analyze my story's structure using Freytag's Pyramid:

Story summary:
[PASTE YOUR STORY SUMMARY OR OUTLINE]

Break down the story into:

**EXPOSITION (Setup)**
- The initial situation
- Character introductions
- World/setting establishment
- The status quo before conflict

**RISING ACTION (Complications)**
- The inciting incident that disrupts the status quo
- Key complications and obstacles
- How stakes escalate
- Subplot developments
- Character growth/change during this phase

**CLIMAX (Crisis Point)**
- The moment of highest tension
- The critical decision or confrontation
- Point of no return

**FALLING ACTION (Consequences)**
- Immediate aftermath of climax
- Resolution of subplots
- Character reactions and adjustments

**RESOLUTION (New Normal)**
- How the world has changed
- Character endpoints
- Loose ends tied up
- Final image/feeling

Also identify any structural issues or gaps in the arc.""",
            "Analyze your existing story or outline to populate the Plot tab.",
            "Plot & Structure"
        ))

        widgets.append(self._create_prompt_widget(
            "Plot Event Breakdown",
            """Break my story into specific plot events I can track:

[PASTE YOUR STORY SUMMARY OR CHAPTER OUTLINE]

For each major event, provide:
1. Event title (brief, descriptive)
2. Stage (exposition, rising_action, climax, falling_action, resolution)
3. Description (2-3 sentences)
4. Outcome (what changes as a result)
5. Characters involved
6. Intensity (0-100, how dramatic/important)
7. Connection to other events

List events in chronological order. I need at least 10-15 events for a complete story arc.""",
            "Create specific events to populate your plot timeline.",
            "Plot & Structure"
        ))

        widgets.append(self._create_prompt_widget(
            "Subplot Development",
            """Help me develop subplots for my story:

Main plot: [DESCRIBE YOUR MAIN PLOT]
Characters: [LIST MAIN CHARACTERS]
Themes: [LIST THEMES YOU WANT TO EXPLORE]

Please suggest 2-4 subplots that:
1. Complement the main plot without overshadowing it
2. Provide character development opportunities
3. Explore your themes from different angles
4. Have their own mini-arc (beginning, middle, end)
5. Intersect with the main plot at key moments

For each subplot, provide:
- Title
- Description
- Characters involved
- Connection to main plot
- Key events (3-5)
- Resolution""",
            "Subplots add depth and complexity to your story.",
            "Plot & Structure"
        ))

        widgets.append(self._create_prompt_widget(
            "Theme Analysis",
            """Analyze the themes in my story:

[PASTE STORY SUMMARY OR KEY SCENES]

Please identify:
1. Primary theme (the main "big idea")
2. Secondary themes (supporting ideas)
3. How each theme is expressed through:
   - Character arcs
   - Plot events
   - Symbolism
   - Dialogue
   - Setting
4. The thematic question the story asks
5. How the ending answers (or complicates) that question

Format as a thematic guide I can reference while writing.""",
            "",
            "Plot & Structure"
        ))

        return self._create_scrollable_content(widgets)

    def _create_worldbuilding_tab(self) -> QWidget:
        """Create the worldbuilding tab."""
        widgets = []

        widgets.append(self._create_prompt_widget(
            "World Overview Extraction",
            """Analyze my story/notes and extract worldbuilding elements:

[PASTE YOUR STORY EXCERPT, NOTES, OR WORLD DESCRIPTION]

Please identify and organize:

**Physical World:**
- Geography (continents, oceans, climate)
- Key locations mentioned
- Environmental features

**History:**
- Historical events referenced
- Past conflicts or wars
- Origin/creation myths
- Technological/cultural evolution

**Culture & Society:**
- Social structures and classes
- Customs and traditions
- Languages mentioned
- Art, music, literature

**Technology/Magic:**
- Level of technology
- Any magic systems or special abilities
- Unique inventions or tools

**Economy:**
- Currency
- Trade goods
- Economic systems

**Politics:**
- Government types
- Power structures
- Current conflicts

Format each section as detailed notes I can expand on.""",
            "Extract worldbuilding from existing work or notes.",
            "Worldbuilding"
        ))

        widgets.append(self._create_prompt_widget(
            "Magic/Technology System Builder",
            """Help me develop my story's [MAGIC SYSTEM / TECHNOLOGY]:

Current ideas:
[PASTE ANY NOTES YOU HAVE]

Please develop:

**Fundamentals:**
- What is it and how does it work?
- Who can use it and why?
- What are the limitations?
- What is the cost/price of using it?

**Rules:**
- Hard rules that are never broken
- Soft rules that are guidelines
- Common misconceptions about it

**Applications:**
- Common uses
- Rare/advanced uses
- Forbidden/dangerous uses
- How it affects daily life

**History:**
- How was it discovered/developed?
- How has it evolved?
- Key events in its history

**Cultural Impact:**
- How does society view it?
- Social structures around it
- Legal regulations

**Story Integration:**
- How does it connect to your plot?
- How does it create conflict?
- How might characters misuse or abuse it?""",
            "Develop consistent rules for magic or technology systems.",
            "Worldbuilding"
        ))

        widgets.append(self._create_prompt_widget(
            "History & Timeline Builder",
            """Help me build a historical timeline for my world:

World overview:
[DESCRIBE YOUR WORLD BRIEFLY]

Current story time period:
[WHEN DOES YOUR STORY TAKE PLACE]

Please create a timeline including:
1. Creation/origin (if applicable)
2. Major eras or ages
3. Pivotal wars or conflicts
4. Rise and fall of civilizations/powers
5. Technological/magical discoveries
6. Events referenced in the current story
7. Recent history leading to the story

For each event, provide:
- Date/period (can be relative like "500 years before story")
- Event name
- Description
- Consequences
- Key figures involved

Create at least 10-15 historical events to give the world depth.""",
            "",
            "Worldbuilding"
        ))

        widgets.append(self._create_prompt_widget(
            "Flora & Fauna Creator",
            """Help me create unique plants and creatures for my world:

World type: [FANTASY/SCI-FI/OTHER]
Climate/biomes: [DESCRIBE ENVIRONMENTS]
Existing creatures: [ANY YOU'VE ALREADY CREATED]

Please create 5 unique flora and 5 unique fauna that:
- Fit the world's ecosystem
- Have practical uses (food, medicine, materials)
- Create story opportunities (danger, mystery, resources)
- Feel original but believable

For each, provide:
- Name (common and scientific if applicable)
- Type/category
- Physical description
- Habitat and behavior
- Special properties
- Danger level (if fauna)
- Cultural/economic significance
- How it might appear in the story""",
            "",
            "Worldbuilding"
        ))

        return self._create_scrollable_content(widgets)

    def _create_factions_tab(self) -> QWidget:
        """Create the factions and politics tab."""
        widgets = []

        widgets.append(self._create_prompt_widget(
            "Faction Extraction & Development",
            """Analyze my story and identify all factions/groups:

[PASTE YOUR STORY EXCERPT OR NOTES]

For each faction, provide:

**Basic Info:**
- Name
- Type (nation, organization, religion, tribe, corporation, etc.)
- Description (2-3 sentences)

**Structure:**
- Leader/leadership style
- Hierarchy
- Size/power level
- Territory or sphere of influence

**Relationships:**
- Allies (and why)
- Enemies (and why)
- Neutral parties
- Internal factions/conflicts

**Resources:**
- Military strength (0-100)
- Economic power (0-100)
- Special resources or advantages

**Goals:**
- Short-term objectives
- Long-term ambitions
- Methods they'll use

**Story Role:**
- How do they relate to the protagonist?
- What conflict do they create or represent?""",
            "Identify and develop groups, nations, and organizations in your story.",
            "Factions & Politics"
        ))

        widgets.append(self._create_prompt_widget(
            "Political System Builder",
            """Help me develop the political system for: [FACTION/NATION NAME]

Context:
[PASTE ANY RELEVANT NOTES]

Please develop:

**Government Type:**
- System (democracy, monarchy, theocracy, etc.)
- How power is transferred
- How long leaders serve

**Structure:**
- Executive branch (who makes decisions)
- Legislative branch (who makes laws)
- Judicial branch (who enforces justice)
- Other bodies (councils, advisors, etc.)

**Key Positions:**
- Titles and roles
- Current holders (if known)
- How positions are filled

**Laws & Customs:**
- Major laws
- Rights of citizens
- Controversial policies
- Enforcement methods

**Current State:**
- Stability level
- Active conflicts
- Public sentiment
- Likely future changes

**Story Integration:**
- How does this system affect your characters?
- What injustices might exist?
- What opportunities for conflict?""",
            "",
            "Factions & Politics"
        ))

        widgets.append(self._create_prompt_widget(
            "Conflict Web Generator",
            """Map the conflicts between factions in my world:

Factions:
[LIST YOUR FACTIONS WITH BRIEF DESCRIPTIONS]

Please create a conflict web showing:

**Active Conflicts:**
- Which factions are at war/in conflict
- The cause of each conflict
- Current state (escalating, stalemate, de-escalating)
- What would resolve it

**Tensions:**
- Which factions have underlying tensions
- What could trigger open conflict
- Historical grievances

**Alliances:**
- Formal alliances and their terms
- Informal partnerships
- Marriages or other binding ties
- What could break these alliances

**Balance of Power:**
- Who is strongest currently
- Who is rising
- Who is declining
- What could shift the balance

**Story Opportunities:**
- Which conflicts involve your protagonist
- Potential turning points
- How conflicts might resolve by story's end""",
            "",
            "Factions & Politics"
        ))

        return self._create_scrollable_content(widgets)

    def _create_analysis_tab(self) -> QWidget:
        """Create the manuscript analysis tab."""
        widgets = []

        intro = QLabel("""
<h3>Manuscript Analysis</h3>
<p>These prompts help you analyze your existing manuscript to extract information
without importing the actual text. Use these to populate your project's metadata and reference materials.</p>
<p><b>Note:</b> These prompts are designed for analysis only.
Your manuscript text stays in your word processor - you'll copy it to Writer Platform's Write tab separately.</p>
        """)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        widgets.append(intro)

        widgets.append(self._create_prompt_widget(
            "Chapter-by-Chapter Analysis",
            """Analyze this chapter and extract key information:

Chapter [NUMBER]: [TITLE]
[PASTE CHAPTER TEXT]

Please provide:

**Summary:** (2-3 sentences)

**Characters Appearing:**
- List all characters with their role in this chapter

**Plot Events:**
- What happens (bullet points)
- How it advances the main plot
- Subplot developments

**Setting:**
- Locations used
- Time passed

**Themes Explored:**
- Which themes appear in this chapter

**Foreshadowing:**
- Any hints about future events

**Questions Raised:**
- What mysteries or questions does this chapter introduce

**Character Development:**
- How do characters change or reveal themselves

**Continuity Notes:**
- Details I need to remember for consistency

I'll use this to build my chapter notes and annotations.""",
            "Analyze chapters one at a time to build comprehensive notes.",
            "Manuscript Analysis"
        ))

        widgets.append(self._create_prompt_widget(
            "Consistency Checker",
            """Check my manuscript excerpt for consistency issues:

[PASTE MANUSCRIPT EXCERPT - MULTIPLE CHAPTERS RECOMMENDED]

Please identify:

**Character Consistency:**
- Name spelling variations
- Personality inconsistencies
- Physical description contradictions
- Relationship inconsistencies

**Timeline Issues:**
- Chronological problems
- Travel time inconsistencies
- Age discrepancies
- Season/weather contradictions

**World Consistency:**
- Setting contradictions
- Rule violations (magic/tech systems)
- Cultural inconsistencies

**Plot Holes:**
- Unresolved setups
- Missing explanations
- Logic gaps

**Factual Errors:**
- Historical inaccuracies (if applicable)
- Scientific errors (if applicable)
- Geographic impossibilities

For each issue, provide:
- The specific problem
- Where it occurs
- Suggested fix""",
            "",
            "Manuscript Analysis"
        ))

        widgets.append(self._create_prompt_widget(
            "Scene-by-Scene Breakdown",
            """Break down this chapter into scenes:

[PASTE CHAPTER TEXT]

For each scene, provide:
1. Scene number
2. Location
3. Characters present
4. POV character (if applicable)
5. Time of day / time passed
6. Scene goal (what the scene accomplishes)
7. Conflict/tension in scene
8. Outcome / what changes
9. Word count estimate
10. Pacing (fast, medium, slow)

This helps me understand my story's rhythm and structure.""",
            "",
            "Manuscript Analysis"
        ))

        widgets.append(self._create_prompt_widget(
            "First Draft Issues Identifier",
            """Analyze my first draft and identify areas for revision:

[PASTE MANUSCRIPT EXCERPT]

Please identify:

**Structural Issues:**
- Pacing problems
- Scene order suggestions
- Missing scenes
- Scenes that could be cut

**Character Issues:**
- Characters who need more development
- Relationships that need work
- Motivation clarity
- Voice consistency

**Prose Issues:**
- Overused words/phrases
- Passive voice overuse
- Show vs. tell opportunities
- Dialogue attribution patterns

**Opening/Ending:**
- Is the opening hooky enough?
- Does the ending satisfy?
- Are stakes clear throughout?

**Overall Impressions:**
- Strongest elements
- Weakest elements
- Priority revisions

Be specific with examples from the text.""",
            "",
            "Manuscript Analysis"
        ))

        return self._create_scrollable_content(widgets)

    def _create_json_export_tab(self) -> QWidget:
        """Create the JSON export tab for direct import."""
        widgets = []

        intro = QLabel("""
<h3>JSON Export for Direct Import</h3>
<p>These prompts generate JSON data that can be pasted directly into Writer Platform's project files.
This is the fastest way to populate your project with AI-generated content.</p>
<p><b>How to use:</b></p>
<ol>
<li>Copy a prompt and paste it with your content into an AI assistant</li>
<li>Copy the JSON response</li>
<li>Save your current project, then close Writer Platform</li>
<li>Open your .writerproj file in a text editor</li>
<li>Merge the JSON into the appropriate section</li>
<li>Reopen the project in Writer Platform</li>
</ol>
<p><b>Tip:</b> Always back up your project before manually editing the JSON!</p>
        """)
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        widgets.append(intro)

        widgets.append(self._create_prompt_widget(
            "Characters JSON Export",
            """Based on the following character information, generate JSON for Writer Platform:

[PASTE YOUR CHARACTER NOTES OR DESCRIPTIONS]

Generate a JSON array of character objects with this structure:
```json
{
  "characters": [
    {
      "id": "char_[unique_id]",
      "name": "Character Name",
      "character_type": "protagonist|antagonist|major|minor",
      "personality": "Detailed personality description...",
      "backstory": "Character's history and background...",
      "social_network": {
        "Other Character Name": "relationship description"
      },
      "notes": "Additional notes..."
    }
  ]
}
```

Generate complete entries for all characters mentioned. Use UUID-style IDs (e.g., "char_a1b2c3d4"). The character_type must be one of: protagonist, antagonist, major, minor.""",
            "Generate character data that can be merged into your project file.",
            "JSON Export"
        ))

        widgets.append(self._create_prompt_widget(
            "Story Planning JSON Export",
            """Based on the following plot information, generate JSON for Writer Platform:

[PASTE YOUR PLOT SUMMARY OR OUTLINE]

Generate JSON with this structure:
```json
{
  "story_planning": {
    "main_plot": "Summary of the main plot...",
    "themes": ["Theme 1", "Theme 2", "Theme 3"],
    "freytag_pyramid": {
      "exposition": "Setup and introduction...",
      "rising_action": "Complications and escalation...",
      "climax": "The peak moment of conflict...",
      "falling_action": "Aftermath and consequences...",
      "resolution": "How things settle...",
      "events": [
        {
          "id": "event_[unique_id]",
          "title": "Event Title",
          "description": "What happens...",
          "outcome": "What changes as a result...",
          "stage": "exposition|rising_action|climax|falling_action|resolution",
          "intensity": 50,
          "sort_order": 1,
          "related_characters": ["Character Name 1"],
          "notes": ""
        }
      ]
    },
    "subplots": [
      {
        "id": "subplot_[unique_id]",
        "title": "Subplot Title",
        "description": "What this subplot is about...",
        "connection_to_main": "How it relates to main plot...",
        "related_characters": ["Character Name"],
        "status": "active|resolved|abandoned"
      }
    ]
  }
}
```

Include at least 10 events across all stages. Intensity is 0-100 (higher = more dramatic).""",
            "Generate plot structure data for your project.",
            "JSON Export"
        ))

        widgets.append(self._create_prompt_widget(
            "Worldbuilding JSON Export",
            """Based on the following world information, generate JSON for Writer Platform:

[PASTE YOUR WORLDBUILDING NOTES]

Generate JSON with this structure:
```json
{
  "worldbuilding": {
    "mythology": "Overview of myths and religions...",
    "planets": "Description of world geography...",
    "climate": "Climate and environment...",
    "history": "Historical overview...",
    "politics": "Political systems...",
    "military": "Military forces and conflicts...",
    "economy": "Economic systems and trade...",
    "power_hierarchy": "Power structures...",
    "custom_sections": {
      "Magic System": "Description of magic...",
      "Technology": "Description of tech level..."
    },
    "factions": [
      {
        "id": "faction_[unique_id]",
        "name": "Faction Name",
        "faction_type": "nation|organization|religion|tribe|corporation|other",
        "description": "Description...",
        "leader": "Leader name or null",
        "territory": ["Location 1", "Location 2"],
        "allies": [],
        "enemies": [],
        "military_strength": 50,
        "economic_power": 50,
        "notes": ""
      }
    ],
    "myths": [
      {
        "id": "myth_[unique_id]",
        "name": "Myth Title",
        "myth_type": "creation|hero|prophecy|legend|other",
        "description": "Brief description...",
        "full_text": "The full story of the myth...",
        "moral_lesson": "What it teaches...",
        "associated_factions": ["Faction Name"]
      }
    ]
  }
}
```

Fill in all sections based on the provided information. Leave sections empty ("") if no information is available.""",
            "Generate complete worldbuilding data for your project.",
            "JSON Export"
        ))

        widgets.append(self._create_prompt_widget(
            "Complete Project JSON Template",
            """Generate a complete Writer Platform project JSON based on this story information:

Title: [YOUR STORY TITLE]
Summary: [2-3 PARAGRAPH SUMMARY]
Characters: [LIST MAIN CHARACTERS]
Setting: [DESCRIBE SETTING]
Genre: [YOUR GENRE]

Generate a complete project JSON with this structure:
```json
{
  "name": "Project Name",
  "description": "Project description...",
  "worldbuilding": { ... },
  "characters": [ ... ],
  "story_planning": { ... },
  "manuscript": {
    "title": "Manuscript Title",
    "author": "Author Name",
    "chapters": []
  },
  "generated_images": [],
  "agent_contacts": [],
  "dictionary": {
    "words": [],
    "definitions": {}
  }
}
```

Populate worldbuilding, characters, and story_planning based on the provided information.
Leave manuscript.chapters empty (the user will add their own text).
Generate unique IDs for all elements (format: type_randomstring, e.g., "char_a1b2c3d4").""",
            "Generate a complete project file to start with.",
            "JSON Export"
        ))

        return self._create_scrollable_content(widgets)
