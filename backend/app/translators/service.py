"""
Translation service interface and implementations.
Supports GLM-4, Kimi/Moonshot, MiniMax, Qwen, Gemini, OpenCode Zen/Go, and Ollama.
"""
from abc import ABC, abstractmethod
from typing import Optional
import httpx
import asyncio
import uuid

from app.config import Settings
from app.core.textnorm import strip_reasoning


# A provider that does not know the configured model fails every request and the
# failover chain then supplies another provider, so the job ends with original
# text and success=False — indistinguishable from a bad translation. Record the
# reason so the app can name the wrong model. Markers cover providers' wordings.
MISSING_MODEL_MARKERS = (
    # Gemini: 'models/<id> is not found for API version v1beta, or is not
    # supported for generateContent' — a wrong ID is a 404, and the message is
    # truncated before it says anything else, so match the opening phrase.
    'is not found',
    'is no longer available',
    'no longer supported',
    'model is unavailable',
    'not supported for generatecontent',
    'model not found',
    'model_not_found',
    'does not exist',
    "doesn't exist",
    'unknown model',
    'unsupported model',
    'invalid model',
    'no such model',
    'not a valid model',
    'model is not available',
)


def is_missing_model_error(message: str) -> bool:
    """True when an error text blames the model ID rather than the request."""
    lowered = (message or '').lower()
    return any(marker in lowered for marker in MISSING_MODEL_MARKERS)


class TranslatorInterface(ABC):
    """Abstract interface for translation services.

    `last_error` carries the reason for the most recent failure: failover hides
    failures by design, so the reason must be retrievable after the fact.
    """

    last_error: str = ''

    def _fail(self, text: str, message: str) -> tuple[str, bool]:
        """Record why a translation did not happen, then report failure."""
        self.last_error = message
        return text, False

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
    
    def __init__(self, settings: Settings, model: str = "gemini-2.5-flash-lite"):
        self.api_url = settings.gemini_api_url
        self.api_key = settings.gemini_api_key
        self.model = model
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return self._fail(text, 'no API key configured')
        
        lang_map = {
            'ja': 'Japanese',
            'en': 'English',
        }
        
        parts: list[str] = []
        if context:
            parts.append(context.strip())
        parts.append(
            f"Translate the following {lang_map.get(source_lang, source_lang)} text to {lang_map.get(target_lang, target_lang)}."
        )
        parts.append(
            "CRITICAL: Return ONLY the translated text. Do NOT include the original text, "
            "do NOT include arrows (→), do NOT include colons or labels, "
            "do NOT include the glossary or any other metadata. Just the translation itself."
        )
        parts.append(f"Text:\n{text}")
        parts.append("Translation:")
        prompt = "\n\n".join(parts)
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/models/{self.model}:generateContent",
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
                        # Response parts, not the prompt `parts` above: reusing the
                        # name made the next request look like it consumed the reply.
                        response_parts = candidates[0].get("content", {}).get("parts", [])
                        if response_parts:
                            translated = response_parts[0].get("text", text)
                            # A reasoning wrapper is never part of a translation.
                            # An answer that is only reasoning means the model never
                            # translated, so fail rather than paste thinking onto a
                            # slide — that also lets the failover chain run.
                            cleaned = strip_reasoning(translated)
                            if not cleaned:
                                message = "answered with reasoning only, no translation"
                                print(f"Gemini {message} (model={self.model})")
                                return self._fail(text, message)
                            return cleaned.strip(), True
                    message = f"HTTP 200 without candidate text: {response.text[:200]}"
                    print(f"Gemini {message} (model={self.model})")
                    return self._fail(text, message)
                message = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"Gemini {message} (model={self.model})")
                return self._fail(text, message)
        except Exception as e:
            message = f"[{type(e).__name__}] {e}"
            print(f"Gemini translation error (model={self.model}): {message}")
            return self._fail(text, message)
    
    def get_model_name(self) -> str:
        return self.model


class OpenCodeTranslator(TranslatorInterface):
    """OpenCode Zen/Go translator - unified access to GLM, Kimi, MiniMax."""
    
    def __init__(self, settings: Settings, model: str = "auto"):
        self.api_url = settings.opencode_api_url
        self.api_key = settings.opencode_api_key
        self.model = model
        # OpenCode Go enforces x-opencode-session: requests without it come back
        # 400 "missing x-opencode-session" and the whole OpenCode lane fails, so
        # failover silently has nowhere to go. The value is an opaque routing
        # hint, and stability keeps the provider's prompt cache warm, so it is
        # generated once per translator instead of once per request.
        self.session_id = f"jpeigo-{uuid.uuid4().hex[:16]}"
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return self._fail(text, 'no API key configured')
        
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
        model_id = self.model if self.model != "auto"else"deepseek-v4-flash"
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.api_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                        # Required by OpenCode Go since 09/05; without it every
                        # request is a 400 and the failover lane is dead.
                        "x-opencode-session": self.session_id,
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
                    # minimax-m3 replies with "<think>The user wants me to
                    # translate…" ahead of the answer, and that wrapper would land
                    # in a slide verbatim. Strip it; a reasoning-only answer means
                    # no translation happened, so fail and let failover run.
                    cleaned = strip_reasoning(translated)
                    if not cleaned:
                        message = "answered with reasoning only, no translation"
                        print(f"OpenCode {message} (model={model_id})")
                        return self._fail(text, message)
                    return cleaned.strip(), True
                message = f"HTTP {response.status_code}: {response.text[:200]}"
                print(f"OpenCode {message} (model={model_id})")
                return self._fail(text, message)
        except Exception as e:
            # Include the exception type: many network errors stringify to an
            # empty message (TimeoutError), which is useless for diagnosis.
            message = f"[{type(e).__name__}] {e}"
            print(f"OpenCode translation error (model={model_id}): {message}")
            return self._fail(text, message)
    
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


class GoogleCloudTranslator(TranslatorInterface):
    """Google Cloud Translation API (fast, reliable, no context awareness)."""
    
    def __init__(self, settings: Settings):
        self.api_key = settings.google_cloud_api_key
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        context: Optional[str] = None,
    ) -> tuple[str, bool]:
        if not self.api_key:
            return text, False
        
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    "https://translation.googleapis.com/language/translate/v2",
                    params={"key": self.api_key},
                    json={
                        "q": [text],
                        "target": target_lang,
                        "format": "text",
                    },
                )
                
                if response.status_code == 200:
                    data = response.json()
                    translations = data.get("data", {}).get("translations", [])
                    if translations:
                        translated = translations[0].get("translatedText", text)
                        return translated, True
                return text, False
        except Exception as e:
            print(f"Google Cloud translation error: {e}")
            return text, False
    
    def get_model_name(self) -> str:
        return "google-cloud"


class TranslationService:
    """
    Translation service that routes to appropriate translator.
    """
    
    def __init__(self, settings: Settings):
        self.settings = settings
        # Last failure per model name, so a bad model ID or a dead provider stays
        # reportable after the failover chain has papered over it. validate_models()
        # probes at startup and /api/health exposes the readout.
        self.model_errors: dict[str, str] = {}
        self.translators = {
            # Gemini models (queried from live API)
            # gemini-3-pro-preview was retired by the provider (404 "no longer
            # available, use gemini-3.1-pro-preview"); the probe in
            # validate_models() caught it — a dead ID here fails every job.
            'gemini-pro': GeminiTranslator(settings, 'gemini-3.1-pro-preview'),
            'gemini-flash': GeminiTranslator(settings, 'gemini-3.5-flash'),
            'gemini-flash-lite': GeminiTranslator(settings, 'gemini-3.1-flash-lite'),
            'gemini-25-flash-lite': GeminiTranslator(settings, 'gemini-2.5-flash-lite'),
            'gemini-flash-38': GeminiTranslator(settings, 'gemini-3.8-flash'),
            # OpenCode models (proxy to the best available)
            # deepseek-v4-flash is gone: v4.1-flash answers better in the same lane
            # and also reads slide images, so one flat-rate model covers translation
            # and the slide check instead of two near-identical entries.
            'opencode-deepseek': OpenCodeTranslator(settings, 'deepseek-v4.1-flash'),
            # kimi-k2.5 is retired upstream ("Model is unavailable"); kimi-k2.6 and
            # kimi-k3 both answer, so use the current one.
            'opencode-kimi': OpenCodeTranslator(settings, 'kimi-k3'),
            'opencode-qwen': OpenCodeTranslator(settings, 'qwen3.8-max'),
            # minimax-m2.5 could not read an image at all (HTTP 400); m3 supersedes
            # it and its reasoning wrapper is stripped before the text is used.
            'opencode-minimax': OpenCodeTranslator(settings, 'minimax-m3'),
            'opencode-longcat': OpenCodeTranslator(settings, 'longcat-2.0'),
            'opencode-glm': OpenCodeTranslator(settings, 'glm-5.3'),
            # Fallback / direct APIs (kept for compatibility)
            'glm': GLMTranslator(settings),
            'kimi': KimiTranslator(settings),
            'minimax': MiniMaxTranslator(settings),
            'qwen': QwenTranslator(settings),
            'ollama': OllamaTranslator(settings),
            'google-cloud': GoogleCloudTranslator(settings),
        }
    
    def get_translator(self, model: str) -> TranslatorInterface:
        """Get the appropriate translator for a model."""
        if model == 'auto':
            # Auto-select based on availability (Gemini 2.5 Flash Lite avoids free tier spending caps)
            if self.settings.gemini_api_key:
                return self.translators['gemini-25-flash-lite']
            if self.settings.opencode_api_key:
                return self.translators['opencode-deepseek']
            if self.settings.google_cloud_api_key:
                return self.translators['google-cloud']
            if self.settings.qwen_api_key:
                return self.translators['qwen']
            if self.settings.ollama_url:
                return self.translators['ollama']
            return self.translators['google-cloud']
        
        # Direct match (e.g. 'gemini-pro', 'opencode-kimi')
        if model in self.translators:
            return self.translators[model]
        
        # Handle opencode sub-models by prefix
        if model.startswith('opencode-'):
            submodel = model.replace('opencode-', '')
            return OpenCodeTranslator(self.settings, submodel)
        
        # Default to Gemini flash lite
        return self.translators.get('gemini-flash-lite', self.translators['gemini-flash-lite'])
    
    def _failover_chain(self, model: str) -> list[str]:
        """Fallback providers to try when the primary fails. Key-gated."""
        if model.startswith('opencode'):
            return ['gemini-25-flash-lite'] if self.settings.gemini_api_key else []
        if model.startswith('gemini') or model == 'auto':
            return ['opencode-deepseek'] if self.settings.opencode_api_key else []
        return ['gemini-25-flash-lite'] if self.settings.gemini_api_key else []

    def _record_failure(self, model_name: str, message: str) -> None:
        """Remember the last failure per model, flagging a bad model ID loudly.

        Failover keeps a job running when a provider is down, which is right, but
        it also hides a retired model ID: every run comes back as original text
        with success=False, which reads as a poor translation rather than a
        configuration error. Say which model was rejected.
        """
        self.model_errors[model_name] = message or 'unknown failure'
        if is_missing_model_error(message):
            print(f"  [MODEL-INVALID] {model_name} rejected the model ID: {message}")

    async def validate_models(self) -> dict[str, str]:
        """Probe every configured model once; return {model: problem} for the failures.

        Opt-in (VALIDATE_MODELS_ON_STARTUP=1) because it spends one small request
        per configured model. Without it a retired ID only shows up as a job that
        came back untranslated.
        """
        problems: dict[str, str] = {}
        for key, translator in self.translators.items():
            if not getattr(translator, 'api_key', None):
                continue
            _, ok = await translator.translate('テスト', 'ja', 'en')
            if not ok:
                problems[key] = getattr(translator, 'last_error', 'unknown failure')
                self._record_failure(getattr(translator, 'get_model_name')(), problems[key])
        return problems

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
        On provider failure, automatically falls back to an alternate provider
        so a dead upstream doesn't poison a whole job with passthrough runs.

        Returns:
            (translated_text, model_used, success)
        """
        translator = self.get_translator(model)
        translated, success = await translator.translate(text, source_lang, target_lang, context)
        model_used = translator.get_model_name()

        if success:
            return translated, model_used, True

        self._record_failure(model_used, getattr(translator, 'last_error', ''))

        # Auto-failover: try alternate providers (one level deep, no loops)
        for fb_key in self._failover_chain(model):
            fb = self.translators.get(fb_key)
            if fb is None:
                continue
            fb_translated, fb_success = await fb.translate(text, source_lang, target_lang, context)
            if fb_success:
                print(f"  [FAILOVER] {model_used} failed → {fb.get_model_name()} used")
                return fb_translated, fb.get_model_name(), True
            self._record_failure(fb.get_model_name(), getattr(fb, 'last_error', ''))

        # Every option failed. The caller keeps the original text with success=False,
        # and that must not be the only trace: this is a configuration problem more
        # often than a translation problem.
        print(f"  [TRANSLATE-FAILED] {model_used} and its fallbacks all failed — original text kept")
        return translated, model_used, False

    async def batch_translate(
        self,
        texts: list[str],
        source_lang: str = 'ja',
        target_lang: str = 'en',
        model: str = 'auto',
        context: Optional[str] = None,
        concurrency: int = 5,
        progress_callback=None,
    ) -> list[tuple[str, str, bool]]:
        """
        Translate multiple texts concurrently.

        Args:
            progress_callback: Optional sync callable invoked after each run
                completes, receiving the count of completed runs so far.

        Returns:
            List of (translated_text, model_used, success)
        """
        semaphore = asyncio.Semaphore(concurrency)
        completed = 0

        async def translate_with_limit(text: str):
            nonlocal completed
            async with semaphore:
                result = await self.translate_text(text, source_lang, target_lang, model, context)
            if progress_callback is not None:
                completed += 1
                try:
                    progress_callback(completed)
                except Exception:
                    pass  # progress reporting must never break translation
            return result

        results = await asyncio.gather(*[translate_with_limit(t) for t in texts])
        return list(results)