# PPTX Translator

AI-powered PowerPoint translation tool with precise formatting preservation.

## Architecture

This project uses a **hybrid architecture**:

- **Frontend**: Next.js (React) - Web UI
- **Backend**: Python FastAPI - PPTX processing & translation

## Why This Approach?

Unlike OCR-based solutions that convert PPTX to images and lose formatting, this tool:

1. **Extracts text runs** at the XML level using `python-pptx`
2. **Preserves styling**: font size, color, bold, italic, typeface
3. **Handles spatial constraints**: Adjusts font size if translated text overflows
4. **Supports vertical text**: Japanese tategaki (縦書き)
5. **Maintains mixed content**: Japanese-English text in same text box

## Quick Start

### 1. Prerequisites

- Node.js 18+ (for frontend)
- Python 3.11+ (for backend)
- API key for at least one translation service (Qwen recommended for free tier)

### 2. Start Backend

```bash
cd backend

# Windows
start.bat

# Linux/Mac
chmod +x start.sh
./start.sh
```

### 3. Configure API Keys

Edit `backend/.env`:

```env
# Recommended: Qwen (free tier available)
QWEN_API_KEY=your_qwen_api_key

# Alternative options:
KIMI_API_KEY=your_kimi_key         # Moonshot AI
GLM_API_KEY=your_glm_key           # Zhipu AI
MINIMAX_API_KEY=your_minimax_key   # MiniMax
OLLAMA_URL=http://localhost:11434  # Local Ollama
```

###4. Start Frontend

```bash
cd ..
npm install
npm run dev
```

### 5. Open Browser

- Original UI (OCR-based): http://localhost:3000
- New UI (python-pptx): http://localhost:3000/translator

## API Keys

### Qwen (Recommended for Free Tier)
1. Go to https://dashscope.aliyun.com/
2. Create account
3. Get API key from console
4. Free tier includes monthly credits

### Kimi/Moonshot
1. Go to https://platform.moonshot.cn/
2. Create account
3. Get API key

### GLM-4 (Zhipu AI)
1. Go to https://open.bigmodel.cn/
2. Create account
3. Get API key

## Features

### Formatting Preservation
- Font size, color, typeface
- Bold, italic, underline
- Text box positioning
- Vertical text (tategaki)
- Mixed Japanese-English content

### Translation Memory
- Caches translations for consistency
- Terminology consistency across slides/files
- Editable translations in review interface

### Workflow
1. Upload PPTX → Extract text runs with formatting
2. Configure translation settings
3. Review and edit translations
4. Export translated PPTX with preserved styling

## Project Structure

```
powerpoint-translator/
├── backend/                    # Python FastAPI backend
│   ├── app/
│   │   ├── core/
│   │   │   ├── extractor.py    # Text run extraction
│   │   │   └── injector.py     # Text re-injection
│   │   ├── models/             # Pydantic models
│   │   ├── translators/
│   │   │   └── service.py      # Translation APIs
│   │   ├── utils/
│   │   │   └── cache.py        # Translation memory
│   │   ├── config.py           # Settings
│   │   └── main.py             # FastAPI app
│   ├── requirements.txt
│   ├── .env.example
│   └── start.sh / start.bat
│
├── app/                        # Next.js frontend
│   ├── api/
│   │   ├── upload-new/         # Upload route
│   │   ├── translate-new/     # Translate route
│   │   └── export-new/        # Export route
│   ├── translator/
│   │   └── page.tsx            # New translation UI
│   └── page.tsx               # Original UI (OCR)
│
├── components/                 # React components
├── public/
├── package.json
└── README.md
```

## API Endpoints

### Backend (FastAPI - Port 8000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload` | POST | Upload PPTX, extract text runs |
| `/api/translate` | POST | Translate extracted text |
| `/api/export` | POST | Export translated PPTX |
| `/api/health` | GET | Health check |
| `/api/cache` | GET/DELETE | Translation memory |

### Frontend (Next.js - Port 3000)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload-new` | POST | Proxy to backend |
| `/api/translate-new` | POST | Proxy to backend |
| `/api/export-new` | POST | Proxy to backend |

## Configuration

### Backend (.env)

```env
# API Keys
QWEN_API_KEY=your_key
KIMI_API_KEY=your_key
GLM_API_KEY=your_key
MINIMAX_API_KEY=your_key

# Ollama (local)
OLLAMA_URL=http://localhost:11434

# File settings
MAX_FILE_SIZE=52428800  # 50MB
```

### Frontend (.env.local)

```env
PYTHON_BACKEND_URL=http://localhost:8000
```

## Troubleshooting

### Backend not starting
```bash
# Check Python version
python --version  # Should be 3.11+

# Install dependencies manually
pip install -r backend/requirements.txt

# Run manually
cd backend
uvicorn app.main:app --reload --port 8000
```

### Translation errors
1. Check API keys in `.env`
2. Check backend health: http://localhost:8000/api/health
3. Check backend logs for error details

### Font overflow warnings
The tool automatically adjusts font size when translated text exceeds text box dimensions. Check the review interface for warnings.

## Development

### Run Backend Tests
```bash
cd backend
pytest
```

### Run Frontend Tests
```bash
npm test
```

### API Documentation
Backend Swagger UI: http://localhost:8000/docs

## License

MIT