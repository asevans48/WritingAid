"""AI integration for Writer Platform."""

# A torchvision built for another torch breaks transformers' Gemma 4
# support. The check is import-free unless the versions disagree.
try:
    from src.ai.mlx_utils import guard_torchvision_if_mismatched as _guard
    _guard()
except Exception:
    pass
