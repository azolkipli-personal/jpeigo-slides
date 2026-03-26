# Getting Valid Google Cloud API Keys

The current key in `.env.local` is not valid for Vision/Translation APIs. Here's how to get proper keys:

## Step 1: Go to Google Cloud Console

1. Open: https://console.cloud.google.com/
2. Sign in with your Google account
3. If you don't have a project, create one: **Select a project → NEW PROJECT**
   - Name: `pptx-translator`
   - Click **Create**

## Step 2: Enable Required APIs

1. **Cloud Vision API** (for OCR):
   - Go to: https://console.cloud.google.com/apis/library/vision.googleapis.com
   - Click **Enable**

2. **Cloud Translation API** (for translation):
   - Go to: https://console.cloud.google.com/apis/library/translate.googleapis.com
   - Click **Enable**

## Step 3: Create API Credentials

1. Go to: https://console.cloud.google.com/apis/credentials
2. Click **+ CREATE CREDENTIALS**
3. Select **API key**
4. Copy the generated key (starts with `AIza...`)
5. Click **RESTRICT KEY** to set restrictions:
   - **Application restrictions**: None (or restrict to your domain)
   - **API restrictions**: Select only:
     - Cloud Vision API
     - Cloud Translation API

## Step 4: Add Key to .env.local

Edit `.env.local` and replace with your new key:

```env
GOOGLE_CLOUD_API_KEY=AIzaSy...your_new_key_here...
```

## Step 5: Test the API

```bash
# Test if key works
curl -X POST "https://translation.googleapis.com/language/translate/v2?key=YOUR_NEW_KEY" \
  -H "Content-Type: application/json" \
  -d '{"q":"Hello","target":"ja"}'
```

Expected response:
```json
{
  "data": {
    "translations": [{"translatedText":"こんにちは"}]
  }
}
```

## Important Notes

- **API keys are free** for reasonable usage (500,000 characters/month for Vision, 500,000 characters/month for Translation)
- **Monitor usage** at: https://console.cloud.google.com/apis/dashboard
- **Never share** your API key publicly
- **Set quotas** to avoid unexpected charges: https://console.cloud.google.com/apis/credentials

## Alternative: Free Options

If you don't want to use Google Cloud:

1. **Tesseract.js** - Already installed, runs locally (no key needed)
2. **LibreTranslate** - Self-hosted, free:
   - Deploy at: https://github.com/LibreTranslate/LibreTranslate
   - Add to `.env.local`:
     ```
     LIBRETRANSLATE_URL=http://localhost:5000
     ```

## Quick Reference

| Step | URL |
|------|-----|
| Cloud Console | https://console.cloud.google.com/ |
| Create Project | https://console.cloud.google.com/projectcreate |
| Enable Vision API | https://console.cloud.google.com/apis/library/vision.googleapis.com |
| Enable Translation API | https://console.cloud.google.com/apis/library/translate.googleapis.com |
| Create API Key | https://console.cloud.google.com/apis/credentials |
| View Usage | https://console.cloud.google.com/apis/dashboard |

## After Getting Key

1. Update `.env.local`
2. Restart dev server: `npm run dev`
3. Test with a PPTX file at http://localhost:3000
