"""Test importing rephrasing_agent to see module-level import messages."""

import sys
print(f"Python: {sys.executable}")
print(f"Version: {sys.version}")
print()

print("="*70)
print("ATTEMPTING TO IMPORT REPHRASING_AGENT")
print("="*70)
print()

# This should trigger the module-level imports and show [MODULE INIT] messages
from src.ai import rephrasing_agent

print()
print("="*70)
print("IMPORT SUCCESSFUL")
print("="*70)
print()

print(f"_TORCH_AVAILABLE: {rephrasing_agent._TORCH_AVAILABLE}")
print(f"_TRANSFORMERS_AVAILABLE: {rephrasing_agent._TRANSFORMERS_AVAILABLE}")
print(f"_MLX_AVAILABLE: {rephrasing_agent._MLX_AVAILABLE}")
