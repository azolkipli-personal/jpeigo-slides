# jpeigo-slides Portable Edition

> A self-contained Windows app for translating PowerPoint files (English ↔ Japanese) with full formatting preservation. No installation required — just unzip and run.

## Quick Start

1. **Download** the latest portable zip from the [Releases](https://github.com/azolkipli-personal/jpeigo-slides/releases) page
2. **Unzip** anywhere (your Desktop, Downloads, or a USB drive — works from any location)
3. **Configure** your API key (see [Setup Guide](#setup) below)
4. **Double-click** `jpeigo-slides.exe`
5. Your browser opens to **http://localhost:8002** — start translating!

## Setup

### 1. Get an API Key

The app needs at least one translation API key. The easiest is **Gemini (Google) — free tier:**

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Sign in with your Google account
3. Click **"Create API Key"**
4. Copy the key (starts with `AIza...`)

### 2. Configure the App

1. Open the folder where you unzipped the app
2. Navigate to the `backend\` subfolder
3. Open `.env.example` in Notepad
4. Replace `GEMINI_API_KEY=` with `GEMINI_API_KEY=AIza...` (paste your actual key)
5. **Save the file as `.env`** (remove `.example` from the name)

That's it! No other setup needed.

### 3. Launch

Double-click `jpeigo-slides.exe`. The terminal window shows the server is running. A browser tab opens automatically.

## Usage

| Step | Action |
|---|---|
| **Upload** | Drag a `.pptx` file onto the upload area (or click to browse) |
| **Configure** | Choose English ↔ Japanese, pick a model |
| **Translate** | Click Translate — all text is processed |
| **Review** | Browse slides via preview images, edit translations inline |
| **Export** | Click Download to save the translated `.pptx` |

## System Requirements

- **Windows 10** or later (64-bit)
- **No Python, no Node.js, no Java required** — everything is bundled
- **LibreOffice** *(optional)* — install for slide preview images. Download from [libreoffice.org](https://www.libreoffice.org/download/)
- **Internet connection** — for translation API calls
- At least **200MB free disk space**

## What's Included

| File | Purpose |
|---|---|
| `jpeigo-slides.exe` | The app — double-click to run |
| `backend/.env` | Your API key configuration (you create this) |
| `backend/.env.example` | Template for the `.env` file |

The `uploads/` and `outputs/` folders are created automatically in the `backend/` directory on first use.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "No API keys configured" (yellow dot) | Create `backend/.env` with your API key, then restart the app |
| "Preview requires LibreOffice" | Install LibreOffice from libreoffice.org, or ignore — the translated file is still correct |
| Antivirus warning | This is a false positive from PyInstaller-packaged apps. Add the app folder to your antivirus exclusions |
| Port 8002 already in use | Edit `backend/.env` and add `PORT=8003`, then restart |

## Building from Source

If you want to build the executable yourself:

1. Install [Node.js 18+](https://nodejs.org/) and [Python 3.10+](https://www.python.org/downloads/)
2. Clone the repo: `git clone https://github.com/azolkipli-personal/jpeigo-slides.git`
3. Run `build.bat` from the project root — it handles everything

## License

MIT
