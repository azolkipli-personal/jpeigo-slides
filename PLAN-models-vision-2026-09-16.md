# Plan — model list refresh + a vision-model selector for the slide check

Written 2026-09-16. Status: **awaiting Ammar's approval** (2 open choices at the bottom).

## Why

Two problems, one ask ("update the list on the app, particularly the models that
come with vision support"):

1. **The list is stale and duplicated.** The dropdown in `app/translator/page.tsx`
   and the registry in `backend/app/translators/service.py` disagree with each
   other and with the providers. The dropdown says "Kimi K2.5" while the registry
   sends `kimi-k3`; "Qwen Max" while it sends `qwen3.7-plus`; the registry also
   holds `glm`/`kimi`/`minimax`/`qwen`/`ollama`/`google-cloud` lanes the dropdown
   never shows.
2. **Nothing tells you which models can see a slide.** The providers won't say:
   Gemini's `models` list has no modality field, and OpenCode's `/models` returns
   only `{id, object, created, owned_by}`. So vision support was measured.

## Measurements (2026-09-16, real calls, no guesses)

Test image: 400x100 PNG, five flat colour blocks (red, blue, yellow, green,
purple), built by hand with `zlib` so the probe has no image-library dependency.
Question: name the colours left to right. A blind model must guess five colours,
so ≥3 matches is a reliable pass.

- **Text lane** (`/tmp/model_text_probe.py`): real translator classes, one JA→EN
  unit — the same payload `/api/translate` sends (temperature 0.3, session header).
  **20/23 candidates usable.**
- **Vision lane** (`/tmp/vision_probe.py`): 10 Gemini models + all 37 OpenCode
  models. Results in `/tmp/vision_probe_results.json`.
- Gotcha found while probing: a raw OpenCode call without `x-opencode-session`
  returns 400 `MissingSessionID` for **every** model, making all 37 look dead.
  The first vision sweep was invalid for that reason and was re-run.

### Gemini — every model tested sees (10/10, all 5/5 blocks)

`gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-3.1-flash-lite`,
`gemini-3.1-pro-preview`, `gemini-3.5-flash`, `gemini-3.5-flash-lite`,
`gemini-3.6-flash`, `gemini-3.8-flash`, `gemini-flash-lite-latest`,
`gemini-pro-latest`.

`gemini-2.5-pro` **fails the translation lane**: HTTP 200 with no candidate text
(`finishReason: MAX_TOKENS`) — its thinking tokens eat the whole output budget in
the app's payload, so it is unusable as shipped. Excluded.

### OpenCode — 13 of 15 candidates translate, 6 of those also see

Both translate **and** see: `kimi-k3`, `qwen3.7-plus`, `qwen3.8-max`,
`minimax-m3`, `deepseek-v4.1-flash`, `longcat-2.0` — plus, from the 37-model
sweep, `deepseek-flash`, `deepseek-v4-flash-vision-exp`, `glm-5.3-flash`,
`mimo-v2.5`, `omen-alpha`, `qwen3.6-plus`, `qwen3.8-flash`.

Translate but **blind** (image content rejected with 400): `deepseek-v4-flash`,
`deepseek-v4-pro`, `glm-5.3`, `hy3`, `kimi-k2.6`, `mimo-v2.5-pro`, `minimax-m2.5`.

Broken outright: `grok-4.6` (401, not supported on this plan), `gpt-5.6-luna`
(HTTP 500).

**Both OpenCode models the app ships today (`deepseek-v4-flash`,
`minimax-m2.5`) are blind** — which is why the vision selector needs its own list.

### Caveat that changes code

`minimax-m3` returns its reasoning in the answer text:
`<think>The user wants me to translate Japanese to English, preserving…`.
Nothing in the codebase strips reasoning wrappers (`grep think>` is empty), so
adding `minimax-m3` without a strip would paste that into slides.

## Changes

### 1. One catalog, one endpoint (`backend/app/model_catalog.py`, new)

Single source of truth for both lists, replacing the copy in `page.tsx`:

- `TRANSLATE_MODELS` — the curated shortlist below: `key` (what the frontend
  sends), lane, real `model_id`, EN/JA label, `recommended` flag.
- `VISION_MODELS` — every model verified to read an image, same shape.
- `GET /api/models` in `main.py` returns `{translate: [...], vision: [...]}`.

### 2. Curated translate shortlist (12 — newest working per family)

Recommended (free-tier friendly): `gemini-25-flash-lite` → 2.5 Flash Lite.

- Gemini: `gemini-flash-lite` 3.1 Flash Lite · `gemini-flash` 3.5 Flash ·
  **`gemini-flash-38` 3.8 Flash (new)** · `gemini-pro` 3.1 Pro
- OpenCode: `opencode-deepseek` V4 Flash · **`opencode-deepseek-41` V4.1 Flash
  (new)** · `opencode-kimi` Kimi K3 · `opencode-qwen` retargeted to Qwen 3.8 Max ·
  `opencode-minimax` retargeted to MiniMax M3 · **`opencode-glm` GLM 5.3 (new)** ·
  **`opencode-longcat` LongCat 2.0 (new)**

Retired from the list: `gemini-2.5-flash` (superseded by 3.8), `kimi-k2.6`,
`deepseek-v4-pro`, `minimax-m2.5`, `qwen3.7-plus` (still reachable through the
registry, just not offered).

### 3. Register the new models (`backend/app/translators/service.py`)

Add the four new entries to the translator dict; keep every existing key working
so a saved selection still resolves. Add `_strip_reasoning()` and apply it in the
Gemini/OpenCode lanes before returning text, so `minimax-m3`'s `<think>` block
(and any future reasoning wrapper) cannot reach a slide.

### 4. Vision-model validation for the slide check

`POST /api/qa/vision` currently accepts any `model` string. Make it:
reject anything not in `VISION_MODELS` with a clear 400, default to
`gemini-3.5-flash`, and record the model in the report (already does).

### 5. Slide-check panel in the UI (new — no QA UI exists today)

`app/translator/page.tsx`:

- fetch `/api/models` on mount, render the translate dropdown from it, with the
  static list kept as a fallback so a backend hiccup cannot empty the picker;
- fix the stale labels (Kimi K2.5 → Kimi K3, Qwen Max → Qwen 3.8 Max,
  Gemini 3 Pro → Gemini 3.1 Pro);
- new "Slide check" panel under the preview: vision-model selector (from
  `vision`), translated/original toggle reusing `previewWhich`, a "Check slides"
  button, and the findings per slide (severity, slide no., issue, suggestion);
- render the stored report from the job's `qa_reports.vision` so a check survives
  a page reload.

New proxy route `app/api/qa/route.ts`, same pattern as `app/api/preview/route.ts`
(forward to `PYTHON_BACKEND_URL`, no key needed — localhost is trusted).

### 6. Drift guard + docs

- `backend/tests/test_model_catalog.py`: every catalog key resolves in the
  registry, every `VISION_MODELS` entry appears in the probe results file as
  `VISION`, no label mentions a model ID the registry does not use.
- Update `pptx-translator` skill: catalog is the single source; the
  `x-opencode-session` trap for bare probes; the `<think>` stripping rule.
- Update `REVIEW-format-integrity-2026-09-16.md` "Still open".

## Verification (before I ask you to test)

1. `venv/bin/python tests/test_model_catalog.py` — catalog ↔ registry agree.
2. `tsc --noEmit`, `npx jest`, `npm run build` — clean.
3. Restart both user units; `curl /api/models` returns both lists.
4. Pick one Gemini and one OpenCode vision model in the panel and run a real
   slide check on the FADC job (`ba354689…`) against `translated` and `original`;
   confirm the report renders and the non-vision rejection works.
5. Then hand the tunnel URL over for your browser test — no commit, no tag until
   you say so.

## Open choices

1. **Slide-check lane** — Gemini only (smallest change: the pass already speaks
   Gemini), or Gemini **and** OpenCode (one more client path, but the OpenCode Go
   subscription is flat-rate, so a 39-slide check costs no per-image spend).
2. **Trim the 12-model translate list** — anything above you do not want in the
   dropdown.
