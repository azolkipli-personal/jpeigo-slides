# Translation Setup Guide

This guide explains what's needed to make the PowerPoint translation feature working.

## Overview

The translation system uses a multi-step process:
1. **PPTX → Images**: Convert PowerPoint to JPEG slides using LibreOffice
2. **OCR**: Extract text from images using Tesseract.js (local) or Google Cloud Vision API
3. **Translation**: Translate text using Google Cloud Translation or LibreTranslate
4. **Image Processing**: Replace text in images with translated text

## Prerequisites

### 1. LibreOffice (Required)

LibreOffice is required to convert PPTX files to images.

**Windows:**
```bash
# Download from: https://www.libreoffice.org/download/download/
# Install with default settings
# Default installation path: C:\Program Files\LibreOffice\program\soffice.exe

# Verify installation
"C:\Program Files\LibreOffice\program\soffice" --version
```

**Linux:**
```bash
sudo apt update
sudo apt install libreoffice
soffice --version
```

**macOS:**
```bash
brew install --cask libreoffice
soffice --version
```

### 2. Environment Variables

Create or update `.env.local` in the project root:

```env
# Required for PPTX conversion
# (LibreOffice must be installed separately)

# Optional: Google Cloud API for better OCR and translation
GOOGLE_CLOUD_API_KEY=your_api_key_here

# Optional: LibreTranslate fallback
# LIBRETRANSLATE_URL=https://your-libretranslate-instance.com

# Optional: ConvertAPI for PPTX conversion (alternative to LibreOffice)
# CONVERT_API_SECRET=your_convertapi_secret
```

### 3. Getting Google Cloud API Keys (Optional)

For better OCR and translation quality:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable these APIs:
   - **Cloud Vision API**: https://console.cloud.google.com/apis/library/vision.googleapis.com
   - **Cloud Translation API**: https://console.cloud.google.com/apis/library/translate.googleapis.com
4. Create credentials (API key): https://console.cloud.google.com/apis/credentials
5. Add the key to `.env.local`

**Note:** Tesseract.js works locally without any API key, but Google Cloud provides better accuracy.

### 4. Install Node Dependencies

```bash
npm install
```

All required dependencies are already in package.json:
- `tesseract.js` - Local OCR (no API key needed)
- `canvas` - Image processing
- `sharp` - Image manipulation
- `@google-cloud/translate` - Google Cloud Translation
- `@google-cloud/vision` - Google Cloud Vision OCR

## Testing the Setup

### 1. Start the Development Server

```bash
npm run dev
```

### 2. Test Upload API

```bash
# Create a test PPTX file, then upload via curl:
curl -X POST -F "file=@test.pptx" http://localhost:3000/api/upload
```

Expected response:
```json
{
  "images": [
    {
      "url": "data:image/jpeg;base64,...",
      "name": "slide1.jpg"
    }
  ]
}
```

### 3. Test Translate API

```bash
# Test with a base64 image
curl -X POST http://localhost:3000/api/translate \
  -H "Content-Type: application/json" \
  -d '{"imageData": "base64_encoded_image_data"}'
```

Expected response:
```json
{
  "originalText": "Hello World",
  "translatedText": "こんにちは、世界",
  "detectedLanguage": "en",
  "targetLanguage": "ja",
  "imageUrl": "data:image/jpeg;base64,...",
  "textBlocks": [...]
}
```

## Troubleshooting

### LibreOffice Not Found

**Error:**
```
LibreOffice not installed
Please install LibreOffice from https://www.libreoffice.org/download/download/
```

**Solution:**
1. Install LibreOffice from https://www.libreoffice.org/download/download/
2. Ensure default installation path or update `app/api/upload/route.ts` with your custom path
3. Restart the development server

### Tesseract.js Fails

**Error:**
```
Tesseract failed: ...
```

**Solution:**
1. Tesseract.js downloads language data on first run (may take time)
2. Ensure internet connection for initial setup
3. Check firewall settings

### Google Cloud API Errors

**Error:**
```
Google Cloud Vision failed: Request had no authentication...
```

**Solution:**
1. Verify `GOOGLE_CLOUD_API_KEY` is set in `.env.local`
2. Ensure APIs are enabled in Google Cloud Console
3. Check API key restrictions (IP, referrer)

### Out of Memory Errors

**Error:**
```
JavaScript heap out of memory
```

**Solution:**
Increase Node.js memory limit:
```bash
NODE_OPTIONS="--max-old-space-size=4096" npm run dev
```

### Canvas/Sharp Build Issues

**Error:**
```
Cannot find module 'canvas'
sharp: Installation error
```

**Solution:**
```bash
# Windows (requires build tools)
npm install --global windows-build-tools
npm rebuild canvas

# Linux
sudo apt-get install build-essential libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev
npm rebuild canvas sharp

# macOS
brew install pkg-config cairo pango jpeg giflib
npm rebuild canvas sharp
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   User uploads  │────▶│  /api/upload    │────▶│   LibreOffice   │
│   PPTX file     │     │  (PPTX→Images)  │     │   (Headless)    │
└─────────────────┘     └─────────────────┘     └─────────────────┘
                                                         │
                                                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Download      │◀────│   /api/export   │◀────│  Processed      │
│   translated    │     │  (Images→PPTX)  │     │  images         │
│   presentation  │     └─────────────────┘     └─────────────────┘
└─────────────────┘              ▲                        │
                                 │                        │
                                 │                        ▼
                                 │               ┌─────────────────┐
                                 │               │  /api/translate │
                                 └───────────────│  (OCR+Translate)│
                                                 └─────────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────────┐
                                               │   Tesseract.js  │
                                               │   (or Google    │
                                               │    Cloud Vision)│
                                               └─────────────────┘
```

## API Endpoints

### POST /api/upload
Convert PPTX file to images.

**Input:** `multipart/form-data` with `file` field (PPTX file)
**Output:** JSON with array of images (base64 encoded)

### POST /api/translate
Extract text from image and translate it.

**Input:** JSON with `imageUrl` or `imageData` (base64)
**Output:** JSON with original text, translated text, and processed image

### POST /api/export
Convert translated images back to PPTX.

**Input:** JSON with `images` array and `language`
**Output:** Binary PPTX file (downloadable)

## Performance Considerations

1. **LibreOffice** is the slowest step (~2-5 seconds per slide)
2. **Tesseract.js** runs locally (~1-3 seconds per slide)
3. **Translation APIs** are fast (~0.5 seconds per slide)
4. **Overall:** ~5-10 seconds per slide, depends on slide complexity

## Security Notes

- Never commit `.env.local` with real API keys
- API keys should have restricted permissions
- Validate file types on upload (only allow `.pptx`)
- Limit file size (add validation in upload route)
- Use rate limiting in production

## Production Deployment

For production, consider:

1. **Use ConvertAPI** instead of LibreOffice (more reliable):
   ```env
   CONVERT_API_SECRET=your_secret
   ```

2. **Use a translation service** with better rate limits

3. **Add queue system** for processing multiple files

4. **Add caching** for repeated translations

5. **Use Web Workers** to avoid blocking the main thread

## Quick Reference

| Component | Status | Notes |
|-----------|--------|-------|
| LibreOffice | Required | Install from website |
| Tesseract.js | Ready | Local OCR, no setup |
| Google Cloud Vision | Optional | Better OCR, needs API key |
| Google Translation | Optional | Better translation, needs API key |
| LibreTranslate | Optional | Self-hosted alternative |

## Next Steps

1. Install LibreOffice
2. Test with a simple PPTX file
3. Add Google Cloud API keys for production use
4. Consider ConvertAPI for faster, more reliable conversion
