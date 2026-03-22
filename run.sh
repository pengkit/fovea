#!/bin/bash
# Fovea - Quick Start

set -e

cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "Error: python3 not found"
    exit 1
fi

# Create venv if not exists
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Install base dependencies
echo "Installing dependencies..."
pip install -q fastapi uvicorn pillow httpx

# Optional: install extra packages
echo ""
echo "Optional packages for full functionality:"
echo "  pip install rawpy          # RAW file support"
echo "  pip install opencv-python  # Blur/exposure detection"
echo "  pip install imagehash      # Duplicate detection"
echo "  pip install face-recognition # Face recognition (needs dlib)"
echo ""

# Create data directories
mkdir -p data thumbnails static

echo "Starting Fovea on http://localhost:8080"
echo "Press Ctrl+C to stop"
echo ""

python3 main.py
