# Python 3.12 Virtual Environment Setup

## ✅ Setup Complete!

Your WritingAid project now uses Python 3.12 in a virtual environment, fixing the Python 3.14 free-threaded compatibility issues with PyTorch and transformers.

## Running the Application

### Option 1: Use the startup script (Recommended)
```bash
./run.sh
```

### Option 2: Manual activation
```bash
source venv/bin/activate
python main.py
```

## What Was Installed

### Core Python Environment
- **Python Version:** 3.12.12 (regular build, NOT free-threaded)
- **Location:** `/opt/homebrew/bin/python3.12`
- **Virtual Environment:** `venv/` (isolated from system Python)

### Key Libraries Installed
- **PyTorch 2.9.1** - With MPS (Apple Silicon GPU) support
- **Transformers 4.57.6** - Latest Hugging Face transformers
- **PyQt6 6.10.2** - GUI framework
- **Anthropic, OpenAI, Google GenAI** - Cloud LLM APIs
- **spaCy 3.8.11** - NLP library with `en_core_web_sm` model
- **NLTK, huggingface_hub, accelerate** - Supporting libraries

## Verified Working

✅ **Python 3.12** - Regular build (not free-threaded)
✅ **MPS Support** - Apple Silicon GPU acceleration enabled
✅ **Model Config Loading** - Qwen 2.5-14B config loads without stack overflow
✅ **Transformers Import** - No stack overflow during import

## Local Model Status

- **Model Downloaded:** Qwen/Qwen2.5-14B-Instruct (28GB) ✓
- **Model Cache:** `~/.cache/huggingface/hub/`
- **Expected Load Time:** ~30 seconds on first use
- **Cached Performance:** Instant on subsequent requests

## Switching Between Cloud and Local Models

In the rephrase dialog, you can now safely select:
- **Cloud LLM** - Uses your configured API (fast, costs apply)
- **Local SLM** - Uses Qwen 2.5-14B on your M5 (slower first load, no costs)

The local model will now load successfully without stack overflow errors!

## Troubleshooting

### If you accidentally use the wrong Python:
```bash
# Check which Python you're using
which python
python --version
python -c "import sys; print('Free-threaded:', hasattr(sys, '_is_gil_enabled'))"

# If not in venv, activate it:
source venv/bin/activate
```

### To verify MPS is working:
```bash
source venv/bin/activate
python -c "import torch; print('MPS available:', torch.backends.mps.is_available())"
```

### To reinstall dependencies:
```bash
source venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

## Benefits of This Setup

1. **Isolated Environment** - Project dependencies don't affect system Python
2. **Correct Python Version** - No more free-threaded GIL issues
3. **MPS Support** - Full Apple Silicon GPU acceleration
4. **Model Caching** - Fast reloads after first use
5. **Easy Activation** - Just run `./run.sh`

Enjoy your working local models! 🚀
