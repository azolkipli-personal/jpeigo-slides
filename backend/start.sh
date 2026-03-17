#!/bin/bash
# PPTX Translator BackendStartup Script

echo"Starting PPTX Translator Backend..."

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python -m venv venv
fi

# Activate virtual environment
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Create necessary directories
mkdir -p uploads outputs .translation_cache

# Copy .env.example to .env if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "Please edit .env and add your API keys!"
fi

# Start the server
echo "Starting FastAPI server on port 8000..."
uvicorn app.main:app --reload --port8000 --host 0.0.0.0