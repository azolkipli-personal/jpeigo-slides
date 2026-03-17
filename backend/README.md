# PPTX Translator Backend

Python FastAPI backend for translating PowerPoint presentations while preserving formatting.

## Features

- **Run-level extraction**: Extracts text at the paragraph run level to preserve mid-sentence formatting
- **Style preservation**: Maintains font size, color, bold, italic, typeface
- **Spatial constraints**: Tracks text box dimensions and adjusts font size if needed
- **Vertical text support**: Handles Japanese tategaki (vertical text)
- **Multiple translation APIs**: Supports GLM-4, Kimi/Moonshot, MiniMax, Qwen, and Ollama
- **Translation memory**: Caches translations for consistency

## Quick Start

### Prerequisites

- Python 3.11+
- pip

### Installation

**Windows:**
```bash
cd backend
start.bat
```

**Linux/Mac:**
```bash
cd backend
chmod +x start.sh
./start.sh
```

### Manual Setup

```bash
# Create virtual environment
python -m venv venv

# Activate it
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your API keys

# Create directories
mkdir -p uploads outputs .translation_cache

# Start server
uvicorn app.main:app --reload --port 8000
```

## API Endpoints

### POST /api/upload

Upload a PPTX file and extract text runs.

**Request:** `multipart/form-data` with `file` field

**Response:**
```json
{  "job_id": "uuid",
  "filename": "presentation.pptx",
  "total_slides": 10,
  "total_text_boxes": 25,
  "total_runs": 150,
  "slides": [
    {
      "slide_index": 0,
      "slide_id": 256,
      "text_boxes": [
        {
          "box_id": "box_0_0",
          "shape_type": "shape",
          "runs": [
            {
              "run_id": "run_0_0_0_0",
              "text": "Hello World",
              "style": {
                "font_size": 24.0,
                "font_color": "#000000",
                "font_name": "Arial",
                "bold": true
              }
            }
          ],
          "constraints": {
            "left": 100000,
            "top": 100000,
            "width": 500000,
            "height": 50000
          }
        }
      ]
    }
  ]
}
```

### POST /api/translate

Translate extracted text runs.

**Request:**
```json
{
  "runs": [...],
  "source_language": "ja",
  "target_language": "en",
  "model": "auto"
}
```

**Response:**
```json
{
  "job_id": "uuid",
  "status": "completed",
  "progress": 100.0,
  "total_runs": 150,
  "translated_runs": [
    {
      "run_id": "run_0_0_0_0",
      "original_text": "こんにちは",
      "translated_text": "Hello",
      "source_language": "ja",
      "target_language": "en",
      "model_used": "qwen",
      "adjusted_font_size": null
    }
  ]
}
```

### POST /api/export

Export translated PPTX file.

**Request:**
```json
{
  "job_id": "uuid",
  "filename": "translated_presentation.pptx"
}
```

**Response:** Binary PPTX file download

### GET /api/health

Health check endpoint.

## Configuration

Edit `.env` file:

```env
# Translation API Keys
GLM_API_KEY=your_glm_key
KIMI_API_KEY=your_kimi_key
MINIMAX_API_KEY=your_minimax_key
MINIMAX_GROUP_ID=your_group_id
QWEN_API_KEY=your_qwen_key

# Ollama (optional)
OLLAMA_URL=http://localhost:11434

# File settings
MAX_FILE_SIZE=52428800  # 50MB
```

## Getting API Keys

### Google Gemini (FREE - Recommended)
1. Go to https://aistudio.google.com/app/apikey
2. Sign in with Google account
3. Create API key
4. Free tier: 15 requests/minute, 1500 requests/day

### OpenCode Zen/Go (Unified API)
1. Go to https://opencode.ai/auth
2. Create account
3. Subscribe to Go ($5 first month, then $10/month) or Zen (pay-as-you-go)
4. Get API key from dashboard
5. Includes: GLM-4, Kimi K2.5, MiniMax M2.5

### Qwen (Alibaba DashScope - Free Tier)
1. Go to https://dashscope.aliyun.com/
2. Create an account
3. Get API key from console
4. Free tier available with limits

### Kimi (Moonshot)
1. Go to https://platform.moonshot.cn/
2. Create an account
3. Get API key from console
4. Free credits available

### GLM-4 (Zhipu AI)
1. Go to https://open.bigmodel.cn/
2. Create an account
3. Get API key from console

### MiniMax
1. Go to https://www.minimaxi.com/
2. Create an account
3. Get API key and Group ID

### Ollama (Local)
1. Install Ollama: https://ollama.ai/
2. Pull a model: `ollama pull llama3`
3. Set OLLAMA_URL=http://localhost:11434

## Architecture

```
backend/
├── app/
│   ├── api/              # API endpoints (future)
│   ├── core/
│   │   ├── extractor.py  # PPTX text extraction
│   │   └── injector.py   # Text re-injection
│   ├── models/
│   │   └── __init__.py    # Pydantic models
│   ├── translators/
│   │   └── service.py     # Translation services
│   ├── utils/
│   │   └── cache.py       # Translation memory
│   ├── config.py          # Settings
│   └── main.py            # FastAPI app
├── uploads/               # Uploaded PPTX files
├── outputs/               # Translated PPTX files
├── .translation_cache/    # Translation memory
├── requirements.txt
├── .env.example
└── start.sh
```

## Development

### Run Tests
```bash
pytest
```

### API Documentation
Open http://localhost:8000/docs for Swagger UI

### Translation Memory
Translations are cached in `.translation_cache/translation_memory.json` for consistency across sessions.