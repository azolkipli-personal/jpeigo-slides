"""Verification passes that run beside the pipeline and never block it.

Layer 1 (`backend/tests/verify_translation_roundtrip.py`) is deterministic and
lives with the tests. What is in this package is the model-assisted half:

- `render`        — PPTX -> PDF -> PNG, shared with the preview path
- `gemini_client` — one small client for text and inline-image questions
- `vision_qa`     — Layer 2: look at each rendered slide for layout damage
- `translation_review` — Layer 3: terminology and register consistency in the text

Both review passes are opt-in and report-only: they produce a report, they never
change a deck, and a failure inside them is recorded as a review error rather than
raised into the job.
"""
