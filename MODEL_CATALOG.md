# WritingAid Model Catalog

## Cross-Platform Model Support

WritingAid now supports **automatic platform detection** and will use the best available backend:

- **Apple Silicon (M1/M2/M3/M4/M5):** MLX (fastest) → PyTorch (fallback)
- **NVIDIA GPUs:** PyTorch with CUDA
- **Intel/AMD CPUs:** PyTorch CPU

## ✅ Latest Models Available (January 2026)

### Qwen 3 Series (NEW!)

**Apple Silicon (MLX):**
- `mlx-community/Qwen3-4B-4bit` (2GB) - Fast, efficient
- `mlx-community/Qwen3-8B-4bit` (4GB) - Best balance
- `mlx-community/Qwen3-30B-A3B-4bit` (15GB) - Highest quality

**Windows/Linux (PyTorch):**
- `Qwen/Qwen3-4B` - Standard 4B model
- `Qwen/Qwen3-8B` - Standard 8B model

### Qwen 2.5 Series

**Apple Silicon (MLX) - Recommended:**
- `mlx-community/Qwen2.5-3B-Instruct-4bit` (1.6GB) - Very fast
- `mlx-community/Qwen2.5-7B-Instruct-4bit` (4GB) - **Excellent choice**
- `mlx-community/Qwen2.5-14B-Instruct-4bit` (7GB) - High quality
- `mlx-community/Qwen2.5-32B-Instruct-4bit` (17GB) - Maximum quality

**Windows/Linux (PyTorch):**
- `Qwen/Qwen2.5-3B-Instruct` (6GB)
- `Qwen/Qwen2.5-7B-Instruct` (14GB)
- `Qwen/Qwen2.5-14B-Instruct` (28GB)
- `Qwen/Qwen2.5-32B-Instruct` (64GB)

### Gemma 3 Series (NEW - Works on MLX!)

**Apple Silicon (MLX) - Now Works!**
- `mlx-community/gemma-3-4b-it-4bit` (2GB) - Fast multimodal
- `mlx-community/gemma-3-12b-it-4bit` (6GB) - High quality
- `mlx-community/gemma-3-27b-it-4bit` (14GB) - Maximum quality

**Windows/Linux (PyTorch):**
- `google/gemma-3-4b-it` (8GB)
- `google/gemma-3-12b-it` (24GB)
- `google/gemma-3-27b-it` (54GB)

**Note:** Gemma3 MLX versions work great on Apple Silicon! The original PyTorch versions had stack overflow issues, but MLX solves this.

### Mistral Series

**Apple Silicon (MLX):**
- `mlx-community/Mistral-7B-Instruct-v0.3-4bit` (4GB)
- `mlx-community/Mistral-Nemo-Instruct-2407-4bit` (7GB) - **Recommended 12B model**
- `mlx-community/Mistral-Small-Instruct-2409-4bit` (12GB) - 22B model

**Windows/Linux (PyTorch):**
- `mistralai/Mistral-7B-Instruct-v0.3` (14GB)
- `mistralai/Mistral-Nemo-Instruct-2407` (24GB)
- `mistralai/Mistral-Small-Instruct-2409` (44GB)

### Phi Series (Microsoft - Efficient Small Models)

**Apple Silicon (MLX):**
- `mlx-community/Phi-3-mini-4k-instruct-4bit` (2GB) - Very efficient 3.8B model
- `mlx-community/Phi-3.5-mini-instruct-4bit` (2GB) - Latest Phi variant

**Windows/Linux (PyTorch):**
- `microsoft/Phi-3-mini-4k-instruct` (7GB)
- `microsoft/Phi-3.5-mini-instruct` (7GB)

## Recommended Configurations

### For 8GB RAM (M1/M2 base)
**MLX:** `mlx-community/Qwen2.5-3B-Instruct-4bit` or `mlx-community/Qwen3-4B-4bit`
**PyTorch:** `Qwen/Qwen2.5-3B-Instruct`

### For 16GB RAM (M1/M2 Pro)
**MLX:** `mlx-community/Qwen2.5-7B-Instruct-4bit` or `mlx-community/Mistral-Nemo-Instruct-2407-4bit`
**PyTorch:** `Qwen/Qwen2.5-7B-Instruct` or `mistralai/Mistral-7B-Instruct-v0.3`

### For 32GB+ RAM (M3/M4/M5 Pro/Max)
**MLX:** `mlx-community/Qwen2.5-14B-Instruct-4bit` or `mlx-community/gemma-3-12b-it-4bit`
**PyTorch:** `Qwen/Qwen2.5-14B-Instruct`

### For 64GB+ RAM (M3/M4/M5 Max/Ultra)
**MLX:** `mlx-community/Qwen2.5-32B-Instruct-4bit` or `mlx-community/gemma-3-27b-it-4bit`
**PyTorch:** `Qwen/Qwen2.5-32B-Instruct`

## Automatic Model Conversion

The system automatically converts standard model IDs to their MLX equivalents on Apple Silicon:

```python
# You specify in config:
"local_model_id": "Qwen/Qwen2.5-7B-Instruct"

# On Apple Silicon, automatically becomes:
# "mlx-community/Qwen2.5-7B-Instruct-4bit"

# On Windows/Linux, uses:
# "Qwen/Qwen2.5-7B-Instruct"
```

This means you can use the same config across platforms!

## Performance Comparison

### Apple Silicon M5 32GB - Qwen 2.5-7B

| Backend | Model Size | Load Time | Memory | Speed |
|---------|-----------|-----------|--------|-------|
| **MLX** (4-bit) | 4GB | 5-10s | 7GB | 30-40 tok/s |
| PyTorch MPS (bf16) | 14GB | 20-30s | 16GB | 10-15 tok/s |

**MLX is 3-4x faster!**

### Windows NVIDIA RTX 4090 - Qwen 2.5-7B

| Backend | Model Size | Load Time | Memory | Speed |
|---------|-----------|-----------|--------|-------|
| PyTorch CUDA (fp16) | 14GB | 15-20s | 15GB | 40-60 tok/s |

## Quantization Levels

### 4-bit (Recommended for MLX)
- **Quality:** 95% of original
- **Size:** 25% of original
- **Speed:** 2-3x faster
- **Best for:** Production use

### 6-bit
- **Quality:** 97% of original
- **Size:** 37.5% of original
- **Speed:** 1.5-2x faster
- **Best for:** Quality-sensitive tasks

### 8-bit
- **Quality:** 99% of original
- **Size:** 50% of original
- **Speed:** 1.5x faster
- **Best for:** Maximum quality with compression

### bf16/fp16 (Full Precision)
- **Quality:** 100%
- **Size:** 100%
- **Speed:** 1x (baseline)
- **Best for:** Research, benchmarking

## Model Sources

All MLX models are available from the [mlx-community](https://huggingface.co/mlx-community) on Hugging Face:

- [Qwen3 Collection](https://huggingface.co/collections/mlx-community/qwen3)
- [Qwen2.5 Collection](https://huggingface.co/collections/mlx-community/qwen25)
- [Gemma 3 Collection](https://huggingface.co/collections/mlx-community/gemma-3-67d14a10480a436ad478b0f9)
- [Mistral NeMo Collection](https://huggingface.co/collections/mlx-community/mistral-nemo-66995cb884e6a96448a09597)
- [Mistral Small Collection](https://huggingface.co/collections/mlx-community/mistral-small-679ba897134af086336aba58)

## How to Change Models

### Method 1: Edit Config File
```bash
# Edit: /Users/aseva/.writer_platform/ai_config.json
"local_model_id": "mlx-community/Qwen2.5-7B-Instruct-4bit"
```

### Method 2: Use Settings Dialog (Coming Soon)
We'll add a model selector with platform-specific recommendations in the settings UI.

## Troubleshooting

### Model Not Found
- First use will auto-download from Hugging Face
- Ensure you have internet connection
- Check model ID is correct

### Out of Memory
- Use a smaller model or lower quantization
- Close other applications
- For 8GB RAM: Use 3B-4bit models
- For 16GB RAM: Use 7B-4bit models
- For 32GB RAM: Use 14B-4bit or 12B-8bit models

### Slow Performance
- On Apple Silicon: Ensure MLX is being used (check logs)
- On NVIDIA: Ensure CUDA is available
- Try a smaller model or lower quantization

### MLX Not Available
- Verify you're running in the venv: `source venv/bin/activate`
- Check MLX is installed: `pip list | grep mlx`
- Ensure you're on Apple Silicon (arm64)

## Credits

- **MLX Framework:** Apple ML Research
- **MLX-LM:** ML-Explore team
- **mlx-community:** Community-maintained model conversions
- **Model Providers:** Qwen (Alibaba), Google (Gemma), Mistral AI

---

**Last Updated:** January 2026
**WritingAid Version:** With MLX Support
