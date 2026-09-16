"""Layer 2 — vision QA: look at each rendered slide and report layout damage.

Opt-in and report-only. The structural half of format integrity is deterministic
and belongs to Layer 1; a vision model cannot count `<a:t>` elements and should
not be asked to. What it can do is notice what a human notices when they open the
deck: text running past a shape, a squeezed line, a blank placeholder, a box that
no longer lines up with its neighbour.

Two deliberate limits:

- One slide per call, so a finding can never be attributed to the wrong slide.
- The prompt forbids judging wording or translation quality. That is Layer 3, and
  a reviewer asked to comment on everything will report the translation instead of
  the layout.

Usage:

    cd backend && venv/bin/python -m app.qa.vision_qa deck.pptx [--max-slides N] \
        [--first-slide N --last-slide M] [--json]

`--first-slide/--last-slide` take an absolute slice of the deck, so a long deck can be
checked in chunks that each fit inside a request timeout. Slide numbers in the report
stay absolute in every case, so chunked output reads like a single pass.
"""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from app.model_catalog import DEFAULT_VISION_MODEL, vision_cost
from app.qa import client, render

# The slide check runs on the OpenCode lane by default: that subscription is
# flat-rate, so a 40-slide deck costs no per-image spend. The model is one of the
# verified see-ers in app/model_catalog.py, not a name picked by feel — and the
# catalog is read here so the CLI and the app cannot recommend different models.
# (The default moved off deepseek-v4.1-flash: it sees slides, but it under-calls
# layout damage, and a check that under-calls certifies a broken deck.)
DEFAULT_MODEL = os.environ.get('VISION_QA_MODEL') or DEFAULT_VISION_MODEL


def slide_number(image: Path) -> int | None:
    """A rendered slide's absolute number, taken from its file name.

    pdftoppm numbers by absolute page even when only a range is rendered, so the
    number survives a chunked check: slide 12 of a deck reviewed in chunks of three
    is still reported as 12 — the number the user sees in PowerPoint, not 3.
    """
    try:
        return int(image.stem.split('-')[-1])
    except (ValueError, IndexError):
        return None


def deck_slide_count(pptx_path) -> int | None:
    """The deck's slide count, read from the .pptx itself (no render round trip).

    The prompt says "slide N of M", and M is the deck, not the chunk: a reviewer told
    it is looking at 3 slides out of 3 judges a slice as if it were the whole talk.
    """
    try:
        from pptx import Presentation
        return len(Presentation(str(pptx_path)).slides)
    except Exception:
        return None

ISSUE_TYPES = (
    'text_overflow', 'clipping', 'overlap', 'misalignment',
    'missing_glyph', 'cramped', 'empty_placeholder', 'other',
)

PROMPT = """You are reviewing the layout of a presentation slide.

This image is slide {number} of {total} from a deck that an automated pipeline \
translated from Japanese into English.

Report only layout damage that is visible in the image:
- text_overflow: text crosses a shape's border, or runs off the slide
- clipping: text is cut off by its own text box
- overlap: text collides with other text or with graphics
- misalignment: boxes, bullets or columns no longer line up with their neighbours
- missing_glyph: blank boxes, tofu, or unreadable substitutes standing in for characters
- cramped: text is visibly squeezed against a border, or its line spacing has collapsed
- empty_placeholder: a shape that should clearly hold text is blank

Do not comment on wording, translation quality, or language choice — a separate \
review covers that. A slide with no layout damage must come back as "ok"; do not \
invent issues to seem useful. Small aesthetic opinions are not issues.

Answer with JSON only, no prose:
{{"verdict": "ok" | "minor" | "broken",
  "issues": [{{"type": "{types}", "severity": "low" | "medium" | "high",
             "where": "the shape or text involved",
             "detail": "what is wrong, in one sentence"}}],
  "summary": "one sentence on this slide's layout"}}
""".replace('{types}', ' | '.join(ISSUE_TYPES))


async def review_slide(model: str, image: Path, number: int, total: int,
                       semaphore: asyncio.Semaphore | None = None,
                       usage: dict | None = None) -> dict:
    """One slide, one call, one verdict. `usage` collects the billed token counts."""
    prompt = PROMPT.format(number=number, total=total)
    guard = semaphore or asyncio.Semaphore(1)
    async with guard:
        answer = await client.generate(model, prompt, images=[image],
                                       max_output_tokens=8192, usage=usage)
    parsed = client.load_json(answer)

    issues = []
    for issue in parsed.get('issues') or []:
        if not isinstance(issue, dict):
            continue
        issue_type = str(issue.get('type', 'other'))
        issues.append({
            'slide': number,
            'type': issue_type if issue_type in ISSUE_TYPES else 'other',
            'severity': str(issue.get('severity', 'low')),
            'where': str(issue.get('where', '')),
            'detail': str(issue.get('detail', '')),
        })
    verdict = str(parsed.get('verdict', 'ok'))
    if issues and verdict == 'ok':
        # The model listed concrete damage and then called the slide clean; the
        # findings are the more specific signal, so keep them and say so.
        verdict = 'minor'
    return {'slide': number, 'verdict': verdict, 'summary': str(parsed.get('summary', '')),
            'issues': issues}


def new_report(pptx_path, model: str) -> dict:
    """The report shape both review paths return, so the UI parses one thing."""
    return {
        'deck': str(pptx_path),
        'model': model,
        'slides_rendered': 0,
        'slides_checked': 0,
        'deck_slides': deck_slide_count(pptx_path),
        'flagged_slides': [],
        'issues': [],
        'errors': [],
        # Token counts as the providers report them, and the dollar estimate those
        # counts imply. The estimate is None when the plan publishes no price.
        'usage': {'prompt_tokens': 0, 'completion_tokens': 0},
        'estimated_cost_usd': None,
    }


def summarize(report: dict) -> dict:
    """Refresh the one-line summary; keeps issues in slide order as they arrive."""
    report['issues'].sort(key=lambda issue: issue.get('slide') or 0)
    report['flagged_slides'].sort(key=lambda slide: slide.get('slide') or 0)
    checked, rendered = report['slides_checked'], report['slides_rendered']
    report['summary'] = (
        f'{checked}/{rendered} slides reviewed; '
        f'{len(report["flagged_slides"])} flagged; {len(report["issues"])} issues'
    )
    if report['errors']:
        report['summary'] += f'; {len(report["errors"])} review errors'
    usage = report.get('usage') or {}
    cost = vision_cost(report.get('model', ''), usage.get('prompt_tokens') or 0,
                       usage.get('completion_tokens') or 0)
    if cost is not None:
        report['estimated_cost_usd'] = round(cost, 5)
        tokens = (usage.get('prompt_tokens') or 0) + (usage.get('completion_tokens') or 0)
        report['summary'] += f'; {tokens:,} tokens, est. ${cost:.4f}'
    return report


async def _collect(report: dict, model: str, images: list[Path], numbers: list[int],
                   total: int, concurrency: int, on_progress=None) -> dict:
    """Review every slide, reporting after each one finishes.

    Progressive, not `gather`: a slide check of a real deck takes minutes, and the
    caller needs to see slides land one by one (and keep the ones already reviewed if a
    later call dies) instead of waiting for the slowest slide in the deck.
    """
    semaphore = asyncio.Semaphore(max(1, concurrency))
    usage = report.setdefault('usage', {'prompt_tokens': 0, 'completion_tokens': 0})
    pending = {
        number: asyncio.create_task(
            review_slide(model, image, number, total, semaphore, usage))
        for number, image in zip(numbers, images)
    }

    while pending:
        done, _ = await asyncio.wait(pending.values(), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            number = next(n for n, pending_task in pending.items() if pending_task is task)
            del pending[number]
            try:
                result = task.result()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:                          # noqa: BLE001 — per slide
                # One unreadable slide is not a failed check: record it and keep going,
                # because the remaining slides still have damage to report.
                report['errors'].append({'slide': number, 'error': str(exc)[:300]})
                summarize(report)
                if on_progress:
                    on_progress(report)
                continue
            report['slides_checked'] += 1
            report['issues'].extend(result['issues'])
            if result['verdict'] != 'ok' or result['issues']:
                report['flagged_slides'].append(result)
            summarize(report)
            if on_progress:
                on_progress(report)
    return summarize(report)


async def review_deck_progressive(pptx_path, model: str | None = None,
                                  dpi: int = render.DEFAULT_DPI,
                                  max_slides: int | None = None, concurrency: int = 3,
                                  images: list[Path] | None = None,
                                  on_progress=None) -> dict:
    """Whole-deck review with a progress callback — the shape a background job uses.

    The whole deck in one pass, deliberately: coverage is the point, and a caller that
    cannot wait must poll rather than ask for fewer slides. Rendering happens once here,
    so a 19-slide check pays for one LibreOffice conversion, not one per request.
    """
    report, images, numbers, total, problem = _prepare(
        pptx_path, model, dpi, max_slides, images, None, None)
    if problem:
        return report
    return await _collect(report, report['model'], images, numbers, total, concurrency,
                          on_progress)


async def review_deck(pptx_path, model: str | None = None, dpi: int = render.DEFAULT_DPI,
                      max_slides: int | None = None, concurrency: int = 3,
                      images: list[Path] | None = None,
                      first_slide: int | None = None,
                      last_slide: int | None = None) -> dict:
    """Render a deck and review each slide, waiting for the whole set.

    `first_slide`/`last_slide` take an absolute slice for scripts and for the CLI, where
    a caller can loop over a deck without a proxy timeout in the way. Slide numbers stay
    absolute, so a sliced report reads exactly like a whole-deck one.

    Never raises for a slide-level failure: a model error is recorded under
    'errors' and the remaining slides are still reviewed, because a partial report
    is more useful than none and this pass must not affect the export.
    """
    report, images, numbers, total, problem = _prepare(
        pptx_path, model, dpi, max_slides, images, first_slide, last_slide)
    if problem:
        return report
    return await _collect(report, report['model'], images, numbers, total, concurrency)


def _prepare(pptx_path, model, dpi, max_slides, images, first_slide, last_slide):
    """Shared setup: report skeleton, key check, render, absolute slide numbers."""
    model = model or DEFAULT_MODEL
    report = new_report(pptx_path, model)

    problem = client.key_problem(model)
    if problem:
        # Stop with the reason rather than reviewing nothing and returning a clean
        # report: a missing key must not look like a deck with no damage.
        report['errors'].append({'slide': 0, 'error': problem})
        report['summary'] = problem
        return report, [], [], 0, problem

    if images is None:
        images = render.render_deck(pptx_path, dpi=dpi, max_slides=max_slides,
                                    first_slide=first_slide, last_slide=last_slide)
    report['slides_rendered'] = len(images)
    numbers = [slide_number(image) or (index + 1) for index, image in enumerate(images)]
    report['first_slide'] = numbers[0] if numbers else None
    report['last_slide'] = numbers[-1] if numbers else None
    # "slide N of M" must name the deck's M, not how many slides this call rendered.
    total = report['deck_slides'] or (numbers[-1] if numbers else len(images))
    return report, images, numbers, total, None


def _print(report: dict) -> None:
    print(report['summary'])
    print(f'model: {report["model"]}')
    for slide in report['flagged_slides']:
        print(f'  slide {slide["slide"]}: {slide["verdict"]} — {slide["summary"]}')
        for issue in slide['issues']:
            print(f'      [{issue["severity"]}/{issue["type"]}] {issue["where"]}: {issue["detail"]}')
    for error in report['errors']:
        print(f'  slide {error["slide"]}: review error — {error["error"]}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Layer 2 vision QA on a deck')
    parser.add_argument('deck', help='path to a .pptx file')
    parser.add_argument('--model', default=None)
    parser.add_argument('--max-slides', type=int, default=None)
    parser.add_argument('--first-slide', type=int, default=None,
                        help='first slide of an absolute range (1-based)')
    parser.add_argument('--last-slide', type=int, default=None,
                        help='last slide of an absolute range, inclusive')
    parser.add_argument('--dpi', type=int, default=render.DEFAULT_DPI)
    parser.add_argument('--json', action='store_true', help='print the full report as JSON')
    args = parser.parse_args()

    if not render.render_available():
        print('cannot render: soffice and pdftoppm are both required (see app/qa/render.py)')
        return 2

    try:
        report = asyncio.run(review_deck(args.deck, model=args.model, dpi=args.dpi,
                                         max_slides=args.max_slides,
                                         first_slide=args.first_slide,
                                         last_slide=args.last_slide))
    except render.RenderError as exc:
        print(f'render failed: {exc}')
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print(report)
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
