"""MLX utilities for Apple Silicon optimized inference."""

import platform


def is_apple_silicon():
    """Check if running on Apple Silicon (M-series chips)."""
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def can_use_mlx():
    """Check if MLX is available and should be used."""
    if not is_apple_silicon():
        return False

    try:
        return True
    except ImportError:
        return False


def get_mlx_info():
    """Get MLX availability information."""
    info = {
        "platform": platform.system(),
        "machine": platform.machine(),
        "is_apple_silicon": is_apple_silicon(),
        "mlx_available": False,
        "mlx_version": None,
    }

    if can_use_mlx():
        try:
            info["mlx_available"] = True
            # MLX doesn't have __version__, just confirm it's importable
            info["mlx_version"] = "installed"
        except (ImportError, AttributeError):
            pass

    return info


def print_mlx_info():
    """Print MLX information for debugging."""
    info = get_mlx_info()

    print("=" * 60)
    print("MLX (Apple ML Framework) Information")
    print("=" * 60)
    print(f"Platform: {info['platform']}")
    print(f"Machine: {info['machine']}")
    print(f"Apple Silicon: {info['is_apple_silicon']}")
    print(f"MLX Available: {info['mlx_available']}")

    if info['mlx_available']:
        print(f"MLX Version: {info['mlx_version']}")
        print("\n✓ MLX is available - using optimized Apple Silicon inference")
    else:
        print("\n✗ MLX not available - falling back to PyTorch")

    print("=" * 60)


class MLXModelCache:
    """Singleton cache for MLX models."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._model = None
            cls._instance._tokenizer = None
            cls._instance._model_id = None
        return cls._instance

    def get_model(self, model_id: str):
        """Get cached MLX model if it matches the requested model_id."""
        if self._model is not None and self._model_id == model_id:
            return self._model, self._tokenizer
        return None, None

    def set_model(self, model_id: str, model, tokenizer):
        """Cache a loaded MLX model."""
        # Unload previous model if different
        if self._model is not None and self._model_id != model_id:
            self._unload_model()

        self._model = model
        self._tokenizer = tokenizer
        self._model_id = model_id
        print(f"MLX model cached: {model_id}")

    def _unload_model(self):
        """Unload the current MLX model from memory."""
        if self._model is not None:
            print(f"Unloading previous MLX model: {self._model_id}")
            del self._model
            del self._tokenizer
            self._model = None
            self._tokenizer = None
            self._model_id = None

    def is_loaded(self, model_id: str = None) -> bool:
        """Check if a model is loaded."""
        if model_id is None:
            return self._model is not None
        return self._model is not None and self._model_id == model_id


# Global MLX model cache
_mlx_cache = MLXModelCache()


def get_mlx_cache() -> MLXModelCache:
    """Get the global MLX model cache instance."""
    return _mlx_cache
