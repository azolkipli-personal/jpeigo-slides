#!/usr/bin/env python3
"""Re-inject a real job's translations and measure the layout-overflow artifacts.

Standalone — no pytest, no network, no API spend (the job store already holds the
translations):

    cd backend && venv/bin/python tests/verify_deck_overflow.py

What it does:

  1. loads job `0e6cb705-37fb-40f1-8cb6-584dfeb27ab2` from the job store,
  2. injects its runs into the PDF->PPTX intermediate with the real injector,
  3. measures, on the intermediate (source) and on the injected deck:
       * frames still on spAutoFit (SHAPE_TO_FIT_TEXT),
       * frames with wrap off whose translated text grew,
       * frames with wrap off whose text no longer fits the box width,
       * text runs whose translated width exceeds the box width,
       * the growing-frame trio the gap-1/gap-2 acceptance pins: frames whose
         translated text is longer than its source (spaces ignored), and how
         many of those are still on spAutoFit / still without wrap,
       * text frames whose box sits past the slide's right edge (off-slide
         boxes — clipped at the boundary whatever autofit/wrap does),
  4. renders both decks with app/qa/render.py and keeps the PNGs under
     outputs/layout_overflow/ for inspection (heavy slides 2, 6, 7, 20 plus
     the off-slide slides 2, 11, 21 are all in there).
"""
from __future__ import annotations

import shutil
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE

from app.core.injector import estimate_text_width, estimate_visual_width, inject_translations
from app.job_store import get_job_store
from app.qa.render import render_deck

JOB_ID = '0e6cb705-37fb-40f1-8cb6-584dfeb27ab2'
HEAVY_SLIDES = (2, 6, 7, 20)
OUT_ROOT = BACKEND / 'outputs' / 'layout_overflow'


def frame_font_pt(text_frame) -> float:
    """Largest explicit run size in the frame; 12.0 when nothing is explicit.

    12.0 is the same fallback check_text_fit() uses.
    """
    sizes = [run.font.size.pt
             for para in text_frame.paragraphs
             for run in para.runs
             if run.font.size]
    return max(sizes) if sizes else 12.0


def frame_box_pt(text_frame, shape) -> float:
    """Usable single-line width of a frame in points (box minus side insets)."""
    margins = 0
    for attr in ('margin_left', 'margin_right'):
        try:
            margins += int(getattr(text_frame, attr) or 0)
        except Exception:
            pass
    try:
        return (int(shape.width) - margins) / 12700
    except (TypeError, ValueError):
        return 0.0


def resolve_frame(slide, shape_path: str):
    """run_id shape path ('7', '1.0') -> shape, or None for table/smartart paths."""
    if 'table' in shape_path or 'smartart' in shape_path:
        return None
    container = slide
    shape = None
    for part in shape_path.split('.'):
        if not part.isdigit():
            return None
        shapes = list(getattr(container, 'shapes', []) or [])
        idx = int(part)
        if idx >= len(shapes):
            return None
        shape = shapes[idx]
        container = shape
    return shape


def groups_by_frame(job) -> dict[tuple[int, str], list]:
    groups: dict[tuple[int, str], list] = defaultdict(list)
    for tr in job.translated_runs:
        parts = tr.run_id.split('_')
        if len(parts) < 3:
            continue
        groups[(int(parts[1]), parts[2])].append(tr)
    return groups


def measure(pptx_path: Path, groups: dict, label: str, text_key: str) -> dict:
    """text_key: 'original_text' for the intermediate, 'translated_text' for the output."""
    prs = Presentation(str(pptx_path))
    m = defaultdict(int)
    per_slide: dict[int, dict] = defaultdict(lambda: defaultdict(int))
    worst: list = []

    for (slide_idx, shape_path), runs in groups.items():
        if slide_idx >= len(prs.slides):
            continue
        shape = resolve_frame(prs.slides[slide_idx], shape_path)
        if shape is None or not getattr(shape, 'has_text_frame', False):
            continue

        tf = shape.text_frame
        text = ''.join(run.text for para in tf.paragraphs for run in para.runs)

        # Source vs translation growth, judged on the job's own record so the
        # same numbers are comparable on both decks.
        original = ''.join(r.original_text for r in runs)
        translated = ''.join(r.translated_text for r in runs)
        grew = estimate_visual_width(translated) > estimate_visual_width(original)
        # The acceptance's "growing frame" count: translation longer than the
        # source in characters, spaces ignored (the measure the 872 / 197 / 254
        # trio was taken with, so before/after runs are comparable).
        grew_chars = (len(translated.replace(' ', ''))
                      > len(original.replace(' ', '')))

        box_pt = frame_box_pt(tf, shape)
        font_pt = frame_font_pt(tf)
        single_line_pt = estimate_text_width(text, font_pt) if box_pt > 0 else 0.0
        exceeds = box_pt > 0 and single_line_pt > box_pt

        spaf = tf.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        wrap_off = tf.word_wrap is False

        m['frames'] += 1
        m['spAutoFit'] += spaf
        m['grew'] += grew
        m['wrap_off'] += wrap_off
        m['exceeds_box'] += exceeds
        m['spAutoFit_grew'] += spaf and grew
        m['wrap_off_grew'] += wrap_off and grew
        m['wrap_off_exceeds'] += wrap_off and exceeds
        m['wrap_on_exceeds'] += (not wrap_off) and exceeds
        m['grew_chars'] += grew_chars
        m['grew_chars_spAutoFit'] += grew_chars and spaf
        m['grew_chars_wrap_off'] += grew_chars and wrap_off
        if grew:
            m['grew_fits'] += (not exceeds)

        for tr in runs:
            run_pt = estimate_text_width(getattr(tr, text_key), font_pt)
            over = box_pt > 0 and run_pt > box_pt
            m['runs'] += 1
            m['runs_over_box'] += over
            m['runs_over_box_wrap_off'] += over and wrap_off

        if exceeds:
            m['over_x110'] += single_line_pt > box_pt * 1.10
            m['over_x125'] += single_line_pt > box_pt * 1.25
            m['over_x150'] += single_line_pt > box_pt * 1.50
            if len(worst) < 3:
                worst.append((slide_idx, shape_path, round(single_line_pt, 1),
                              round(box_pt, 1), text[:40]))

        s = per_slide[slide_idx]
        s['frames'] += 1
        s['spAutoFit'] += spaf
        s['wrap_off_grew'] += wrap_off and grew
        s['wrap_off_exceeds'] += wrap_off and exceeds

    print(f'\n=== {label}: {pptx_path.name} ===')
    header = f'{"metric":40}{"total":>8}'
    print(header)
    for key in ('frames', 'grew', 'grew_chars', 'grew_chars_spAutoFit',
                'grew_chars_wrap_off', 'spAutoFit', 'spAutoFit_grew', 'wrap_off',
                'wrap_off_grew', 'exceeds_box', 'wrap_off_exceeds',
                'wrap_on_exceeds', 'grew_fits', 'over_x110', 'over_x125',
                'over_x150', 'runs', 'runs_over_box', 'runs_over_box_wrap_off'):
        print(f'{key:40}{m[key]:>8}')
    for slide_idx, shape_path, single, box, sample in worst:
        print(f'  over: slide {slide_idx} shape {shape_path} '
              f'{single}pt text vs {box}pt box  {sample!r}')
    print('\nper heavy slide (frames / spAutoFit / wrap_off&grew / wrap_off&exceeds):')
    for idx in HEAVY_SLIDES:
        s = per_slide[idx]
        print(f'  slide {idx:>2}: {s["frames"]:>4} / {s["spAutoFit"]:>4} / '
              f'{s["wrap_off_grew"]:>4} / {s["wrap_off_exceeds"]:>4}')
    return dict(m)


def offslide(pptx_path: Path, label: str) -> dict:
    """Text frames whose box sits past the slide's right edge (gap 1).

    A frame out there is clipped at the slide boundary whatever its wrap or
    autofit does, so the box itself has to come back inside. Empty frames are
    reported apart: this deck carries one full-bleed background frame about
    120EMU (0.01pt) over the edge on every slide — no text to clip, so it is
    not one of the 32.
    """
    prs = Presentation(str(pptx_path))
    past: list[tuple[int, int]] = []
    empty: list[tuple[int, int]] = []
    for slide_idx, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if not getattr(shape, 'has_text_frame', False):
                continue
            try:
                spill_emu = int(shape.left) + int(shape.width) - int(prs.slide_width)
            except (TypeError, ValueError):
                continue
            if spill_emu <= 0:
                continue
            text = ''.join(run.text for para in shape.text_frame.paragraphs
                           for run in para.runs)
            (past if text.strip() else empty).append((slide_idx, spill_emu))

    per_slide: dict[int, int] = defaultdict(int)
    for slide_idx, _ in past:
        per_slide[slide_idx] += 1
    worst = max((spill for _, spill in past), default=0) / 12700

    print(f'\n=== off-slide boxes ({label}): {pptx_path.name} ===')
    print(f'text frames past the slide right edge: {len(past)}   '
          f'worst spill {worst:.1f}pt')
    if past:
        slides = ', '.join(f'{si + 1} ({n})' if n > 1 else f'{si + 1}'
                           for si, n in sorted(per_slide.items()))
        print(f'slides: {slides}')
    if empty:
        eworst = max(spill for _, spill in empty) / 12700
        print(f'(plus {len(empty)} empty background frames over the edge, worst '
              f'{eworst:.2f}pt — nothing to clip, left as the source has them)')
    return {'past_right': len(past), 'worst_spill_pt': worst}


def render_pair(source: Path, injected: Path) -> None:
    for label, deck in (('source', source), ('injected', injected)):
        dest = OUT_ROOT / label
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        pages = render_deck(str(deck), timeout=900)
        for page in pages:
            shutil.copy(page, dest / page.name)
        print(f'rendered {len(pages)} pages -> {dest}')


def main() -> int:
    job = get_job_store().load(JOB_ID)
    if job is None:
        print(f'job {JOB_ID} not found in the job store')
        return 1

    upload_dir = BACKEND / 'uploads'
    original = Path(job.source_filename or job.filename).name
    source = upload_dir / f'{JOB_ID}_{original}.pptx'
    if not source.exists():
        print(f'intermediate not found: {source}')
        return 1

    groups = groups_by_frame(job)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    injected = OUT_ROOT / 'injected.pptx'
    ok, failed = inject_translations(str(source), str(injected), job.translated_runs, None)
    print(f'\ninject ok={ok} failed={len(failed)} runs={len(job.translated_runs)}')

    before = measure(source, groups, 'source (intermediate)', 'original_text')
    after = measure(injected, groups, 'injected (translated)', 'translated_text')

    print('\n=== delta (injected - source) ===')
    for key in ('spAutoFit', 'wrap_off', 'wrap_off_grew', 'wrap_off_exceeds',
                'exceeds_box', 'runs_over_box', 'runs_over_box_wrap_off',
                'grew_chars_spAutoFit', 'grew_chars_wrap_off'):
        print(f'{key:30}{after[key] - before[key]:>+6}   {before[key]} -> {after[key]}')

    src_off = offslide(source, 'source (intermediate)')
    inj_off = offslide(injected, 'injected (translated)')
    print(f'\noff-slide text frames: {src_off["past_right"]} (source) -> '
          f'{inj_off["past_right"]} (injected), '
          f'worst spill {src_off["worst_spill_pt"]:.1f}pt -> '
          f'{inj_off["worst_spill_pt"]:.1f}pt')

    if '--render' in sys.argv:
        render_pair(source, injected)
    else:
        print('\n(skip rendering — pass --render to write PNGs)')

    if inj_off['past_right']:
        print(f'FAIL: {inj_off["past_right"]} off-slide text frames remain in '
              f'the injected deck')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
