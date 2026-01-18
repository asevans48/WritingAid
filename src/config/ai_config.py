"""AI configuration management with persistent storage."""

import json
from pathlib import Path
from typing import Dict, Any
import os


class AIConfig:
    """Manage AI configuration with persistent storage."""

    DEFAULT_SETTINGS = {
        # API Keys (stored in config for non-sensitive providers, secure storage preferred)
        "claude_api_key": "",
        "chatgpt_api_key": "",
        "gemini_api_key": "",

        # Model Selection
        "default_llm": "claude",
        "claude_model": "claude-3-5-sonnet-20241022",
        "openai_model": "gpt-4-turbo-preview",
        "gemini_model": "gemini-pro",

        # Generation Parameters
        "temperature": 0.7,
        "max_tokens": 2000,
        "top_p": 0.95,

        # Features
        "disable_all_ai": False,  # Master toggle to disable all AI/LLM features
        "enable_chat": True,
        "enable_character_gen": True,
        "enable_plot_suggestions": True,
        "enable_worldbuilding_help": True,
        "enable_writing_suggestions": True,
        "enable_grammar_check": True,
        "enable_image_generation": True,
        "enable_auto_save": True,

        # Context Settings
        "context_window": 10,
        "enable_project_context": True,

        # Advanced Options
        "enable_streaming": False,
        "enable_fallback": True,
        "enable_caching": True,

        # Local SLM Settings
        "enable_local_models": False,  # Enable local/small language models support
        "local_model_id": "",  # Hugging Face model ID (e.g., "microsoft/Phi-4-mini-instruct")
        "local_model_quantization": "none",  # "none", "4bit", "8bit"
        "local_model_device": "auto",  # "auto", "cuda", "cpu", "mps"
        "local_model_trust_remote_code": False,  # Whether to trust remote code for model loading
        "prefer_local_model": False,  # Use local model instead of cloud by default
        "local_model_max_tokens": 1024,  # Max tokens for local model generation

        # Session State
        "last_project_path": ""
    }

    def __init__(self):
        """Initialize AI config."""
        self.config_dir = Path.home() / ".writer_platform"
        self.config_file = self.config_dir / "ai_config.json"
        self.settings = self._load_settings()

    def _load_settings(self) -> Dict[str, Any]:
        """Load settings from disk or return defaults."""
        if not self.config_file.exists():
            return self.DEFAULT_SETTINGS.copy()

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # Merge with defaults to ensure all keys exist
                settings = self.DEFAULT_SETTINGS.copy()
                settings.update(loaded)
                return settings
        except Exception as e:
            print(f"Error loading AI config: {e}")
            return self.DEFAULT_SETTINGS.copy()

    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """Save settings to disk.

        Args:
            settings: Settings dictionary to save

        Returns:
            True if save successful, False otherwise
        """
        try:
            # Create config directory if it doesn't exist
            self.config_dir.mkdir(parents=True, exist_ok=True)

            # Update current settings
            self.settings.update(settings)

            # Save to file
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)

            return True
        except Exception as e:
            print(f"Error saving AI config: {e}")
            return False

    def get_settings(self) -> Dict[str, Any]:
        """Get current settings.

        Returns:
            Settings dictionary
        """
        return self.settings.copy()

    def get_api_key(self, provider: str) -> str:
        """Get API key for specific provider.

        Args:
            provider: Provider name (claude, chatgpt, gemini)

        Returns:
            API key string or empty string if not set
        """
        key_map = {
            "claude": "claude_api_key",
            "chatgpt": "chatgpt_api_key",
            "openai": "chatgpt_api_key",
            "gemini": "gemini_api_key"
        }
        key_name = key_map.get(provider.lower(), "")
        return self.settings.get(key_name, "")

    def get_model(self, provider: str) -> str:
        """Get model name for specific provider.

        Args:
            provider: Provider name (claude, chatgpt/openai, gemini)

        Returns:
            Model name string
        """
        model_map = {
            "claude": "claude_model",
            "chatgpt": "openai_model",
            "openai": "openai_model",
            "gemini": "gemini_model"
        }
        model_key = model_map.get(provider.lower(), "")
        return self.settings.get(model_key, "")

    def is_ai_disabled(self) -> bool:
        """Check if all AI features are disabled.

        Returns:
            True if AI is disabled, False otherwise
        """
        return self.settings.get("disable_all_ai", False)

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a specific AI feature is enabled.

        Args:
            feature: Feature name (chat, character_gen, plot_suggestions, etc.)

        Returns:
            True if feature is enabled, False otherwise
        """
        # If all AI is disabled, no features are enabled
        if self.is_ai_disabled():
            return False
        key = f"enable_{feature}"
        return self.settings.get(key, True)

    def has_valid_api_key(self, provider: str = None) -> bool:
        """Check if valid API key exists.

        Args:
            provider: Optional provider name. If None, checks default provider.

        Returns:
            True if API key exists and is not empty
        """
        if provider is None:
            provider = self.settings.get("default_llm", "claude")

        api_key = self.get_api_key(provider)
        return bool(api_key and len(api_key) > 10)

    def get_generation_params(self) -> Dict[str, Any]:
        """Get generation parameters for AI requests.

        Returns:
            Dictionary with temperature, max_tokens, top_p
        """
        return {
            "temperature": self.settings.get("temperature", 0.7),
            "max_tokens": self.settings.get("max_tokens", 2000),
            "top_p": self.settings.get("top_p", 0.95)
        }

    def reset_to_defaults(self) -> bool:
        """Reset all settings to defaults.

        Returns:
            True if reset successful
        """
        self.settings = self.DEFAULT_SETTINGS.copy()
        return self.save_settings(self.settings)

    def get_last_project_path(self) -> str:
        """Get the path of the last opened project.

        Returns:
            Path string or empty string if none
        """
        return self.settings.get("last_project_path", "")

    def set_last_project_path(self, path: str) -> bool:
        """Save the last opened project path.

        Args:
            path: Project file path

        Returns:
            True if save successful
        """
        self.settings["last_project_path"] = path
        return self.save_settings(self.settings)

    # Local SLM Methods

    def get_local_model_settings(self) -> Dict[str, Any]:
        """Get all local model settings.

        Returns:
            Dictionary with local model configuration
        """
        return {
            "model_id": self.settings.get("local_model_id", ""),
            "quantization": self.settings.get("local_model_quantization", "none"),
            "device": self.settings.get("local_model_device", "auto"),
            "trust_remote_code": self.settings.get("local_model_trust_remote_code", False),
            "prefer_local": self.settings.get("prefer_local_model", False),
            "max_tokens": self.settings.get("local_model_max_tokens", 1024),
        }

    def set_local_model(self, model_id: str, trust_remote_code: bool = False) -> bool:
        """Set the local model to use.

        Args:
            model_id: Hugging Face model ID
            trust_remote_code: Whether model requires trust_remote_code

        Returns:
            True if saved successfully
        """
        self.settings["local_model_id"] = model_id
        self.settings["local_model_trust_remote_code"] = trust_remote_code
        return self.save_settings(self.settings)

    def get_local_model_id(self) -> str:
        """Get the configured local model ID.

        Returns:
            Model ID string or empty if not set
        """
        return self.settings.get("local_model_id", "")

    def should_prefer_local_model(self) -> bool:
        """Check if local model should be preferred over cloud.

        Returns:
            True if local model is preferred
        """
        return self.settings.get("prefer_local_model", False)

    def set_prefer_local_model(self, prefer: bool) -> bool:
        """Set whether to prefer local model.

        Args:
            prefer: True to prefer local model

        Returns:
            True if saved successfully
        """
        self.settings["prefer_local_model"] = prefer
        return self.save_settings(self.settings)


# Global instance
_ai_config = None


def get_ai_config() -> AIConfig:
    """Get global AI config instance.

    Returns:
        AIConfig instance
    """
    global _ai_config
    if _ai_config is None:
        _ai_config = AIConfig()
    return _ai_config
