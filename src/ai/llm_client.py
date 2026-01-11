"""LLM Client for AI integration with Claude, ChatGPT, Gemini, and Hugging Face models."""

from typing import Optional, Dict, List, Any, TYPE_CHECKING
from enum import Enum
import anthropic
import openai
from google import genai

if TYPE_CHECKING:
    from src.ai.conversation_store import ConversationStore, RatedConversation


class LLMProvider(Enum):
    """Supported LLM providers."""
    CLAUDE = "claude"
    CHATGPT = "chatgpt"
    GEMINI = "gemini"
    HUGGINGFACE = "huggingface"
    HUGGINGFACE_LOCAL = "huggingface_local"  # Local model via transformers


class HuggingFaceConfig:
    """Configuration for Hugging Face models."""

    def __init__(
        self,
        model_id: str,
        use_local: bool = False,
        device: str = "auto",
        quantization: Optional[str] = None,  # "4bit", "8bit", or None
        max_memory: Optional[Dict[str, str]] = None,
        trust_remote_code: bool = False
    ):
        self.model_id = model_id
        self.use_local = use_local
        self.device = device
        self.quantization = quantization
        self.max_memory = max_memory
        self.trust_remote_code = trust_remote_code


class LLMClient:
    """Unified client for multiple LLM providers."""

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str = "",
        model: Optional[str] = None,
        hf_config: Optional[HuggingFaceConfig] = None,
        conversation_store: Optional['ConversationStore'] = None,
        enable_conversation_logging: bool = False
    ):
        """Initialize LLM client with specified provider.

        Args:
            provider: The LLM provider to use
            api_key: API key for cloud providers
            model: Model name/ID to use
            hf_config: Configuration for Hugging Face models
            conversation_store: Store for saving rated conversations
            enable_conversation_logging: Whether to log conversations for rating
        """
        self.provider = provider
        self.api_key = api_key
        self.hf_config = hf_config
        self.conversation_store = conversation_store
        self.enable_conversation_logging = enable_conversation_logging

        # Conversation history for current session
        self._current_messages: List[Dict[str, str]] = []

        # Default models
        self.model = model or self._get_default_model()

        # Initialize provider-specific client
        self.client = None
        self._hf_pipeline = None
        self._hf_tokenizer = None

        if provider == LLMProvider.CLAUDE:
            self.client = anthropic.Anthropic(api_key=api_key)
        elif provider == LLMProvider.CHATGPT:
            openai.api_key = api_key
            self.client = openai
        elif provider == LLMProvider.GEMINI:
            self.client = genai.Client(api_key=api_key)
        elif provider == LLMProvider.HUGGINGFACE:
            self._init_huggingface_api()
        elif provider == LLMProvider.HUGGINGFACE_LOCAL:
            self._init_huggingface_local()

    def _init_huggingface_api(self) -> None:
        """Initialize Hugging Face Inference API client."""
        try:
            from huggingface_hub import InferenceClient
            self.client = InferenceClient(token=self.api_key)
        except ImportError:
            raise ImportError(
                "huggingface_hub is required for Hugging Face API. "
                "Install with: pip install huggingface_hub"
            )

    def _init_huggingface_local(self) -> None:
        """Initialize local Hugging Face model."""
        if not self.hf_config:
            raise ValueError("HuggingFaceConfig is required for local models")

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

            model_kwargs = {}

            # Handle quantization
            if self.hf_config.quantization == "4bit":
                from transformers import BitsAndBytesConfig
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16
                )
            elif self.hf_config.quantization == "8bit":
                from transformers import BitsAndBytesConfig
                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_8bit=True
                )

            # Set device
            if self.hf_config.device == "auto":
                model_kwargs["device_map"] = "auto"
            elif self.hf_config.device != "cpu":
                model_kwargs["device_map"] = self.hf_config.device

            # Memory limits
            if self.hf_config.max_memory:
                model_kwargs["max_memory"] = self.hf_config.max_memory

            # Trust remote code (for some models like Phi, Qwen)
            if self.hf_config.trust_remote_code:
                model_kwargs["trust_remote_code"] = True

            # Load tokenizer and model
            self._hf_tokenizer = AutoTokenizer.from_pretrained(
                self.hf_config.model_id,
                trust_remote_code=self.hf_config.trust_remote_code
            )

            model = AutoModelForCausalLM.from_pretrained(
                self.hf_config.model_id,
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                **model_kwargs
            )

            # Create pipeline
            self._hf_pipeline = pipeline(
                "text-generation",
                model=model,
                tokenizer=self._hf_tokenizer
            )

        except ImportError as e:
            raise ImportError(
                f"transformers and torch are required for local models. "
                f"Install with: pip install transformers torch. Error: {e}"
            )

    def _get_default_model(self) -> str:
        """Get default model for provider."""
        defaults = {
            LLMProvider.CLAUDE: "claude-3-5-sonnet-20241022",
            LLMProvider.CHATGPT: "gpt-4-turbo-preview",
            LLMProvider.GEMINI: "gemini-2.0-flash-exp",
            LLMProvider.HUGGINGFACE: "mistralai/Mistral-7B-Instruct-v0.2",
            LLMProvider.HUGGINGFACE_LOCAL: "microsoft/phi-2"
        }
        return defaults.get(self.provider, "")

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        task_type: str = "general"
    ) -> str:
        """Generate text using the configured LLM provider.

        Args:
            prompt: The user prompt
            system_prompt: Optional system instructions
            max_tokens: Maximum tokens in response
            temperature: Creativity/randomness (0-1)
            task_type: Type of task for conversation logging

        Returns:
            Generated text response
        """
        # Track messages for conversation logging
        if self.enable_conversation_logging:
            if system_prompt and not self._current_messages:
                self._current_messages.append({"role": "system", "content": system_prompt})
            self._current_messages.append({"role": "user", "content": prompt})

        try:
            if self.provider == LLMProvider.CLAUDE:
                response = self._generate_claude(prompt, system_prompt, max_tokens, temperature)
            elif self.provider == LLMProvider.CHATGPT:
                response = self._generate_chatgpt(prompt, system_prompt, max_tokens, temperature)
            elif self.provider == LLMProvider.GEMINI:
                response = self._generate_gemini(prompt, system_prompt, max_tokens, temperature)
            elif self.provider == LLMProvider.HUGGINGFACE:
                response = self._generate_huggingface_api(prompt, system_prompt, max_tokens, temperature)
            elif self.provider == LLMProvider.HUGGINGFACE_LOCAL:
                response = self._generate_huggingface_local(prompt, system_prompt, max_tokens, temperature)
            else:
                response = f"Error: Unknown provider {self.provider}"

            # Log assistant response
            if self.enable_conversation_logging:
                self._current_messages.append({"role": "assistant", "content": response})

            return response
        except Exception as e:
            return f"Error generating text: {str(e)}"

    def _generate_huggingface_api(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Generate text using Hugging Face Inference API."""
        full_prompt = prompt
        if system_prompt:
            full_prompt = f"<|system|>\n{system_prompt}\n<|user|>\n{prompt}\n<|assistant|>\n"

        response = self.client.text_generation(
            full_prompt,
            model=self.model,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=True
        )
        return response

    def _generate_huggingface_local(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Generate text using local Hugging Face model."""
        if not self._hf_pipeline:
            raise RuntimeError("Local model pipeline not initialized")

        # Build prompt based on model type
        full_prompt = prompt
        if system_prompt:
            # Use ChatML format for most instruction models
            full_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"

        outputs = self._hf_pipeline(
            full_prompt,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=True,
            pad_token_id=self._hf_tokenizer.eos_token_id,
            return_full_text=False
        )

        return outputs[0]['generated_text'].strip()

    def save_current_conversation(
        self,
        task_type: str = "general",
        project_name: Optional[str] = None,
        project_genre: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> Optional[str]:
        """Save the current conversation to the store for later rating.

        Args:
            task_type: Type of task (character_dev, worldbuilding, etc.)
            project_name: Name of the project
            project_genre: Genre of the project
            tags: Additional tags

        Returns:
            Conversation ID if saved, None otherwise
        """
        if not self.conversation_store or not self._current_messages:
            return None

        from src.ai.conversation_store import (
            ConversationMetadata, create_conversation_from_messages
        )

        metadata = ConversationMetadata(
            project_name=project_name,
            project_genre=project_genre,
            task_type=task_type,
            provider=self.provider.value,
            model_name=self.model,
            tags=tags or []
        )

        conversation = create_conversation_from_messages(
            self._current_messages,
            metadata
        )

        return self.conversation_store.add_conversation(conversation)

    def clear_conversation_history(self) -> None:
        """Clear current conversation history."""
        self._current_messages.clear()

    def get_current_conversation(self) -> List[Dict[str, str]]:
        """Get current conversation messages."""
        return self._current_messages.copy()

    def _generate_claude(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Generate text using Claude."""
        messages = [{"role": "user", "content": prompt}]

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.client.messages.create(**kwargs)
        return response.content[0].text

    def _generate_chatgpt(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Generate text using ChatGPT."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        return response.choices[0].message.content

    def _generate_gemini(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float
    ) -> str:
        """Generate text using Gemini."""
        from google.genai import types

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens
        )

        response = self.client.models.generate_content(
            model=self.model,
            contents=full_prompt,
            config=config
        )
        return response.text


class WritingAssistant:
    """AI assistant specialized for writing tasks."""

    # Writing rules for prompts
    WRITING_RULES = """
    When providing writing assistance, ensure:
    - Show, don't tell - Use vivid descriptions and actions rather than exposition
    - Create compelling and emotional stories that resonate with readers
    - Never violate established plot points or character consistency
    - Use ONLY natural transitions between scenes and ideas
    - Detect and help eliminate common tropes to create unique content
    - Ensure writing is readable, compelling, with varied sentence structure
    - Maintain a unique voice and avoid repetitive patterns
    """

    def __init__(self, llm_client: LLMClient):
        """Initialize writing assistant with LLM client."""
        self.llm = llm_client

    def get_chapter_hints(
        self,
        chapter_content: str,
        manuscript_context: str,
        plot_points: str
    ) -> str:
        """Get AI hints for improving a chapter."""
        system_prompt = f"{self.WRITING_RULES}\n\nYou are a writing coach helping authors improve their manuscript."

        prompt = f"""
        Manuscript Context: {manuscript_context}

        Plot Points: {plot_points}

        Current Chapter:
        {chapter_content}

        Provide 3-5 specific, actionable hints to improve this chapter while maintaining consistency with the overall manuscript.
        Focus on showing vs telling, emotional impact, pacing, and character development.
        """

        return self.llm.generate_text(prompt, system_prompt)

    def brutal_critique(
        self,
        content: str,
        content_type: str = "chapter"
    ) -> str:
        """Provide honest, brutal critique of writing."""
        system_prompt = f"""{self.WRITING_RULES}

        You are a brutally honest literary critic and editor. Your job is to provide:
        1. Honest assessment of strengths and weaknesses
        2. Line-by-line edits where needed
        3. Specific areas for improvement
        4. Recognition of what works well

        Be direct, constructive, and don't sugarcoat issues. Writers need honest feedback to improve.
        """

        prompt = f"""
        Analyze this {content_type} and provide a comprehensive critique:

        {content}

        Provide:
        1. Overall assessment
        2. Specific line-item edits with explanations
        3. Structural issues
        4. What needs immediate attention
        5. What works well (if anything)
        """

        return self.llm.generate_text(prompt, system_prompt, max_tokens=8000)

    def worldbuilding_help(
        self,
        category: str,
        existing_content: str,
        prompt_question: str
    ) -> str:
        """Help with worldbuilding elements."""
        system_prompt = """You are a worldbuilding expert helping authors create rich, consistent fictional worlds.
        Focus on internal consistency, depth, and unique elements that avoid common tropes."""

        prompt = f"""
        Worldbuilding Category: {category}

        Existing Content:
        {existing_content}

        Question/Request:
        {prompt_question}

        Provide detailed, creative suggestions that maintain consistency with existing worldbuilding.
        """

        return self.llm.generate_text(prompt, system_prompt)

    def character_development(
        self,
        character_name: str,
        character_info: str,
        development_request: str
    ) -> str:
        """Help develop character details."""
        system_prompt = f"""{self.WRITING_RULES}

        You are a character development specialist. Help create deep, consistent, believable characters
        with unique personalities, motivations, and growth arcs. Avoid stereotypes and tropes.
        """

        prompt = f"""
        Character: {character_name}

        Current Information:
        {character_info}

        Development Request:
        {development_request}

        Provide detailed character development suggestions that create a unique, compelling character.
        """

        return self.llm.generate_text(prompt, system_prompt)

    def generate_image_prompt(
        self,
        image_type: str,
        description: str,
        style_preferences: str = ""
    ) -> str:
        """Generate optimized prompt for image generation."""
        system_prompt = """You are an expert at creating prompts for AI image generation.
        Generate detailed, specific prompts that produce high-quality results."""

        prompt = f"""
        Image Type: {image_type}
        Description: {description}
        Style Preferences: {style_preferences}

        Create an optimized prompt for AI image generation (Stable Diffusion, DALL-E, or similar).
        Be specific about composition, lighting, style, and details.
        """

        return self.llm.generate_text(prompt, system_prompt, max_tokens=500)
