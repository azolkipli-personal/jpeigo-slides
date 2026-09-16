"""Strip a model's reasoning wrapper from its answer.

Reasoning models put their thinking in the answer text, either inside tags
(`<think>…</think>`, `<thinking>`, `<reasoning>`) or as an unclosed block when the
output budget runs out first. Observed live: `minimax-m3` answering a translation
request with `<think>The user wants me to translate Japanese to English…`, which
would be pasted into a slide if returned as the translation.

A wrapper is never part of a translation, so it is removed rather than escaped.
An unclosed wrapper means the model never got to its answer, so everything from
the tag on is dropped — the caller then sees an empty answer and fails honestly
instead of shipping half a thought.
"""
import re

# Tags seen in the wild on the OpenCode lane. `analysis` and `thinking` are
# alternates some relays use for the same block.
_TAGS = ('think', 'thinking', 'reasoning', 'analysis')

_CLOSED = re.compile(
    r'<\s*(?:' + '|'.join(_TAGS) + r')\s*>.*?<\s*/\s*(?:' + '|'.join(_TAGS) + r')\s*>',
    re.DOTALL | re.IGNORECASE,
)
_UNCLOSED = re.compile(
    r'<\s*(?:' + '|'.join(_TAGS) + r')\s*>.*$', re.DOTALL | re.IGNORECASE)
# Some models emit the closing tag on its own after a truncated block.
_STRAY_CLOSE = re.compile(
    r'<\s*/\s*(?:' + '|'.join(_TAGS) + r')\s*>', re.IGNORECASE)


def strip_reasoning(text: str) -> str:
    """Return `text` with any reasoning wrapper removed."""
    if not text:
        return text
    cleaned = _CLOSED.sub('', text)
    cleaned = _UNCLOSED.sub('', cleaned)
    cleaned = _STRAY_CLOSE.sub('', cleaned)
    return cleaned.strip()


def has_reasoning(text: str) -> bool:
    """True when a reasoning wrapper was present (for reporting, not cleaning)."""
    return bool(text) and bool(
        _CLOSED.search(text) or _UNCLOSED.search(text) or _STRAY_CLOSE.search(text))
