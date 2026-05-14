# PPTX Translator

## Why

Translating PowerPoint presentations is genuinely painful. The standard approach — export to images, run OCR, translate text, paste back — destroys your formatting. Font sizes break. Colors shift. Text boxes overflow. Vertical Japanese text (tategaki) gets mangled. If you're localising a corporate deck with 50+ slides, every round of manual fixes costs hours. And the result still looks off. This problem hits anyone who works across Japanese and English in a business context: sales teams, marketing, product managers, consultants.

## What

PPTX Translator translates PowerPoint files while preserving formatting — font sizes, colors, bold/italic/underline, text box positions, and even vertical Japanese text. It works at the XML level inside the `.pptx` file, extracting and re-injecting translated text runs without touching the layout. No OCR hacks, no image-based workarounds, no reformatting hell.

The impact: what used to take hours per deck now takes minutes. Upload → review → export. The translated PPTX comes out looking like the original, just in a different language.

## Features

- **XML-level text extraction** — Reads text runs directly from the PPTX structure using python-pptx
- **Full formatting preservation** — Font size, color, typeface, bold, italic, underline, text box positioning
- **Vertical text support** — Handles Japanese tategaki (縦書き) correctly
- **Spatial awareness** — Auto-adjusts font size when translated text overflows the text box
- **Mixed-language content** — Preserves mixed Japanese-English within the same text box
- **Translation memory** — Caches translations for consistency across slides and files
- **Review interface** — Preview and edit translations before export
- **Multi-provider** — Works with Qwen, Kimi, GLM, MiniMax, or local Ollama models

## Quick Start

### Prerequisites
- Node.js 18+
- Python 3.11+
- API key for at least one translation service (Qwen has a free tier)

### Start Backend
```bash
cd backend
chmod +x start.sh && ./start.sh   # Linux/Mac
# Or: start.bat                     # Windows
```

### Configure API Keys
Edit `backend/.env` and add your keys:
```env
QWEN_API_KEY=your_key_here
```

### Start Frontend
```bash
npm install
npm run dev
```

Open http://localhost:3000/translator

## Tech Stack

- **Frontend**: Next.js 16, React 19, Tailwind CSS
- **Backend**: Python FastAPI, python-pptx
- **Translation**: Qwen, Kimi (Moonshot), GLM-4 (Zhipu), MiniMax, Ollama (local)
- **OCR** (legacy mode): Google Cloud Vision, Tesseract.js
- **Export**: pptxgenjs, Canvas API

## License

MIT
