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

        system_prompt = f"""You are an expert at crafting prompts for AI image generation for STORYTELLING and CHARACTER DESIGN.
Your task is to enhance the user's prompt while maintaining their core intent and ENSURING story-appropriate, focused results.

Style: {style}
- concise: Keep it brief but descriptive (1-2 sentences)
- detailed: Add rich visual details, lighting, composition (2-3 sentences)
- artistic: Include artistic style references and techniques (2-3 sentences)

CRITICAL RULES FOR CHARACTER PORTRAITS:
1. SINGLE CHARACTER ONLY: Describe ONE person. Say "solo character", "single person", "individual portrait"
2. PROFESSIONAL FORMATS ONLY: Use "portrait photograph", "character portrait", "character design", "concept art", "painted portrait"
3. NEVER USE: social media, profile picture, avatar, selfie, phone camera, screenshot, app icon, facebook, instagram, dating app, ID photo, mugshot
4. FRAMING: "head and shoulders", "bust portrait", "3/4 view", "close-up portrait" (for headshots), "full body standing pose" (for full body)
5. LIGHTING: "studio lighting", "soft natural light", "dramatic rim lighting", "cinematic lighting"
6. BACKGROUND: Match the character's environment (e.g., "workshop background" for blacksmith, "urban alley" for street hacker)
   - Use "neutral background", "blurred background", or contextual settings ONLY
   - NEVER: UI elements, frames, borders, windows, screens
7. ART STYLE: "digital painting", "concept art", "oil painting", "photorealistic portrait", "character sheet"

STORY-APPROPRIATE CONTEXT:
- If character has a profession, include environmental hints (tools, setting)
- Capture PERSONALITY through expression, posture, and style
- Maintain GENRE consistency (fantasy characters shouldn't look modern, sci-fi shouldn't look medieval)
- Emphasize STYLE OF DRESS mentioned in the character description

ABSOLUTE PROHIBITIONS:
- DO NOT add extra people, crowds, or background characters
- DO NOT reference any modern social media or digital UI
- DO NOT include text, logos, captions, or overlays
- DO NOT create unrealistic mashups (e.g., "alien in business suit" unless that's the story)

General Rules:
1. Preserve the user's EXACT physical features and descriptions
2. Add visual details that ENHANCE storytelling (lighting, colors, composition, expression)
3. Keep environmental details RELEVANT to the character's role/world
4. Keep it under 150 words
5. Do NOT add NSFW content
6. GENRE CONSISTENCY: Fantasy stays fantasy, sci-fi stays sci-fi, historical stays historical
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
        # CRITICAL: Emphasize SINGLE character to avoid group shots
        base_prompt_parts = [
            f"Solo character portrait of {character.name}",
            "single person",
            "individual character design",
            "professional portrait photography"
        ]

        # Add physical description first (most important)
        if character.physical_description:
            base_prompt_parts.append(character.physical_description)

        # Add personality cues for expression/posture
        if character.personality:
            # Extract visual personality hints
            personality_lower = character.personality.lower()
            if any(word in personality_lower for word in ['confident', 'bold', 'strong', 'determined']):
                base_prompt_parts.append("confident expression, strong posture")
            elif any(word in personality_lower for word in ['shy', 'nervous', 'timid', 'anxious']):
                base_prompt_parts.append("reserved expression, subtle body language")
            elif any(word in personality_lower for word in ['friendly', 'warm', 'kind', 'gentle']):
                base_prompt_parts.append("warm expression, approachable demeanor")
            elif any(word in personality_lower for word in ['serious', 'stern', 'stoic']):
                base_prompt_parts.append("serious expression, focused gaze")
            elif any(word in personality_lower for word in ['mischievous', 'playful', 'clever']):
                base_prompt_parts.append("slight smirk, intelligent eyes")

        # Add environmental context from backstory/notes
        role_text = getattr(character, 'role', None) or character.backstory or character.notes
        if role_text:
            role_lower = role_text.lower()
            if any(word in role_lower for word in ['blacksmith', 'smith', 'forge']):
                base_prompt_parts.append("workshop setting, leather apron")
            elif any(word in role_lower for word in ['hacker', 'programmer', 'tech']):
                base_prompt_parts.append("urban tech environment, hooded jacket")
            elif any(word in role_lower for word in ['soldier', 'warrior', 'fighter']):
                base_prompt_parts.append("battle-worn armor, determined stance")
            elif any(word in role_lower for word in ['noble', 'lord', 'lady', 'royal']):
                base_prompt_parts.append("elegant formal attire, refined setting")
            elif any(word in role_lower for word in ['merchant', 'trader']):
                base_prompt_parts.append("practical clothing, weathered appearance")

        # Add additional prompt (from UI - headshot vs full body)
        if additional_prompt:
            base_prompt_parts.append(additional_prompt)
        else:
            # Add default quality terms if no additional prompt
            base_prompt_parts.append("neutral background, soft cinematic lighting")

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
        """Generate scene visualization focused on STORY ELEMENTS.

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

        # Build story-focused prompt
        prompt_parts = [scene_description]

        # Add story/narrative framing
        prompt_parts.append("story illustration")
        prompt_parts.append("narrative scene")

        # Add style
        if style:
            prompt_parts.append(f"style: {style}")
        else:
            # Default to cinematic/illustrative if no style specified
            prompt_parts.append("cinematic composition")

        # Combine
        prompt = ", ".join(prompt_parts)

        # Enhance prompt with story-focused system prompt
        enhanced_prompt = self._enhance_scene_prompt(prompt)

        logger.info("Generating scene image (story-focused)")
        logger.debug(f"Enhanced prompt: {enhanced_prompt}")

        return self._generate_image(prompt=enhanced_prompt, save_path=save_path)

    def _enhance_scene_prompt(self, base_prompt: str) -> str:
        """Enhance scene prompt with story-focused guidance.

        Args:
            base_prompt: Basic scene description

        Returns:
            Enhanced prompt optimized for story illustration
        """
        logger.info("=" * 60)
        logger.info("SCENE PROMPT ENHANCEMENT")
        logger.info("=" * 60)
        logger.info(f"Base prompt: {base_prompt}")

        llm = self._get_prompt_llm()
        if not llm:
            logger.info("Prompt enhancement disabled, returning base prompt")
            logger.info("=" * 60)
            return base_prompt

        style = self.settings.get("prompt_enhancement_style", "detailed")
        logger.info(f"Enhancement style: {style}")

        system_prompt = f"""You are an expert at crafting prompts for AI image generation of STORY SCENES and ILLUSTRATIONS.
Your task is to enhance the user's scene description while keeping it STORY-APPROPRIATE and COHERENT.

Style: {style}
- concise: Keep it brief but vivid (1-2 sentences)
- detailed: Add rich environmental details, atmosphere, composition (2-3 sentences)
- artistic: Include artistic style references and cinematic techniques (2-3 sentences)

CRITICAL RULES FOR SCENE GENERATION:
1. STORY CONSISTENCY: Keep all elements consistent with the genre (fantasy/sci-fi/historical/modern)
2. COHERENT ELEMENTS: All objects, characters, and settings should make sense together
3. NO RANDOM MASHUPS: Don't combine incompatible elements (e.g., "alien on a ranch" unless that's the story)
4. NARRATIVE FOCUS: Emphasize the STORY moment being depicted
5. ENVIRONMENTAL CONTEXT: Add weather, time of day, atmosphere that fits the scene

WHAT TO INCLUDE:
- Setting details (location, time of day, weather)
- Mood and atmosphere (tense, peaceful, dramatic, mysterious)
- Lighting (golden hour, stormy, moonlit, harsh daylight)
- Composition (wide shot, close-up, dramatic angle)
- Art style (digital painting, concept art, photorealistic, oil painting)

WHAT TO AVOID:
- Social media elements (profile pictures, UI, screenshots)
- Modern tech in fantasy settings (unless it's sci-fi/cyberpunk)
- Unrealistic genre mixing (medieval knights with smartphones)
- Out-of-place elements (random objects that don't fit the scene)
- Text, logos, watermarks, frames

EXAMPLE ENHANCEMENTS:
User: "A person ranching"
Good: "Western ranch scene at golden hour, cowboy on horseback herding cattle across open prairie, dramatic clouds, warm sunset lighting, cinematic wide shot, photorealistic western art"
Bad: "Alien facebook profile in ranch setting" ❌

User: "Tavern scene"
Good: "Medieval tavern interior, warm fireplace light, wooden tables with patrons drinking, stone walls, atmospheric smoke, oil painting style, cozy and rustic"
Bad: "Tavern with modern smartphones and neon signs" ❌

Keep it under 150 words. Focus on VISUAL storytelling."""

        try:
            logger.info(f"Calling LLM for scene prompt enhancement")

            response = llm.generate_text(
                prompt=base_prompt,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=200
            )

            enhanced = response.strip()
            logger.info(f"Enhanced scene prompt: {enhanced}")
            logger.info("=" * 60)
            return enhanced
        except Exception as e:
            logger.error(f"Failed to enhance scene prompt: {e}", exc_info=True)
            logger.info("Returning base prompt due to enhancement failure")
            logger.info("=" * 60)
            return base_prompt

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

        # Enhanced negative prompt to exclude unwanted elements
        default_negative = (
            "blurry, low quality, distorted, deformed, ugly, bad anatomy, "
            "multiple people, group photo, crowd, extra people, "
            "social media, profile picture, selfie, phone screen, screenshot, "
            "facebook, instagram, app interface, UI elements, text overlay, "
            "watermark, logo, caption, frame, border, window, "
            "alien profile, unrealistic mashup, out of genre, "
            "modern clothing on fantasy character, "
            "duplicate, clone, copy"
        )
        negative_prompt = self.settings.get("image_negative_prompt", default_negative)
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

            # Detect model family
            model_lower = model_id.lower()
            is_flux2 = "flux2" in model_lower
            is_sd35 = "sd3.5" in model_lower or "stable-diffusion-3.5" in model_lower

            if is_flux2:
                # FLUX-2 models (klein-4b, klein-9b)
                if "klein-9b" in model_lower:
                    model = "flux2-klein-9b"
                elif "klein-4b" in model_lower:
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

            elif is_sd35:
                # Stable Diffusion 3.5 models via MFLUX
                if "large" in model_lower:
                    model = "stabilityai/stable-diffusion-3.5-large"
                else:
                    model = "stabilityai/stable-diffusion-3.5-medium"

                logger.info(f"MLX Generation - Using SD 3.5 model: {model}")

                cmd = [
                    "mflux-generate-sd3",
                    "--model", model,
                    "--prompt", prompt,
                    "--steps", str(num_steps),
                    "--seed", str(seed),
                    "--height", str(height),
                    "--width", str(width),
                    "--guidance", str(guidance_scale),
                    "--output", str(save_path)
                ]

                logger.info(f"MLX Generation - SD3.5 Command: {' '.join(cmd[:4])} ... (prompt truncated)")
                logger.info(f"MLX Generation - Full command args: model={model}, steps={num_steps}, seed={seed}, size={width}x{height}, guidance={guidance_scale}")

            else:
                # FLUX-1 models (dev, schnell, krea-dev)
                if "schnell" in model_lower:
                    model = "schnell"
                elif "krea" in model_lower:
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
            import gc
            from diffusers import DiffusionPipeline

            # Clear any sticky CUDA error state from prior operations
            # (e.g. a failed bitsandbytes load or LLM generation).
            # Without this, a prior assert poisons ALL subsequent calls.
            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                except RuntimeError:
                    pass
                torch.cuda.empty_cache()
                gc.collect()
                # Test if CUDA is actually usable — if a prior error
                # left it in a broken state, fall back to CPU.
                try:
                    _test = torch.zeros(1, device="cuda")
                    del _test
                except RuntimeError as e:
                    logger.warning(
                        f"CUDA in error state, falling back to CPU: {e}")
                    torch.cuda.empty_cache()
                    # Mark CUDA as unavailable for this call
                    os.environ["_IMGGEN_FORCE_CPU"] = "1"

            model_id = self.settings.get("image_model_id", "black-forest-labs/FLUX.2-klein-4B")

            logger.info(f"Loading PyTorch model: {model_id}")

            # Unload any local LLM models to free VRAM and clear any
            # poisoned CUDA state from bitsandbytes quantized models.
            from src.ai.llm_client import unload_all_local_clients
            n_unloaded = unload_all_local_clients(clear_cuda=True, clear_mlx=False)
            if n_unloaded:
                logger.info(f"Unloaded {n_unloaded} local LLM(s) to free VRAM")

            # Determine device and dtype
            import os as _os
            _force_cpu = _os.environ.pop("_IMGGEN_FORCE_CPU", None)
            if torch.cuda.is_available() and not _force_cpu:
                device = "cuda"
                # Blackwell (CC 12.0+) and Ampere+ (CC 8.0+) prefer bfloat16
                cc = torch.cuda.get_device_capability(0)
                dtype = torch.bfloat16 if cc[0] >= 8 else torch.float16
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
                dtype = torch.float16
            else:
                device = "cpu"
                dtype = torch.float32

            logger.info(f"Using device: {device}, dtype: {dtype}")

            # Detect model family for parameter adjustments
            model_lower = model_id.lower()
            is_flux = "flux" in model_lower
            is_flux2 = "flux.2" in model_lower or "flux2" in model_lower

            # Get HF token for gated models
            hf_token = self._get_huggingface_token()
            pipe_kwargs = {"torch_dtype": dtype, "use_safetensors": True}
            if hf_token:
                pipe_kwargs["token"] = hf_token

            # Load pipeline
            pipe = DiffusionPipeline.from_pretrained(model_id, **pipe_kwargs)

            # Memory management: use CPU offload on GPUs with < 14 GB free
            if device == "cuda":
                free_mem = torch.cuda.mem_get_info(0)[0] / (1024**3)
                logger.info(f"GPU free memory: {free_mem:.1f} GB")
                if free_mem < 14:
                    try:
                        pipe.enable_model_cpu_offload()
                        logger.info("Enabled CPU offload for memory efficiency")
                    except Exception:
                        pipe = pipe.to(device)
                else:
                    pipe = pipe.to(device)
            else:
                pipe = pipe.to(device)

            # FLUX-specific parameter overrides
            if is_flux:
                # FLUX models don't use negative prompts
                negative_prompt = None
                # FLUX.2 Klein uses 4 steps, guidance 1.0
                # FLUX.1 schnell uses 4 steps, guidance 0.0
                # FLUX.1 dev uses 20-50 steps, guidance 3.5
                if is_flux2:
                    num_steps = min(num_steps, 4) if num_steps <= 4 else num_steps
                    if num_steps > 8:
                        num_steps = 4
                    guidance_scale = 1.0
                elif "schnell" in model_lower:
                    num_steps = 4
                    guidance_scale = 0.0
                else:
                    # FLUX.1-dev
                    guidance_scale = 3.5
                # FLUX likes multiples of 16
                width = max(512, (width // 16) * 16)
                height = max(512, (height // 16) * 16)

            logger.info(f"Generating image with PyTorch ({width}x{height}, {num_steps} steps, guidance={guidance_scale})")

            # Generator on CPU to avoid device-side asserts on newer architectures
            generator = torch.Generator(device="cpu").manual_seed(seed)

            # Build generation kwargs
            gen_kwargs = {
                "prompt": prompt,
                "width": width,
                "height": height,
                "num_inference_steps": num_steps,
                "guidance_scale": guidance_scale,
                "generator": generator,
            }
            if negative_prompt and not is_flux:
                gen_kwargs["negative_prompt"] = negative_prompt

            image = pipe(**gen_kwargs).images[0]

            # Save
            save_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(save_path))
            logger.info(f"Image saved to: {save_path}")

            # Free VRAM
            del pipe
            if device == "cuda":
                torch.cuda.empty_cache()

            return save_path

        except ImportError as e:
            logger.error(f"Required library not installed: {e}")
            logger.error("Install with: pip install torch diffusers transformers accelerate")
            return None
        except Exception as e:
            logger.error(f"PyTorch generation failed: {e}")
            return None

    def _generate_with_dalle(self, prompt: str, save_path: Path) -> Optional[Path]:
        """Generate image using OpenAI image models (GPT Image or DALL-E 3)."""
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

            # Determine which model to use
            model_id = self.settings.get("image_model_id", "gpt-image-1")
            is_gpt_image = model_id.startswith("gpt-image")

            width = self.settings.get("image_width", 1024)
            height = self.settings.get("image_height", 1024)

            if is_gpt_image:
                logger.info(f"Generating image with {model_id}")

                # GPT Image sizes: 1024x1024, 1536x1024, 1024x1536
                if width == height:
                    size = "1024x1024"
                elif width > height:
                    size = "1536x1024"
                else:
                    size = "1024x1536"

                response = client.images.generate(
                    model=model_id,
                    prompt=prompt,
                    size=size,
                    n=1
                )
            else:
                logger.info("Generating image with DALL-E 3")

                # DALL-E 3 sizes: 1024x1024, 1792x1024, 1024x1792
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
            logger.error(f"OpenAI image generation failed: {e}")
            return None


# Global instance
_image_generation_agent = None


def get_image_generation_agent() -> ImageGenerationAgent:
    """Get the global image generation agent instance."""
    global _image_generation_agent
    if _image_generation_agent is None:
        _image_generation_agent = ImageGenerationAgent()
    return _image_generation_agent
