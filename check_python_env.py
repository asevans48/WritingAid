"""Diagnostic script to check Python environment and packages."""

import sys
import os

print("=" * 70)
print("PYTHON ENVIRONMENT DIAGNOSTIC")
print("=" * 70)

print(f"\nPython Executable: {sys.executable}")
print(f"Python Version: {sys.version}")
print(f"Virtual Environment: {sys.prefix}")

print(f"\nPython Path:")
for i, path in enumerate(sys.path[:10], 1):
    print(f"  {i}. {path}")

print(f"\n{'=' * 70}")
print("PACKAGE AVAILABILITY")
print("=" * 70)

# Check torch
try:
    import torch
    print(f"\n[OK] PyTorch: {torch.__version__}")
    print(f"  Location: {torch.__file__}")
    print(f"  CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"  CUDA version: {torch.version.cuda}")
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
except ImportError as e:
    print(f"\n[FAIL] PyTorch: NOT AVAILABLE")
    print(f"  Error: {e}")

# Check transformers
try:
    import transformers
    print(f"\n[OK] Transformers: {transformers.__version__}")
    print(f"  Location: {transformers.__file__}")
except ImportError as e:
    print(f"\n[FAIL] Transformers: NOT AVAILABLE")
    print(f"  Error: {e}")

# Check PyQt6
try:
    from PyQt6.QtCore import QT_VERSION_STR
    print(f"\n[OK] PyQt6: {QT_VERSION_STR}")
except ImportError as e:
    print(f"\n[FAIL] PyQt6: NOT AVAILABLE")
    print(f"  Error: {e}")

print(f"\n{'=' * 70}")
print("RUN THIS SCRIPT WITH:")
print("=" * 70)
print("1. System Python: python check_python_env.py")
print("2. Venv Python: .venv\\Scripts\\python.exe check_python_env.py")
print("3. How app runs: <check how you launch the app>")
print("=" * 70)
