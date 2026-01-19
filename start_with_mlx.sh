#!/bin/bash
# WritingAid startup script - Ensures correct Python with MLX

set -e  # Exit on error

cd "$(dirname "$0")"

echo "========================================================================"
echo "WritingAid Startup - MLX Version"
echo "========================================================================"
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "❌ ERROR: Virtual environment not found!"
    echo "   Expected: venv/"
    echo ""
    echo "   Please run the setup first:"
    echo "   /opt/homebrew/bin/python3.12 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Verify Python
PYTHON_VERSION=$(python --version 2>&1)
PYTHON_PATH=$(which python)

echo "✓ Python activated"
echo "  Version: $PYTHON_VERSION"
echo "  Path: $PYTHON_PATH"
echo ""

# Check for free-threaded Python
IS_FREE_THREADED=$(python -c "import sys; print('yes' if hasattr(sys, '_is_gil_enabled') else 'no')")

if [ "$IS_FREE_THREADED" = "yes" ]; then
    echo "❌ ERROR: Free-threaded Python detected!"
    echo "   This Python will NOT work with MLX and transformers."
    echo ""
    echo "   Solution: Recreate venv with regular Python 3.12"
    echo "   /opt/homebrew/bin/python3.12 -m venv venv --clear"
    exit 1
fi

# Check MLX availability
echo "🔍 Checking MLX installation..."
MLX_CHECK=$(python -c "
try:
    import mlx.core as mx
    from mlx_lm import load
    print('yes')
except ImportError:
    print('no')
" 2>&1)

if [ "$MLX_CHECK" = "yes" ]; then
    echo "✓ MLX is available"
else
    echo "❌ MLX is NOT available"
    echo "   Installing MLX..."
    pip install mlx mlx-lm
fi

echo ""
echo "========================================================================"
echo "🚀 Starting WritingAid..."
echo "========================================================================"
echo ""

# Run the application
python main.py

# Capture exit code
EXIT_CODE=$?

echo ""
echo "========================================================================"
echo "Application exited with code: $EXIT_CODE"
echo "========================================================================"

exit $EXIT_CODE
