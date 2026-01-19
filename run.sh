#!/bin/bash
# WritingAid startup script with Python 3.12 virtual environment

cd "$(dirname "$0")"

# Activate virtual environment
source venv/bin/activate

# Verify Python version
echo "Using Python: $(python --version)"
echo "Location: $(which python)"
echo ""

# Run the application
python main.py
