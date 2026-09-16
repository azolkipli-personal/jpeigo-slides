# jpeigo-slide — Review: post-translation format & design integrity

**Date:** 2026-09-16
**Branch:** `feature/google-slides-native` (4 uncommitted files in working tree)
**Scope:** Can a more advanced AI model guarantee format/design integrity after translation, and what should change.
**Method:** read the actual pipeline (extractor → translator service → injector → export → preview), plus two surgical experiments (PPTX XML font check, live public-endpoint probe). Everything below marked ✅ was verified by running something, not inferred.

---

## 0. Two things to deal with before anything else

Both are **uncommitted working-tree edits** on the current branch.

### 🔴 P0 — The public auth wall is disabled

`middleware.ts:6`

```js
export const config = {
  matcher: ['/nonexistent-route'],   // ← was: '/((?!_next/static|_next/image|favicon.ico|login$|api/auth).*)'
};
```

The matcher now matches no real route, so the middleware body — which is correct and well-written, including a fail-closed 503 when `AUTH_SECRET` is unset and a 401 for `/api/*` — **never executes**. The comment above it still says "Skip static assets, the login page itself, and the auth endpoint", which is what the original matcher did. This reads like a debug-time bypass that was never reverted.

Exposure is real, not theoretical. The tunnel ingress is a plain public hostname with **no Cloudflare Access in front** (`~/.cloudflared/config.yml`: `jpeigo.aztechwerx.site → http://localhost:3002`).

✅ Verified from outside the LAN, over the public internet:

```
GET  https://jpeigo.aztechwerx.site/translator   → 200   (no redirect to /login)
GET  https://jpeigo.aztechwerx.site/api/translate-new → 405  (route exists, ungated)
GET  https://jpeigo.aztechwerx.site/api/export-new    → 405
GET  https://jpeigo.aztechwerx.site/api/upload-new    → 405
GET  https://jpeigo.aztechwerx.site/api/preview       → 405
```

A 405 (not a 401/307) proves the route is reached with no auth gate. Anyone on the internet can upload decks and run translations, which spends the `GEMINI_API_KEY` / `OPENCODE_API_KEY` balances on your dime. `/login` still renders (200) but is now purely decorative.

**Fix:** restore the original matcher, rebuild, verify with a curl from outside the LAN. One line.

### 🟠 P1 — `/api/health` no longer checks anything

`app/api/health/route.ts` is now the entire file:

```js
export async function GET() {
  return NextResponse.json({ status: 'healthy' });
}
```

It used to proxy the Python backend's health endpoint. It is now a hardcoded lie: the frontend health pill will show green with the backend dead. Either restore the proxy or delete the route and the pill — a fiction is worse than an absence.

---

## 1. How format preservation actually works today

Worth stating plainly, because it defines what is and isn't possible:

- **Extraction** (`backend/app/core/extractor.py`) walks shapes → paragraphs → runs, capturing per-run `FontStyle` (size, colour, name, bold, italic, underline, strike, `vertical`) and per-box `SpatialConstraints` (left/top/width/height/anchor). Runs are addressed by a synthetic ID: `run_{slide}_{shape}_{para}_{run}_{counter}`.
- **Translation** (`backend/app/main.py:431`) sends **each run's text to the LLM independently**, with one global glossary/context string shared by all of them. Results are cached in translation memory keyed on the individual run text.
- **Injection** (`backend/app/core/injector.py`) re-opens the **original** PPTX and writes translated text back into the matching run, re-applying font properties. Export passes `original_document=None` (`main.py:592`), so the extracted `SpatialConstraints` are **never used at injection time**.
- **Preview** (`app/api/preview/route.ts`) renders **only the translated deck**: `soffice --headless --convert-to pdf` → `pdftoppm` → PNGs, cached by `job_id`.

So "format preservation" currently means *font properties on the run survive*, plus one heuristic font-size shrink for EN→JA. There is no geometry logic, no fit check, and no verification of the produced file.

---

## 2. Defects found (all verified)

### 2.1 🔴 The Yu Gothic switch does not do what it says

`injector.py:146-150`

```python
if target_language == 'ja':
    run.font.name = 'Yu Gothic'
```

✅ Verified experimentally: `run.font.name` in python-pptx writes **only `<a:latin>`**. A saved run:

```xml
<a:rPr sz="1800"><a:latin typeface="Yu Gothic"/></a:rPr>
```

There is no `<a:ea>` element. CJK glyphs are rendered from the **East Asian** typeface (`a:ea`, else the theme's `minorEastAsian`), *not* `a:latin`. So Japanese text keeps the source deck's East Asian font and the override is largely cosmetic in the XML. Fix: write `a:ea` (and ideally `a:cs`) directly on `rPr`.

Related, and it bites the preview: **Yu Gothic is not installed on this machine** ✅ (`fc-list | grep -i "yu gothic"` → 0; only Noto Sans/Serif CJK JP and Droid Sans Japanese). So the in-app preview renders with a substituted font. What you see in the preview is not what PowerPoint shows on Windows — and on macOS the JP client doesn't have Yu Gothic either. Font choice needs to be a deliberate, checked decision, not a hardcoded name.

### 2.2 🔴 Per-run font scaling reintroduces font disproportion

`injector.py:374-386` (and the table branch at `306-319`)

```python
scale = calculate_font_scale(tr.original_text, tr.translated_text)   # per RUN
...
adjusted_size = tr.adjusted_font_size
if scale < 1.0 and orig_font_size:
    adjusted_size = orig_font_size.pt * scale   # ← overwrites any explicit fit
if adjusted_size:
    run.font.size = Pt(adjusted_size)
```

Two problems:

1. **The scale is computed per run, from that run's own text.** A paragraph split across several runs (any deck with a bold lead-in, coloured term, or a link) gets a *different* font size per run. That is exactly the "font disproportion" symptom this code was added to fix, moved rather than removed. Scale must be computed once per paragraph (or textbox) and applied uniformly to all its runs.
2. **The ratio scale silently overrides `adjusted_font_size`.** The explicit, geometry-derived fit value is discarded whenever the character-ratio heuristic fires. Priority is backwards: a box-fit measurement should win over a char-width guess.

### 2.3 🟠 The fit machinery is dead code

✅ `grep -rn "check_text_fit|estimate_text_width|calculate_font_scale" app/` → the only call sites are the two `calculate_font_scale` lines above. `check_text_fit()` (`injector.py:75`) is **never called from anywhere**. `estimate_text_width()` is only used inside it. `adjusted_font_size` / `adjustment_reason` are read by the injector (`315`, `382`) but **never written by any code path** — the service, the translate endpoint and the export endpoint all leave them `None`.

So the intended design — measure text against the box, shrink to fit, tell the injector — is half-built: the consumer exists, the producer was never written. `SpatialConstraints` is extracted and then passed as `None` at export.

### 2.4 🟠 SmartArt text is written to the wrong nodes

The extractor and injector enumerate SmartArt `<a:t>` elements differently.

Extractor (`extractor.py:290-308`) — **skips empty elements** but keeps a dense counter:

```python
for pt in dgm_xml.iter(...):
    for t_elem in pt.iter(...):
        text = (t_elem.text or '').strip()
        if not text:
            continue                    # ← skipped
        run_id = generate_run_id(slide_idx, f"smartart_{shape_idx}", 0, text_idx)
        text_idx += 1                    # ← counts only non-empty
```

Injector (`injector.py:231-238`) — **keeps empty elements**:

```python
a_t_elements = []
for pt in dgm_xml.iter(...):
    for t_elem in pt.iter(...):
        a_t_elements.append(t_elem)     # ← no empty filter
...
t_elem = a_t_elements[run_idx]           # run_idx came from the extractor's dense counter
```

SmartArt data models routinely contain empty `<a:t>` placeholder points, so the indices diverge after the first one. Result: translated text lands in the **wrong SmartArt node**, silently — it isn't a failure, so it never appears in `failed_runs`. Wrong-but-plausible output is the worst failure mode for a client deck. Fix: give extraction and injection one shared enumeration (or have extraction store the resolved node path, which it already builds at `297-305` and then throws away).

### 2.5 🟠 Per-run translation fragments sentences

`main.py:431` translates each run in isolation. A Japanese paragraph split into runs — routine whenever formatting changes mid-paragraph — becomes N independently-translated fragments, so grammar and terminology break across the seam, and the translation-memory cache locks those fragments in permanently. This is also the root cause of the overflow problems §2.2 and §2.3 are trying to paper over: **text length is the variable that drives overflow, and nothing in the pipeline constrains it.** Translating per paragraph with the run boundaries preserved (translate the joined paragraph, redistribute the result across runs by proportion, or ask for a run-boundary-delimited response) removes the need for most of the font-scaling hackery.

### 2.6 🟡 Nothing is verified after injection, and failures are swallowed

`main.py:586-605` — export runs `inject_translations`, and if `not success` it loops over the failed runs and `print()`s them. The file is served either way. Runs where every provider failed (`success=False`, original text passed through, so Japanese remains on an English deck) are counted only for a Telegram notification (`515-518`). `failed_runs` from injection never reaches the UI.

Net effect: a deck can come back 20% untranslated, or with text in the wrong SmartArt nodes, and the app reports success. The user has no way to know without manually eyeballing every slide.

### 2.7 🟡 The frontend hides translation errors

`app/translator/page.tsx:328-333`

```js
} catch (err) { console.error(...); setError(err.message || text.translationFailed); }
finally {
  ...
  setError(null); // Clear error on completion
}
```

`finally` runs after `catch`, so the error set on failure is cleared in the same commit. Translation failures render nothing. (`console.error` still fires, which is why it was probably never noticed.)

### 2.8 🟡 Smaller items

- **No tests at all** — `backend/tests/` does not exist, and there are no verification scripts in the repo. Nothing stops these regressions from returning.
- **Hardcoded model IDs** (`translators/service.py:508-516`): `gemini-3-pro-preview`, `gemini-3.5-flash`, `gemini-3.1-flash-lite`, `kimi-k2.5`, `qwen3.7-plus`, `minimax-m2.5`. If an ID is wrong or retired, translation silently returns the original text with `success=False` and the failover chain masks it. The model list should be validated against the provider at startup, not trusted from a literal.
- **`[INJECTOR]` debug `print()`s** on the hot path (`311`, `346`, `377`).
- **Gemini translator reuses `parts`** as both the prompt-part list and the response-part list (`service.py:61-74` then `97`). Harmless today, an easy trap later.

**Not examined:** the `feature/google-slides-native` branch's Google Slides path, `export-new`, `cache.py` internals, `notify.py`, and the slide-rendering React components beyond error handling. The upstream `export`/`injector` path above is what the preview route uses, so it is the one that matters for format integrity.

---

## 3. Your actual question: can a better AI model verify format & design after translation?

**Short answer: yes — but a stronger model is not the main lever, and used alone it will not do the job.**

The distinction that matters: format integrity has a *structural* half and a *perceptual* half, and they need different tools. A text LLM can't see a slide at all; even a top vision model looking at a rendered PNG can't count `<a:t>` elements or verify that `a:ea` was written. The structural half is deterministic and should never be delegated to a model — it's cheaper, exact, and has no false-positive rate.

Your pipeline is unusually well-positioned here, because it already has the two hard pieces: **per-run addressing** (`run_id` survives extract → translate → inject) and **a working render path** (`/api/preview` does PPTX → PDF → PNG). Both halves of the answer are mostly plumbing on top of what exists.

### Layer 1 — Deterministic structural verification (no AI, highest ROI)

Re-open the exported PPTX and diff it against the original. Catches §2.1, §2.2, §2.4, §2.6 automatically:

- Shape / paragraph / run-count parity per slide; flag anything dropped or duplicated.
- **Per-paragraph font-size uniformity** — flag any paragraph whose runs disagree on size. This is §2.2, detected in one pass.
- **Font landing check** — assert the intended font is present in `a:latin` *and* `a:ea` for CJK runs (§2.1).
- **Text-doesn't-fit check** — measure real text extents with actual font metrics (`fontTools` + `PIL`, or `Pillow`'s `ImageFont.getbbox` against the installed TTF) and compare against the shape's box, accounting for line count and insets. This is what `check_text_fit` was reaching for with a 2.2×-per-CJK-char guess; doing it with real metrics is both simpler and correct.
- **Residue check** — count runs still containing source-language characters on a `target=en` job, and count `success=False` passthroughs.
- **SmartArt node mapping** — assert each translated value landed in the node it came from.

Output: a per-slide JSON report keyed by `run_id`. Cost: milliseconds, no tokens, no false positives. **This is where I'd start.** It would have caught every format bug in §2 without a single API call.

### Layer 2 — Visual QA with a vision model (this is where "a more advanced AI model" genuinely earns its place)

Once Layer 1 has eliminated structural breakage, the residue is genuinely perceptual: text overflowing its box visually, overlapping shapes, a table column that no longer reads as a column, an image pushed off-canvas, placeholder text left empty, a line whose sizes look inconsistent. Geometry can flag *candidates*; only a look can judge *severity*.

The mechanism: render the **original** and the **translated** deck to PNGs, pair them per slide, and ask a multimodal model to compare against a fixed rubric, returning structured JSON per slide (`{slide, issue, severity, region, note}`). Aggregate into a QA report; show a badge on affected slide thumbnails in the existing preview UI.

Practical notes:

- **`/api/preview` only renders the translated deck today** (§1) — you need to add an original-render path. The original is still on disk at `settings.upload_dir/{job_id}_*.pptx` (`main.py:576-582`), so this is a small addition, not new infrastructure.
- **No new provider needed.** `GEMINI_API_KEY` is already configured, and the Gemini flash family is multimodal. (I could not enumerate the key's live model list — that call was blocked — so verify which vision-capable model IDs your key can actually reach before wiring it in.)
- **⚠️ LibreOffice ≠ PowerPoint, and this will colour every finding.** LibreOffice substitutes fonts it doesn't have, and it does not implement PowerPoint's autofit/line-breaking identically. On this box **Yu Gothic is absent** ✅, so JP previews render in Noto CJK. A vision model judging a LibreOffice render is judging a *proxy*: expect false positives for anything font-metric-dependent, and treat results as advisory signals for a human, never as a pass/fail gate. If you want the vision pass to be trustworthy, install the fonts the deck actually specifies (Yu Gothic is a Windows font — licensing applies; Noto Sans JP is the practical, freely-installable substitute if you're willing to standardise on it).
- **Cost scales with slides.** Run it on export, opt-in per job — not on every translation.

### Layer 3 — Translation-quality review by a second model (text-only, cheapest per unit of value)

Independent of layout, a second model reading the `translated_runs` list can catch what the translator itself can't see: terminology drift across slides, leftover untranslated source text, prompt/instruction leakage, sentences fragmented at run boundaries (§2.5), and register problems — which matters for a Japanese client deliverable, where politeness level consistency is as much a quality signal as accuracy. Text-only means it's cheap and fast, and it's the layer most likely to catch something a client would actually complain about.

### The honest trade-off summary

- **Structural problems → deterministic checks.** Do not use AI. AI is strictly worse here: slower, costlier, non-deterministic, and it cannot see the XML.
- **Perceptual problems → vision model.** AI is the only option, and it's a *proxy judgment on a proxy render*.
- **Content problems → text model.** Cheap and effective.
- **The pipeline fixes in §2 (per-paragraph scaling, `a:ea`, paragraph-level translation, restored auth) matter more than the verification layer.** Verification tells you the deck is broken; it doesn't stop the breakage. A QA layer on top of a broken injector just produces an accurate bug report faster.
- **Do not let the QA model auto-fix anything at first.** Report-only until you've measured its false-positive rate on 5–10 real decks. An auto-fixer with a 10% false-positive rate on a client deliverable is worse than no QA at all.

---

## 4. Suggested update list, prioritised

**P0 — do now**
1. Restore the `middleware.ts` matcher and rebuild; verify the public URL 401/307s. (§0)
2. Restore or remove `/api/health` — stop reporting a fixed "healthy". (§0)

**P1 — the format fixes (these are the ones you asked about)**
3. Compute font scale **per paragraph / per textbox**, apply uniformly to its runs. (§2.2)
4. Make explicit box-fit sizing win over the ratio heuristic — don't let `scale` overwrite `adjusted_font_size`. (§2.2)
5. Write `a:ea` + `a:cs` alongside `a:latin` for JP target; make the JP font a configured, checked choice. (§2.1)
6. Unify SmartArt enumeration between extractor and injector (or use the XML path extraction already builds). (§2.4)
7. Translate per paragraph with run boundaries preserved, instead of per run. (§2.5)
8. Surface failures: return `success=False` and injector `failed_runs` to the UI, per slide. (§2.6)
9. Fix the frontend error swallow at `page.tsx:328-333`. (§2.7)

**P2 — build the verification layer**
10. **Layer 1 deterministic verifier** — a post-export structural report. Start here; no AI, biggest catch rate. (§3)
11. Add original-deck rendering to the preview path so before/after pairs exist. (§3)
12. **Layer 2 vision QA** on export, opt-in, report-only; install/standardise fonts first so the render is meaningful. (§3)
13. **Layer 3 translation-quality review** for terminology and register consistency. (§3)
14. Validate the hardcoded model ID list against the providers at startup. (§2.8)
15. Stand up a `backend/tests/` golden-deck test: extract → translate (stubbed) → inject → assert structural parity. This is the actual guard against all of the above coming back. (§2.8)

---

## 5. What I'd measure before and after

Track one number per job: **structurally-flagged run count** (Layer 1) plus **vision-flagged slides** (Layer 2). Then you can tell whether a change helped, and whether an expensive QA model is actually earning its cost — which is the only way to know if "a more advanced AI model" was the right buy for this pipeline.

---

## 6. Status — 2026-09-16

### Done and verified

**P0 — the two regressions from §0**
- `middleware.ts` and `app/api/health/route.ts` reverted to `HEAD` (byte-identical, `git diff --stat` empty).
- Live proof from the public URL, no cookie: `/translator` 200 → **307** `/login?next=%2Ftranslator`; `/api/translate-new`, `/api/export-new`, `/api/upload-new`, `/api/preview` 405 → **401**; correct passphrase → 200 + `HttpOnly` cookie → `/translator` 200.
- `/api/health` again reports backend state, including `gemini_configured` / `opencode_configured`.

**Injector (§2.1–§2.4, §2.6–§2.7)** — `backend/app/core/injector.py` rewritten
- `a:ea` + `a:cs` written beside `a:latin`, in schema order, idempotently; font from `JP_FONT_FAMILY` (default `Yu Gothic`).
- One font scale per paragraph instead of per run — the cause of mixed sizes inside one paragraph.
- `adjusted_font_size` (the geometry-fit result) is no longer overwritten; `resolve_font_size` takes the minimum.
- `check_text_fit()` is now actually called with real `SpatialConstraints` instead of `None`; SmartArt enumeration matches the extractor's document-order walk.
- Export surfaces failed injections (`X-Injection-Failed` / `X-Injection-Total`) instead of printing and serving a partial deck anyway; the Next proxy re-emits those headers and `page.tsx` raises them in the UI.

**Layer 1 (§3, item 10) — built: `backend/tests/verify_translation_roundtrip.py`**
- Live mode (`--source`, through the real backend) and offline mode (`--original` + `--translated`); `--inspect` scores a deck with no original.
- Checks slide/paragraph/run parity, emptied runs, per-paragraph size uniformity, `<a:ea>` on Japanese runs, provider failures (`success=False`), leftover source text.
- **Result on `test_real.pptx` (10 slides, 204 runs): 0 violations.** Reproducible across two runs (185 changed / 19 identity / 0 provider failures, identical byte size); export `X-Injection-Failed=0`.
- The 19 untouched runs are legitimately untouchable: single letters (`R`, `W`, `T`), figures (`20,084,500`, `0円`), brand `NavRAG`.
- Measured against the 62-slide Orix export from 2026-08-24 for comparison (that job targets English, so its 98 Japanese runs are untranslated leftovers and prove nothing about the `a:ea` fix — noted, not claimed).

**Unit regression guard (item 15, first half) — `backend/tests/test_injector_units.py`**
- 17 checks, all passing, no pytest needed. Each asserts the post-fix behaviour *and* demonstrates the pre-fix one, e.g. one paragraph of `test_real.pptx`: per-run scaling gave **10.5pt vs 18.0pt** in the same paragraph; paragraph scaling now gives **11.0pt to both**.

### Still open
- **§2.5 per-run translation fragmentation** (`backend/app/translators/service.py`, untouched) — "Recap (…" splits into `'R' | 'ecap ('`, so the model sees a bare `'R'` and the fragment stays English. Layer 1 now *reports* this (18 runs) but does not fix it. This is the largest remaining quality item.
- **Font decision (§2.1)** — `JP_FONT_FAMILY` defaults to `Yu Gothic`, which is not installed here, so previews still substitute Noto. Switching to a font that exists is a config change, not a code change.
- **SmartArt enumeration** is duplicated in extractor and injector with the same expression; a shared helper would make drift impossible rather than merely absent.
- **Layer 2 / Layer 3** (items 11–13) and the golden-deck test's stubbed-translation half (item 15) not started.
