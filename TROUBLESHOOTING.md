# ⚠️ IMPORTANT: How to Run WritingAid

## ❌ Wrong Way (Will Cause Errors)

```bash
# DON'T run with system Python
python main.py          # ❌ Uses system Python
python3 main.py         # ❌ Uses system Python
/usr/local/bin/python3 main.py  # ❌ Uses Python 3.14 free-threaded
```

**These will fail with errors like:**
- "ignore_mismatched_sizes" error
- Stack overflow errors
- MLX not available
- Wrong Python version

## ✅ Correct Way

### Option 1: Use the startup script (Recommended)
```bash
./run.sh
```

### Option 2: Manual activation
```bash
source venv/bin/activate
python main.py
```

### Option 3: Direct venv Python
```bash
venv/bin/python main.py
```

## How to Verify You're Using the Right Python

Before running, check:
```bash
source venv/bin/activate
python --version          # Should show: Python 3.12.12
python -c "import sys; print('Free-threaded:', hasattr(sys, '_is_gil_enabled'))"
# Should show: Free-threaded: False
```

## If Running from IDE (VS Code, PyCharm, etc.)

Configure your IDE to use the virtual environment Python:

### VS Code
1. Open Command Palette (Cmd+Shift+P)
2. Type "Python: Select Interpreter"
3. Choose: `./venv/bin/python` (Python 3.12.12)

### PyCharm
1. Go to: Settings → Project → Python Interpreter
2. Click gear icon → Add → Existing Environment
3. Select: `/Users/aseva/gitcode/WritingAid/venv/bin/python`

## Why This Matters

Your system has **three different Python installations**:
1. **System Python 3.9.6** (`/usr/bin/python3`) - Too old, missing MLX
2. **Python 3.14 free-threaded** (`/usr/local/bin/python3`) - Causes stack overflows
3. **Venv Python 3.12.12** (`venv/bin/python`) - ✅ Correct one with MLX

The app **MUST** use Python 3.12 from the venv for local models to work!

## Quick Fix for Current Error

If you're seeing "ignore_mismatched_sizes" error:

1. **Close the app completely**
2. **Run from terminal:**
   ```bash
   cd /Users/aseva/gitcode/WritingAid
   ./run.sh
   ```
3. **Try rephrasing again with "Local SLM"**

## How to Check Which Python the App Is Using

When the app starts, check the console output:
```
[MODULE INIT] ✓ MLX available - using Apple Silicon optimized inference
```

If you see this, you're using the correct Python!

If you see errors or warnings, you're using the wrong Python.

---

**TL;DR: Always run with `./run.sh` or `source venv/bin/activate` first!**
