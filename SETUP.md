# PowerPoint Translator - Setup Guide

## Quick Start

Your app converts PowerPoint slides to images and translates text between English ↔ Japanese.

---

## 🔑 Google Cloud API Setup (Required)

### Step 1: Create Google Cloud Account

1. Go to https://console.cloud.google.com/
2. Sign in with your Google account
3. Accept the terms of service

### Step 2: Create a New Project

1. Click the project dropdown at the top (next to "Google Cloud")
2. Click "NEW PROJECT"
3. Enter project name: `powerpoint-translator`
4. Click "CREATE"
5. Wait for project creation, then select it

### Step 3: Enable Required APIs

#### Enable Cloud Vision API:
1. Go to https://console.cloud.google.com/apis/library/vision.googleapis.com
2. Make sure your project is selected
3. Click "ENABLE"
4. Wait for activation

#### Enable Cloud Translation API:
1. Go to https://console.cloud.google.com/apis/library/translate.googleapis.com
2. Make sure your project is selected
3. Click "ENABLE"
4. Wait for activation

### Step 4: Create API Key

1. Go to https://console.cloud.google.com/apis/credentials
2. Click "+ CREATE CREDENTIALS" at the top
3. Select "API key"
4. Copy the API key that appears (it looks like: `AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`)
5. (Optional) Click "RESTRICT KEY" to add security restrictions

### Step 5: Add API Key to Your App

1. Open the file: `.env.local` in your project root
2. Add this line (replace with your actual key):
   ```
   GOOGLE_CLOUD_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
   ```
3. Save the file

Your `.env.local` should now look like:
```env
CONVERT_API_SECRET=eCpRM97k48j1FHrtkDzhBed5wyyrgoxbl
GOOGLE_CLOUD_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

### Step 6: Restart Development Server

1. Stop the current server (press `Ctrl+C` in terminal)
2. Start it again:
   ```bash
   npm run dev
   ```

---

## 💰 Free Tier Limits

Google Cloud provides generous free tiers:
- **Vision API**: 1,000 images per month FREE
- **Translation API**: 500,000 characters per month FREE

You won't be charged unless you exceed these limits.

---

## ✅ Testing

1. Upload a PowerPoint file with English or Japanese text
2. Wait for conversion to images
3. Each slide will show:
   - The image
   - "Translating..." indicator
   - Translated text (English → Japanese or Japanese → English)

---

## 🐛 Troubleshooting

### "Missing GOOGLE_CLOUD_API_KEY" error
- Make sure you added the key to `.env.local`
- Make sure you restarted the dev server after adding the key
- Check for typos in the environment variable name

### "API not enabled" error
- Go back to Google Cloud Console
- Make sure both Vision API and Translation API are enabled
- Wait a few minutes for activation

### No translation appears
- Check browser console for errors (F12)
- Check terminal for error messages
- Verify your API key is valid

---

## 📚 Links

- [Google Cloud Console](https://console.cloud.google.com/)
- [Vision API Documentation](https://cloud.google.com/vision/docs)
- [Translation API Documentation](https://cloud.google.com/translate/docs)
