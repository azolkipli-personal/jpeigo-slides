"""
Translation service interface and implementations.
Supports GLM-4, Kimi/Moonshot, MiniMax, Qwen, Gemini, OpenCode Zen/Go, and Ollama.
"""
from abc import ABC, abstractmethod
from typing import Optional
import httpx
import asyncio

from app.config import Settings


class TranslatorInterface(ABC):
    """Abstract interface for translation services."""
    
    @abstractmethod
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        """
        Translate text from source to target language.
        
        Returns:
            (translated_text, success)
        """
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier."""
        pass


class GeminiTranslator(TranslatorInterface):
    """Google Gemini translator (free tier available)."""
    
    def __init__(self, settings: Settings):
        self.api_url = settings.gemini_api_url
        self.api_key = settings.gemini_api_key
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return text, False
        
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        prompt = f"""Translate the following text from {lang_map.get(source_lang, source_lang)} to {lang_map.get(target_lang, target_lang)}.
Preserve the original formatting and structure. Only provide the translation, no explanations.

{f'Context: {context}' if context else ''}

Text to translate:
{text}

Translation:"""
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/models/gemini-1.5-flash:generateContent",
                    headers={
                        "Content-Type": "application/json",
                    },
                    params={"key": self.api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.3,
                            "maxOutputTokens": 2048,
                        },
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [{}])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            translated = parts[0].get("text", text)
                            return translated.strip(), True
                return text, False
        except Exception as e:
            print(f"Gemini translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return "gemini-1.5-flash"


class OpenCodeTranslator(TranslatorInterface):
    """OpenCode Zen/Go translator - unified access to GLM, Kimi, MiniMax."""
    
    def __init__(self, settings: Settings, model: str = "auto"):
        self.api_url = settings.opencode_api_url
        self.api_key = settings.opencode_api_key
        self.model = model
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return text, False
        
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        prompt = f"""Translate from {lang_map.get(source_lang, source_lang)} to {lang_map.get(target_lang, target_lang)}.
Preserve formatting. Output only the translation.

{f'Context: {context}' if context else ''}

Original: {text}
Translation:"""
        
        # Model selection: auto picks best available
        model_id = self.model if self.model != "auto"else"glm-4"
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    translated = data.get("choices", [{}])[0].get("message", {}).get("content", text)
                    return translated.strip(), True
                return text, False
        except Exception as e:
            print(f"OpenCode translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return f"opencode-{self.model}"


class GLMTranslator(TranslatorInterface):
    """GLM-4 translator via BigModel API."""
    
    def __init__(self, settings: Settings):
        self.api_url = settings.glm_api_url
        self.api_key = settings.glm_api_key
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return text, False
        
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        prompt = f"""Translate the following text from {lang_map.get(source_lang, source_lang)} to {lang_map.get(target_lang, target_lang)}.
Preserve the original formatting and structure. Only provide the translation, no explanations.

{f'Context: {context}' if context else ''}

Text to translate:
{text}

Translation:"""
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "glm-4",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    translated = data.get("choices", [{}])[0].get("message", {}).get("content", text)
                    return translated.strip(), True
                return text, False
        except Exception as e:
            print(f"GLM translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return "glm-4"


class KimiTranslator(TranslatorInterface):
    """Kimi (Moonshot) translator via Moonshot API."""
    
    def __init__(self, settings: Settings):
        self.api_url = settings.kimi_api_url
        self.api_key = settings.kimi_api_key
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return text, False
        
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        prompt = f"""Translate from {lang_map.get(source_lang, source_lang)} to {lang_map.get(target_lang, target_lang)}.
Maintain formatting. Output only the translation.

{f'Context: {context}' if context else ''}

Original:
{text}

Translation:"""
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "moonshot-v1-8k",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    translated = data.get("choices", [{}])[0].get("message", {}).get("content", text)
                    return translated.strip(), True
                return text, False
        except Exception as e:
            print(f"Kimi translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return "kimi"


class MiniMaxTranslator(TranslatorInterface):
    """MiniMax translator."""
    
    def __init__(self, settings: Settings):
        self.api_url = settings.minimax_api_url
        self.api_key = settings.minimax_api_key
        self.group_id = settings.minimax_group_id
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key or not self.group_id:
            return text, False
        
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        prompt = f"""Translate from {lang_map.get(source_lang, source_lang)} to {lang_map.get(target_lang, target_lang)}.
{f'Context: {context}' if context else ''}

Original: {text}
Translation:"""
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/text/chatcompletion_v2",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "abab6.5s-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    translated = data.get("choices", [{}])[0].get("message", {}).get("content", text)
                    return translated.strip(), True
                return text, False
        except Exception as e:
            print(f"MiniMax translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return "minimax"


class QwenTranslator(TranslatorInterface):
    """Qwen translator via DashScope API."""
    
    def __init__(self, settings: Settings):
        self.api_url = settings.qwen_api_url
        self.api_key = settings.qwen_api_key
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return text, False
        
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        prompt = f"""Translate from {lang_map.get(source_lang, source_lang)} to {lang_map.get(target_lang, target_lang)}.
{f'Context: {context}' if context else ''}

Original: {text}
Translation:"""
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/services/aigc/text-generation/generation",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "qwen-turbo",
                        "input": {"messages": [{"role": "user", "content": prompt}]},
                        "parameters": {"temperature": 0.3},
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    translated = data.get("output", {}).get("text", text)
                    return translated.strip(), True
                return text, False
        except Exception as e:
            print(f"Qwen translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return "qwen"


class OllamaTranslator(TranslatorInterface):
    """Local translation via Ollama."""
    
    def __init__(self, settings: Settings):
        self.api_url = settings.ollama_url or "http://localhost:11434"
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        prompt = f"""Translate from {lang_map.get(source_lang, source_lang)} to {lang_map.get(target_lang, target_lang)}.
{f'Context: {context}' if context else ''}

Original: {text}
Translation:"""
        
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.api_url}/api/generate",
                    json={
                        "model": "llama3",
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    translated = data.get("response", text)
                    return translated.strip(), True
                return text, False
        except Exception as e:
            print(f"Ollama translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return "ollama"


class TranslationService:
    """
    Translation service that routes to appropriate translator.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.translators = {
            'glm': GLMTranslator(settings),
            'kimi': KimiTranslator(settings),
            'minimax': MiniMaxTranslator(settings),
            'qwen': QwenTranslator(settings),
            'gemini': GeminiTranslator(settings),
            'opencode': OpenCodeTranslator(settings, 'auto'),
            'opencode-glm': OpenCodeTranslator(settings, 'glm-4'),
            'opencode-kimi': OpenCodeTranslator(settings, 'kimi-k2-5'),
            'opencode-minimax': OpenCodeTranslator(settings, 'minimax-m2-5'),
            'ollama': OllamaTranslator(settings),
        }
    
    def get_translator(self, model: str) -> TranslatorInterface:
        """Get the appropriate translator for a model."""
        if model == 'auto':
            # Auto-select based on availability (priority: free/cheap first)
            if self.settings.gemini_api_key:
                return self.translators['gemini']
            if self.settings.opencode_api_key:
                return self.translators['opencode']
            if self.settings.qwen_api_key:
                return self.translators['qwen']
            if self.settings.kimi_api_key:
                return self.translators['kimi']
            if self.settings.glm_api_key:
                return self.translators['glm']
            if self.settings.minimax_api_key:
                return self.translators['minimax']
            if self.settings.ollama_url:
                return self.translators['ollama']
            # Default to Gemini structure even without key (will fail gracefully)
            return self.translators['gemini']
        
        # Handle opencode sub-models
        if model.startswith('opencode-'):
            submodel = model.replace('opencode-', '')
            return OpenCodeTranslator(self.settings, submodel)
        
        return self.translators.get(model, self.translators['gemini'])
    
    async def translate_text(
        self,
        text: str,
        source_lang: str = 'ja',
        target_lang: str = 'en',
        model: str = 'auto',
        context: Optional[str] = None,
    ) -> tuple[str, str, bool]:
        """
        Translate text using the specified model.
        
        Returns:
            (translated_text, model_used, success)
        """
        translator = self.get_translator(model)
        translated, success = await translator.translate(text, source_lang, target_lang, context)
        return translated, translator.get_model_name(), success
    
    async def batch_translate(
        self,
        texts: list[str],
        source_lang: str = 'ja',
        target_lang: str = 'en',
        model: str = 'auto',
        context: Optional[str] = None,
        concurrency: int = 5,
    ) -> list[tuple[str, str, bool]]:
        """
        Translate multiple texts concurrently.
        
        Returns:
            List of (translated_text, model_used, success)
        """
        semaphore = asyncio.Semaphore(concurrency)
        
        async def translate_with_limit(text: str):
            async with semaphore:
                return await self.translate_text(text, source_lang, target_lang, model, context)
        
        results = await asyncio.gather(*[translate_with_limit(t) for t in texts])
        return list(results)