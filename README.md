# jpeigo-slides Portable

> **XML-level PowerPoint translation** — translate `.pptx` files between English and Japanese while preserving every pixel of formatting. No installation needed — just unzip and run.

---

## Quick Start

1. **Download** the latest portable zip from the [Releases page](https://github.com/azolkipli-personal/jpeigo-slides/releases)
2. **Unzip** anywhere on your Windows machine
3. **Configure** your API key (see [Setup](#-setup) below)
4. **Double-click** `jpeigo-slides.exe`
5. Browser opens to **http://localhost:8002** — start translating!

### What you get

| Feature | Works? |
|---|---|
| Translate English ↔ Japanese | ✅ |
| SmartArt diagrams | ✅ |
| Tables | ✅ |
| Grouped shapes | ✅ |
| Vertical text (縦書き) | ✅ |
| Formatting preservation | ✅ |
| Slide preview images | ✅ *(requires LibreOffice)* |
| In-app setup guide | ✅ **http://localhost:8002/setup** |

---

## ⚙️ Setup

### Get an API Key

The app needs at least one translation API key. **Gemini (Google)** has a free tier:

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **"Create API Key"** — copy the key

### Configure the App

1. Open the folder where you unzipped the app
2. Go into the `backend\` subfolder
3. Open `.env.example` in Notepad
4. Replace `GEMINI_API_KEY=` with `GEMINI_API_KEY=AIza...` (your actual key)
5. **Save as `.env`** (remove `.example`)

That's it. Restart the app and the health indicator turns green.

### Available Providers

| Provider | Env Variable | Free Tier |
|---|---|---|
| Gemini (Google) | `GEMINI_API_KEY` | ✅ Yes |
| OpenCode | `OPENCODE_API_KEY` | — |
| Google Cloud | `GOOGLE_CLOUD_API_KEY` | $300 credit |
| Qwen (Alibaba) | `QWEN_API_KEY` | ✅ Yes |
| GLM (Zhipu) | `GLM_API_KEY` | ✅ Yes |
| Kimi (Moonshot) | `KIMI_API_KEY` | — |
| MiniMax | `MINIMAX_API_KEY` | — |

All env vars are documented in `backend/.env.example`.

---

## 📦 System Requirements

- **Windows 10** or later (64-bit)
- **No Python, Node.js, or Java required** — everything is bundled in the .exe
- **LibreOffice** *(optional)* — only needed for slide preview images. Download from [libreoffice.org](https://www.libreoffice.org/download/)
- **Internet connection** — for translation API calls
- ~200MB disk space

---

## 🖥️ Using the App

| Step | What to do |
|---|---|
| **Upload** | Drag a `.pptx` file onto the upload area (or click to browse, max 50MB) |
| **Configure** | Choose English or Japanese as source/target, pick a model |
| **Translate** | Click Translate — texts are sent to the API with 5 concurrent calls |
| **Review** | Browse slides via preview images, edit any translation inline |
| **Export** | Click Download to save the translated `.pptx` — all formatting preserved |

### Slide Preview

After translation, the app renders slide preview images using **LibreOffice**. If LibreOffice isn't installed, the preview area shows a message — you can still download the translated file, it's fully correct.

To enable previews: install [LibreOffice](https://www.libreoffice.org/download/) (any version) and restart the app.

---

## Architecture

```
┌────────────────────────────────────────┐
│         jpeigo-slides.exe              │
│  ┌──────────────────────────────────┐  │
│  │  Python FastAPI (port 8002)      │  │
│  │  ┌────────────────────────────┐  │  │
│  │  │  Frontend (static HTML/JS) │  │  │
│  │  ├────────────────────────────┤  │  │
│  │  │  API Endpoints             │  │  │
│  │  │  • /api/upload             │  │  │
│  │  │  • /api/translate          │  │  │
│  │  │  • /api/export             │  │  │
│  │  │  • /api/preview            │  │  │
│  │  │  • /api/health             │  │  │
│  │  ├────────────────────────────┤  │  │
│  │  │  /setup  — in-app guide    │  │  │
│  │  └────────────────────────────┘  │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

Everything runs as a single process on a single port. No proxies, no Node server, no separate frontend build step.

---

## 🔧 Building from Source

To build the `.exe` yourself on Windows:

```bash
# Prerequisites: Node.js 18+, Python 3.10+
git clone https://github.com/azolkipli-personal/jpeigo-slides.git
cd jpeigo-slides
git checkout windows-portable
build.bat
```

The script:
1. Installs npm deps & builds the frontend as static export
2. Installs Python deps
3. Packs everything into `backend\dist\jpeigo-slides.exe`

---

## ❓ Troubleshooting

| Symptom | Fix |
|---|---|
| "No API keys configured" (yellow dot) | Create `backend\.env` — see [Setup](#-setup) |
| "Preview requires LibreOffice" | Install LibreOffice, or ignore — the translated file is fine |
| Antivirus flags the .exe | False positive from PyInstaller. Add folder to exclusions |
| Port 8002 already in use | Add `PORT=8003` to your `backend\.env` and restart |
| Need help? | Open an issue on [GitHub](https://github.com/azolkipli-personal/jpeigo-slides/issues) |

---

## License

MIT
