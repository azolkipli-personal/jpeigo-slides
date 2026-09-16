#!/usr/bin/env python3
"""Unit checks for the injector formatting fixes.

Standalone — no pytest required:

    cd backend && venv/bin/python tests/test_injector_units.py

Each check asserts post-fix behaviour AND demonstrates the pre-fix behaviour it
replaced, so a regression shows up as a failing check rather than a bad deck.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pptx import Presentation
from pptx.util import Pt

from app.core.injector import (
    A_NS,
    JP_FONT_FAMILY,
    _paragraph_key,
    calculate_font_scale,
    paragraph_font_scale,
    resolve_font_size,
    set_run_typefaces,
)
from app.models import TranslatedRun

FAILURES = []


def check(name, ok, detail=''):
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  — {detail}' if detail else ''))
    if not ok:
        FAILURES.append(name)


def blank_run():
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(0, 0, 300, 60)
    run = box.text_frame.paragraphs[0].add_run()
    run.text = 'x'
    return run


def slots(run):
    rPr = run._r.get_or_add_rPr()
    return [tag for tag in ('latin', 'ea', 'cs') if rPr.find(f'{{{A_NS}}}{tag}') is not None]


def run_of(run_id, original, translated, target='ja', adjusted=None):
    return TranslatedRun(
        run_id=run_id,
        original_text=original,
        translated_text=translated,
        source_language='en',
        target_language=target,
        model_used='test',
        adjusted_font_size=adjusted,
    )


print('\n[1] East Asian font slot (§2.1)')

old_run = blank_run()
old_run.font.name = JP_FONT_FAMILY
check('pre-fix: run.font.name alone writes only <a:latin>', slots(old_run) == ['latin'],
      f'slots={slots(old_run)}')

new_run = blank_run()
set_run_typefaces(new_run, JP_FONT_FAMILY)
rPr = new_run._r.get_or_add_rPr()
order = slots(new_run)
check('post-fix: latin, ea and cs all written', order == ['latin', 'ea', 'cs'], f'slots={order}')
check('post-fix: every slot carries the typeface',
      all(rPr.find(f'{{{A_NS}}}{tag}').get('typeface') == JP_FONT_FAMILY for tag in ('ea', 'cs')),
      f'font={JP_FONT_FAMILY}')
check('post-fix: schema order latin < ea < cs preserved',
      [list(rPr).index(rPr.find(f'{{{A_NS}}}{t}')) for t in ('latin', 'ea', 'cs')] ==
      sorted(list(rPr).index(rPr.find(f'{{{A_NS}}}{t}')) for t in ('latin', 'ea', 'cs')))

# Idempotent: re-applying must not duplicate the elements.
set_run_typefaces(new_run, JP_FONT_FAMILY)
check('post-fix: re-applying is idempotent',
      len(list(rPr)) == len(set(list(rPr))), f'{len(list(rPr))} children')


print('\n[2] Paragraph-level uniform scaling (§2.2)')
# A real fragment pair from test_real.pptx: one paragraph, two runs, one of them
# a bare single letter. Per-run ratios differ sharply.
long_run = run_of('run_3_4_2_0_17', 'Workshop ', 'ワークショップ')
short_run = run_of('run_3_4_2_1_18', 'R', 'R')

old_sizes = [18.0 * calculate_font_scale(r.original_text, r.translated_text)
             for r in (long_run, short_run)]
check('pre-fix: per-run ratios give the two runs different sizes',
      round(old_sizes[0], 1) != round(old_sizes[1], 1),
      f"{old_sizes[0]:.1f}pt vs {old_sizes[1]:.1f}pt")

para_scale = paragraph_font_scale([long_run, short_run])
new_sizes = [resolve_font_size(r, para_scale, Pt(18)) for r in (long_run, short_run)]
check('post-fix: one scale for the paragraph', round(new_sizes[0], 2) == round(new_sizes[1], 2),
      f"scale={para_scale:.2f} -> both {new_sizes[0]:.1f}pt")
check('post-fix: scaling still applies when needed', new_sizes[0] < 18.0,
      f'{new_sizes[0]:.1f}pt < 18.0pt')

english = run_of('run_3_9_2_0_40', 'Workshop ', 'Workshop', target='en')
check('post-fix: non-Japanese targets are left alone',
      paragraph_font_scale([english]) == 1.0 and resolve_font_size(english, 1.0, Pt(18)) is None)


print('\n[3] adjusted_font_size is no longer discarded (§2.3)')
fit_run = run_of('run_4_1_0_0_5', 'あ' * 30, 'a' * 60, adjusted=9.0)
size = resolve_font_size(fit_run, 0.5, Pt(20))
check('post-fix: the geometry fit result wins over the paragraph scale', size == 9.0,
      f'adjusted=9.0, scale would give {20 * 0.5:.1f} -> resolved {size}')
size_no_scale = resolve_font_size(fit_run, 1.0, Pt(20))
check('post-fix: adjusted size survives an unscaled paragraph',
      size_no_scale == 9.0, f'scale=1.0 -> resolved {size_no_scale}')
check('pre-fix equivalent: scale alone would have written 10.0pt', (20 * 0.5) != 9.0,
      'old code set Pt(orig*scale) and dropped the field')

untouched = run_of('run_4_1_0_1_6', 'text', 'テキスト')
check('post-fix: nothing to do means no size stamp (runs keep inherited size)',
      resolve_font_size(untouched, 1.0, Pt(18)) is None)


print('\n[4] Paragraph grouping, incl. table cells (§2.6)')
check('same paragraph -> same key',
      _paragraph_key(run_of('run_7_12_3_0_9', 'a', 'あ')) ==
      _paragraph_key(run_of('run_7_12_3_1_10', 'b', 'い')))
check('different paragraphs -> different keys',
      _paragraph_key(run_of('run_7_12_3_0_9', 'a', 'あ')) !=
      _paragraph_key(run_of('run_7_12_4_0_11', 'a', 'あ')))
check('table cell runs in one cell+paragraph group together',
      _paragraph_key(run_of('run_2_5.1.0_2_0_31', 'a', 'あ')) ==
      _paragraph_key(run_of('run_2_5.1.0_2_1_32', 'b', 'い')))
check('runs in different table cells stay separate',
      _paragraph_key(run_of('run_2_5.1.0_2_0_31', 'a', 'あ')) !=
      _paragraph_key(run_of('run_2_5.2.0_2_0_33', 'a', 'あ')))

print()
if FAILURES:
    print(f'{len(FAILURES)} CHECK(S) FAILED: ' + ', '.join(FAILURES))
    sys.exit(1)
print('All injector unit checks passed.')
