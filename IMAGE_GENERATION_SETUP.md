# Image Generation Setup Guide

WritingAid supports AI-powered image generation for character portraits, cover art, and scene visualization.

## Prerequisites

Image generation requires additional dependencies based on your hardware.

## Installation by Platform

### Apple Silicon (M1/M2/M3/M4/M5 Macs)

**Recommended: Use MFLUX for optimal performance on Apple Silicon**

```bash
# Activate your virtual environment first
source venv/bin/activate

# Install MFLUX (MLX-based FLUX models)
pip install mflux

# If MLX is not already installed
pip install mlx mlx-lm
```

**Why MFLUX?**
- 3-4x faster than PyTorch on Apple Silicon
- Lower memory usage (4-bit quantization)
- Native unified memory architecture support
- No CUDA required

**Supported Models:**
- FLUX Dev 4-bit (High quality, 10GB VRAM)
- FLUX Schnell 4-bit (Fast, 6GB VRAM)
- Stable Diffusion XL (General purpose, 8GB VRAM)

### Windows/Linux with NVIDIA GPU

```bash
# Activate your virtual environment first
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Install Diffusers and dependencies
pip install diffusers accelerate transformers

# Make sure you have PyTorch with CUDA support
# Check your CUDA version first: nvidia-smi
# Then install PyTorch for your CUDA version (see requirements.txt for details)
pip install torch --index-url https://download.pytorch.org/whl/cu121  # CUDA 12.1
```

**Supported Models:**
- FLUX.1 Dev 12B (Highest quality, 20GB VRAM)
- FLUX.1 Schnell 12B (Fast high-quality, 16GB VRAM)
- Stable Diffusion XL (General purpose, 12GB VRAM)

### CPU-Only (Any Platform)

You can use CPU for image generation, but it will be slower:

```bash
pip install diffusers transformers
```

**Note:** CPU generation takes 5-10x longer than GPU/MLX. Consider using cloud providers instead.

### Cloud-Based (No Local Hardware Required)

Use OpenAI DALL-E 3 - no additional installation needed!

Just configure your OpenAI API key in Settings → API Keys.

## Configuration

1. **Open WritingAid**
2. **Go to Settings** (gear icon or File → Settings)
3. **Navigate to "🎨 Image Generation" tab**
4. **Configure:**
   - **Image Model**: Select appropriate model for your hardware
   - **Prompt Enhancement**: Choose LLM for enhancing prompts (local or cloud)
   - **Image Settings**: Adjust size, steps, guidance scale
   - **Character Context**: Enable to use character backstory in generation

## Quick Start

### Generate a Character Portrait

1. Go to **Characters** tab and create/edit a character
2. Add a **Physical Description** (e.g., "Tall elven warrior with silver hair and green eyes, wearing ornate armor")
3. Go to **Visuals** tab
4. Select **"Character Portrait"** as image type
5. Choose your character from the dropdown
6. (Optional) Add style preferences (e.g., "fantasy art style, digital painting")
7. Click **"Generate Image"**

The system will:
- Pull character's physical description, personality, and backstory
- Enhance the prompt using an LLM (if enabled)
- Generate the image using your configured model
- Save it to your project

### Generate Cover Art or Scenes

1. Go to **Visuals** tab
2. Select **"Cover Art"** or **"Scene Visualization"**
3. Enter a description
4. (Optional) Add style preferences
5. Click **"Generate Image"**

## Troubleshooting

### "MFLUX not installed" on Mac

```bash
source venv/bin/activate
pip install mflux
```

### "No module named 'diffusers'" on Windows/Linux

```bash
pip install diffusers accelerate transformers
```

### Out of Memory Errors

**On Mac:**
- Use smaller models (Schnell instead of Dev)
- Try 4-bit quantization models
- Close other applications

**On NVIDIA GPU:**
- Use smaller models or enable CPU offloading
- Reduce image size or inference steps in settings
- Check VRAM usage: `nvidia-smi`

### Slow Generation

**On Mac:**
- Ensure MFLUX is installed and being used (check logs)
- Verify MLX backend: `pip list | grep mlx`

**On NVIDIA:**
- Ensure CUDA version matches PyTorch: `nvidia-smi` and `python -c "import torch; print(torch.version.cuda)"`
- Use Schnell variant for faster generation

### Image Quality Issues

1. **Increase inference steps** (20-50 steps)
2. **Adjust guidance scale** (7.5-12.0)
3. **Use prompt enhancement** (enable in settings)
4. **Add more details** to character physical descriptions
5. **Try different models** (FLUX Dev for quality, SDXL for variety)

## Model Recommendations by RAM

### 8GB RAM (M1/M2 Base)
- FLUX Schnell 4-bit
- Stable Diffusion 2.1

### 16GB RAM (M1/M2 Pro)
- FLUX Dev 4-bit
- SDXL 1.0

### 32GB+ RAM (M3/M4/M5 Pro/Max)
- FLUX Dev 4-bit (best quality)
- Any model works well

### NVIDIA RTX 3060 (12GB VRAM)
- FLUX Schnell
- SDXL 1.0

### NVIDIA RTX 4090 (24GB VRAM)
- FLUX.1 Dev 12B (highest quality)
- Any model works

## Performance Tips

1. **First generation is slow**: Models need to download (10-20GB)
2. **Subsequent generations are faster**: Models are cached
3. **Use 4-bit quantization on Mac**: 75% smaller, 95% quality, 3x faster
4. **Enable prompt enhancement**: Better prompts = better images
5. **Batch multiple images**: Generate several at once with different seeds

## Advanced Configuration

### Custom Model Paths

Edit `~/.writer_platform/genai_config.json`:

```json
{
  "image_model_id": "your-custom-model-id",
  "image_output_dir": "/custom/path/to/images"
}
```

### Negative Prompts

Default negative prompt prevents common issues. Customize in settings:
- "blurry, low quality, distorted, deformed, ugly, bad anatomy"

### Seed Control

Set a specific seed in `genai_config.json` for reproducible results:
```json
{
  "image_seed": 42
}
```

Set to `-1` for random seeds.

## Getting Help

- Check logs for detailed error messages
- Report issues: https://github.com/anthropics/claude-code/issues
- See `MODEL_CATALOG.md` for complete model list

---

**Last Updated:** January 2026
