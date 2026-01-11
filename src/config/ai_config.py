"""AI configuration management with persistent storage."""

import json
from pathlib import Path
from typing import Dict, Any
import os


class AIConfig:
    """Manage AI configuration with persistent storage."""

    DEFAULT_SETTINGS = {
        # API Keys
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
        "enable_caching": True
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

    def is_feature_enabled(self, feature: str) -> bool:
        """Check if a specific AI feature is enabled.

        Args:
            feature: Feature name (chat, character_gen, plot_suggestions, etc.)

        Returns:
            True if feature is enabled, False otherwise
        """
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
