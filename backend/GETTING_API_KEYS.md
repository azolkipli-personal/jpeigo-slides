# Getting API Keys for PPTX Translator

This guide explains how to get API keys for each translation provider.

## Free Options (Recommended for Getting Started)

### Google Gemini (FREE)
**Best for: Free tier with generous limits**

1. Go to https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the API key

**Free Tier Limits:**
- 15 requests per minute
- 1,500 requests per day
- No credit card required

Add to `backend/.env`:
```
GEMINI_API_KEY=your_api_key_here
```

---

### Qwen / Alibaba DashScope (FREE Credits)
**Best for: Chinese-focused translations**

1. Go to https://dashscope.aliyun.com/
2. Create an Alibaba Cloud account
3. Navigate to Console > API Keys
4. Create a new API key

**Free Tier:**
- Monthly free credits
- Good for Chinese-English translation

Add to `backend/.env`:
```
QWEN_API_KEY=your_api_key_here
```

---

## Paid Options (Better Quality / More Features)

### OpenCode Zen/Go
**Best for: Unified access to multiple models**

OpenCode provides access to GLM-4, Kimi K2.5, and MiniMax M2.5 through a single API.

1. Go to https://opencode.ai/auth
2. Create an account
3. Choose a plan:
   - **Go**: $5 first month, then $10/month (generous limits)
   - **Zen**: Pay-as-you-go ($20 minimum balance)
4. Get API key from dashboard

**Available Models:**
- GLM-4 (Zhipu AI)
- Kimi K2.5 (Moonshot)
- MiniMax M2.5

Add to `backend/.env`:
```
OPENCODE_API_KEY=your_api_key_here
```

---

### Kimi / Moonshot
**Best for: Long context translations**

1. Go to https://platform.moonshot.cn/
2. Create account and verify
3. Navigate to API Keys section
4. Create new API key

**Features:**
- 128K context window
- Good for long documents
- Free credits for new users

Add to `backend/.env`:
```
KIMI_API_KEY=your_api_key_here
```

---

### GLM-4 (Zhipu AI)
**Best for: Chinese language specialist**

1. Go to https://open.bigmodel.cn/
2. Create account
3. Get API key from console
4. New users get free credits

Add to `backend/.env`:
```
GLM_API_KEY=your_api_key_here
```

---

### MiniMax
**Best for: Fast responses**

1. Go to https://www.minimaxi.com/
2. Create account
3. Get API key and Group ID from console

Add to `backend/.env`:
```
MINIMAX_API_KEY=your_api_key_here
MINIMAX_GROUP_ID=your_group_id_here
```

---

## Local Option (No API Key Required)

### Ollama
**Best for: Privacy, offline use, no costs**

1. Install Ollama: https://ollama.ai/
2. Pull a translation-capable model:
   ```bash
   ollama pull llama3
   # or
   ollama pull qwen2
   ```
3. Run Ollama server (usually starts automatically)
4. Set the URL:

Add to `backend/.env`:
```
OLLAMA_URL=http://localhost:11434
```

**Note:** Local models may have lower translation quality compared to cloud APIs.

---

## Pricing Comparison

| Provider | Free Tier | Paid Cost | Best For |
|----------|-----------|------------|----------|
| Gemini | 1500 req/day | Pay-as-you-go | Getting started |
| Qwen | Monthly credits | Pay-as-you-go | Chinese content |
| OpenCode Go | No | $10/month | Multiple models |
| OpenCode Zen | No | $20 minimum | High quality |
| Kimi | Free credits | Pay-as-you-go | Long documents |
| GLM-4 | Free credits | Pay-as-you-go | Chinese specialist |
| MiniMax | No | Pay-as-you-go | Fast responses |
| Ollama | Unlimited | Free | Privacy/local |

---

## Recommended Setup

For beginners (free):
```
GEMINI_API_KEY=your_gemini_key
```

For best quality:
```
OPENCODE_API_KEY=your_opencode_key
```

For Chinese-English:
```
QWEN_API_KEY=your_qwen_key
```

For privacy/local:
```
OLLAMA_URL=http://localhost:11434
```