# jpeigo-slides | PPTX Translator

> **XML-level PowerPoint translation** — translate `.pptx` files while preserving every pixel of formatting. Built for Japanese ↔ English localisation.

<p align="center">
  <a href="https://github.com/sponsors/azolkipli-personal">
    <img src="https://img.shields.io/badge/Sponsor-%E2%9D%A4%EF%B8%8F%20jpeigo--slides-DB61A2?style=for-the-badge&logo=github&logoColor=white" alt="Sponsor jpeigo-slides">
  </a>
</p>

Translate corporate decks, proposals, and presentations without the usual reformatting nightmare. No OCR. No image hacks. No broken layouts.

---

## Why This Exists

Translating PowerPoint presentations is genuinely painful. The standard approach — export to images, run OCR, translate, paste back — destroys your formatting. Font sizes break. Colors shift. Text boxes overflow. Japanese vertical text (tategaki) gets mangled. If you're localising a corporate deck with 50+ slides, every round of manual fixes costs hours.

**jpeigo-slides** works at the XML level inside the `.pptx` file, extracting text runs and re-injecting translated text without touching the layout. The result: a translated file that looks like the original, just in a different language.

---

## Features

- **XML-level text extraction** — Reads text runs directly from the PPTX structure via `python-pptx`
- **Full formatting preservation** — Font size, color, typeface, bold, italic, underline, text box positioning
- **SmartArt / Diagram support** — Extracts and injects text from SmartArt diagrams (slides with `<dgm:pt>` elements)
- **Table support** — Handles text within table cells
- **Grouped shapes** — Recursive traversal of nested shape groups
- **Vertical Japanese text** — Correctly handles tategaki (縦書き)
- **Spatial awareness** — Auto-adjusts font size when translated text overflows its text box
- **Translation memory** — Caches translations for consistency across slides and sessions
- **Review interface** — Preview and edit translations before downloading
- **Preview images** — Renders translated slides as PNG via LibreOffice + pdftoppm (with disk caching)
- **Multi-provider** — Gemini, OpenCode (DeepSeek / Kimi / Qwen / MiniMax), Google Cloud, GLM, Kimi, MiniMax, Qwen, Ollama

---

## Architecture

```
┌──────────────────┐     ┌───────────────────┐
│  Next.js Frontend │────▶│  Python FastAPI    │
│  (port 3002)      │◀────│  Backend (port 8002)│
│                   │     │                    │
│  - Upload UI      │     │  - PPTX extraction │
│  - Translation UI │     │  - PPTX injection  │
│  - Slide preview  │     │  - Translation API │
│  - Edit/Export    │     │  - Translation mem  │
└──────────────────┘     └───────────────────┘
```

The Next.js frontend proxies API calls to the Python backend. The backend does all the heavy lifting — parsing the `.pptx` ZIP structure, extracting XML text runs, calling translation APIs, and re-injecting translated text into the XML.

---

## Prerequisites

- **Node.js** 18+
- **Python** 3.10+
- **LibreOffice** (for slide preview images) — `soffice` must be on PATH
- **pdftoppm** (part of `poppler-utils`) — for PDF → PNG conversion
- At least one **API key** for a translation provider

---

## Installation

### 1. Clone & Install Frontend

```bash
git clone https://github.com/azolkipli-personal/jpeigo-slides.git
cd jpeigo-slides
npm install
```

### 2. Set Up Python Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

If `requirements.txt` doesn't exist, install dependencies manually:

```bash
pip install "python-pptx>=1.0.2" "fastapi>=0.115.0" "uvicorn[standard]>=0.34.0" \
    "pydantic>=2.0.0" "pydantic-settings>=2.0.0" "lxml>=5.3.0" "httpx>=0.28.0"
```

### 3. Configure API Keys

Copy the example env file and add your keys:

```bash
cp .env.example .env
# Edit .env with your API keys
```

See [Configuration](#configuration) below for all available options.

### 4. Start the Backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8002
```

Or use the convenience script:
```bash
chmod +x start.sh && ./start.sh
```

### 5. Start the Frontend

```bash
# From the project root
npm run dev
```

Open **http://localhost:3002/translator** in your browser.

---

## Configuration

All configuration is done via environment variables in `backend/.env`.

### Translation Providers (at least one required)

| Variable | Description | Example |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini API key (free tier available) | `AIza...` |
| `OPENCODE_API_KEY` | OpenCode API key (unified access to curated models) | `sk-...` |
| `GOOGLE_CLOUD_API_KEY` | Google Cloud Translation API key | `AIza...` |
| `GLM_API_KEY` | GLM-4 (BigModel) API key | — |
| `KIMI_API_KEY` | Kimi / Moonshot API key | — |
| `MINIMAX_API_KEY` | MiniMax API key (also needs `MINIMAX_GROUP_ID`) | — |
| `QWEN_API_KEY` | Qwen (DashScope) API key | — |
| `OLLAMA_URL` | Local Ollama URL for offline translation | `http://localhost:11434` |

### Server Settings

| Variable | Default | Description |
|---|---|---|
| `CORS_ORIGINS` | `["http://localhost:3002"]` | Allowed CORS origins |
| `DEFAULT_MODEL` | `gemini` | Default translation model |
| `DEBUG` | `false` | Enable debug mode |

### Advanced

| Variable | Default | Description |
|---|---|---|
| `PYTHON_BACKEND_URL` (frontend `.env.local`) | `http://localhost:8002` | Backend URL for the Next.js proxy |
| `GEMINI_API_URL` | `https://generativelanguage.googleapis.com/v1beta` | Gemini API endpoint |
| `OPENCODE_API_URL` | `https://api.opencode.ai/v1` | OpenCode API endpoint |

---

## Usage

1. **Upload** — Drag & drop a `.pptx` file (up to 50MB)
2. **Configure** — Select source/target language (English ↔ Japanese) and translation model
3. **Translate** — Click Translate — all text is processed with concurrent API calls
4. **Review** — Browse slides via preview images, edit any translation inline
5. **Export** — Download the translated `.pptx` — all formatting preserved

### Supported Models

**Gemini (Google):**

> ⚠️ **Free tier:** Use `gemini-25-flash-lite`. Newer Gemini models (3.x like 3.5 Flash and 3.1 Flash Lite) trigger HTTP 429 "monthly spending cap reached" on free tier accounts. Paid tier users can use any model below.

- `gemini-25-flash-lite` — Gemini 2.5 Flash Lite ✅ **recommended for free tier**
- `gemini-pro` — Gemini 3 Pro (paid tier)
- `gemini-flash` — Gemini 3.5 Flash (paid tier)
- `gemini-flash-lite` — Gemini 3.1 Flash Lite (paid tier)

**OpenCode (unified API):**
- `opencode-deepseek` — DeepSeek V4
- `opencode-kimi` — Kimi K2.5
- `opencode-qwen` — Qwen Max
- `opencode-minimax` — MiniMax M2.5

**Direct APIs:**
- `glm`, `kimi`, `minimax`, `qwen`, `ollama`, `google-cloud`

---

## Project Structure

```
jpeigo-slides/
├── app/                    # Next.js frontend
│   ├── api/                # API route handlers (proxies to backend)
│   │   ├── upload-new/     # File upload endpoint
│   │   ├── translate-new/  # Translation endpoint
│   │   ├── export-new/     # Download endpoint
│   │   ├── preview/        # Slide preview images
│   │   └── health/         # Health check
│   └── translator/         # Main translator UI page
├── backend/
│   └── app/
│       ├── core/
│       │   ├── extractor.py   # PPTX text extraction (shapes, tables, SmartArt)
│       │   └── injector.py    # Text re-injection into PPTX XML
│       ├── translators/
│       │   └── service.py     # Translation providers (Gemini, OpenCode, etc.)
│       ├── utils/
│       │   └── cache.py       # Translation memory
│       ├── models/            # Pydantic data models
│       ├── config.py          # Environment variable configuration
│       └── main.py            # FastAPI application & endpoints
├── components/             # Shared React components
└── package.json
```

---

## How It Works

### Extraction

1. Opens the `.pptx` as a ZIP and reads each slide's XML
2. Iterates shapes: text boxes, grouped shapes, tables, SmartArt diagrams
3. For SmartArt: follows `<dgm:relIds>` relationships to the diagram data part and extracts `<a:t>` elements
4. Each text run gets a unique `run_id` encoding slide, shape, paragraph, and run position
5. Returns a structured JSON with all text, styling, and spatial constraints

### Translation

1. Frontend sends all extracted runs to the backend
2. Backend checks translation memory cache first (avoiding re-translation)
3. Uncached texts are sent to the selected provider concurrently (up to 5 parallel requests)
4. Results are cached for future use

### Injection

1. Opens the original `.pptx` with `python-pptx`
2. Groups translated runs by slide → shape
3. For regular shapes: finds the Python-pptx `Run` object and calls `run.text = translated_text`
4. For SmartArt: directly manipulates the diagram XML via lxml, updating `<a:t>` elements
5. Saves the modified `.pptx`

---

## Development

### Adding a Translation Provider

1. Create a new class implementing `TranslatorInterface` in `backend/app/translators/service.py`
2. Add the API key and URL fields to `backend/app/config.py`
3. Register the translator in `TranslationService.__init__`
4. Add the model option to the frontend's model selector in `app/translator/page.tsx`

### Running Tests

```bash
# Backend
cd backend && source venv/bin/activate
python -m pytest

# Frontend
npm test
```

---

## License

MIT
