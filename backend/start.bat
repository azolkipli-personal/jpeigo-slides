@echo off
REM PPTX Translator Backend Startup Script for Windows

echo Starting PPTX Translator Backend...

REM Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

REM Create necessary directories
if not exist "uploads" mkdir uploads
if not exist "outputs" mkdir outputs
if not exist ".translation_cache" mkdir .translation_cache

REM Copy .env.example to .env if it doesn't exist
if not exist ".env" (
    echo Creating .env file from .env.example...
    copy .env.example .env
    echo Please edit .env and add your API keys!
)

REM Start the server
echo Starting FastAPI server on port 8000...
uvicorn app.main:app --reload --port8000 --host 0.0.0.0