"""Cross-platform device detection utilities for PyTorch models."""


def detect_device():
    """
    Detect the best available device for PyTorch model inference.

    Returns:
        tuple: (device_name, dtype, use_device_map)
            - device_name: "cuda", "mps", or "cpu"
            - dtype: torch dtype (bfloat16, float16, or float32)
            - use_device_map: bool, whether to use device_map="auto"

    Priority order:
    1. CUDA (NVIDIA GPUs) - best for quantization
    2. MPS (Apple Silicon) - M1/M2/M3/M4/M5 Macs
    3. CPU - fallback
    """
    try:
        import torch

        mps_available = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()
        cuda_available = torch.cuda.is_available()

        if cuda_available:
            # NVIDIA GPU - use float16 and device_map for multi-GPU support
            return "cuda", torch.float16, True
        elif mps_available:
            # Apple Silicon - use bfloat16 (better range than float16)
            # Don't use device_map on MPS to avoid stack overflow
            return "mps", torch.bfloat16, False
        else:
            # CPU fallback - use float32 for compatibility
            # Print a warning if CUDA might be expected but not available
            _print_cuda_warning()
            return "cpu", torch.float32, False

    except ImportError:
        # PyTorch not installed, default to CPU
        return "cpu", None, False


def _print_cuda_warning():
    """Print a warning if CUDA is not available but might be expected."""
    import platform
    import subprocess

    # Only warn on Windows/Linux where CUDA GPUs are common
    if platform.system() == "Darwin":
        return  # macOS uses MPS, not CUDA

    try:
        # Check if nvidia-smi exists (indicates NVIDIA GPU present)
        if platform.system() == "Windows":
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
        else:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )

        if result.returncode == 0 and result.stdout.strip():
            gpu_name = result.stdout.strip().split('\n')[0]
            print("\n" + "=" * 70)
            print("⚠️  WARNING: NVIDIA GPU detected but CUDA is not available in PyTorch!")
            print("=" * 70)
            print(f"  GPU Found: {gpu_name}")
            print(f"  PyTorch CUDA: torch.cuda.is_available() = False")
            print()
            print("  This usually means PyTorch was installed without CUDA support.")
            print("  The default 'pip install torch' gets CPU-only on Windows/Linux!")
            print()
            print("  To fix this, reinstall PyTorch with CUDA:")
            print("    1. pip uninstall torch torchvision torchaudio -y")
            print("    2. pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124")
            print()
            print("  (Replace cu124 with cu131 for CUDA 13.1, or cu118 for CUDA 11.8)")
            print("  Visit https://pytorch.org/get-started/locally/ for the correct command.")
            print("=" * 70 + "\n")
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        # nvidia-smi not found or other error - no warning needed
        pass


def can_use_quantization(device_name=None):
    """
    Check if quantization (4-bit/8-bit) is supported on the current device.

    Args:
        device_name: Optional device name. If None, auto-detects.

    Returns:
        bool: True if quantization is supported (CUDA only)

    Note:
        BitsAndBytes quantization only works with CUDA GPUs.
        Apple Silicon (MPS) and CPU don't support BitsAndBytes.
    """
    if device_name is None:
        device_name, _, _ = detect_device()

    # Only CUDA supports BitsAndBytes quantization
    return device_name == "cuda"


def get_device_info():
    """
    Get detailed information about available devices.

    Returns:
        dict: Device information including availability and capabilities
    """
    try:
        import torch

        info = {
            "cuda_available": torch.cuda.is_available(),
            "mps_available": hasattr(torch.backends, 'mps') and torch.backends.mps.is_available(),
            "pytorch_version": torch.__version__,
            "cuda_version": torch.version.cuda if torch.cuda.is_available() else None,
            "quantization_supported": False,
        }

        if info["cuda_available"]:
            info["cuda_device_count"] = torch.cuda.device_count()
            info["cuda_device_name"] = torch.cuda.get_device_name(0)
            info["quantization_supported"] = True

        # Determine recommended device
        if info["cuda_available"]:
            info["recommended_device"] = "cuda"
        elif info["mps_available"]:
            info["recommended_device"] = "mps"
        else:
            info["recommended_device"] = "cpu"

        return info

    except ImportError:
        return {
            "cuda_available": False,
            "mps_available": False,
            "pytorch_version": None,
            "recommended_device": "cpu",
            "quantization_supported": False,
        }


def print_device_info():
    """Print device information to console for debugging."""
    info = get_device_info()

    print("=" * 60)
    print("PyTorch Device Information")
    print("=" * 60)
    print(f"PyTorch Version: {info.get('pytorch_version', 'Not installed')}")
    print(f"CUDA Available: {info['cuda_available']}")

    if info["cuda_available"]:
        print(f"  - CUDA Version (PyTorch built with): {info.get('cuda_version')}")
        print(f"  - GPU Count: {info.get('cuda_device_count')}")
        print(f"  - GPU Name: {info.get('cuda_device_name')}")
    else:
        # Show what PyTorch was built with
        try:
            import torch
            cuda_build = getattr(torch.version, 'cuda', None)
            if cuda_build:
                print(f"  - PyTorch CUDA build: {cuda_build} (but runtime unavailable)")
            else:
                print(f"  - PyTorch CUDA build: None (CPU-only build!)")
        except Exception:
            pass

    print(f"MPS (Apple Silicon) Available: {info['mps_available']}")
    print(f"Quantization Supported: {info['quantization_supported']}")
    print(f"Recommended Device: {info['recommended_device']}")
    print("=" * 60)
