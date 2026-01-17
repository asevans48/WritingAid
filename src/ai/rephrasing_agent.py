"""Rephrasing agent for text rewriting with multiple options."""

from typing import List, Dict, Any, Optional, TYPE_CHECKING
from dataclasses import dataclass
from enum import Enum

if TYPE_CHECKING:
    from src.ai.llm_client import LLMClient
    from src.models.project import WriterProject


class RephraseStyle(Enum):
    """Available rephrasing styles."""
    FORMAL = "formal"
    CASUAL = "casual"
    CONCISE = "concise"
    ELABORATE = "elaborate"
    DRAMATIC = "dramatic"
    POETIC = "poetic"
    ACTIVE_VOICE = "active_voice"
    CLEARER = "clearer"


@dataclass
class RephraseOption:
    """A single rephrasing option."""
    text: str
    style: str
    explanation: str


@dataclass
class RephraseResult:
    """Result of rephrasing operation."""
    original: str
    options: List[RephraseOption]
    model_used: str
    cost_estimate: float


class RephrasingAgent:
    """Agent for generating multiple rephrasing options for text.

    Supports both cloud LLMs and local small language models (SLMs).
    """

    REPHRASE_SYSTEM = """You are a skilled editor helping an author rephrase their writing.
Your job is to provide several alternative phrasings while preserving the original meaning.

Guidelines:
- Maintain the original intent and key information
- Match the style requested (formal, casual, concise, etc.)
- Keep the same tense unless specifically asked to change it
- Preserve any character names, proper nouns, or specific terminology
- Make the text flow naturally

For each option, briefly explain what makes it different from the original."""

    STYLE_PROMPTS = {
        RephraseStyle.FORMAL: "Make the text more formal and professional",
        RephraseStyle.CASUAL: "Make the text more casual and conversational",
        RephraseStyle.CONCISE: "Make the text more concise without losing meaning",
        RephraseStyle.ELABORATE: "Expand the text with more detail and description",
        RephraseStyle.DRAMATIC: "Make the text more dramatic and impactful",
        RephraseStyle.POETIC: "Make the text more poetic and lyrical",
        RephraseStyle.ACTIVE_VOICE: "Convert to active voice if possible",
        RephraseStyle.CLEARER: "Make the text clearer and easier to understand",
    }

    def __init__(
        self,
        llm_client: Optional['LLMClient'] = None,
        project: Optional['WriterProject'] = None,
        use_local_model: bool = False
    ):
        """Initialize rephrasing agent.

        Args:
            llm_client: LLM client for API calls
            project: Project for context
            use_local_model: Whether to use local SLM instead of cloud API
        """
        self.llm = llm_client
        self.project = project
        self.use_local_model = use_local_model
        self._local_model = None
        self._local_tokenizer = None

    def _init_local_model(self):
        """Initialize local small language model."""
        if self._local_model is not None:
            return

        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch

            # Use a small, fast model for rephrasing
            model_id = "microsoft/Phi-3-mini-4k-instruct"

            print(f"Loading local model: {model_id}")

            self._local_tokenizer = AutoTokenizer.from_pretrained(
                model_id,
                trust_remote_code=True
            )

            # Try to use GPU if available
            device = "cuda" if torch.cuda.is_available() else "cpu"

            self._local_model = AutoModelForCausalLM.from_pretrained(
                model_id,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map="auto" if device == "cuda" else None,
                trust_remote_code=True
            )

            if device == "cpu":
                self._local_model = self._local_model.to(device)

            print(f"Local model loaded on {device}")

        except ImportError:
            raise ImportError(
                "Local model requires transformers and torch. "
                "Install with: pip install transformers torch"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to load local model: {e}")

    def _generate_local(self, prompt: str, max_tokens: int = 500) -> str:
        """Generate text using local model."""
        self._init_local_model()

        messages = [
            {"role": "system", "content": self.REPHRASE_SYSTEM},
            {"role": "user", "content": prompt}
        ]

        inputs = self._local_tokenizer.apply_chat_template(
            messages,
            return_tensors="pt",
            add_generation_prompt=True
        )

        if hasattr(self._local_model, 'device'):
            inputs = inputs.to(self._local_model.device)

        outputs = self._local_model.generate(
            inputs,
            max_new_tokens=max_tokens,
            temperature=0.7,
            do_sample=True,
            pad_token_id=self._local_tokenizer.eos_token_id
        )

        response = self._local_tokenizer.decode(
            outputs[0][inputs.shape[1]:],
            skip_special_tokens=True
        )

        return response

    def rephrase(
        self,
        text: str,
        styles: Optional[List[RephraseStyle]] = None,
        context: str = "",
        num_options: int = 4
    ) -> RephraseResult:
        """Generate multiple rephrasing options for text.

        Args:
            text: Text to rephrase
            styles: Optional list of specific styles to generate
            context: Optional context about the text (character, scene, etc.)
            num_options: Number of options to generate if no styles specified

        Returns:
            RephraseResult with multiple options
        """
        if not styles:
            # Default styles for variety
            styles = [
                RephraseStyle.CONCISE,
                RephraseStyle.CLEARER,
                RephraseStyle.ELABORATE,
                RephraseStyle.DRAMATIC
            ][:num_options]

        # Build prompt
        context_str = f"\nContext: {context}\n" if context else ""

        style_instructions = "\n".join([
            f"{i+1}. {self.STYLE_PROMPTS[style]} ({style.value})"
            for i, style in enumerate(styles)
        ])

        prompt = f"""Please rephrase the following text in {len(styles)} different ways:

Original text: "{text}"
{context_str}
Generate these variations:
{style_instructions}

For each variation, provide:
- The rephrased text
- A brief explanation (1 sentence) of what changed

Format your response as:
OPTION 1 ({styles[0].value}):
[rephrased text]
EXPLANATION: [brief explanation]

OPTION 2 ({styles[1].value}):
[rephrased text]
EXPLANATION: [brief explanation]

(continue for all options)
"""

        # Generate using either local or cloud model
        if self.use_local_model:
            response = self._generate_local(prompt, max_tokens=800)
            model_used = "local-phi-3"
            cost = 0.0
        else:
            if not self.llm:
                raise ValueError("No LLM client configured. Enable local model or provide LLM client.")

            response = self.llm.generate_text(
                prompt,
                self.REPHRASE_SYSTEM,
                max_tokens=800,
                temperature=0.7
            )
            model_used = self.llm.model if hasattr(self.llm, 'model') else "unknown"
            cost = 0.002  # Rough estimate

        # Parse response
        options = self._parse_response(response, styles)

        return RephraseResult(
            original=text,
            options=options,
            model_used=model_used,
            cost_estimate=cost
        )

    def _parse_response(self, response: str, styles: List[RephraseStyle]) -> List[RephraseOption]:
        """Parse LLM response into structured options."""
        options = []

        # Split by option markers
        lines = response.split('\n')
        current_option = None
        current_text = []
        current_explanation = ""
        current_style = None

        for line in lines:
            line = line.strip()

            # Check for option header
            if line.upper().startswith("OPTION"):
                # Save previous option if exists
                if current_option and current_text:
                    options.append(RephraseOption(
                        text=' '.join(current_text).strip(),
                        style=current_style or "general",
                        explanation=current_explanation
                    ))

                # Start new option
                current_text = []
                current_explanation = ""

                # Extract style from header if present
                for style in styles:
                    if style.value.lower() in line.lower():
                        current_style = style.value
                        break
                else:
                    current_style = "general"

                current_option = True

            elif line.upper().startswith("EXPLANATION:"):
                current_explanation = line.split(":", 1)[1].strip()

            elif current_option and line and not line.startswith("["):
                # Add to current text (skip placeholder brackets)
                if not line.startswith("(") or not line.endswith(")"):
                    current_text.append(line)

        # Add last option
        if current_option and current_text:
            options.append(RephraseOption(
                text=' '.join(current_text).strip(),
                style=current_style or "general",
                explanation=current_explanation
            ))

        # If parsing failed, try simpler approach
        if not options:
            # Just split by double newlines and take non-empty sections
            sections = response.split('\n\n')
            for i, section in enumerate(sections):
                section = section.strip()
                if section and len(section) > 10:
                    # Clean up common markers
                    for marker in ["Option", "Variation", "Alternative", "1.", "2.", "3.", "4."]:
                        if section.startswith(marker):
                            section = section[len(marker):].strip()
                            if section.startswith(":"):
                                section = section[1:].strip()
                            break

                    style = styles[i].value if i < len(styles) else "general"
                    options.append(RephraseOption(
                        text=section,
                        style=style,
                        explanation=""
                    ))

                if len(options) >= len(styles):
                    break

        return options

    def quick_rephrase(self, text: str, style: RephraseStyle) -> str:
        """Quickly rephrase text in a single style.

        Args:
            text: Text to rephrase
            style: Style to use

        Returns:
            Rephrased text
        """
        prompt = f"""Rephrase the following text to be more {style.value}:

"{text}"

Provide only the rephrased text, nothing else."""

        if self.use_local_model:
            response = self._generate_local(prompt, max_tokens=300)
        else:
            if not self.llm:
                raise ValueError("No LLM client configured.")

            response = self.llm.generate_text(
                prompt,
                "You are a helpful writing assistant. Provide only the rephrased text.",
                max_tokens=300,
                temperature=0.7
            )

        # Clean up response
        response = response.strip()
        if response.startswith('"') and response.endswith('"'):
            response = response[1:-1]

        return response
