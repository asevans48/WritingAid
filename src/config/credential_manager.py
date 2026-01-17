"""Secure credential storage using system keyring (Windows Credential Manager)."""

import keyring
from typing import Optional


# Service name for the application in the credential store
SERVICE_NAME = "WriterPlatform"


class CredentialManager:
    """Manage secure storage of API keys and credentials.

    Uses the system keyring (Windows Credential Manager on Windows,
    Keychain on macOS, Secret Service on Linux).
    """

    # Credential keys
    HUGGINGFACE_TOKEN = "huggingface_token"
    CLAUDE_API_KEY = "claude_api_key"
    OPENAI_API_KEY = "openai_api_key"
    GEMINI_API_KEY = "gemini_api_key"

    def __init__(self, service_name: str = SERVICE_NAME):
        """Initialize credential manager.

        Args:
            service_name: Service name for credential storage
        """
        self.service_name = service_name

    def store_credential(self, key: str, value: str) -> bool:
        """Store a credential securely.

        Args:
            key: Credential identifier (e.g., 'huggingface_token')
            value: The credential value to store

        Returns:
            True if stored successfully, False otherwise
        """
        if not value:
            # Don't store empty values, delete instead
            return self.delete_credential(key)

        try:
            keyring.set_password(self.service_name, key, value)
            return True
        except Exception as e:
            print(f"Failed to store credential '{key}': {e}")
            return False

    def get_credential(self, key: str) -> Optional[str]:
        """Retrieve a credential from secure storage.

        Args:
            key: Credential identifier

        Returns:
            Credential value or None if not found
        """
        try:
            return keyring.get_password(self.service_name, key)
        except Exception as e:
            print(f"Failed to retrieve credential '{key}': {e}")
            return None

    def delete_credential(self, key: str) -> bool:
        """Delete a credential from secure storage.

        Args:
            key: Credential identifier

        Returns:
            True if deleted (or didn't exist), False on error
        """
        try:
            keyring.delete_password(self.service_name, key)
            return True
        except keyring.errors.PasswordDeleteError:
            # Credential doesn't exist, that's fine
            return True
        except Exception as e:
            print(f"Failed to delete credential '{key}': {e}")
            return False

    def has_credential(self, key: str) -> bool:
        """Check if a credential exists.

        Args:
            key: Credential identifier

        Returns:
            True if credential exists, False otherwise
        """
        return self.get_credential(key) is not None

    # Convenience methods for specific credentials

    def store_huggingface_token(self, token: str) -> bool:
        """Store Hugging Face API token."""
        return self.store_credential(self.HUGGINGFACE_TOKEN, token)

    def get_huggingface_token(self) -> Optional[str]:
        """Get Hugging Face API token."""
        return self.get_credential(self.HUGGINGFACE_TOKEN)

    def store_api_key(self, provider: str, api_key: str) -> bool:
        """Store API key for a provider.

        Args:
            provider: Provider name (claude, openai, gemini)
            api_key: The API key

        Returns:
            True if stored successfully
        """
        key_map = {
            "claude": self.CLAUDE_API_KEY,
            "openai": self.OPENAI_API_KEY,
            "chatgpt": self.OPENAI_API_KEY,
            "gemini": self.GEMINI_API_KEY,
        }
        key = key_map.get(provider.lower())
        if key:
            return self.store_credential(key, api_key)
        return False

    def get_api_key(self, provider: str) -> Optional[str]:
        """Get API key for a provider.

        Args:
            provider: Provider name (claude, openai, gemini)

        Returns:
            API key or None
        """
        key_map = {
            "claude": self.CLAUDE_API_KEY,
            "openai": self.OPENAI_API_KEY,
            "chatgpt": self.OPENAI_API_KEY,
            "gemini": self.GEMINI_API_KEY,
        }
        key = key_map.get(provider.lower())
        if key:
            return self.get_credential(key)
        return None


# Global instance
_credential_manager: Optional[CredentialManager] = None


def get_credential_manager() -> CredentialManager:
    """Get global credential manager instance.

    Returns:
        CredentialManager instance
    """
    global _credential_manager
    if _credential_manager is None:
        _credential_manager = CredentialManager()
    return _credential_manager
