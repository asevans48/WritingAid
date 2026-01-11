"""LLM Client for AI integration with Claude, ChatGPT, and Gemini."""

from typing import Optional, Dict, List
from enum import Enum
import anthropic
import openai
import google.generativeai as genai


class LLMProvider(Enum):
    """Supported LLM providers."""
    CLAUDE = "claude"
    CHATGPT = "chatgpt"
    GEMINI = "gemini"


class LLMClient:
    """Unified client for multiple LLM providers."""

    def __init__(
        self,
        provider: LLMProvider,
        api_key: str,
        model: Optional[str] = None
    ):
        """Initialize LLM client with specified provider."""
        self.provider = provider
        self.api_key = api_key

        # Default models
        self.model = model or self._get_default_model()

        # Initialize provider-specific client
        if provider == LLMProvider.CLAUDE:
            self.client = anthropic.Anthropic(api_key=api_key)
        elif provider == LLMProvider.CHATGPT:
            openai.api_key = api_key
            self.client = openai
        elif provider == LLMProvider.GEMINI:
            genai.configure(api_key=api_key)
            self.client = genai

    def _get_default_model(self) -> str:
        """Get default model for provider."""
        defaults = {
            LLMProvider.CLAUDE: "claude-3-5-sonnet-20241022",
            LLMProvider.CHATGPT: "gpt-4-turbo-preview",
            LLMProvider.GEMINI: "gemini-pro"
        }
        return defaults[self.provider]

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7
    ) -> str:
        """Generate text using the configured LLM provider."""
        try:
            if self.provider == LLMProvider.CLAUDE:
                return self._generate_claude(prompt, system_prompt, max_tokens, temperature)
            elif self.provider == LLMProvider.CHATGPT:
                return self._generate_chatgpt(prompt, system_prompt, max_tokens, temperature)
            elif self.provider == LLMProvider.GEMINI:
                return self._generate_gemini(prompt, system_prompt, max_tokens, temperature)
        except Exception as e:
            return f"Error generating text: {str(e)}"

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
        model = genai.GenerativeModel(self.model)

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        generation_config = {
            "max_output_tokens": max_tokens,
            "temperature": temperature
        }

        response = model.generate_content(
            full_prompt,
            generation_config=generation_config
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
