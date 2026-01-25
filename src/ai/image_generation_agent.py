"""Image Generation Agent for character portraits and scene visualization.

Supports both Apple Silicon (MLX) and NVIDIA/CPU (PyTorch) backends.
"""

from typing import Optional
from pathlib import Path
from datetime import datetime
import logging
import sys

from src.config.genai_config import get_genai_config, ImageGenProvider
from src.ai.mlx_utils import can_use_mlx
from src.ai.llm_client import LLMClient, LLMProvider
from src.models.project import Character

# Set up console logging for image generation
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Add console handler if not already present
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('[Image Generation] %(levelname)s: %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


class ImageGenerationAgent:
    """Agent for generating character portraits and scene images."""

    def __init__(self):
        """Initialize image generation agent."""
        self.genai_config = get_genai_config()
        self.settings = self.genai_config.get_settings()

        # Image generation backend (lazy loaded)
        self._image_generator = None
        self._prompt_llm: Optional[LLMClient] = None

    def _get_huggingface_token(self) -> Optional[str]:
        """Get HuggingFace token from secure storage, config, or environment.

        Priority order:
        1. Credential manager (secure keyring storage)
        2. genai_config.json
        3. HF_TOKEN environment variable
        4. huggingface-cli login token

        Returns:
            HuggingFace token or None if not configured
        """
        import os

        # 1. Check credential manager (most secure, preferred method)
        try:
            from src.config.credential_manager import get_credential_manager
            cred_manager = get_credential_manager()
            token = cred_manager.get_huggingface_token()
            if token:
                logger.debug("HuggingFace token found in credential manager")
                return token
        except Exception as e:
            logger.debug(f"Could not access credential manager: {e}")

        # 2. Check genai_config.json
        token = self.settings.get("huggingface_token", "")
        if token:
            logger.debug("HuggingFace token found in genai_config.json")
            return token

        # 3. Check environment variable
        token = os.environ.get("HF_TOKEN", "")
        if token:
            logger.debug("HuggingFace token found in HF_TOKEN environment variable")
            return token

        # 4. Check huggingface-cli login (stored token)
        try:
            from huggingface_hub import HfFolder
            token = HfFolder.get_token()
            if token:
                logger.debug("HuggingFace token found from huggingface-cli login")
                return token
        except Exception:
            pass

        return None

    def _get_prompt_llm(self) -> Optional[LLMClient]:
        """Get LLM for prompt enhancement if enabled."""
        if not self.settings.get("use_prompt_enhancement", True):
            return None

        if self._prompt_llm is None:
            provider_str = self.settings.get("prompt_llm_provider", "local")

            if provider_str == "local":
                # Use local SLM for prompt enhancement
                from src.config.ai_config import get_ai_config
                ai_config = get_ai_config()
                ai_settings = ai_config.get_settings()

                model_id = self.settings.get("prompt_llm_model_id", "")
                if not model_id:
                    # Fallback to default local model
                    from src.ai.agent_suite import get_default_local_model
                    model_id = get_default_local_model()

                from src.ai.llm_client import HuggingFaceConfig
                hf_config = HuggingFaceConfig(
                    model_id=model_id,
                    device="auto",
                    quantization="4bit" if "4bit" in model_id else "8bit",
                    trust_remote_code=ai_settings.get("local_model_trust_remote_code", True)
                )
                self._prompt_llm = LLMClient(provider=LLMProvider.HUGGINGFACE, hf_config=hf_config)
            else:
                # Use cloud provider
                provider_map = {
                    "claude": LLMProvider.CLAUDE,
                    "chatgpt": LLMProvider.OPENAI,
                    "gemini": LLMProvider.GEMINI
                }
                provider = provider_map.get(provider_str, LLMProvider.CLAUDE)
                self._prompt_llm = LLMClient(provider=provider)

        return self._prompt_llm

    def enhance_prompt(self, base_prompt: str, character: Optional[Character] = None) -> str:
        """Enhance image prompt using LLM.

        Args:
            base_prompt: Basic description from user
            character: Optional character for context

        Returns:
            Enhanced prompt optimized for image generation
        """
        logger.info("=" * 60)
        logger.info("PROMPT ENHANCEMENT")
        logger.info("=" * 60)
        logger.info(f"Base prompt: {base_prompt}")
        logger.info(f"Character provided: {character.name if character else 'None'}")

        llm = self._get_prompt_llm()
        if not llm:
            logger.info("Prompt enhancement disabled, returning base prompt")
            logger.info("=" * 60)
            return base_prompt

        # Build context from character if provided
        character_context = ""
        if character and self.settings.get("include_character_context", True):
            char_weight = self.settings.get("character_prompt_weight", 0.8)

            context_parts = []
            if character.physical_description:
                context_parts.append(f"Physical: {character.physical_description}")
                logger.info(f"Added physical description: {character.physical_description[:100]}...")
            if character.personality:
                context_parts.append(f"Personality: {character.personality}")
                logger.info(f"Added personality: {character.personality[:100]}...")
            if character.backstory:
                context_parts.append(f"Background: {character.backstory[:200]}")  # Limit length
                logger.info(f"Added backstory (truncated): {character.backstory[:100]}...")

            if context_parts:
                character_context = f"\n\nCharacter Context (weight: {char_weight}):\n" + "\n".join(context_parts)
                logger.info(f"Character context weight: {char_weight}")

        style = self.settings.get("prompt_enhancement_style", "detailed")
        logger.info(f"Enhancement style: {style}")

        system_prompt = f"""You are an expert at crafting prompts for AI image generation.
Your task is to enhance the user's prompt while maintaining their core intent.

Style: {style}
- concise: Keep it brief but descriptive (1-2 sentences)
- detailed: Add rich visual details, lighting, composition (2-3 sentences)
- artistic: Include artistic style references and techniques (2-3 sentences)

CRITICAL RULES FOR CHARACTER PORTRAITS:
1. ALWAYS describe as: "portrait photograph", "character portrait", "painted portrait", or "headshot"
2. NEVER use: social media, profile picture, avatar, selfie, phone camera, screenshot, app icon
3. Include proper framing: "head and shoulders", "bust portrait", "3/4 view", "close-up portrait"
4. Add professional lighting: "studio lighting", "soft natural light", "dramatic rim lighting"
5. Specify a proper background: "neutral background", "blurred background", "atmospheric background"
6. For artistic styles, reference traditional art: "oil painting", "digital painting", "concept art"

General Rules:
1. Preserve the user's core description and physical features
2. Add visual details (lighting, colors, composition, camera angle)
3. Specify art style if not mentioned (prefer traditional portraiture or photography)
4. Keep it under 150 words
5. Do NOT add NSFW content
6. Focus on visual elements only - this is for a character portrait, NOT a social media profile
{character_context}"""

        try:
            logger.info(f"Calling LLM for prompt enhancement (provider: {self.settings.get('prompt_llm_provider', 'local')})")
            logger.info(f"LLM model: {self.settings.get('prompt_llm_model_id', 'default')}")

            response = llm.generate_text(
                prompt=base_prompt,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=200
            )

            enhanced = response.strip()
            logger.info(f"Enhanced prompt: {enhanced}")
            logger.info("=" * 60)
            return enhanced
        except Exception as e:
            logger.error(f"Failed to enhance prompt: {e}", exc_info=True)
            logger.info("Returning base prompt due to enhancement failure")
            logger.info("=" * 60)
            return base_prompt

    def generate_character_image(
        self,
        character: Character,
        additional_prompt: str = "",
        save_path: Optional[Path] = None
    ) -> Optional[Path]:
        """Generate character portrait using character information.

        Args:
            character: Character to generate image for
            additional_prompt: Additional style/context instructions
            save_path: Where to save the generated image

        Returns:
            Path to generated image or None if generation failed
        """
        if not self.settings.get("image_generation_enabled", True):
            logger.warning("Image generation is disabled in settings")
            return None

        # Build base prompt from character with explicit portrait framing
        # This helps avoid social media profile-style outputs
        base_prompt_parts = [
            f"Character portrait of {character.name}",
            "head and shoulders framing",
            "professional portrait photography"
        ]

        if character.physical_description:
            base_prompt_parts.append(character.physical_description)

        if additional_prompt:
            base_prompt_parts.append(additional_prompt)
        else:
            # Add default quality terms if no additional prompt
            base_prompt_parts.append("neutral background, soft lighting")

        base_prompt = ", ".join(base_prompt_parts)

        # Enhance prompt with LLM if enabled
        enhanced_prompt = self.enhance_prompt(base_prompt, character)

        logger.info(f"Generating image for character: {character.name}")
        logger.debug(f"Base prompt: {base_prompt}")
        logger.debug(f"Enhanced prompt: {enhanced_prompt}")

        # Generate the image
        return self._generate_image(
            prompt=enhanced_prompt,
            save_path=save_path,
            associated_id=character.id
        )

    def generate_scene_image(
        self,
        scene_description: str,
        style: str = "",
        save_path: Optional[Path] = None
    ) -> Optional[Path]:
        """Generate scene visualization.

        Args:
            scene_description: Description of the scene
            style: Style preferences (e.g., "photorealistic", "oil painting")
            save_path: Where to save the generated image

        Returns:
            Path to generated image or None if generation failed
        """
        if not self.settings.get("image_generation_enabled", True):
            logger.warning("Image generation is disabled in settings")
            return None

        # Combine description and style
        prompt = scene_description
        if style:
            prompt = f"{scene_description}, style: {style}"

        # Enhance prompt
        enhanced_prompt = self.enhance_prompt(prompt)

        logger.info("Generating scene image")
        logger.debug(f"Enhanced prompt: {enhanced_prompt}")

        return self._generate_image(prompt=enhanced_prompt, save_path=save_path)

    def _generate_image(
        self,
        prompt: str,
        save_path: Optional[Path] = None,
        associated_id: Optional[str] = None
    ) -> Optional[Path]:
        """Internal method to generate image using configured backend.

        Args:
            prompt: Enhanced prompt for generation
            save_path: Where to save the image
            associated_id: ID of associated character/chapter

        Returns:
            Path to generated image or None if failed
        """
        provider_str = self.settings.get("image_provider", "local_mlx" if can_use_mlx() else "local_torch")
        provider = ImageGenProvider(provider_str)

        # Get generation parameters
        width = self.settings.get("image_width", 1024)
        height = self.settings.get("image_height", 1024)
        num_steps = self.settings.get("image_num_inference_steps", 20)
        guidance_scale = self.settings.get("image_guidance_scale", 7.5)
        negative_prompt = self.settings.get("image_negative_prompt", "blurry, low quality, distorted, deformed, ugly, bad anatomy")
        seed = self.settings.get("image_seed", -1)

        if seed == -1:
            import random
            seed = random.randint(0, 2**32 - 1)

        # Determine save path
        if save_path is None:
            output_dir = Path(self.settings.get("image_output_dir", Path.home() / ".writer_platform" / "generated_images"))
            output_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = output_dir / f"generated_{timestamp}_{seed}.png"

        # Log all generation parameters
        logger.info("=" * 60)
        logger.info("IMAGE GENERATION PARAMETERS")
        logger.info("=" * 60)
        logger.info(f"Provider: {provider}")
        logger.info(f"Model ID: {self.settings.get('image_model_id', 'NOT SET')}")
        logger.info(f"Prompt: {prompt[:200]}{'...' if len(prompt) > 200 else ''}")
        logger.info(f"Dimensions: {width}x{height}")
        logger.info(f"Steps: {num_steps}")
        logger.info(f"Guidance Scale: {guidance_scale}")
        logger.info(f"Seed: {seed}")
        logger.info(f"Output Path: {save_path}")
        logger.info(f"Negative Prompt: {negative_prompt[:100]}{'...' if len(negative_prompt) > 100 else ''}")
        logger.info("=" * 60)

        try:
            if provider == ImageGenProvider.LOCAL_MLX:
                return self._generate_with_mlx(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    num_steps=num_steps,
                    guidance_scale=guidance_scale,
                    seed=seed,
                    save_path=save_path
                )
            elif provider == ImageGenProvider.LOCAL_TORCH:
                return self._generate_with_pytorch(
                    prompt=prompt,
                    negative_prompt=negative_prompt,
                    width=width,
                    height=height,
                    num_steps=num_steps,
                    guidance_scale=guidance_scale,
                    seed=seed,
                    save_path=save_path
                )
            elif provider == ImageGenProvider.OPENAI_DALLE:
                return self._generate_with_dalle(prompt=prompt, save_path=save_path)
            else:
                logger.error(f"Unsupported image provider: {provider}")
                return None

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return None

    def _generate_with_mlx(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        num_steps: int,
        guidance_scale: float,
        seed: int,
        save_path: Path
    ) -> Optional[Path]:
        """Generate image using MLX (Apple Silicon via MFLUX CLI)."""
        try:
            import subprocess
            import sys
            import os

            model_id = self.settings.get("image_model_id", "mflux/flux2-klein-9b")

            logger.info(f"MLX Generation - Model ID from config: {model_id}")

            # Set up Hugging Face token for model downloads
            # MFLUX uses huggingface_hub which respects HF_TOKEN env var
            hf_token = self._get_huggingface_token()
            if hf_token:
                logger.info("MLX Generation - HuggingFace token found, setting HF_TOKEN for model download")
                os.environ['HF_TOKEN'] = hf_token
            else:
                logger.warning("MLX Generation - No HuggingFace token found. Model download may fail for gated models.")
                logger.warning("MLX Generation - Set HF token in genai_config.json or run: huggingface-cli login")

            # Detect FLUX-2 models
            is_flux2 = "flux2" in model_id.lower()
            logger.info(f"MLX Generation - Detected FLUX-2: {is_flux2}")

            if is_flux2:
                # FLUX-2 models (klein-4b, klein-9b)
                if "klein-9b" in model_id.lower():
                    model = "flux2-klein-9b"
                elif "klein-4b" in model_id.lower():
                    model = "flux2-klein-4b"
                else:
                    model = "flux2-klein-4b"  # default

                logger.info(f"MLX Generation - Using FLUX-2 model variant: {model}")

                # Build FLUX-2 command
                cmd = [
                    "mflux-generate-flux2",
                    "--model", model,
                    "--prompt", prompt,
                    "--steps", str(num_steps),
                    "--seed", str(seed),
                    "--height", str(height),
                    "--width", str(width),
                    "--guidance", "1.0",  # FLUX-2 uses fixed guidance 1.0
                    "--output", str(save_path)
                ]

                logger.info(f"MLX Generation - FLUX-2 Command: {' '.join(cmd[:4])} ... (prompt truncated)")
                logger.info(f"MLX Generation - Full command args: model={model}, steps={num_steps}, seed={seed}, size={width}x{height}, guidance=1.0")
            else:
                # FLUX-1 models (dev, schnell, krea-dev)
                if "schnell" in model_id.lower():
                    model = "schnell"
                elif "krea" in model_id.lower():
                    model = "krea-dev"
                else:
                    model = "dev"

                logger.info(f"MLX Generation - Using FLUX-1 model variant: {model}")

                # Parse quantization
                if "8bit" in model_id:
                    quantize = "8"
                elif "4bit" in model_id:
                    quantize = "4"
                else:
                    quantize = "8"  # default

                logger.info(f"MLX Generation - Quantization: {quantize}-bit")

                # Build FLUX-1 command
                cmd = [
                    "mflux-generate",
                    "--model", model,
                    "--prompt", prompt,
                    "--steps", str(num_steps),
                    "--seed", str(seed),
                    "--height", str(height),
                    "--width", str(width),
                    "--guidance", str(guidance_scale),
                    "--quantize", quantize,
                    "--output", str(save_path)
                ]

                logger.info(f"MLX Generation - FLUX-1 Command: {' '.join(cmd[:4])} ... (prompt truncated)")
                logger.info(f"MLX Generation - Full command args: model={model}, steps={num_steps}, seed={seed}, size={width}x{height}, guidance={guidance_scale}, quantize={quantize}")

            # Run MFLUX with real-time console output
            logger.info("MLX Generation - Starting subprocess execution...")
            logger.info(f"MLX Generation - Command binary: {cmd[0]}")
            logger.info("MLX Generation - MFLUX output will stream below:")
            logger.info("-" * 60)

            result = subprocess.run(
                cmd,
                stdout=sys.stdout,  # Stream output to console in real-time
                stderr=sys.stderr,  # Stream errors to console in real-time
                text=True,
                timeout=600  # 10 minute timeout
            )

            logger.info("-" * 60)
            logger.info(f"MLX Generation - Subprocess completed with return code: {result.returncode}")

            if result.returncode != 0:
                logger.error("=" * 60)
                logger.error("MFLUX EXECUTION FAILED")
                logger.error("=" * 60)
                logger.error(f"Return code: {result.returncode}")
                logger.error("=" * 60)
                return None
            else:
                logger.info("MLX Generation - Command executed successfully")

            # Check if file was created
            logger.info(f"MLX Generation - Checking for output file at: {save_path}")
            logger.info(f"MLX Generation - File exists check: {save_path.exists()}")

            if save_path.exists():
                file_size = save_path.stat().st_size
                logger.info(f"MLX Generation - SUCCESS! Image saved to: {save_path}")
                logger.info(f"MLX Generation - File size: {file_size / 1024 / 1024:.2f} MB")
                return save_path
            else:
                logger.warning("MLX Generation - Expected file not found, checking alternate extensions...")
                # MFLUX may have created with different extension
                for ext in ['.png', '.jpg', '.jpeg']:
                    alt_path = save_path.with_suffix(ext)
                    logger.info(f"MLX Generation - Checking {alt_path}: {alt_path.exists()}")
                    if alt_path.exists():
                        file_size = alt_path.stat().st_size
                        logger.info(f"MLX Generation - SUCCESS! Image saved to: {alt_path}")
                        logger.info(f"MLX Generation - File size: {file_size / 1024 / 1024:.2f} MB")
                        return alt_path

                logger.error("=" * 60)
                logger.error("MLX Generation - OUTPUT FILE NOT FOUND")
                logger.error("=" * 60)
                logger.error(f"Expected path: {save_path}")
                logger.error(f"Parent directory exists: {save_path.parent.exists()}")
                logger.error(f"Parent directory contents: {list(save_path.parent.glob('*')) if save_path.parent.exists() else 'N/A'}")
                logger.error(f"STDOUT:\n{result.stdout}")
                logger.error("=" * 60)
                return None

        except subprocess.TimeoutExpired:
            logger.error("=" * 60)
            logger.error("MLX Generation - TIMEOUT (10 minutes)")
            logger.error("=" * 60)
            logger.error("MFLUX generation timed out after 10 minutes")
            logger.error("This may indicate the model is too large for available RAM")
            logger.error("=" * 60)
            return None
        except Exception as e:
            logger.error("=" * 60)
            logger.error("MLX Generation - EXCEPTION")
            logger.error("=" * 60)
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Exception message: {e}", exc_info=True)
            logger.error("Install MFLUX with: pip install mflux")
            logger.error("=" * 60)
            return None

    def _generate_with_pytorch(
        self,
        prompt: str,
        negative_prompt: str,
        width: int,
        height: int,
        num_steps: int,
        guidance_scale: float,
        seed: int,
        save_path: Path
    ) -> Optional[Path]:
        """Generate image using PyTorch (NVIDIA/CPU)."""
        try:
            import torch
            from diffusers import DiffusionPipeline

            model_id = self.settings.get("image_model_id", "black-forest-labs/FLUX.1-dev")

            logger.info(f"Loading PyTorch model: {model_id}")

            # Determine device
            if torch.cuda.is_available():
                device = "cuda"
                dtype = torch.float16
            elif torch.backends.mps.is_available():
                device = "mps"
                dtype = torch.float16
            else:
                device = "cpu"
                dtype = torch.float32

            logger.info(f"Using device: {device}")

            # Load pipeline
            pipe = DiffusionPipeline.from_pretrained(
                model_id,
                torch_dtype=dtype,
                use_safetensors=True
            )
            pipe = pipe.to(device)

            # Generate
            logger.info(f"Generating image with PyTorch ({width}x{height}, {num_steps} steps)")

            generator = torch.Generator(device=device).manual_seed(seed)

            image = pipe(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                num_inference_steps=num_steps,
                guidance_scale=guidance_scale,
                generator=generator
            ).images[0]

            # Save
            image.save(str(save_path))
            logger.info(f"Image saved to: {save_path}")

            return save_path

        except ImportError as e:
            logger.error(f"Required library not installed: {e}")
            logger.error("Install with: pip install torch diffusers transformers accelerate")
            return None
        except Exception as e:
            logger.error(f"PyTorch generation failed: {e}")
            return None

    def _generate_with_dalle(self, prompt: str, save_path: Path) -> Optional[Path]:
        """Generate image using OpenAI DALL-E 3."""
        try:
            import openai
            from src.config.ai_config import get_ai_config

            ai_config = get_ai_config()
            ai_settings = ai_config.get_settings()
            api_key = self.settings.get("dalle_api_key") or ai_settings.get("chatgpt_api_key")

            if not api_key:
                logger.error("No OpenAI API key configured")
                return None

            client = openai.OpenAI(api_key=api_key)

            logger.info("Generating image with DALL-E 3")

            # DALL-E 3 sizes: 1024x1024, 1792x1024, 1024x1792
            width = self.settings.get("image_width", 1024)
            height = self.settings.get("image_height", 1024)

            if width == height:
                size = "1024x1024"
            elif width > height:
                size = "1792x1024"
            else:
                size = "1024x1792"

            response = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size=size,
                quality="standard",
                n=1
            )

            # Download image
            import requests
            image_url = response.data[0].url
            img_data = requests.get(image_url).content

            with open(save_path, 'wb') as f:
                f.write(img_data)

            logger.info(f"Image saved to: {save_path}")
            return save_path

        except Exception as e:
            logger.error(f"DALL-E generation failed: {e}")
            return None


# Global instance
_image_generation_agent = None


def get_image_generation_agent() -> ImageGenerationAgent:
    """Get the global image generation agent instance."""
    global _image_generation_agent
    if _image_generation_agent is None:
        _image_generation_agent = ImageGenerationAgent()
    return _image_generation_agent
