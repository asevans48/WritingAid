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
from src.ai.mlx_utils import can_use_mlx
from src.config.ai_config import get_ai_config
from src.services.tts_service import get_tts_service
from src.services.tts_document_generator import TTSDocumentGenerator, create_default_config, get_tts_output_dir

if TYPE_CHECKING:
    from src.models.project import WriterProject


def get_default_local_model() -> str:
    """Get platform-specific default local model.

    Returns:
        MLX model on Apple Silicon, PyTorch model elsewhere
    """
    if can_use_mlx():
        return "mlx-community/Qwen2.5-7B-Instruct-4bit"
    else:
        return "microsoft/Phi-3.5-mini-instruct"


class AgentMode(Enum):
    """Agent operating modes."""
    WORLDBUILDING = "worldbuilding"
    CHARACTER_DEVELOPMENT = "character_development"
    CHAPTER_ANALYSIS = "chapter_analysis"
    CHAPTER_PLANNING = "chapter_planning"
    GENERAL_CHAT = "general_chat"
    RECOMMENDATIONS = "recommendations"
    TEXT_TO_SPEECH = "text_to_speech"


@dataclass
class AgentConfig:
    """Configuration for agent suite with platform-aware defaults."""
    use_local_model: bool = False
    local_model_id: str = None  # Will be set to platform default if None
    primary_provider: str = "claude"
    enable_conversation_logging: bool = True
    cost_tracking: bool = True

    def __post_init__(self):
        """Set platform-specific default model if not specified."""
        if self.local_model_id is None:
            self.local_model_id = get_default_local_model()


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

        # Per-task LLM cache. Each task can route to a different trained
        # model selected in CreativeOS settings; we lazily build the local
        # LLMClient on first use and reuse it after. The cache enforces
        # an LRU policy so a writing session that touches several
        # task-specific models doesn't pile them up in RAM. When the
        # cap is hit, the least-recently-used client gets ``unload()``
        # called on it before being dropped, releasing its weights.
        # Keyed by trained-model path (the registry key), since the
        # same path may serve multiple tasks via the resolver chain.
        from collections import OrderedDict
        self._task_local_llms: "OrderedDict[str, Optional[LLMClient]]" = (
            OrderedDict())
        # Cap is sourced from the user's CreativeOS settings
        # (``max_loaded_models``) so it stays in lockstep with the
        # global LoadedModelCache cap. Falls back to 2 when the
        # settings layer isn't reachable. The cap is re-read on
        # every ``get_llm_for_task`` call so a settings change takes
        # effect on the next task without restarting.
        self._task_local_llm_cap = self._read_max_models_from_config()

    @staticmethod
    def _read_max_models_from_config() -> int:
        """Read ``max_loaded_models`` from CreativeOS settings.

        Bounded to [1, 8] — 1 is "always one at a time" (slow but
        minimal RAM); above 8 is almost never useful (RAM headroom
        runs out before the cap matters). Defaults to 2 on any
        config-import failure so the writing tool is always usable.
        """
        try:
            from src.config.creativeos_config import (
                get_creativeos_config,
            )
            cfg = get_creativeos_config()
            n = int(cfg.get("max_loaded_models", 2) or 2)
            return max(1, min(8, n))
        except Exception:
            return 2

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

    def reset_task_llm_cache(self) -> None:
        """Drop cached per-task LLMs.

        Call after the user changes their per-task model selection in
        CreativeOS settings, OR after an external call to
        ``unload_all_local_clients`` (e.g. the Training Studio freeing
        RAM). Cheap — clients are rebuilt lazily on next request.
        """
        self._task_local_llms.clear()
        # If our own local_llm was unloaded, forget it too so the next
        # call rebuilds fresh weights instead of crashing on an empty
        # pipeline. Cloud primary_llm is unaffected.
        try:
            if (self.local_llm is not None
                    and not self.local_llm.has_loaded_local_model()):
                self.local_llm = None
        except Exception:
            pass

    def _build_task_local_llm(self, model_path: str) -> Optional[LLMClient]:
        """Build an LLMClient pointing at a per-task trained model.

        We treat trained-model paths the same as any other local model id
        — the existing local provider stack handles them, and if the
        path is a LoRA-adapter directory the underlying loader picks the
        adapter up via PEFT. Falls back to None if construction fails so
        callers can degrade to ``primary_llm``.
        """
        if not model_path:
            return None
        try:
            local_settings = self.ai_config.get_local_model_settings()
            quantization = local_settings.get("quantization", "none")
            if quantization == "none":
                quantization = None
            trust = local_settings.get("trust_remote_code", True)

            hf_config = HuggingFaceConfig(
                model_id=model_path,
                use_local=True,
                device="auto",
                quantization=quantization,
                trust_remote_code=trust,
            )
            is_mlx = "mlx" in model_path.lower()
            provider = (LLMProvider.MLX_LOCAL if (is_mlx and can_use_mlx())
                        else LLMProvider.HUGGINGFACE_LOCAL)
            return LLMClient(provider=provider, hf_config=hf_config)
        except Exception as e:
            print(f"[AgentSuite] Could not load task model "
                  f"'{model_path}': {e}")
            return None

    def get_llm_for_task(self, task: str) -> 'LLMClient':
        """Return the LLMClient that should handle the given task.

        Resolution chain:
            1. Per-task model spec from CreativeOS settings (any kind:
               trained, local HF/MLX, or cloud)
            2. ``model_for_general`` spec, same options
            3. The agent suite's ``primary_llm`` (cloud or default local)

        This is what call sites should use instead of ``self.primary_llm``
        directly. The returned client may be local OR cloud depending on
        which kind the user picked.

        ``task`` should be one of: ``rephrase``, ``plot``, ``worldbuilding``,
        ``character``, ``general``. Unknown tasks fall through to the
        primary LLM unchanged.
        """
        try:
            from src.config.creativeos_config import get_creativeos_config
            cfg = get_creativeos_config()
            res = cfg.resolve_task_model(task)
        except Exception:
            return self.primary_llm

        # Refresh the cap from settings — the user may have raised
        # ``max_loaded_models`` while the writing tool was open and
        # we don't want to require a restart for the new cap to apply.
        self._task_local_llm_cap = self._read_max_models_from_config()

        spec = (res or {}).get("spec") or {"kind": ""}
        kind = spec.get("kind", "")
        if not kind:
            return self.primary_llm

        # Cache key is the canonical spec — same model, same key,
        # whether it came in as ``trained:Foo`` or ``hf:foo/bar``. We
        # use the resolved-to local path / hf id / cloud signature so
        # the cache de-duplicates correctly.
        if kind == "trained":
            trained = (res or {}).get("trained_model") or {}
            cache_key = trained.get("path", "")
        elif kind in ("hf", "mlx", "local"):
            cache_key = f"{kind}:{spec.get('model_id', '')}"
        elif kind == "cloud":
            # Cloud clients are cheap and don't hold weights; key on
            # provider+model so swapping models for the same provider
            # rebuilds.
            cache_key = (f"cloud:{spec.get('provider', '')}"
                         f":{spec.get('model') or ''}")
        else:
            return self.primary_llm
        if not cache_key:
            return self.primary_llm

        cached = self._task_local_llms.get(cache_key)
        if cached is not None:
            # Detect a stale entry whose weights were dropped by the
            # Training Studio's "Free RAM for training" flow. We rebuild
            # transparently rather than returning a dead client.
            try:
                still_loaded = cached.has_loaded_local_model()
            except Exception:
                # Cloud clients return False for has_loaded_local_model
                # — treat them as still-good since they don't hold
                # weights in RAM anyway.
                still_loaded = True
            if still_loaded or kind == "cloud":
                # Mark this entry as most-recently-used so it survives
                # the next eviction round.
                self._task_local_llms.move_to_end(cache_key)
                return cached
            self._task_local_llms.pop(cache_key, None)

        # Build the client. Reuse the new task_llm helper so cloud /
        # local / trained all share one construction path.
        try:
            from src.ai.task_llm import build_task_llm_override
            client = build_task_llm_override(task)
        except Exception as e:
            print(f"[AgentSuite] task LLM build failed for {task}: {e}")
            client = None
        if client is None:
            # Cache the miss so we don't keep retrying the failing build
            self._task_local_llms[cache_key] = None
            self._task_local_llms.move_to_end(cache_key)
            return self.primary_llm

        # Evict LRU entries if we're at the cap. Only count entries
        # that are actually loaded (have weights in RAM) — None
        # entries cost nothing (miss-cache markers), and cloud
        # entries cost no RAM either, so neither should consume slots
        # in the local-model cap.
        def _is_local_loaded(c):
            if c is None:
                return False
            try:
                return bool(c.has_loaded_local_model())
            except Exception:
                return False
        loaded_keys = [k for k, v in self._task_local_llms.items()
                       if _is_local_loaded(v)]
        while len(loaded_keys) >= self._task_local_llm_cap:
            oldest = loaded_keys[0]
            evicted = self._task_local_llms.pop(oldest, None)
            if evicted is not None:
                try:
                    evicted.unload()
                except Exception:
                    pass
            loaded_keys = [k for k, v in self._task_local_llms.items()
                           if _is_local_loaded(v)]

        self._task_local_llms[cache_key] = client
        self._task_local_llms.move_to_end(cache_key)
        return client

    def loaded_task_models(self) -> list:
        """Snapshot of currently-loaded per-task models. UI use.

        Returns a list of dicts ``{path, basename, loaded}`` ordered
        oldest → newest (LRU order). The bool ``loaded`` is True for
        entries with active LLMClient weights, False for cached
        miss-markers (failed builds we didn't retry). Each entry's
        ``basename`` is the trailing path segment so the UI can show
        a short label without exposing the full disk path.
        """
        from pathlib import Path as _P
        snap: list = []
        for path, client in self._task_local_llms.items():
            snap.append({
                "path": path,
                "basename": _P(path).name if path else "(unknown)",
                "loaded": client is not None,
            })
        return snap

    def _init_local_llm(self):
        """Initialize local LLM for cost savings.

        On Apple Silicon, uses MLX (mlx-lm) for efficient inference with
        native 4-bit quantization support. On other platforms uses the
        Hugging Face transformers pipeline (CUDA quantization via BitsAndBytes).
        """
        try:
            local_settings = self.ai_config.get_local_model_settings()
            quantization = local_settings.get("quantization", "none")
            # Treat "none" as no quantization
            if quantization == "none":
                quantization = None

            trust = local_settings.get("trust_remote_code", True)

            hf_config = HuggingFaceConfig(
                model_id=self.config.local_model_id,
                use_local=True,
                device="auto",
                quantization=quantization,
                trust_remote_code=trust
            )

            # On Apple Silicon use MLX for inference; elsewhere use transformers
            if can_use_mlx():
                provider = LLMProvider.MLX_LOCAL
            else:
                provider = LLMProvider.HUGGINGFACE_LOCAL

            self.local_llm = LLMClient(
                provider=provider,
                hf_config=hf_config
            )

            backend = "MLX" if can_use_mlx() else "HuggingFace"
            print(f"Local model loaded ({backend}): {self.config.local_model_id}"
                  f" [{quantization or 'full precision'}]")
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

    def suggest_paragraph_improvement(self,
                                       paragraph: str,
                                       *,
                                       context_before: str = "",
                                       context_after: str = "",
                                       max_suggestions: int = 2,
                                       genre: str = "") -> list:
        """Return up to ``max_suggestions`` rephrased versions of
        ``paragraph`` for the checkpoint-manifest reviewer.

        Each suggestion preserves meaning and length within ±25%;
        rephrases for clarity, voice, and prose rhythm. The
        surrounding paragraphs (``context_before`` / ``context_after``)
        give the model enough scaffolding to keep tense, POV, and
        character voice consistent. Returns ``[]`` on any LLM
        failure so the caller can surface a "no suggestions" state
        without crashing the dialog.

        The call routes through ``get_llm_for_task('rephrase')`` so
        the user's per-task trained-model preference (if any) is
        honoured and the LRU cache shares loaded models with other
        rephrase work.
        """
        text = (paragraph or "").strip()
        if not text:
            return []
        try:
            llm = self.get_llm_for_task("rephrase")
        except Exception:
            llm = self.primary_llm
        if not llm:
            return []
        n = max(1, min(5, int(max_suggestions)))
        sys_prompt = (
            "You are a literary editor. Rewrite the given paragraph "
            "to read more naturally — preserve meaning, length "
            "(within 25%), tense, POV, and character voice. "
            "Do not summarise. Output ONLY the numbered rewrites, "
            "one per line, prefixed '1. ' / '2. ' / etc., no "
            "commentary or quotes around them.")
        ctx_block = ""
        if context_before:
            ctx_block += (
                f"PARAGRAPH BEFORE (for tense/voice cues):\n"
                f"{context_before[-400:]}\n\n")
        if context_after:
            ctx_block += (
                f"PARAGRAPH AFTER (for tense/voice cues):\n"
                f"{context_after[:400]}\n\n")
        genre_clause = (
            f" Stay in the {genre} genre register." if genre else "")
        prompt = (
            f"{ctx_block}REWRITE THIS PARAGRAPH ({n} alternatives):"
            f"{genre_clause}\n\n{text}\n\n"
            f"Numbered rewrites (1.-{n}.):")
        try:
            raw = llm.generate_text(
                prompt=prompt,
                system_prompt=sys_prompt,
                max_tokens=max(800, len(text) * 3),
                temperature=0.7,
                task_type="rephrase")
        except Exception as e:
            print(f"[suggest_paragraph_improvement] LLM call failed: {e}")
            return []
        return self._parse_numbered_rewrites(raw, n)

    @staticmethod
    def _parse_numbered_rewrites(raw: str, max_n: int) -> list:
        """Pull numbered rewrites out of an LLM response.

        Handles three common shapes:
          * ``1. text\\n2. text\\n…``
          * ``1) text\\n2) text\\n…``
          * Plain newline-separated paragraphs (when the model
            ignored the numbering instruction).

        Returns at most ``max_n`` non-empty trimmed rewrites.
        """
        if not raw:
            return []
        import re as _re
        text = raw.strip()
        # Try numbered pattern first.
        candidates = _re.findall(
            r"^\s*\d+[\.\)]\s+(.+?)(?=\n\s*\d+[\.\)]|\Z)",
            text, flags=_re.MULTILINE | _re.DOTALL)
        if not candidates:
            # Fall back: blank-line separated chunks, capped to N.
            candidates = [
                c.strip() for c in _re.split(r"\n{2,}", text)
                if c.strip()]
        results = []
        for c in candidates:
            clean = c.strip().strip('"').strip("'")
            if clean and clean not in results:
                results.append(clean)
            if len(results) >= max_n:
                break
        return results

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
        elif any(word in message_lower for word in ["plan chapter", "chapter plan", "outline chapter", "chapter outline", "plan this chapter"]):
            return self._handle_chapter_planning(message)
        elif any(word in message_lower for word in ["rephrase", "rewrite", "write this as", "write from", "pov of", "point of view"]):
            return self._handle_rephrase_request(message)
        elif any(word in message_lower for word in ["suggest", "recommend", "ideas for", "help with"]):
            return self._handle_recommendations(message)
        elif any(word in message_lower for word in ["read aloud", "speak text", "text to speech", "tts", "read this", "generate tts", "convert to speech", "audio", "narrate"]):
            return self._handle_tts_request(message)
        elif any(word in message_lower for word in [
                "pacing", "sentence length", "tuldava", "lexical complexity",
                "lexical density", "compare to genre", "genre baseline",
                "genre stats", "conlit", "how fast", "how slow",
                "too long", "too short", "rhythm of"]):
            return self._handle_pacing_analysis(message)
        elif self.current_mode == AgentMode.WORLDBUILDING:
            return self._handle_worldbuilding_chat(message)
        elif self.current_mode == AgentMode.CHAPTER_ANALYSIS:
            return self._handle_chapter_analysis(message)
        elif self.current_mode == AgentMode.CHAPTER_PLANNING:
            return self._handle_chapter_planning(message)
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

        # If the user has chosen a 'character' trained model in CreativeOS
        # settings, route this call to it; otherwise pass None so the
        # worldbuilding agent's complexity-based routing kicks in.
        task_llm = self.get_llm_for_task("character")
        override = task_llm if task_llm is not self.primary_llm else None

        # Use worldbuilding agent
        character_data = self.worldbuilding_agent.help_create_character(
            user_description=message,
            world_context=world_context,
            llm_override=override,
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

        task_llm = self.get_llm_for_task("worldbuilding")
        override = task_llm if task_llm is not self.primary_llm else None

        faction_data = self.worldbuilding_agent.help_create_faction(
            user_description=message,
            world_context=world_context,
            llm_override=override,
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

        task_llm = self.get_llm_for_task("worldbuilding")
        override = task_llm if task_llm is not self.primary_llm else None

        place_data = self.worldbuilding_agent.help_create_place(
            user_description=message,
            world_context=world_context,
            available_planets=planets,
            llm_override=override,
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

    def _handle_chapter_planning(self, message: str, chapter_data: dict = None) -> str:
        """Handle chapter planning assistance.

        Args:
            message: User's request about chapter planning
            chapter_data: Optional dict with chapter planning data including:
                - chapter_title: Title of the chapter
                - chapter_number: Chapter number
                - outline: Current chapter outline
                - description: Chapter description
                - todos: List of todo items
                - notes: Planning notes

        Returns:
            AI response with planning assistance
        """
        if not self.project:
            return "Please open a project first to get chapter planning assistance."

        # Get world and story context for consistency
        world_context = self._get_world_context(message)
        story_context = self._get_story_planning_context()

        # Build context about current chapter planning
        chapter_context = ""
        if chapter_data:
            chapter_context = f"""
**Current Chapter: {chapter_data.get('chapter_title', 'Untitled')} (Chapter {chapter_data.get('chapter_number', '?')})**

Outline:
{chapter_data.get('outline', '(No outline yet)')}

Description:
{chapter_data.get('description', '(No description yet)')}

Current Todos:
{self._format_todos(chapter_data.get('todos', []))}

Notes:
{chapter_data.get('notes', '(No notes yet)')}

Subplot Notes:
{chapter_data.get('subplot_notes', '(No subplot notes yet)')}
"""

        system_prompt = """You are a writing planning assistant helping an author develop their chapter plans.
You help with:
- Creating chapter outlines that fit the overall story arc
- Suggesting scenes and plot points
- Identifying what needs to happen for story consistency
- Breaking down complex chapters into manageable todos
- Ensuring character arcs progress appropriately
- Tracking subplot progression across chapters
- Considering how magic systems and worldbuilding elements affect the chapter
- Checking for plot consistency

IMPORTANT: Do NOT write the actual chapter content. Only provide planning assistance, suggestions,
and structural guidance. The author writes the prose themselves. Remember this is the writer's art -
your suggestions should be useful but not forceful. Respect the author's creative vision.

Keep responses focused and actionable. Suggest specific tasks the author can add to their todo list.
"""

        # Include character details for POV / voice awareness
        character_context = self.get_character_context()

        prompt = f"""
{story_context}

{world_context}

{f"Characters:{chr(10)}{character_context}" if character_context else ""}

{chapter_context}

User Request:
{message}

Provide planning assistance for this chapter. Be specific and actionable.
If suggesting todos, format them as a bulleted list that the author can add to their planning.
"""

        # Per-task routing: if the user picked a 'plot' trained model
        # (or general fallback), get_llm_for_task returns it; otherwise
        # we fall back to the original local-vs-cloud heuristic.
        task_llm = self.get_llm_for_task("plot")
        if task_llm is self.primary_llm:
            llm = self.local_llm if self.local_llm and len(message) < 300 else self.primary_llm
        else:
            llm = task_llm
        response = llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=600,
            temperature=0.7
        )

        try:
            from src.data.learning_capture import capture_plot
            capture_plot(prompt=prompt, completion=response)
        except Exception:
            pass

        return response

    def _format_todos(self, todos: list) -> str:
        """Format todos for display in context."""
        if not todos:
            return "(No todos yet)"

        formatted = []
        for todo in todos:
            if isinstance(todo, dict):
                check = "☑" if todo.get('completed') else "☐"
                priority = todo.get('priority', 'normal')
                priority_marker = " [HIGH]" if priority == 'high' else (" [low]" if priority == 'low' else "")
                formatted.append(f"{check} {todo.get('text', '')}{priority_marker}")
            elif isinstance(todo, str):
                formatted.append(f"☐ {todo}")

        return "\n".join(formatted) if formatted else "(No todos yet)"

    def _get_story_planning_context(self) -> str:
        """Get story planning context for chapter planning assistance."""
        if not self.project:
            return ""

        sp = self.project.story_planning
        context_parts = ["**Story Context:**"]

        if sp.main_plot:
            context_parts.append(f"Main Plot: {sp.main_plot[:400]}")

        if sp.themes:
            context_parts.append(f"Themes: {', '.join(sp.themes[:5])}")

        # Freytag pyramid stages
        fp = sp.freytag_pyramid
        if fp.exposition:
            context_parts.append(f"Exposition: {fp.exposition[:150]}")
        if fp.rising_action:
            context_parts.append(f"Rising Action: {fp.rising_action[:150]}")
        if fp.climax:
            context_parts.append(f"Climax: {fp.climax[:150]}")

        # Key plot events
        if fp.events:
            events_summary = [f"- {e.title}" for e in fp.events[:5]]
            context_parts.append(f"Key Events:\n" + "\n".join(events_summary))

        # Subplots
        if sp.subplots:
            subplot_summary = [f"- {s.title}" for s in sp.subplots[:3]]
            context_parts.append(f"Subplots:\n" + "\n".join(subplot_summary))

        return "\n\n".join(context_parts)

    def get_chapter_planning_context(self, chapter) -> str:
        """Get full context for chapter planning AI assistance.

        Args:
            chapter: Chapter object with planning data

        Returns:
            Formatted context string for AI
        """
        if not chapter:
            return ""

        context_parts = []

        # Chapter info
        context_parts.append(f"**Chapter {chapter.number}: {chapter.title}**")

        if chapter.word_count:
            context_parts.append(f"Current word count: {chapter.word_count}")

        # Planning data
        planning = chapter.planning

        if planning.outline:
            context_parts.append(f"\n**Outline:**\n{planning.outline}")

        if planning.description:
            context_parts.append(f"\n**Description:**\n{planning.description}")

        if planning.todos:
            todos_text = self._format_todos([
                {'text': t.text, 'completed': t.completed, 'priority': t.priority}
                for t in planning.todos
            ])
            context_parts.append(f"\n**Writing Tasks:**\n{todos_text}")

        notes_text = planning.notes_as_text
        if notes_text:
            context_parts.append(f"\n**Notes:**\n{notes_text}")

        subplots_text = planning.subplots_as_text if hasattr(planning, 'subplots_as_text') else ""
        if subplots_text:
            context_parts.append(f"\n**Subplot Notes:**\n{subplots_text}")

        if planning.scene_list:
            context_parts.append(f"\n**Scenes:**\n" + "\n".join(f"- {s}" for s in planning.scene_list))

        if planning.characters_featured:
            context_parts.append(f"\n**Characters Featured:** {', '.join(planning.characters_featured)}")

        if planning.locations:
            context_parts.append(f"\n**Locations:** {', '.join(planning.locations)}")

        if planning.pov_character:
            context_parts.append(f"\n**POV Character:** {planning.pov_character}")

        if planning.timeline_position:
            context_parts.append(f"\n**Timeline Position:** {planning.timeline_position}")

        return "\n".join(context_parts)

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

        # Route to a worldbuilding-specific trained model if the user
        # picked one; otherwise fall through to the agent's defaults.
        task_llm = self.get_llm_for_task("worldbuilding")
        override = task_llm if task_llm is not self.primary_llm else None

        agent_response = self.worldbuilding_agent.get_recommendations(
            category=category,
            context=world_context,
            question=message,
            existing_elements=existing,
            llm_override=override,
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

        task_llm = self.get_llm_for_task("worldbuilding")
        if task_llm is self.primary_llm:
            llm = self.local_llm if self.local_llm and len(message) < 200 else self.primary_llm
        else:
            llm = task_llm
        response = llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=400,
            temperature=0.7,
            continue_if_truncated=True,
            max_continuations=2,
        )

        return response

    def get_character_context(self, character_names: List[str] = None) -> str:
        """Build detailed context string for specified characters (or all if none specified).

        Args:
            character_names: Optional list of character names to include.
                If None, returns brief context for all characters.

        Returns:
            Formatted string with character details.
        """
        if not self.project or not self.project.characters:
            return ""

        chars = self.project.characters
        if character_names:
            names_lower = [n.lower() for n in character_names]
            chars = [c for c in chars if c.name.lower() in names_lower]

        if not chars:
            return ""

        parts = []
        for c in chars:
            desc = [f"Name: {c.name}", f"Role: {c.character_type}"]
            if c.personality:
                desc.append(f"Personality: {c.personality}")
            if c.backstory:
                backstory = c.backstory[:300] + ("..." if len(c.backstory) > 300 else "")
                desc.append(f"Backstory: {backstory}")
            if c.notes:
                desc.append(f"Notes: {c.notes[:200]}")
            parts.append("\n".join(desc))
        return "\n---\n".join(parts)

    def _handle_rephrase_request(self, message: str, scene_description: str = "",
                                 surrounding_before: str = "",
                                 surrounding_after: str = "") -> str:
        """Handle rephrase/rewrite requests via chat, with character POV and scene awareness.

        Args:
            message: User's rephrase request
            scene_description: Optional description of what's happening in the scene
            surrounding_before: Text before the selection for continuity context
            surrounding_after: Text after the selection for continuity context
        """
        if not self.project:
            return "Please open a project first."

        # Try to detect character names mentioned in the message
        char_names_mentioned = []
        if self.project.characters:
            for c in self.project.characters:
                if c.name.lower() in message.lower():
                    char_names_mentioned.append(c.name)

        character_context = self.get_character_context(char_names_mentioned) if char_names_mentioned else ""

        world_context = self._get_world_context(message)

        system_prompt = """You are a skilled writing assistant helping an author rephrase and rewrite passages.

Guidelines:
- Maintain the original intent and key information
- Respect the author's voice — this is their art, offer alternatives not dictation
- When a character's POV is specified, let their personality and worldview color the language subtly
- If character details are provided, use them to inform word choice, perception, and emotional filtering
- If surrounding text is provided, use it for continuity — match flow and tone — but do NOT include it in your output
- If a scene description is given, let it inform the mood and sensory details of the rephrasing
- Preserve character names, proper nouns, and terminology
- Keep the same tense unless asked to change it"""

        prompt_parts = [f"User request: {message}"]
        if character_context:
            prompt_parts.append(f"\nPOV CHARACTER DETAILS:\n{character_context}")
        if scene_description:
            prompt_parts.append(f"\nSCENE: {scene_description}")
        if surrounding_before or surrounding_after:
            prompt_parts.append("\nSURROUNDING TEXT (for context only — do NOT rephrase):")
            if surrounding_before:
                prompt_parts.append(f"[BEFORE]: ...{surrounding_before[-300:]}")
            if surrounding_after:
                prompt_parts.append(f"[AFTER]: {surrounding_after[:300]}...")
        if world_context:
            prompt_parts.append(f"\nWorld Context:\n{world_context[:800]}")

        prompt = "\n".join(prompt_parts)

        # Route to the user's rephrase model if they picked one, else
        # use the default cloud LLM.
        llm = self.get_llm_for_task("rephrase")
        response = llm.generate_text(
            prompt,
            system_prompt,
            max_tokens=600,
            temperature=0.7
        )

        self.session_cost += 0.003
        return response

    def _handle_pacing_analysis(self, message: str) -> str:
        """Pacing / structural analysis using CONLIT genre baselines.

        Three sources feed the response:

          1. The current chapter content (from ``self.context``) is
             measured by ``pacing_analyzer.analyze_text`` — same
             metrics CONLIT publishes (avg sentence length, avg word
             length, Tuldava lexical complexity, dialogue ratio).
          2. The project's genre (``self.project.genre``) determines
             which CONLIT baseline to compare against. We try fuzzy
             matching against our genre taxonomy first, then fall back
             to "literary" as the most generic CONLIT-covered genre.
          3. The configured LLM is given the raw stats + comparison +
             the user's actual question, and asked to interpret them
             into craft advice.

        Graceful fallbacks:
          - No chapter loaded → tell the user to open a chapter and
            try again, but still answer general pacing questions
            from the LLM.
          - CONLIT not loaded → analyze the draft anyway, tell the
            user where to load CONLIT for genre comparison.
          - Genre is one CONLIT doesn't cover (horror, western, …)
            → analyze + explain that CONLIT only has mystery / scifi /
            romance / literary, fall back to a related genre.
        """
        # 1. Pull text to analyze. Prefer the current chapter; fall
        # back to the most recently active one if nothing is open.
        chapter_text = ""
        chapter_label = ""
        if self.project:
            current = (self.context.get("current_chapter_content")
                       if hasattr(self, "context") and self.context else None)
            if current:
                chapter_text = current
                chapter_label = (
                    self.context.get("current_chapter_title", "")
                    or "current chapter")
            else:
                # Fall back: most recently-edited chapter
                chapters = list(self.project.manuscript.chapters or [])
                if chapters:
                    ch = sorted(chapters,
                                key=lambda c: getattr(c, "updated_at", ""),
                                reverse=True)[0]
                    chapter_text = (ch.content or "").strip()
                    chapter_label = ch.title or f"chapter {ch.number}"

        if not chapter_text or len(chapter_text.split()) < 30:
            return (
                "I'd love to analyze pacing, but I can't find a chapter "
                "with at least 30 words. Open a chapter in the manuscript "
                "editor and ask again. (You can also ask general pacing "
                "questions — those don't need a chapter — but for the "
                "CONLIT comparison I need actual prose.)")

        # 2. Run analyzer
        try:
            from src.ai.pacing_analyzer import (
                analyze_text, compare_to_genre,
            )
        except Exception as e:
            return f"Pacing analyzer unavailable: {e}"
        stats = analyze_text(chapter_text)
        if not stats:
            return ("Could not analyze the chapter — it may be empty or "
                    "non-textual. Try a chapter with at least a few "
                    "paragraphs of prose.")

        # 3. Resolve target genre. Try project metadata first; fall
        # back to fuzzy matching the user's message.
        target_genre = self._resolve_target_genre(message)

        # 4. Pull CONLIT baseline (if loaded) and compare
        try:
            from src.data.conlit_loader import (
                get_genre_stats_cached, summary_lines,
            )
            conlit_stats = get_genre_stats_cached() or {}
        except Exception:
            conlit_stats = {}

        comparison = {}
        if target_genre and conlit_stats:
            comparison = compare_to_genre(stats, target_genre, conlit_stats)

        # 5. Build the LLM context bundle. The LLM gets raw stats,
        # CONLIT baseline (when available), and the user's original
        # question — and is asked for craft-level interpretation.
        ctx_lines = [
            f"=== Pacing measurement of {chapter_label} ===",
            f"Word count: {stats['token_count']:,}",
            f"Sentence count: {stats['sentence_count']:,}",
            f"Average sentence length: {stats['avg_sentence_length']:.1f} words",
            f"Average word length: {stats['avg_word_length']:.2f} chars",
            f"Tuldava lexical complexity: {stats['tuldava_score']:.2f}",
            f"Dialogue ratio: {stats['dialogue_ratio']:.2%}",
        ]
        if comparison:
            ctx_lines.append("")
            ctx_lines.append(
                f"=== Comparison vs CONLIT {comparison['genre']} baseline "
                f"(n={comparison['baseline_n_books']} contemporary novels) ===")
            for f, d in comparison.get("deltas", {}).items():
                flag = " ⚠ outside ±1.5σ" if d["outside_norm"] else ""
                ctx_lines.append(
                    f"  {f}: {d['value']} vs baseline {d['baseline']} "
                    f"(z={d['z_score']:+.1f}, {d['direction']}){flag}")
            ctx_lines.append(f"Headline: {comparison['summary']}")
        elif target_genre and not conlit_stats:
            ctx_lines.append("")
            ctx_lines.append(
                "[CONLIT genre baseline not loaded — only the user's "
                "draft stats are available. The user can load CONLIT "
                "via Training Studio settings to enable comparison.]")
        elif target_genre:
            ctx_lines.append("")
            ctx_lines.append(
                f"[CONLIT does not cover '{target_genre}' — its "
                f"baselines are mystery / scifi / romance / literary. "
                f"Provide stylistic guidance from your own knowledge "
                f"of the genre instead.]")

        ctx_block = "\n".join(ctx_lines)

        system_prompt = (
            "You are a craft-level editor advising a writer about pacing "
            "and prose rhythm. You have access to measured statistics on "
            "their current chapter and (when available) CONLIT genre "
            "baselines computed across thousands of contemporary novels. "
            "Use the numbers as evidence — quote specific deltas — and "
            "translate them into concrete craft advice (sentence-length "
            "variation, paragraph rhythm, dialogue density, vocabulary "
            "choices). Be specific. Don't write the prose for them; "
            "diagnose and suggest.")

        prompt = (
            f"{ctx_block}\n\n"
            f"=== User's question ===\n{message}\n\n"
            f"Respond as a craft editor. Cite the numbers above. Keep "
            f"the response focused and actionable.")

        # 6. Route through the per-task model selection (plot is the
        # closest existing task; pacing is a structural concern).
        llm = self.get_llm_for_task("plot")
        try:
            response = llm.generate_text(
                prompt, system_prompt, max_tokens=700, temperature=0.5)
        except Exception as e:
            # If the LLM fails, still return the raw measurements —
            # the numbers themselves are useful even without prose
            # interpretation.
            return (f"Could not get LLM interpretation: {e}\n\n"
                    f"Raw measurements:\n{ctx_block}")

        # Capture for transfer-learning if opted in (same pattern as
        # capture_plot for chapter planning).
        try:
            from src.data.learning_capture import capture_plot
            capture_plot(prompt=prompt, completion=response)
        except Exception:
            pass

        # Return the LLM's interpretation prefixed with a measurement
        # summary so the user always sees the numbers.
        return (f"📊 **Pacing measurement** ({chapter_label}, "
                f"{stats['token_count']:,} words):\n"
                f"  • avg sentence length: "
                f"**{stats['avg_sentence_length']:.1f} words**"
                + (f" (CONLIT {target_genre} baseline: "
                   f"{comparison['deltas'].get('avg_sentence_length', {}).get('baseline', '?')})"
                   if comparison.get('deltas', {}).get('avg_sentence_length')
                   else "")
                + f"\n  • lexical complexity (Tuldava): "
                f"**{stats['tuldava_score']:.2f}**\n"
                f"  • dialogue ratio: "
                f"**{stats['dialogue_ratio']:.0%}**\n\n"
                f"{response}")

    def _resolve_target_genre(self, message: str) -> str:
        """Best-effort: pull a canonical genre key from the project +
        the message, restricted to genres CONLIT actually covers."""
        # CONLIT only has mystery / scifi / romance / literary
        CONLIT_COVERED = {"mystery", "scifi", "romance", "literary"}

        # Try the user's message first (if they explicitly named a genre)
        try:
            from src.data.genres import match_genres
            from_msg = match_genres(message)
            for g in from_msg:
                if g in CONLIT_COVERED:
                    return g
        except Exception:
            pass
        # Fall back to project metadata
        if self.project and getattr(self.project, "genre", ""):
            try:
                from src.data.genres import match_genres
                for g in match_genres(self.project.genre):
                    if g in CONLIT_COVERED:
                        return g
            except Exception:
                pass
        # Final fallback: literary fiction is the most general
        return "literary"

    def _handle_general_chat(self, message: str) -> str:
        """Handle general conversation."""
        system_prompt = """You are a helpful writing assistant. Provide guidance,
        suggestions, and support. Do not write content - help the author develop
        their own ideas. Be encouraging and constructive."""

        # If the user has chosen a 'general' trained model, route through it.
        # ``continue_if_truncated`` covers the local-model case where a
        # 300-token budget runs out mid-sentence — same behaviour as the
        # Hub and Training Studio test runner. Cloud LLMs almost never
        # truncate at this size, so the heuristic is a no-op for them.
        llm = self.get_llm_for_task("general")
        response = llm.generate_text(
            message,
            system_prompt,
            max_tokens=300,
            temperature=0.7,
            continue_if_truncated=True,
            max_continuations=2,
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

        # Add magic systems summary
        if hasattr(wb, 'magic_systems') and wb.magic_systems:
            magic_summaries = []
            for ms in wb.magic_systems[:5]:
                summary = ms.name
                if ms.magic_type:
                    summary += f" ({ms.magic_type.value})"
                magic_summaries.append(summary)
            context_parts.append(f"Magic Systems: {', '.join(magic_summaries)}")

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
        detailed: bool = True,
        chapter=None
    ) -> ChapterAnalysis:
        """Analyze chapter and return structured analysis.

        Args:
            chapter_text: Full chapter text
            chapter_title: Chapter title
            detailed: If True, provides detailed line-item analysis
            chapter: Optional Chapter object for planning context

        Returns:
            ChapterAnalysis object
        """
        context_parts = []
        chapter_synopsis = ""

        if self.project:
            sp = self.project.story_planning

            # Story arc context
            if sp.main_plot:
                context_parts.append(f"Main Plot: {sp.main_plot[:400]}")
            if sp.themes:
                context_parts.append(f"Themes: {', '.join(sp.themes[:6])}")
            if sp.freytag_pyramid:
                fp = sp.freytag_pyramid
                stages = []
                if fp.exposition:
                    stages.append(f"Exposition: {fp.exposition[:150]}")
                if fp.rising_action:
                    stages.append(f"Rising Action: {fp.rising_action[:150]}")
                if fp.climax:
                    stages.append(f"Climax: {fp.climax[:150]}")
                if stages:
                    context_parts.append("Story Arc:\n" + "\n".join(stages))
            if sp.subplots:
                names = [s.title for s in sp.subplots[:5]]
                context_parts.append(f"Subplots: {', '.join(names)}")
            if hasattr(sp, 'promises') and sp.promises:
                promise_lines = [
                    f"- {p.title}: {p.description[:100]}" for p in sp.promises[:5]
                ]
                context_parts.append("Story Promises:\n" + "\n".join(promise_lines))

            # Characters
            if self.project.characters:
                char_lines = []
                for c in self.project.characters[:12]:
                    line = f"- {c.name} ({c.character_type})"
                    if c.personality:
                        line += f": {c.personality[:120]}"
                    char_lines.append(line)
                context_parts.append("Characters:\n" + "\n".join(char_lines))

            # Chapter planning context
            if chapter and hasattr(chapter, 'planning'):
                planning = chapter.planning
                chapter_ctx = []
                if planning.description:
                    chapter_synopsis = planning.description
                    chapter_ctx.append(f"Chapter Goal: {planning.description[:300]}")
                elif planning.outline:
                    chapter_synopsis = planning.outline[:400]
                    chapter_ctx.append(f"Outline: {planning.outline[:300]}")
                if planning.pov_character:
                    chapter_ctx.append(f"POV Character: {planning.pov_character}")
                if planning.characters_featured:
                    chapter_ctx.append(f"Featured: {', '.join(planning.characters_featured)}")
                if getattr(planning, 'tone', ''):
                    chapter_ctx.append(f"Tone: {planning.tone}")
                if getattr(planning, 'voice', ''):
                    chapter_ctx.append(f"Voice: {planning.voice}")
                if planning.todos:
                    incomplete = [t for t in planning.todos if not t.completed]
                    if incomplete:
                        chapter_ctx.append(
                            "Remaining tasks: " + ", ".join(t.text for t in incomplete[:5])
                        )
                if chapter_ctx:
                    context_parts.append("Chapter Plan:\n" + "\n".join(chapter_ctx))

            # Heuristic synopsis if planning had none
            if not chapter_synopsis and chapter_text:
                paras = [p.strip() for p in chapter_text.split('\n\n') if p.strip()]
                if paras:
                    chapter_synopsis = paras[0][:300]
                    if len(paras) > 1:
                        chapter_synopsis += f" …{paras[-1][:200]}"

            # Chapter position in manuscript
            if self.project.manuscript and self.project.manuscript.chapters:
                all_chs = self.project.manuscript.chapters
                total = len(all_chs)
                if chapter:
                    for i, ch in enumerate(all_chs):
                        if ch.id == chapter.id:
                            context_parts.append(
                                f"Chapter {i + 1} of {total} in the manuscript"
                            )
                            if i > 0:
                                context_parts.append(
                                    f"Previous chapter: \"{all_chs[i - 1].title}\""
                                )
                            if i < total - 1:
                                context_parts.append(
                                    f"Next chapter: \"{all_chs[i + 1].title}\""
                                )
                            break

        manuscript_context = "\n\n".join(context_parts)

        analysis = self.chapter_agent.analyze_chapter(
            chapter_text=chapter_text,
            chapter_title=chapter_title,
            manuscript_context=manuscript_context,
            detailed=detailed,
            chapter_synopsis=chapter_synopsis
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
    local_model_id: Optional[str] = None
) -> AgentSuite:
    """Factory function to create configured agent suite with platform-aware defaults.

    Args:
        project: Optional WriterProject
        use_local_model: Whether to use local model for cost savings
        local_model_id: HuggingFace model ID for local model (auto-detects platform default if None)

    Returns:
        Configured AgentSuite
    """
    # Use platform-specific default if no model specified
    if local_model_id is None:
        local_model_id = get_default_local_model()

    config = AgentConfig(
        use_local_model=use_local_model,
        local_model_id=local_model_id,
        enable_conversation_logging=True,
        cost_tracking=True
    )

    return AgentSuite(project=project, config=config)
