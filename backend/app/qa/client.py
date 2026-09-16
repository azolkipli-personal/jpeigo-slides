"""One QA client, two lanes: Gemini and OpenCode.

The QA passes ask a model a question — sometimes with slide images attached — and
want the text back. That is a different contract from `translators/service.py`,
whose classes carry failover and a `success` flag, so this module stays separate.

`generate()` picks the lane from the model ID, so a caller only has to pass a
model name:

- `gemini-…`  → the Gemini `generateContent` API (inline_data image parts)
- anything else → OpenCode's OpenAI-compatible `/chat/completions`
  (image_url data-URL parts). Costs real money per call on OpenCode Go: the plan's
  limit is a dollar amount per model, so a slide check is priced in tokens, not
  "flat rate". Measured on a real deck slide (kimi-k3, 1,987 in / 1,304 out):
  ~$0.026 per slide, ~$0.48 per 19-slide deck — 16% of kimi-k3's entire 5-hour
  allowance, i.e. ~31 decks per month before the model is exhausted.

Both lanes are asked for JSON and both answers go through the same tolerant
`load_json`, because a reviewer that answers in prose is still a usable answer.
"""
import base64
import json
import re
import uuid
from pathlib import Path

import httpx

from app.config import get_settings
from app.core.textnorm import strip_reasoning

GEMINI_ROOT = 'https://generativelanguage.googleapis.com/v1beta/models'
DEFAULT_OPENCODE_BASE = 'https://opencode.ai/zen/go/v1'

# OpenCode Go rejects any request without this header since 09/05 (400
# MissingSessionID). Generated once per process: the value is an opaque routing
# hint, and stability keeps the provider's prompt cache warm.
OPENCODE_SESSION = f'jpeigo-qa-{uuid.uuid4().hex[:16]}'


class QAError(RuntimeError):
    """The QA model call failed, or answered with something unusable."""


def lane_for(model: str) -> str:
    """Which provider serves this model ID."""
    return 'gemini' if (model or '').startswith('gemini') else 'opencode'


def _read_image(path) -> tuple[str, str]:
    """(mime type, base64) for a rendered slide."""
    data = Path(path).read_bytes()
    mime = 'image/jpeg' if str(path).lower().endswith(('.jpg', '.jpeg')) else 'image/png'
    return mime, base64.b64encode(data).decode()


# Low is deliberate: a layout review should not be creative. But the plan is not
# uniform about it — `kimi-k2.7-code` answers HTTP 400 "invalid temperature" for
# anything but 1, which is the only reason it was ever written off as unusable. It
# sees images perfectly well (five of five colour blocks at temperature 1), so the
# constraint belongs here as a per-model override rather than as an exclusion.
DEFAULT_TEMPERATURE = 0.1
TEMPERATURE_OVERRIDES: dict[str, float] = {'kimi-k2.7-code': 1}


def temperature_for(model: str) -> float:
    """The temperature this model will actually accept."""
    return TEMPERATURE_OVERRIDES.get(model, DEFAULT_TEMPERATURE)


def _add_usage(usage: dict | None, data: dict,
               prompt_key: str = 'prompt_tokens',
               completion_key: str = 'completion_tokens') -> None:
    """Add one provider response's token counts into a running total.

    Providers spell these differently — OpenAI-shaped lanes send `prompt_tokens`/
    `completion_tokens`, Gemini sends `promptTokenCount`/`candidatesTokenCount` — so
    the keys are arguments. Nothing is recorded when no dict is passed in.
    """
    if usage is None:
        return
    usage['prompt_tokens'] = usage.get('prompt_tokens', 0) + (data.get(prompt_key) or 0)
    usage['completion_tokens'] = usage.get('completion_tokens', 0) + (data.get(completion_key) or 0)


async def _gemini(api_key: str | None, model: str, prompt: str, images,
                  max_output_tokens: int, timeout: float,
                  usage: dict | None = None) -> str:
    if not api_key:
        raise QAError('no Gemini API key configured')

    parts: list[dict] = [{'text': prompt}]
    for path in images:
        mime, data = _read_image(path)
        parts.append({'inline_data': {'mime_type': mime, 'data': data}})

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f'{GEMINI_ROOT}/{model}:generateContent',
            params={'key': api_key},
            json={'contents': [{'parts': parts}],
                  'generationConfig': {
                      'temperature': 0.1,
                      # A review answer is JSON; asking for JSON is cheaper and
                      # more reliable than asking for prose and parsing it back.
                      'responseMimeType': 'application/json',
                      # Gemini 3.x counts thinking tokens against this budget, so
                      # a long review used to come back cut off mid-object.
                      'thinkingConfig': {'thinkingBudget': 0},
                      'maxOutputTokens': max(max_output_tokens, 8192),
                  }},
        )
    if response.status_code != 200:
        raise QAError(f'Gemini HTTP {response.status_code}: {response.text[:300]}')

    data = response.json()
    candidates = data.get('candidates') or []
    if not candidates:
        raise QAError(f'Gemini returned no candidates: {str(data)[:300]}')
    chunks = [part.get('text', '') for part in candidates[0].get('content', {}).get('parts', [])]
    text = strip_reasoning(''.join(chunks).strip())
    if not text:
        raise QAError(f'Gemini returned an empty answer: {str(data)[:300]}')
    _add_usage(usage, data.get('usageMetadata') or {},
               prompt_key='promptTokenCount', completion_key='candidatesTokenCount')
    return text


async def _opencode(api_key: str | None, model: str, prompt: str, images,
                    max_output_tokens: int, timeout: float,
                    base_url: str | None = None,
                    usage: dict | None = None) -> str:
    if not api_key:
        raise QAError('no OpenCode API key configured')

    content: list[dict] = [{'type': 'text', 'text': prompt}]
    for path in images:
        mime, data = _read_image(path)
        content.append({'type': 'image_url',
                        'image_url': {'url': f'data:{mime};base64,{data}'}})

    base = (base_url or DEFAULT_OPENCODE_BASE).rstrip('/')
    budget = max(max_output_tokens, 4096)
    last_error = ''
    # Two attempts, because a reasoning model can spend its entire budget thinking
    # and answer nothing. Seen live: deepseek-v4.1-flash reviewing slide 3 of a real
    # deck returned content='' with finish_reason='length', while slides 1-2 came
    # back as clean JSON. Running out of room is a budget problem, not a verdict.
    for _ in range(2):
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f'{base}/chat/completions',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                    # Required by OpenCode Go since 09/05; without it every request
                    # is a 400 and the lane looks entirely dead.
                    'x-opencode-session': OPENCODE_SESSION,
                },
                json={
                    'model': model,
                    'messages': [{'role': 'user', 'content': content}],
                    'temperature': temperature_for(model),
                    'max_tokens': budget,
                },
            )
        if response.status_code != 200:
            raise QAError(
                f'OpenCode HTTP {response.status_code} ({model}): {response.text[:300]}')

        data = response.json()
        # Recorded before the answer is judged: a retry bills for both attempts, and
        # an empty-length answer that we throw away was still paid for.
        _add_usage(usage, data.get('usage') or {})
        choices = data.get('choices') or []
        if not choices:
            raise QAError(f'OpenCode returned no choices ({model}): {str(data)[:300]}')
        choice = choices[0]
        message = choice.get('message') or {}
        answer = message.get('content')
        if isinstance(answer, list):  # some relays return content parts
            answer = ''.join(part.get('text', '') for part in answer
                             if isinstance(part, dict))
        # Reasoning models may also park their thinking in a sibling field, which is
        # ignored here: only `content` is the answer.
        answer = strip_reasoning((answer or '').strip())
        if answer:
            return answer

        last_error = (f'empty answer, finish_reason={choice.get("finish_reason")}, '
                      f'{len(str(data))} chars: {str(data)[:200]}')
        if choice.get('finish_reason') != 'length':
            break
        budget *= 4  # it was thinking, not answering: give it room once
    raise QAError(f'OpenCode produced no answer ({model}) — {last_error}')


def key_problem(model: str) -> str | None:
    """Why this model cannot run, or None when its lane has a key.

    Returns a message instead of raising so a report can carry the reason: a
    missing key must not look like a deck with no problems.
    """
    settings = get_settings()
    if lane_for(model) == 'gemini' and not settings.gemini_api_key:
        return f'{model} needs GEMINI_API_KEY, which is not configured'
    if lane_for(model) == 'opencode' and not getattr(settings, 'opencode_api_key', None):
        return f'{model} needs OPENCODE_API_KEY, which is not configured'
    return None


async def generate(model: str, prompt: str, images=(), max_output_tokens: int = 4096,
                   timeout: float = 300.0, usage: dict | None = None) -> str:
    """Ask `model` one question, optionally with rendered slides attached.

    Pass a dict as `usage` to have the provider's token counts added into it, keyed
    `prompt_tokens`/`completion_tokens`. Costs are invisible otherwise, and on
    OpenCode Go they are billed against a dollar limit per model.
    """
    settings = get_settings()
    if lane_for(model) == 'gemini':
        return await _gemini(settings.gemini_api_key, model, prompt, images,
                             max_output_tokens, timeout, usage=usage)
    return await _opencode(
        getattr(settings, 'opencode_api_key', None), model, prompt, images,
        max_output_tokens, timeout, usage=usage,
        base_url=getattr(settings, 'opencode_api_url', DEFAULT_OPENCODE_BASE),
    )


def load_json(text: str) -> dict:
    """Parse a JSON object out of a model answer, fences and prose included.

    Tolerant on purpose: answers arrive as bare JSON, as a fenced block, behind a
    leading word or token, or truncated when the output budget runs out. Scanning
    for the first balanced object handles all of those; a plain find('{')/rfind('}')
    would silently swallow trailing prose into the parse.
    """
    fenced = re.search(r'```(?:json)?\s*(.*?)(?:```|$)', text, re.DOTALL)
    candidate = (fenced.group(1) if fenced else text).strip()

    for source in (candidate, text):
        try:
            parsed = json.loads(source)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    start = candidate.find('{')
    if start != -1:
        depth, in_string, escaped = 0, False, False
        for position in range(start, len(candidate)):
            char = candidate[position]
            if in_string:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[start:position + 1])
                    except json.JSONDecodeError as exc:
                        raise QAError(f'could not parse JSON from the model answer: {exc}') from exc
        raise QAError(f'the model answer was cut off before the JSON closed '
                      f'({len(candidate)} chars): {candidate[:200]!r}')
    raise QAError('the model answer contained no JSON object')
