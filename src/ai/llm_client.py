"""LLM Client for AI integration with Claude, ChatGPT, Gemini, and Hugging Face models."""

import gc
import weakref
from typing import Optional, Dict, List, TYPE_CHECKING
from enum import Enum
import anthropic
import openai
from google import genai
from src.ai.device_utils import detect_device, can_use_quantization


# Sentence-final punctuation set used by the truncation heuristic.
# Includes English + smart-quote forms + a couple of CJK marks so the
# heuristic doesn't false-positive on non-English assistant replies.
_SENTENCE_END_CHARS = '.!?"\'"”’)。！？'


def _looks_truncated(text: str) -> bool:
    """Heuristic: does this assistant reply look cut off mid-thought?

    True when the response is non-trivial (>=1 character of content)
    AND its last non-whitespace character isn't sentence-final
    punctuation. The writing-tool chat caller passes
    ``continue_if_truncated=True`` so a "Yeah, the trick to a strong
    opening is" reply triggers an automatic follow-up rather than
    leaving the user stranded.
    """
    if not text:
        return False
    stripped = text.rstrip()
    if not stripped:
        return False
    return stripped[-1] not in _SENTENCE_END_CHARS

if TYPE_CHECKING:
    from src.ai.conversation_store import ConversationStore


# Registry of *local* LLMClient instances currently holding model weights
# in RAM. Stored as weak refs so a client can still be garbage collected
# normally — we only use the registry to find live instances when the
# Training Studio needs to free RAM. Cloud clients (Claude/ChatGPT/etc.)
# never register here; their "weight" is a network connection.
_LIVE_LOCAL_CLIENTS: "weakref.WeakSet[LLMClient]" = weakref.WeakSet()


def list_loaded_local_clients() -> List["LLMClient"]:
    """Return live local LLMClient instances that still hold weights."""
    return [c for c in _LIVE_LOCAL_CLIENTS if c.has_loaded_local_model()]


def unload_all_local_clients(clear_cuda: bool = True,
                             clear_mlx: bool = True) -> int:
    """Drop every loaded local model from RAM. Returns count unloaded.

    Used by the Training Studio before kicking off a fine-tune so the
    base model + dataset have room to load. Safe to call when no local
    clients are loaded — it's a no-op then.

    The clients themselves stay alive (so per-task LLM caches don't
    need to be invalidated), but their weights are gone. The next call
    to ``generate_text`` would need to be on a fresh client; callers
    that still hold a reference should drop it after this call.
    """
    n = 0
    for client in list(_LIVE_LOCAL_CLIENTS):
        if client.has_loaded_local_model():
            try:
                client.unload()
                n += 1
            except Exception as e:
                print(f"[llm_client] unload failed: {e}")

    # Aggressive cache clears so the freed weights actually return
    # memory to the OS (otherwise PyTorch / MLX may keep large arenas
    # cached for the next allocation).
    if clear_cuda:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception:
            pass
    if clear_mlx:
        try:
            import mlx.core as mx
            # Newer MLX exposes mx.clear_cache directly; older versions
            # only had mx.metal.clear_cache. Try the new path first.
            if hasattr(mx, "clear_cache"):
                mx.clear_cache()
            elif hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
                mx.metal.clear_cache()
        except Exception:
            pass
    gc.collect()
    return n


class LLMProvider(Enum):
    """Supported LLM providers."""
    CLAUDE = "claude"
    CHATGPT = "chatgpt"
    GEMINI = "gemini"
    HUGGINGFACE = "huggingface"
    HUGGINGFACE_LOCAL = "huggingface_local"  # Local model via transformers
    MLX_LOCAL = "mlx_local"  # Local model via MLX (Apple Silicon)


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
        self._mlx_model = None
        self._mlx_tokenizer = None

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
            _LIVE_LOCAL_CLIENTS.add(self)
        elif provider == LLMProvider.MLX_LOCAL:
            self._init_mlx_local()
            _LIVE_LOCAL_CLIENTS.add(self)

    # ── RAM management for local providers ──

    def has_loaded_local_model(self) -> bool:
        """True if this client currently holds model weights in RAM.

        Cloud clients always return False. After ``unload()`` this also
        returns False until something reloads the weights.
        """
        if self.provider == LLMProvider.HUGGINGFACE_LOCAL:
            return self._hf_pipeline is not None
        if self.provider == LLMProvider.MLX_LOCAL:
            return self._mlx_model is not None
        return False

    def loaded_model_label(self) -> str:
        """Human-readable label for memory-usage dialogs."""
        if self.has_loaded_local_model():
            backend = ("MLX" if self.provider == LLMProvider.MLX_LOCAL
                       else "HuggingFace")
            return f"{self.model} ({backend})"
        return ""

    def unload(self) -> None:
        """Drop this client's model weights from RAM.

        Idempotent — calling on a client that hasn't loaded anything is
        a no-op. Safe to call from any thread *as long as* nothing else
        is currently calling ``generate_text`` on the same client. The
        Training Studio gates this behind a user-facing alert before
        kicking off a fine-tune.

        After unload, the client object remains valid but
        ``has_loaded_local_model()`` returns False. Callers that want
        to use it again should typically construct a fresh client.
        """
        if self.provider not in (LLMProvider.HUGGINGFACE_LOCAL,
                                 LLMProvider.MLX_LOCAL):
            return
        # Drop pipeline / tokenizer / model references. The Python GC
        # then reclaims the underlying tensors when no one else holds
        # them; the cache-clear in ``unload_all_local_clients`` returns
        # the freed buffers to the OS.
        self._hf_pipeline = None
        self._hf_tokenizer = None
        self._mlx_model = None
        self._mlx_tokenizer = None

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
        """Initialize local Hugging Face model with cross-platform support."""
        if not self.hf_config:
            raise ValueError("HuggingFaceConfig is required for local models")

        try:
            import sys
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline

            # Increase recursion limit to prevent stack overflow
            old_recursion_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(5000)

            try:
                model_kwargs = {
                    "low_cpu_mem_usage": True,
                    "attn_implementation": "eager",  # Avoid flash attention stack overflow
                }

                # Use shared device detection utility
                device_name, dtype, use_device_map = detect_device()

                # Handle user-specified device override
                if self.hf_config.device != "auto":
                    if self.hf_config.device == "cpu":
                        device_name = "cpu"
                        dtype = torch.float32
                        use_device_map = False
                    elif self.hf_config.device == "cuda" and torch.cuda.is_available():
                        device_name = "cuda"
                        dtype = torch.float16
                        use_device_map = True
                    elif self.hf_config.device == "mps" and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                        device_name = "mps"
                        dtype = torch.bfloat16
                        use_device_map = False

                print(f"Device configuration - device: {device_name}, dtype: {dtype}, device_map: {use_device_map}")

                # Handle quantization (only works with CUDA)
                quantization_enabled = False
                if self.hf_config.quantization in ["4bit", "8bit"]:
                    if can_use_quantization(device_name):
                        from transformers import BitsAndBytesConfig
                        if self.hf_config.quantization == "4bit":
                            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                                load_in_4bit=True,
                                bnb_4bit_compute_dtype=torch.float16
                            )
                        else:  # 8bit
                            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                                load_in_8bit=True
                            )
                        model_kwargs["device_map"] = "auto"
                        quantization_enabled = True
                        print(f"Using {self.hf_config.quantization} quantization on CUDA")
                    else:
                        print(f"Warning: {self.hf_config.quantization} quantization only works with CUDA. Using standard precision on {device_name}.")

                # Set device_map for CUDA (if not already set by quantization)
                if use_device_map and device_name == "cuda" and not quantization_enabled:
                    model_kwargs["device_map"] = "auto"

                # Memory limits (primarily for CUDA)
                if self.hf_config.max_memory and device_name == "cuda":
                    model_kwargs["max_memory"] = self.hf_config.max_memory

                # Trust remote code (for some models like Phi, Qwen)
                if self.hf_config.trust_remote_code:
                    model_kwargs["trust_remote_code"] = True

                # Load tokenizer
                self._hf_tokenizer = AutoTokenizer.from_pretrained(
                    self.hf_config.model_id,
                    trust_remote_code=self.hf_config.trust_remote_code
                )

                print(f"Loading model on {device_name} with dtype {dtype}")

                # Load model
                model = AutoModelForCausalLM.from_pretrained(
                    self.hf_config.model_id,
                    torch_dtype=dtype,
                    **model_kwargs
                )

                # Move to target device if not using device_map
                if "device_map" not in model_kwargs:
                    model = model.to(device_name)
                    print(f"Model moved to {device_name}")

                # Create pipeline with correct device parameter
                # For CUDA with device_map, use device=-1 to let device_map handle it
                # For MPS/CPU, use device name string
                if "device_map" in model_kwargs:
                    pipeline_device = -1  # Let device_map handle it
                elif device_name == "cuda":
                    pipeline_device = 0  # First CUDA device
                else:
                    pipeline_device = device_name  # "mps" or "cpu"

                self._hf_pipeline = pipeline(
                    "text-generation",
                    model=model,
                    tokenizer=self._hf_tokenizer,
                    device=pipeline_device
                )

                print(f"Model initialized successfully on {device_name}")

            finally:
                # Always restore original recursion limit
                sys.setrecursionlimit(old_recursion_limit)

        except ImportError as e:
            raise ImportError(
                f"transformers and torch are required for local models. "
                f"Install with: pip install transformers torch. Error: {e}"
            )

    def _init_mlx_local(self) -> None:
        """Initialize local MLX model for Apple Silicon.

        Uses the global MLXModelCache to share a single loaded model across
        all LLMClient instances and the RephrasingAgent, avoiding duplicate
        loads that waste memory and time.
        """
        if not self.hf_config:
            raise ValueError("HuggingFaceConfig is required for MLX models")

        try:
            model_id = self.hf_config.model_id
            quantization = self.hf_config.quantization

            # Check the global cache first — shared with RephrasingAgent
            from src.ai.mlx_utils import get_mlx_cache
            cache = get_mlx_cache()
            cached_model, cached_tokenizer = cache.get_model(model_id)
            if cached_model is not None:
                print(f"Using cached MLX model: {model_id}")
                self._mlx_model = cached_model
                self._mlx_tokenizer = cached_tokenizer
                return

            print(f"Loading MLX model: {model_id}")

            from mlx_lm import load

            # Load MLX model — try mlx_lm first, fall back to mlx_vlm
            # for newer architectures (gemma4, etc.) not yet in mlx_lm
            try:
                self._mlx_model, self._mlx_tokenizer = load(model_id)
            except Exception as load_err:
                err_str = str(load_err)
                if "not supported" in err_str.lower() or "model type" in err_str.lower():
                    print(f"mlx_lm does not support this model type, trying mlx_vlm...")
                    try:
                        from mlx_vlm import load as vlm_load
                        self._mlx_model, self._mlx_tokenizer = vlm_load(model_id)
                    except ImportError:
                        raise RuntimeError(
                            f"Model type not supported by mlx_lm. "
                            f"Install mlx_vlm:\n  pip install --upgrade mlx-vlm"
                        )
                elif "'list' object has no attribute 'keys'" in err_str:
                    raise RuntimeError(
                        f"Failed to load '{model_id}': tokenizer config incompatibility.\n\n"
                        f"Run: pip install --upgrade mlx mlx-lm mlx-vlm transformers"
                    )
                else:
                    raise RuntimeError(
                        f"Failed to load '{model_id}': {load_err}\n\n"
                        f"Try: pip install --upgrade mlx mlx-lm"
                    )

            # Store in global cache so other components reuse it
            cache.set_model(model_id, self._mlx_model, self._mlx_tokenizer)

            # Apply on-the-fly quantization if requested and model isn't already quantized.
            already_quantized = "4bit" in model_id or "8bit" in model_id
            if quantization and not already_quantized:
                try:
                    import mlx.nn as nn
                    import mlx.core as mx

                    bits = 4 if quantization == "4bit" else 8
                    group_size = 64

                    print(f"Applying MLX {bits}-bit quantization (group_size={group_size})...")
                    nn.quantize(self._mlx_model, group_size=group_size, bits=bits)
                    mx.eval(self._mlx_model.parameters())
                    print(f"MLX {bits}-bit quantization applied successfully.")

                except Exception as q_err:
                    print(f"Warning: MLX quantization failed ({q_err}). Running in full precision.")

            print(f"MLX model initialized successfully: {model_id}")

        except ImportError as e:
            raise ImportError(
                f"mlx-lm is required for MLX models on Apple Silicon. "
                f"Install with: pip install mlx mlx-lm. Error: {e}"
            )

    def _get_default_model(self) -> str:
        """Get default model for provider."""
        defaults = {
            LLMProvider.CLAUDE: "claude-3-5-sonnet-20241022",
            LLMProvider.CHATGPT: "gpt-4-turbo-preview",
            LLMProvider.GEMINI: "gemini-2.0-flash-exp",
            LLMProvider.HUGGINGFACE: "mistralai/Mistral-7B-Instruct-v0.2",
            LLMProvider.HUGGINGFACE_LOCAL: "microsoft/phi-2",
            LLMProvider.MLX_LOCAL: "mlx-community/Llama-3.2-3B-Instruct-4bit"
        }
        return defaults.get(self.provider, "")

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        task_type: str = "general",
        conversation_history: Optional[List[Dict[str, str]]] = None,
        continue_if_truncated: bool = False,
        max_continuations: int = 2,
    ) -> str:
        """Generate text using the configured LLM provider.

        Args:
            prompt: The user prompt
            system_prompt: Optional system instructions
            max_tokens: Maximum tokens in response
            temperature: Creativity/randomness (0-1)
            task_type: Type of task for conversation logging
            conversation_history: Prior turns as [{"role": "user"|"assistant", "content": str}, ...]
            continue_if_truncated: when True, after the initial pass
                we run a "looks truncated" heuristic on the response;
                if it cut off mid-thought (no sentence-final punct +
                ran near max_tokens) we feed the partial back as
                assistant context and ask the model to continue, up
                to ``max_continuations`` extra rounds. Used by the
                writing tool's chat path so users don't see partial
                replies on small local models.
            max_continuations: hard cap on extra "continue" rounds
                when ``continue_if_truncated`` is True. Each extra
                round costs ``max_tokens`` more output budget.

        Returns:
            Generated text response
        """
        # Track messages for conversation logging
        if self.enable_conversation_logging:
            if system_prompt and not self._current_messages:
                self._current_messages.append({"role": "system", "content": system_prompt})
            self._current_messages.append({"role": "user", "content": prompt})

        history = list(conversation_history or [])

        def _one_pass(p, hist):
            if self.provider == LLMProvider.CLAUDE:
                return self._generate_claude(p, system_prompt, max_tokens, temperature, hist)
            elif self.provider == LLMProvider.CHATGPT:
                return self._generate_chatgpt(p, system_prompt, max_tokens, temperature, hist)
            elif self.provider == LLMProvider.GEMINI:
                return self._generate_gemini(p, system_prompt, max_tokens, temperature, hist)
            elif self.provider == LLMProvider.HUGGINGFACE:
                return self._generate_huggingface_api(p, system_prompt, max_tokens, temperature, hist)
            elif self.provider == LLMProvider.HUGGINGFACE_LOCAL:
                return self._generate_huggingface_local(p, system_prompt, max_tokens, temperature, hist)
            elif self.provider == LLMProvider.MLX_LOCAL:
                return self._generate_mlx_local(p, system_prompt, max_tokens, temperature, hist)
            return f"Error: Unknown provider {self.provider}"

        try:
            response = _one_pass(prompt, history)

            # Auto-continuation. Cloud LLMs almost never truncate at
            # 4k tokens; this is targeted at local models that hit
            # their max_new_tokens budget mid-sentence. We keep the
            # heuristic conservative: only continue when the response
            # is non-empty AND lacks sentence-final punctuation. The
            # follow-up round uses the partial as the assistant's
            # most-recent turn so the model literally finishes the
            # thought rather than restarting.
            if continue_if_truncated:
                rounds = 0
                while (rounds < max_continuations
                        and _looks_truncated(response)):
                    rounds += 1
                    follow_history = history + [
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": response},
                    ]
                    next_chunk = _one_pass(
                        "Continue exactly from where you left off — "
                        "do not repeat any text you already produced.",
                        follow_history)
                    if not next_chunk or not next_chunk.strip():
                        break
                    # Glue with a single space if the partial didn't
                    # end with whitespace already.
                    glue = "" if response.endswith((" ", "\n")) else " "
                    response = (response + glue + next_chunk).strip()

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
        temperature: float,
        history: List[Dict[str, str]] = None
    ) -> str:
        """Generate text using Hugging Face Inference API."""
        history_text = ""
        if history:
            parts = []
            for msg in history:
                role_tag = "<|user|>" if msg["role"] == "user" else "<|assistant|>"
                parts.append(f"{role_tag}\n{msg['content']}")
            history_text = "\n".join(parts) + "\n"

        if system_prompt:
            full_prompt = f"<|system|>\n{system_prompt}\n{history_text}<|user|>\n{prompt}\n<|assistant|>\n"
        else:
            full_prompt = f"{history_text}<|user|>\n{prompt}\n<|assistant|>\n"

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
        temperature: float,
        history: List[Dict[str, str]] = None
    ) -> str:
        """Generate text using local Hugging Face model."""
        if not self._hf_pipeline:
            raise RuntimeError("Local model pipeline not initialized")

        # Build ChatML format with history
        parts = []
        if system_prompt:
            parts.append(f"<|im_start|>system\n{system_prompt}<|im_end|>")
        for msg in (history or []):
            role = msg["role"]
            parts.append(f"<|im_start|>{role}\n{msg['content']}<|im_end|>")
        parts.append(f"<|im_start|>user\n{prompt}<|im_end|>")
        parts.append("<|im_start|>assistant\n")
        full_prompt = "\n".join(parts)

        outputs = self._hf_pipeline(
            full_prompt,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=True,
            pad_token_id=self._hf_tokenizer.eos_token_id,
            return_full_text=False
        )

        return outputs[0]['generated_text'].strip()

    def _generate_mlx_local(
        self,
        prompt: str,
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
        history: List[Dict[str, str]] = None
    ) -> str:
        """Generate text using local MLX model on Apple Silicon."""
        if not self._mlx_model or not self._mlx_tokenizer:
            raise RuntimeError("MLX model not initialized")

        # Build prompt via the safe template applier. Handles three
        # cases:
        #   1. Tokenizer has chat_template configured → use it.
        #   2. Tokenizer is missing chat_template (e.g. Cydonia 24B
        #      v3.1 ships without it) → look up a Jinja template
        #      by model-id family (Mistral / Llama / Qwen / Gemma
        #      / Phi) and pass it via the chat_template= kwarg.
        #   3. Family unknown → plain "System: ... User: ...
        #      Assistant:" fallback string.
        # Fixes: "Cannot use chat template functions because
        # tokenizer.chat_template is not set" on Cydonia and any
        # other community fine-tunes that drop the template field.
        from src.ai.chat_template_fallbacks import (
            apply_chat_template_safe,
        )
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        mlx_model_id = (
            self.hf_config.model_id if self.hf_config else "")
        full_prompt = apply_chat_template_safe(
            self._mlx_tokenizer,
            messages,
            model_id=mlx_model_id,
            add_generation_prompt=True)

        # Try mlx_lm.generate first, fall back to mlx_vlm.generate for
        # newer model architectures (gemma4, etc.)
        try:
            from mlx_lm import generate
            from mlx_lm.sample_utils import make_sampler
            sampler = make_sampler(temp=temperature)
            response = generate(
                self._mlx_model,
                self._mlx_tokenizer,
                prompt=full_prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                verbose=False
            )
        except Exception:
            # Model was likely loaded via mlx_vlm — use its generate
            from mlx_vlm import generate as vlm_generate
            response = vlm_generate(
                self._mlx_model,
                self._mlx_tokenizer,
                full_prompt,
                max_tokens=max_tokens,
                temp=temperature,
                verbose=False
            )

        # mlx_vlm.generate may return a GenerationResult object, not a string
        if not isinstance(response, str):
            response = getattr(response, 'text', '') or str(response)

        return response.strip()

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
        temperature: float,
        history: List[Dict[str, str]] = None
    ) -> str:
        """Generate text using Claude."""
        messages = list(history) if history else []
        messages.append({"role": "user", "content": prompt})

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
        temperature: float,
        history: List[Dict[str, str]] = None
    ) -> str:
        """Generate text using ChatGPT."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
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
        temperature: float,
        history: List[Dict[str, str]] = None
    ) -> str:
        """Generate text using Gemini."""
        from google.genai import types

        # Prepend conversation history as formatted text
        history_text = ""
        if history:
            lines = []
            for msg in history:
                role = "User" if msg["role"] == "user" else "Assistant"
                lines.append(f"{role}: {msg['content']}")
            history_text = "\n".join(lines) + "\n\n"

        full_prompt = history_text + prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{full_prompt}"

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
