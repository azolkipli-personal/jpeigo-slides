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

from app.core.extractor import extract_runs_from_text_frame
from app.core.injector import (
    A_NS,
    JP_FONT_FAMILY,
    _paragraph_key,
    calculate_font_scale,
    clear_run_text,
    paragraph_font_scale,
    replace_text_in_shape,
    resolve_font_size,
    set_run_typefaces,
    span_targets,
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

print('\n[5] Run coalescing — one unit per formatting-identical group (§2.5)')


def textbox_with(paragraphs):
    """Build a textbox whose paragraphs hold the given (text, bold) runs."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(0, 0, 400, 200)
    frame = box.text_frame
    for p_idx, runs in enumerate(paragraphs):
        para = frame.paragraphs[0] if p_idx == 0 else frame.add_paragraph()
        for text, bold in runs:
            r = para.add_run()
            r.text = text
            r.font.bold = bold
    return box


# The real slide-4 heading, split exactly as test_real.pptx stores it.
split_word = textbox_with([[('Ways of ', False), ('W', False), ('orking & ', False),
                            ('Governance', False)]])
n_runs = len(list(split_word.text_frame.paragraphs[0].runs))
units = extract_runs_from_text_frame(split_word.text_frame, 0, 0, 'shape')
check('pre-fix: the paragraph is stored as 4 separate runs', n_runs == 4, f'{n_runs} runs')
check('post-fix: identical-format runs become one translation unit',
      len(units) == 1, f'{len(units)} unit(s)')
check('post-fix: the model sees the whole sentence, not fragments',
      units[0].text == 'Ways of Working & Governance', repr(units[0].text))
check('post-fix: the unit records the span it covers',
      units[0].merged_span == [0, 3] and units[0].run_index == 0,
      f'span={units[0].merged_span}')
check('pre-fix equivalent: "W" and "orking & " were separate model jobs',
      n_runs == 4 and len(units) == 1, '4 isolated strings -> 1 sentence')

mixed = textbox_with([[('Gap: ', True), ('the plan slipped', False)]])
mixed_units = extract_runs_from_text_frame(mixed.text_frame, 0, 0, 'shape')
check('mixed formatting stays split (bold label + body)',
      len(mixed_units) == 2 and all(u.merged_span is None for u in mixed_units),
      f'{len(mixed_units)} units, spans={[u.merged_span for u in mixed_units]}')

padded = textbox_with([[('TBD', False), ('            ', False), ('TBD', False)]])
padded_units = extract_runs_from_text_frame(padded.text_frame, 0, 0, 'shape')
check('whitespace-only runs break adjacency and are never merged',
      len(padded_units) == 2 and all(u.merged_span is None for u in padded_units),
      f'{len(padded_units)} units, spans={[u.merged_span for u in padded_units]}')

wide = textbox_with([[('TBD                ', False), ('       TBD', False)]])
wide_units = extract_runs_from_text_frame(wide.text_frame, 0, 0, 'shape')
check('runs whose text pads a column with spaces stay separate',
      len(wide_units) == 2 and all(u.merged_span is None for u in wide_units),
      f'{len(wide_units)} units, spans={[u.merged_span for u in wide_units]}')

from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls

br_box = textbox_with([[('Line one', False), ('Line two', False)]])
br_para = br_box.text_frame.paragraphs[0]
p_el = br_para._p
second = list(br_para.runs)[1]._r
p_el.insert(p_el.index(second), parse_xml(f'<a:br {nsdecls("a")}/>'))
br_units = extract_runs_from_text_frame(br_box.text_frame, 0, 0, 'shape')
check('a line break between two runs never merges them',
      len(br_units) == 2 and all(u.merged_span is None for u in br_units),
      f'{len(br_units)} units, spans={[u.merged_span for u in br_units]}')


print('\n[6] Injector writes the span into the first run (§2.5)')
span_box = textbox_with([[('Ways of ', False), ('W', False), ('orking & ', False),
                          ('Governance', False)]])
merged_unit = run_of('run_0_0_0_0_1', 'Ways of Working & ', '働き方と')
merged_unit.merged_span = [0, 2]
tail_unit = run_of('run_0_0_0_3_2', 'Governance', 'ガバナンス')

failed = replace_text_in_shape(span_box, [merged_unit, tail_unit], 0, '0')
para_runs = list(span_box.text_frame.paragraphs[0].runs)
texts = [r.text for r in para_runs]
check('span translation is written into the first run', texts[0] == '働き方と', repr(texts))
check('the rest of the span is blanked', texts[1] == '' and texts[2] == '', repr(texts))
check('runs outside the span are untouched', texts[3] == 'ガバナンス', repr(texts[3]))
check('blanked runs are emptied, not removed (run indices stay valid)',
      len(para_runs) == 4, f'{len(para_runs)} runs still present')
check('nothing reported as an injection failure', failed == [], f'{len(failed)} failed')

mismatch_box = textbox_with([[('Ways of ', False), ('W', False), ('orking & ', False)]])
mismatch_unit = run_of('run_0_0_0_0_9', 'never the real source', 'X')
mismatch_unit.merged_span = [0, 2]
failed = replace_text_in_shape(mismatch_box, [mismatch_unit], 0, '0')
mismatch_texts = [r.text for r in mismatch_box.text_frame.paragraphs[0].runs]
check('a span whose source text does not match is refused',
      failed == [mismatch_unit], f'{len(failed)} reported failed')
check('refusal writes nothing and blanks nothing',
      mismatch_texts == ['Ways of ', 'W', 'orking & '], repr(mismatch_texts))

oob = run_of('run_0_0_0_0_12', 'x', 'y')
oob.merged_span = [0, 5]
check('span_targets refuses a span running past the paragraph',
      span_targets([blank_run()], oob) == (None, []))

plain_box = textbox_with([[('Workshop ', False), ('R', False)]])
plain_unit = run_of('run_0_0_0_1_11', 'R', '復習')
failed = replace_text_in_shape(plain_box, [plain_unit], 0, '0')
check('units without a span still write a single run',
      [r.text for r in plain_box.text_frame.paragraphs[0].runs] == ['Workshop ', '復習']
      and failed == [],
      'the un-coalesced path is unchanged')

print()
if FAILURES:
    print(f'{len(FAILURES)} CHECK(S) FAILED: ' + ', '.join(FAILURES))
    sys.exit(1)
print('All injector unit checks passed.')


def test_injector_units() -> None:
    """The module-level checks above run at import; expose their verdict to pytest so
    `pytest tests/` cannot be green while injection is broken."""
    assert not FAILURES, f'injector checks failed: {FAILURES}'
