"""Integrated Agent Suite for cost-effective AI assistance.

This module coordinates all AI agents and provides a unified conversational
interface for worldbuilding, character development, and writing assistance.
"""

from typing import Optional, Dict, List, Any, TYPE_CHECKING
from enum import Enum
from dataclasses import dataclass
from pathlib import Path

from src.ai.llm_client import LLMClient, LLMProvider, HuggingFaceConfig
from src.ai.worldbuilding_agent import WorldbuildingAgent
from src.ai.chapter_analysis_agent import ChapterAnalysisAgent, ChapterAnalysis
from src.ai.enhanced_rag import EnhancedRAGSystem
from src.ai.semantic_search import SearchMethod
from src.config.ai_config import get_ai_config
from src.services.tts_service import get_tts_service, TTSEngine
from src.services.tts_document_generator import TTSDocumentGenerator, TTSDocumentConfig, create_default_config, get_tts_output_dir

if TYPE_CHECKING:
    from src.models.project import WriterProject


class AgentMode(Enum):
    """Agent operating modes."""
    WORLDBUILDING = "worldbuilding"
    CHARACTER_DEVELOPMENT = "character_development"
    CHAPTER_ANALYSIS = "chapter_analysis"
    GENERAL_CHAT = "general_chat"
    RECOMMENDATIONS = "recommendations"
    TEXT_TO_SPEECH = "text_to_speech"


@dataclass
class AgentConfig:
    """Configuration for agent suite."""
    use_local_model: bool = False
    local_model_id: str = "microsoft/Phi-3.5-mini-instruct"
    primary_provider: str = "claude"
    enable_conversation_logging: bool = True
    cost_tracking: bool = True


class AgentSuite:
    """Unified agent suite for AI-assisted worldbuilding and writing.

    This class coordinates multiple specialized agents and provides:
    - Cost-effective hybrid cloud/local LLM routing
    - Conversational interface for creating worldbuilding elements
    - Line-item chapter analysis
    - Recommendations without writing content
    """

    def __init__(
        self,
        project: Optional['WriterProject'] = None,
        config: Optional[AgentConfig] = None
    ):
        """Initialize agent suite.

        Args:
            project: WriterProject for context
            config: AgentConfig for customization
        """
        self.project = project
        self.config = config or AgentConfig()
        self.ai_config = get_ai_config()

        # Initialize LLM clients
        self.primary_llm: Optional[LLMClient] = None
        self.local_llm: Optional[LLMClient] = None

        # Initialize specialized agents (lazy loaded)
        self._worldbuilding_agent: Optional[WorldbuildingAgent] = None
        self._chapter_agent: Optional[ChapterAnalysisAgent] = None

        # Initialize RAG system for semantic context retrieval
        self._rag_system: Optional[EnhancedRAGSystem] = None
        self._rag_initialized = False

        # Conversation state
        self.current_mode = AgentMode.GENERAL_CHAT
        self.conversation_history: List[Dict[str, str]] = []

        # Cost tracking
        self.session_cost = 0.0

        # TTS service
        self._tts_service = None
        self._tts_generator = None

        # Initialize primary LLM
        self._init_primary_llm()

        # Initialize local LLM if configured
        if self.config.use_local_model:
            self._init_local_llm()

        # Initialize RAG system
        self._init_rag_system()

    def _init_primary_llm(self):
        """Initialize primary cloud LLM."""
        provider = self.config.primary_provider
        api_key = self.ai_config.get_api_key(provider)
        model = self.ai_config.get_model(provider)

        if not api_key:
            raise ValueError(
                f"No API key configured for {provider}. "
                "Please configure in Settings > AI Configuration."
            )

        provider_enum = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.CHATGPT,
            "openai": LLMProvider.CHATGPT,
            "gemini": LLMProvider.GEMINI
        }.get(provider.lower(), LLMProvider.CLAUDE)

        self.primary_llm = LLMClient(
            provider=provider_enum,
            api_key=api_key,
            model=model,
            enable_conversation_logging=self.config.enable_conversation_logging
        )

    def _init_local_llm(self):
        """Initialize local LLM for cost savings."""
        try:
            # Configure for 4-bit quantization for memory efficiency
            hf_config = HuggingFaceConfig(
                model_id=self.config.local_model_id,
                use_local=True,
                device="auto",
                quantization="4bit",
                trust_remote_code=True
            )

            self.local_llm = LLMClient(
                provider=LLMProvider.HUGGINGFACE_LOCAL,
                hf_config=hf_config
            )

            print(f"Local model loaded: {self.config.local_model_id}")
        except Exception as e:
            print(f"Failed to load local model: {e}")
            print("Falling back to cloud-only mode.")
            self.config.use_local_model = False

    def _init_rag_system(self):
        """Initialize RAG system for semantic context retrieval."""
        if not self.project:
            return

        try:
            self._rag_system = EnhancedRAGSystem(
                project=self.project,
                llm_client=self.primary_llm
            )
            self._rag_system.rebuild_index()
            self._rag_initialized = True
            print("RAG system initialized successfully")
        except Exception as e:
            print(f"Failed to initialize RAG system: {e}")
            self._rag_initialized = False

    def refresh_rag_index(self):
        """Refresh the RAG index when project data changes."""
        if self._rag_system:
            self._rag_system.rebuild_index()

    @property
    def rag_system(self) -> Optional[EnhancedRAGSystem]:
        """Get RAG system (initialized on demand)."""
        if not self._rag_initialized and self.project:
            self._init_rag_system()
        return self._rag_system

    @property
    def worldbuilding_agent(self) -> WorldbuildingAgent:
        """Get worldbuilding agent (lazy loaded)."""
        if not self._worldbuilding_agent:
            self._worldbuilding_agent = WorldbuildingAgent(
                primary_llm=self.primary_llm,
                local_llm=self.local_llm,
                project=self.project
            )
        return self._worldbuilding_agent

    @property
    def chapter_agent(self) -> ChapterAnalysisAgent:
        """Get chapter analysis agent (lazy loaded)."""
        if not self._chapter_agent:
            self._chapter_agent = ChapterAnalysisAgent(
                primary_llm=self.primary_llm,
                local_llm=self.local_llm
            )
        return self._chapter_agent

    def chat(self, user_message: str, mode: Optional[AgentMode] = None) -> str:
        """Conversational interface with the agent.

        Args:
            user_message: User's message
            mode: Optional mode to switch to

        Returns:
            Agent's response
        """
        if mode:
            self.current_mode = mode

        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": user_message})

        # Route to appropriate handler based on mode and content
        response = self._route_message(user_message)

        # Add response to history
        self.conversation_history.append({"role": "assistant", "content": response})

        return response

    def _route_message(self, message: str) -> str:
        """Route message to appropriate agent based on context."""
        message_lower = message.lower()

        # Check for mode-switching keywords
        if any(word in message_lower for word in ["create character", "new character", "character named"]):
            return self._handle_character_creation(message)
        elif any(word in message_lower for word in ["create faction", "new faction", "faction called"]):
            return self._handle_faction_creation(message)
        elif any(word in message_lower for word in ["create place", "new place", "location called", "add place"]):
            return self._handle_place_creation(message)
        elif any(word in message_lower for word in ["analyze chapter", "review chapter", "feedback on"]):
            return self._handle_chapter_analysis(message)
        elif any(word in message_lower for word in ["suggest", "recommend", "ideas for", "help with"]):
            return self._handle_recommendations(message)
        elif any(word in message_lower for word in ["read aloud", "speak text", "text to speech", "tts", "read this", "generate tts", "convert to speech", "audio", "narrate"]):
            return self._handle_tts_request(message)
        elif self.current_mode == AgentMode.WORLDBUILDING:
            return self._handle_worldbuilding_chat(message)
        elif self.current_mode == AgentMode.CHAPTER_ANALYSIS:
            return self._handle_chapter_analysis(message)
        elif self.current_mode == AgentMode.TEXT_TO_SPEECH:
            return self._handle_tts_request(message)
        else:
            return self._handle_general_chat(message)

    def _handle_character_creation(self, message: str) -> str:
        """Handle character creation request."""
        if not self.project:
            return "Please open a project first before creating characters."

        # Get world context using RAG for relevant character-related info
        world_context = self._get_world_context(message)

        # Use worldbuilding agent
        character_data = self.worldbuilding_agent.help_create_character(
            user_description=message,
            world_context=world_context
        )

        # Format response
        response = f"""I've drafted some character suggestions based on your description:

**Name:** {character_data.get('name', '[Choose a name]')}
**Type:** {character_data.get('character_type', 'Supporting')}

**Personality Ideas:**
{character_data.get('personality', '[Develop personality]')}

**Full Suggestions:**
{character_data.get('notes', '')}

Would you like me to:
1. Add this character to your project (you can edit details after)
2. Refine any aspect of the character
3. Generate additional ideas

Just let me know what you'd like to do next!
"""
        return response

    def _handle_faction_creation(self, message: str) -> str:
        """Handle faction creation request."""
        if not self.project:
            return "Please open a project first before creating factions."

        world_context = self._get_world_context(message)

        faction_data = self.worldbuilding_agent.help_create_faction(
            user_description=message,
            world_context=world_context
        )

        response = f"""Here are some faction ideas based on your description:

{faction_data.get('description', '')}

I can help you:
1. Add this faction to your project
2. Develop specific aspects (goals, structure, conflicts)
3. Suggest how this faction interacts with existing ones

What would you like to do?
"""
        return response

    def _handle_place_creation(self, message: str) -> str:
        """Handle place/location creation request."""
        if not self.project:
            return "Please open a project first before creating places."

        world_context = self._get_world_context(message)

        # Get available planets
        planets = [p.name for p in self.project.worldbuilding.planets] if hasattr(self.project.worldbuilding, 'planets') else []

        place_data = self.worldbuilding_agent.help_create_place(
            user_description=message,
            world_context=world_context,
            available_planets=planets
        )

        response = f"""Here are some ideas for this place:

{place_data.get('notes', '')}

I can help you:
1. Add this place to your project
2. Add it to a map
3. Develop more details
4. Connect it to existing locations

What would you like to do next?
"""
        return response

    def _handle_chapter_analysis(self, message: str) -> str:
        """Handle chapter analysis request."""
        # This is a conversational stub - full implementation would
        # need integration with chapter selection UI

        response = """I can analyze chapters for you! Here's what I can do:

**Quick Review** (cost-effective, ~$0.01)
- Overall impression
- Top 3 strengths and areas to improve
- Few specific suggestions

**Detailed Analysis** (~$0.05-0.10)
- Comprehensive assessment
- 5-7 line-item suggestions with explanations
- Pacing and character consistency notes
- Paragraph-level feedback

Please select a chapter from your manuscript, and let me know if you want a quick review or detailed analysis.
"""
        return response

    def _handle_recommendations(self, message: str) -> str:
        """Handle recommendation requests."""
        if not self.project:
            return "Please open a project to get context-specific recommendations."

        # Determine category from message
        category = "general"
        if "character" in message.lower():
            category = "characters"
        elif "faction" in message.lower() or "organization" in message.lower():
            category = "factions"
        elif "place" in message.lower() or "location" in message.lower():
            category = "places"
        elif "plot" in message.lower() or "story" in message.lower():
            category = "plot"

        world_context = self._get_world_context(message)

        # Get existing elements
        existing = self._get_existing_elements(category)

        agent_response = self.worldbuilding_agent.get_recommendations(
            category=category,
            context=world_context,
            question=message,
            existing_elements=existing
        )

        # Update cost tracking
        self.session_cost += agent_response.cost_estimate

        response = f"""{agent_response.content}

---
*Cost: ${agent_response.cost_estimate:.4f} | Model: {agent_response.model_used}*
"""
        return response

    def _handle_worldbuilding_chat(self, message: str) -> str:
        """Handle general worldbuilding conversation."""
        # General worldbuilding assistance
        world_context = self._get_world_context(message)

        system_prompt = """You are a worldbuilding consultant helping an author.
        Provide creative suggestions and ask clarifying questions.
        Do NOT write content for them - suggest and recommend.
        Keep responses concise for cost efficiency."""

        prompt = f"""
World Context:
{world_context[:1000]}

User Message:
{message}

Provide helpful suggestions or ask clarifying questions.
"""

        llm = self.local_llm if self.local_llm and len(message) < 200 else self.primary_llm
        response = llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=400,
            temperature=0.7
        )

        return response

    def _handle_general_chat(self, message: str) -> str:
        """Handle general conversation."""
        system_prompt = """You are a helpful writing assistant. Provide guidance,
        suggestions, and support. Do not write content - help the author develop
        their own ideas. Be encouraging and constructive."""

        response = self.primary_llm.generate_text(
            message,
            system_prompt,
            max_tokens=300,
            temperature=0.7
        )

        return response

    def _handle_tts_request(self, message: str) -> str:
        """Handle text-to-speech related requests."""
        message_lower = message.lower()

        # Check what type of TTS action is requested
        if "generate" in message_lower or "convert" in message_lower or "document" in message_lower:
            return self._get_tts_generation_help()
        elif "stop" in message_lower or "pause" in message_lower:
            return self._stop_tts()
        elif "status" in message_lower or "available" in message_lower or "check" in message_lower:
            return self._get_tts_status()
        elif "voice" in message_lower or "configure" in message_lower or "settings" in message_lower:
            return self._get_tts_voice_info()
        elif "help" in message_lower:
            return self._get_tts_help()
        else:
            return self._get_tts_help()

    def _get_tts_help(self) -> str:
        """Get TTS help information."""
        tts_service = self.get_tts_service()
        status = "available" if tts_service and tts_service.is_available() else "not available"
        engine = tts_service.engine.value if tts_service else "none"

        return f"""**Text-to-Speech Capabilities**

Current Status: {status}
Active Engine: {engine}

**Available Actions:**

1. **Read Aloud** - Use the 🔊 Read button in the chapter toolbar, or right-click on selected text
2. **Generate TTS Document** - Convert chapter text to speaker-formatted document for multi-voice synthesis
3. **Stop Playback** - Use the ⏹ Stop button or say "stop TTS"

**TTS Engines:**
- **pyttsx3**: Offline, basic voices (default)
- **edge-tts**: Microsoft Azure voices (requires internet)
- **VibeVoice**: Multi-speaker synthesis (requires installation)

**For VibeVoice:**
1. Install from Settings > TTS Settings > Install VibeVoice
2. Generate a TTS document with speaker assignments (🎙 Generate TTS button)
3. Run the generated document through VibeVoice for multi-voice audio

Would you like to:
- Check TTS availability ("tts status")
- Configure voices ("tts voices")
- Generate a TTS document ("generate tts document")
"""

    def _get_tts_status(self) -> str:
        """Get TTS system status."""
        tts_service = self.get_tts_service()

        if not tts_service:
            return """**TTS Status: Not Available**

Text-to-Speech service is not initialized.

To enable TTS:
1. Install pyttsx3: `pip install pyttsx3`
2. Or install edge-tts: `pip install edge-tts`
3. Restart the application
"""

        status_lines = ["**TTS Status Report**", ""]
        status_lines.append(f"Service Available: {'Yes' if tts_service.is_available() else 'No'}")
        status_lines.append(f"Current Engine: {tts_service.engine.value}")
        status_lines.append(f"Voice: {tts_service.voice}")

        # Check VibeVoice installation
        vv_installed = tts_service.is_vibevoice_installed()
        status_lines.append(f"VibeVoice Installed: {'Yes' if vv_installed else 'No'}")

        if vv_installed:
            status_lines.append(f"VibeVoice Path: {tts_service._vibevoice_path}")
            status_lines.append(f"VibeVoice Model: {tts_service._vibevoice_model}")

        # Available voices
        voices = tts_service.get_voices()
        if voices:
            status_lines.append(f"\nAvailable Voices ({len(voices)}):")
            for v in voices[:5]:
                status_lines.append(f"  - {v.name} ({v.id})")
            if len(voices) > 5:
                status_lines.append(f"  ... and {len(voices) - 5} more")

        return "\n".join(status_lines)

    def _get_tts_voice_info(self) -> str:
        """Get TTS voice configuration info."""
        tts_service = self.get_tts_service()

        if not tts_service or not tts_service.is_available():
            return "TTS is not available. Please install pyttsx3 or edge-tts first."

        voices = tts_service.get_voices()
        voice_info = ["**Available TTS Voices**", ""]

        for voice in voices:
            voice_info.append(f"**{voice.name}** (ID: `{voice.id}`)")
            if voice.language:
                voice_info.append(f"  Language: {voice.language}")
            if voice.gender:
                voice_info.append(f"  Gender: {voice.gender}")
            voice_info.append("")

        voice_info.append("**VibeVoice Voices** (if installed):")
        voice_info.append("- Carter: Deep, authoritative male voice")
        voice_info.append("- Davis: Warm, friendly male voice")
        voice_info.append("- Emma: Clear, professional female voice")
        voice_info.append("- Frank: Mature, steady male voice")
        voice_info.append("- Grace: Soft, gentle female voice")
        voice_info.append("- Mike: Energetic, youthful male voice")
        voice_info.append("- Samuel: Distinguished, formal male voice")
        voice_info.append("")
        voice_info.append("To change voices, go to Settings > TTS Settings")

        return "\n".join(voice_info)

    def _get_tts_generation_help(self) -> str:
        """Get help for TTS document generation."""
        return """**TTS Document Generation**

To generate a TTS document from your chapter:

1. **From Toolbar**: Click the 🎙 **Generate TTS** button in the chapter editor
2. **From Context Menu**: Right-click and select **Text to Speech > Generate TTS Doc for Chapter...**
3. **For Selected Text**: Select text, right-click, and choose **Generate TTS Doc from Selection...**

**The Generator Dialog allows you to:**
- Choose the TTS format (VibeVoice, Plain, or SSML)
- Configure multiple speakers with different voices
- Enable/disable dialogue detection
- Set custom speaker names

**Output:**
- TTS documents are saved to: `~/.writer_platform/tts_output/`
- Format: `{chapter_name}_tts.txt`
- Files are overwritten when regenerated (no duplicates)

**For VibeVoice multi-speaker synthesis:**
```
Speaker 1: [narrator text]
Speaker 2: [dialogue text]
Speaker 3: [different character]
```

Would you like me to explain more about speaker configuration or dialogue detection?
"""

    def _stop_tts(self) -> str:
        """Stop TTS playback."""
        tts_service = self.get_tts_service()
        if tts_service:
            tts_service.stop()
            return "TTS playback stopped."
        return "TTS service is not available."

    def get_tts_service(self):
        """Get or initialize the TTS service."""
        if self._tts_service is None:
            try:
                self._tts_service = get_tts_service()
            except Exception as e:
                print(f"Failed to initialize TTS service: {e}")
        return self._tts_service

    def get_tts_generator(self, config=None):
        """Get or initialize the TTS document generator."""
        if self._tts_generator is None or config is not None:
            self._tts_generator = TTSDocumentGenerator(config or create_default_config())
        return self._tts_generator

    def speak_text(self, text: str) -> bool:
        """Speak text aloud using TTS.

        Args:
            text: Text to speak

        Returns:
            True if successful
        """
        tts_service = self.get_tts_service()
        if not tts_service or not tts_service.is_available():
            return False

        tts_service.speak(text)
        return True

    def generate_tts_document(self, text: str, chapter_name: str = "chapter", config=None):
        """Generate a TTS document from text.

        Args:
            text: Source text to convert
            chapter_name: Name for the output file
            config: Optional TTSDocumentConfig

        Returns:
            Tuple of (output file path, list of speaker names used)
        """
        generator = self.get_tts_generator(config)
        output_dir = get_tts_output_dir()
        return generator.generate_tts_document(text, output_dir, chapter_name)

    def _get_world_context(self, query: str = "") -> str:
        """Get relevant world context for current conversation.

        Uses RAG system for semantic search if available and query provided,
        otherwise falls back to basic context extraction.

        Args:
            query: Optional query to find relevant context for

        Returns:
            Formatted context string
        """
        if not self.project:
            return ""

        # Try to use RAG system for targeted context retrieval
        if query and self.rag_system:
            try:
                context = self.rag_system.get_context_for_ai(
                    query=query,
                    max_tokens=1500,
                    method=SearchMethod.HYBRID
                )
                if context:
                    return context
            except Exception as e:
                print(f"RAG context retrieval failed: {e}")

        # Fallback to basic context extraction
        wb = self.project.worldbuilding
        context_parts = []

        # Add key worldbuilding sections
        if wb.mythology:
            context_parts.append(f"Mythology: {wb.mythology[:200]}")
        if wb.history:
            context_parts.append(f"History: {wb.history[:200]}")
        if wb.politics:
            context_parts.append(f"Politics: {wb.politics[:200]}")

        # Add factions summary
        if hasattr(wb, 'factions') and wb.factions:
            faction_names = [f.name for f in wb.factions[:10]]
            context_parts.append(f"Key Factions: {', '.join(faction_names)}")

        # Add technologies summary
        if hasattr(wb, 'technologies') and wb.technologies:
            tech_names = [t.name for t in wb.technologies[:10]]
            context_parts.append(f"Technologies: {', '.join(tech_names)}")

        # Add places summary
        if hasattr(wb, 'places') and wb.places:
            place_names = [p.name for p in wb.places[:10]]
            context_parts.append(f"Key Places: {', '.join(place_names)}")

        # Add character names
        if self.project.characters:
            char_names = [c.name for c in self.project.characters[:10]]
            context_parts.append(f"Key Characters: {', '.join(char_names)}")

        # Add story promises
        if hasattr(self.project.story_planning, 'promises') and self.project.story_planning.promises:
            promises = [p.title for p in self.project.story_planning.promises[:5]]
            context_parts.append(f"Story Promises: {', '.join(promises)}")

        return "\n\n".join(context_parts)

    def _get_existing_elements(self, category: str) -> List[str]:
        """Get list of existing elements for a category."""
        if not self.project:
            return []

        if category == "characters":
            return [c.name for c in self.project.characters]
        elif category == "factions":
            return [f.name for f in getattr(self.project.worldbuilding, 'factions', [])]
        elif category == "places":
            return [p.name for p in getattr(self.project.worldbuilding, 'places', [])]

        return []

    def analyze_chapter_full(
        self,
        chapter_text: str,
        chapter_title: str,
        detailed: bool = True
    ) -> ChapterAnalysis:
        """Analyze chapter and return structured analysis.

        Args:
            chapter_text: Full chapter text
            chapter_title: Chapter title
            detailed: If True, provides detailed line-item analysis

        Returns:
            ChapterAnalysis object
        """
        manuscript_context = ""
        if self.project:
            # Get relevant context from project
            sp = self.project.story_planning
            if sp.main_plot:
                manuscript_context = f"Main Plot: {sp.main_plot[:300]}"

        analysis = self.chapter_agent.analyze_chapter(
            chapter_text=chapter_text,
            chapter_title=chapter_title,
            manuscript_context=manuscript_context,
            detailed=detailed
        )

        self.session_cost += analysis.estimated_cost

        return analysis

    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cost summary for current session.

        Returns:
            Dict with cost breakdown
        """
        wb_stats = {}
        if self._worldbuilding_agent:
            wb_stats = self._worldbuilding_agent.get_usage_stats()

        chapter_cost = 0.0
        if self._chapter_agent:
            chapter_cost = self._chapter_agent.get_total_cost()

        return {
            "session_total": round(self.session_cost, 4),
            "worldbuilding_agent": wb_stats,
            "chapter_agent_cost": chapter_cost,
            "local_model_enabled": self.config.use_local_model,
            "primary_provider": self.config.primary_provider
        }

    def reset_session(self):
        """Reset session state and conversation."""
        self.conversation_history.clear()
        self.session_cost = 0.0
        self.current_mode = AgentMode.GENERAL_CHAT

        if self._worldbuilding_agent:
            self._worldbuilding_agent.reset_usage_stats()
        if self._chapter_agent:
            self._chapter_agent.reset_cost()

    def export_conversation(self, file_path: Path) -> bool:
        """Export conversation history to file.

        Args:
            file_path: Path to export to

        Returns:
            True if successful
        """
        try:
            import json
            from datetime import datetime

            data = {
                "exported_at": datetime.now().isoformat(),
                "project": self.project.name if self.project else None,
                "conversation": self.conversation_history,
                "cost_summary": self.get_cost_summary()
            }

            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            return True
        except Exception as e:
            print(f"Error exporting conversation: {e}")
            return False


def create_agent_suite(
    project: Optional['WriterProject'] = None,
    use_local_model: bool = False,
    local_model_id: str = "microsoft/Phi-3.5-mini-instruct"
) -> AgentSuite:
    """Factory function to create configured agent suite.

    Args:
        project: Optional WriterProject
        use_local_model: Whether to use local model for cost savings
        local_model_id: HuggingFace model ID for local model

    Returns:
        Configured AgentSuite
    """
    config = AgentConfig(
        use_local_model=use_local_model,
        local_model_id=local_model_id,
        enable_conversation_logging=True,
        cost_tracking=True
    )

    return AgentSuite(project=project, config=config)
