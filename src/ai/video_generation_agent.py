"""Video Generation Agent for scene-based video creation.

Supports local generation via diffusers (WAN 2.1, etc.) with automatic
VRAM management — unloads other local models before loading the video
pipeline.
"""

import gc
import logging
import sys
import uuid
from pathlib import Path
from typing import Optional

from src.config.ai_config import get_ai_config
from src.ai.llm_client import LLMClient, LLMProvider, unload_all_local_clients
from src.models.project import (
    Character, VideoScene, WriterProject,
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    _ch = logging.StreamHandler(sys.stdout)
    _ch.setLevel(logging.INFO)
    _ch.setFormatter(logging.Formatter("[VideoGen] %(levelname)s: %(message)s"))
    logger.addHandler(_ch)

# Resolution presets -------------------------------------------------------
RESOLUTION_MAP = {
    "480p": (854, 480),
    "720p": (1280, 720),
    "1080p": (1920, 1080),
}


class VideoGenerationAgent:
    """Orchestrates prompt optimisation and local video generation."""

    def __init__(self):
        self._ai_config = get_ai_config()
        self._settings = self._ai_config.get_settings()
        self._pipeline = None  # Lazy-loaded diffusers pipeline
        self._pipeline_model_id: Optional[str] = None
        self._prompt_llm: Optional[LLMClient] = None

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _get_prompt_llm(self) -> Optional[LLMClient]:
        """Return an LLM client for prompt optimisation (cloud or local)."""
        if self._prompt_llm is not None:
            return self._prompt_llm

        from src.config.ai_config import get_ai_config
        ai_settings = get_ai_config().get_settings()
        provider_str = ai_settings.get("default_llm", "claude")

        provider_map = {
            "claude": LLMProvider.CLAUDE,
            "chatgpt": LLMProvider.OPENAI,
            "gemini": LLMProvider.GEMINI,
        }
        provider = provider_map.get(provider_str)
        if provider:
            self._prompt_llm = LLMClient(provider=provider)
        return self._prompt_llm

    def optimize_prompt(
        self,
        scene: VideoScene,
        characters: list[Character],
        worldbuilding_context: str = "",
        chapter_text: str = "",
    ) -> str:
        """Build and optimise a video-generation prompt for *scene*.

        Merges the user prompt with character descriptions, worldbuilding
        notes and chapter text, then asks an LLM to rewrite for the
        target video model.
        """
        # ── Assemble raw context ──────────────────────────────────────
        parts: list[str] = []
        if scene.prompt:
            parts.append(f"Scene direction: {scene.prompt}")
        if scene.description:
            parts.append(f"Narrative description: {scene.description}")

        # Character physique / appearance (consistency anchor)
        for char in characters:
            desc_bits = [f"Character — {char.name}"]
            if char.physical_description:
                desc_bits.append(f"  Appearance: {char.physical_description}")
            if char.personality:
                desc_bits.append(f"  Demeanor: {char.personality}")
            parts.append("\n".join(desc_bits))

        if worldbuilding_context:
            parts.append(f"World context: {worldbuilding_context}")
        if chapter_text:
            # Truncate to avoid blowing context windows
            excerpt = chapter_text[:2000]
            parts.append(f"Relevant chapter text: {excerpt}")

        raw_context = "\n\n".join(parts)

        # ── LLM rewrite ──────────────────────────────────────────────
        llm = self._get_prompt_llm()
        if not llm:
            logger.info("No LLM available — using raw assembled prompt")
            return raw_context

        system_prompt = (
            "You are an expert at writing prompts for AI video generation models "
            "(e.g. Wan 2.1, Runway, Kling). Given a scene description together "
            "with character details, worldbuilding notes and chapter text, write "
            "a single concise video-generation prompt (max 250 words).\n\n"
            "Rules:\n"
            "1. VISUAL ONLY — describe what the camera sees: action, lighting, "
            "   colour palette, camera movement, composition.\n"
            "2. CHARACTER CONSISTENCY — always include explicit physical "
            "   descriptions (hair colour, build, clothing) so the model can "
            "   maintain identity across scenes.\n"
            "3. CINEMATIC LANGUAGE — use terms like 'tracking shot', 'close-up', "
            "   'wide establishing shot', 'shallow depth of field', etc.\n"
            "4. MOOD & ATMOSPHERE — convey emotion through lighting and colour.\n"
            "5. NO dialogue, no text overlays, no UI elements.\n"
            "6. Do NOT narrate — describe the visual scene only.\n"
            "7. Output the prompt ONLY — no commentary."
        )

        try:
            result = llm.generate_text(
                prompt=raw_context,
                system_prompt=system_prompt,
                temperature=0.6,
                max_tokens=350,
            )
            optimized = result.strip()
            logger.info("Prompt optimised via LLM (%d chars)", len(optimized))
            return optimized
        except Exception as exc:
            logger.warning("LLM prompt optimisation failed: %s", exc)
            return raw_context

    def generate_scenes_from_chapter(
        self,
        chapter_text: str,
        chapter_id: str,
        num_scenes: int = 5,
        characters: Optional[list[Character]] = None,
        worldbuilding_context: str = "",
        user_direction: str = "",
    ) -> list[VideoScene]:
        """Ask an LLM to break a chapter into *num_scenes* video scenes.

        Returns a list of VideoScene objects with populated prompt,
        description, and character_ids fields.  The caller is responsible
        for inserting them into a VideoProject.
        """
        llm = self._get_prompt_llm()
        if not llm:
            raise RuntimeError(
                "No LLM configured — cannot auto-generate scenes. "
                "Please set up a cloud or local LLM in Settings."
            )

        # Build character roster for the LLM
        char_block = ""
        char_list = characters or []
        if char_list:
            lines = []
            for c in char_list:
                lines.append(
                    f"- {c.name} (id={c.id}): "
                    f"{c.physical_description or 'no physical description'}"
                )
            char_block = "Characters available:\n" + "\n".join(lines)

        system_prompt = (
            "You are a cinematic scene planner for a novel-to-video adaptation. "
            "Given chapter text, a list of characters, worldbuilding notes and "
            "optional user direction, break the chapter into exactly "
            f"{num_scenes} visually compelling scenes.\n\n"
            "For EACH scene output a JSON object with these keys:\n"
            "  title       — short scene title (5-8 words)\n"
            "  prompt      — concise visual prompt for AI video generation "
            "(what the camera sees: action, lighting, composition, mood)\n"
            "  description — 2-3 sentence narrative description\n"
            "  character_ids — list of character id strings present\n"
            "  duration_seconds — suggested duration (3-10 seconds)\n\n"
            "Return a JSON array of scene objects. NO commentary outside "
            "the JSON array. Ensure CHARACTER CONSISTENCY by including "
            "physical descriptors each time a character appears.\n\n"
            f"{char_block}\n\n"
            f"Worldbuilding context:\n{worldbuilding_context[:2000]}\n\n"
            f"User direction: {user_direction or 'Pick the most visually compelling moments.'}"
        )

        import json as _json

        response = llm.generate_text(
            prompt=chapter_text[:6000],
            system_prompt=system_prompt,
            temperature=0.7,
            max_tokens=3000,
        )

        # Parse the JSON array from the response
        scenes: list[VideoScene] = []
        try:
            # Strip markdown code fences if present
            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[:-3]
                elif "```" in text:
                    text = text[: text.rfind("```")]
            raw_scenes = _json.loads(text)
        except _json.JSONDecodeError:
            logger.error("Failed to parse scene JSON from LLM response")
            raise RuntimeError(
                "The AI returned an unparseable response. Please try again."
            )

        for idx, raw in enumerate(raw_scenes):
            scene = VideoScene(
                id=str(uuid.uuid4()),
                order=idx,
                title=raw.get("title", f"Scene {idx + 1}"),
                prompt=raw.get("prompt", ""),
                description=raw.get("description", ""),
                chapter_id=chapter_id,
                character_ids=raw.get("character_ids", []),
                duration_seconds=float(raw.get("duration_seconds", 5)),
            )
            scenes.append(scene)

        logger.info("Generated %d scenes from chapter", len(scenes))
        return scenes

    # ------------------------------------------------------------------
    # Video generation (local diffusers pipeline)
    # ------------------------------------------------------------------

    def _ensure_pipeline(self, model_id: str):
        """Load (or swap) the diffusers video pipeline, freeing VRAM first."""
        if self._pipeline is not None and self._pipeline_model_id == model_id:
            return  # Already loaded

        # Unload everything else to maximise VRAM headroom
        logger.info("Unloading all local models before loading video pipeline …")
        unload_all_local_clients(clear_cuda=True, clear_mlx=True)

        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

        logger.info("Loading video pipeline: %s", model_id)

        try:
            import torch
            from diffusers import DiffusionPipeline

            dtype = torch.float16 if torch.cuda.is_available() else torch.float32
            device = "cuda" if torch.cuda.is_available() else "cpu"

            # Try to get HF token
            hf_token = self._get_hf_token()

            self._pipeline = DiffusionPipeline.from_pretrained(
                model_id,
                torch_dtype=dtype,
                token=hf_token,
            )
            self._pipeline.to(device)

            # Enable memory-efficient attention when available
            if hasattr(self._pipeline, "enable_model_cpu_offload"):
                try:
                    self._pipeline.enable_model_cpu_offload()
                    logger.info("Enabled CPU offload for memory efficiency")
                except Exception:
                    pass

            self._pipeline_model_id = model_id
            logger.info("Video pipeline loaded on %s", device)
        except Exception as exc:
            self._pipeline = None
            self._pipeline_model_id = None
            raise RuntimeError(
                f"Failed to load video model '{model_id}': {exc}"
            ) from exc

    def _get_hf_token(self) -> Optional[str]:
        """Retrieve HuggingFace token from credential manager / env."""
        import os

        try:
            from src.config.credential_manager import get_credential_manager
            token = get_credential_manager().get_huggingface_token()
            if token:
                return token
        except Exception:
            pass

        token = os.environ.get("HF_TOKEN", "")
        if token:
            return token

        try:
            from huggingface_hub import HfFolder
            return HfFolder.get_token()
        except Exception:
            pass
        return None

    def generate_video(
        self,
        scene: VideoScene,
        model_id: str,
        output_dir: Path,
        fps: int = 24,
        resolution: str = "720p",
    ) -> Path:
        """Generate a video clip for *scene* and return the output path.

        The generated file is saved as ``<output_dir>/<scene.id>.mp4``.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{scene.id}.mp4"

        prompt = scene.optimized_prompt or scene.prompt
        if not prompt:
            raise ValueError("Scene has no prompt — cannot generate video.")

        self._ensure_pipeline(model_id)

        width, height = RESOLUTION_MAP.get(resolution, (1280, 720))
        num_frames = max(int(scene.duration_seconds * fps), fps)  # At least 1 second

        logger.info(
            "Generating video: %dx%d, %d frames @ %d fps",
            width, height, num_frames, fps,
        )

        try:
            result = self._pipeline(
                prompt=prompt,
                num_frames=num_frames,
                height=height,
                width=width,
                num_inference_steps=30,
                guidance_scale=7.5,
            )

            # Export frames to mp4
            frames = result.frames[0] if hasattr(result, "frames") else result[0]
            self._export_frames_to_mp4(frames, out_path, fps)

            logger.info("Video saved to %s", out_path)
            return out_path

        except Exception as exc:
            logger.error("Video generation failed: %s", exc)
            raise

    @staticmethod
    def _export_frames_to_mp4(frames, out_path: Path, fps: int):
        """Write a list of PIL images / numpy arrays to an mp4 file."""
        try:
            from diffusers.utils import export_to_video
            export_to_video(frames, str(out_path), fps=fps)
            return
        except Exception:
            pass

        # Fallback: use imageio
        try:
            import imageio
            import numpy as np

            writer = imageio.get_writer(str(out_path), fps=fps, codec="libx264")
            for frame in frames:
                if hasattr(frame, "numpy"):
                    frame = frame.numpy()
                if not isinstance(frame, np.ndarray):
                    import PIL.Image
                    if isinstance(frame, PIL.Image.Image):
                        frame = np.array(frame)
                writer.append_data(frame)
            writer.close()
            return
        except ImportError:
            pass

        raise RuntimeError(
            "Cannot export video — install 'imageio[ffmpeg]' or a recent "
            "version of diffusers with export_to_video support."
        )

    def unload_pipeline(self):
        """Free the video pipeline from VRAM."""
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
            self._pipeline_model_id = None
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            logger.info("Video pipeline unloaded")


# ── Singleton accessor ────────────────────────────────────────────────────
_video_generation_agent: Optional[VideoGenerationAgent] = None


def get_video_generation_agent() -> VideoGenerationAgent:
    global _video_generation_agent
    if _video_generation_agent is None:
        _video_generation_agent = VideoGenerationAgent()
    return _video_generation_agent
