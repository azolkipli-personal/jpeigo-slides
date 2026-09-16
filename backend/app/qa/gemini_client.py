"""Compatibility shim — the QA client moved to `app.qa.client`.

That module now serves both lanes (Gemini and OpenCode), so this one only
re-exports what callers used to import from here. New code should import
`app.qa.client` directly.

The old `generate(api_key, model, …)` signature is gone on purpose: the client
resolves the key for the model's own lane, so a stale key argument cannot send a
Gemini credential to OpenCode or the reverse.
"""
from app.qa.client import (  # noqa: F401
    QAError,
    generate,
    key_problem,
    lane_for,
    load_json,
)

__all__ = ['QAError', 'generate', 'key_problem', 'lane_for', 'load_json']
