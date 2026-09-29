#!/usr/bin/env python3
"""Layout-overflow checks: length-aware scaling for every target language, plus
the neutralising of the PDF-import autofit/wrap artifacts on injected frames.

Standalone — no pytest required:

    cd backend && venv/bin/python tests/test_layout_overflow.py

Why these exist: the measured causes of the JP->EN deck overflow were (1) a font
scale that only ever ran for EN->JA, (2) every frame left on spAutoFit so the box
grew over its neighbour, (3) wrap left off so the overflow ran off the slide
edge, and (4) frames the translation did not disturb being fair game for a
layout change nobody asked for. The two gaps left open by that fix are covered
here as well: (5) frames whose box already sits past the slide's right edge are
clamped back inside (and their text shrunk when clamping is not enough), and
(6) real table cells — which return before apply_frame_layout() on the frame
path — get the same neutralisation, measured on the cell's own width.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Pt

from app.core.injector import (
    SLIDE_EDGE_MARGIN_EMU,
    calculate_font_scale,
    estimate_text_width,
    frame_text_exceeds_box,
    frame_text_grew,
    paragraph_font_scale,
    replace_text_in_shape,
    resolve_font_size,
    CellBox,
    MIN_LEGIBLE_FONT_PT,
)
from app.models import TranslatedRun

FAILURES = []


def check(name, ok, detail=''):
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  — {detail}' if detail else ''))
    if not ok:
        FAILURES.append(name)


def run_of(run_id, original, translated, target='en'):
    return TranslatedRun(
        run_id=run_id,
        original_text=original,
        translated_text=translated,
        source_language='ja' if target == 'en' else 'en',
        target_language=target,
        model_used='test',
    )


def pdf_import_frame(source_text, font_pt=12.0, width_pt=400.0, height_pt=60.0):
    """A text frame shaped the way LibreOffice's PDF import writes them:
    wrap off and spAutoFit on."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Pt(0), Pt(0), Pt(width_pt), Pt(height_pt))
    frame = box.text_frame
    frame.word_wrap = False
    frame.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
    run = frame.paragraphs[0].add_run()
    run.text = source_text
    run.font.size = Pt(font_pt)
    return box, frame


def inject(box, runs):
    failed = replace_text_in_shape(box, runs, 0, '0')
    assert failed == [], f'unexpected injection failures: {failed}'


print('\n[1] a frame whose text grows gets a non-growing autofit')

box, frame = pdf_import_frame('Hello world', width_pt=400.0)
check('pre-fix: the PDF-import frame starts on spAutoFit with wrap off',
      frame.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT and frame.word_wrap is False,
      f'auto_size={frame.auto_size} word_wrap={frame.word_wrap}')

runs = [run_of('run_0_0_0_0_1', 'Hello world', 'Hello there my dear friend')]
inject(box, runs)
check('the frame is classified as grown (and as still fitting its box)',
      frame_text_grew(runs) and not frame_text_exceeds_box(frame, box),
      f'grew={frame_text_grew(runs)} exceeds={frame_text_exceeds_box(frame, box)}')

check('post-fix: the grown frame is off spAutoFit',
      frame.auto_size != MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT, f'auto_size={frame.auto_size}')
check('post-fix: the replacement is normAutofit (shrink text, never grow the box)',
      frame.auto_size == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE, f'auto_size={frame.auto_size}')
check('the translation really did grow (and was written)',
      frame.paragraphs[0].runs[0].text == 'Hello there my dear friend',
      repr(frame.paragraphs[0].runs[0].text))
check('wrap is untouched while the text still fits the box width',
      frame.word_wrap is False, f'word_wrap={frame.word_wrap}')


print('\n[2] a frame that needs wrap gets word_wrap=True')

box, frame = pdf_import_frame('短い', font_pt=18.0, width_pt=120.0)
long_translation = ('This English translation is far longer than the original '
                    'Japanese label ever was')
inject(box, [run_of('run_0_0_0_0_1', '短い', long_translation)])
check('the frame is classified as needing wrap',
      frame_text_exceeds_box(frame, box),
      f'{len(long_translation)} chars at 18pt in a 120pt box')
check('post-fix: word_wrap is turned on', frame.word_wrap is True,
      f'word_wrap={frame.word_wrap}')
check('post-fix: a frame that no longer fits is also off spAutoFit',
      frame.auto_size == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE, f'auto_size={frame.auto_size}')

box, frame = pdf_import_frame('Source text that already fits its box', width_pt=600.0)
inject(box, [run_of('run_0_0_0_0_1', 'Source text that already fits its box',
                    'Fits')])
check('a translation that still fits is not given wrap',
      frame.word_wrap is False, f'word_wrap={frame.word_wrap}')


print('\n[3] a frame unchanged by translation is left alone')

box, frame = pdf_import_frame('Governance framework', width_pt=400.0)
inject(box, [run_of('run_0_0_0_0_1', 'Governance framework', 'Governance')])

check('the shorter translation was written',
      frame.paragraphs[0].runs[0].text == 'Governance',
      repr(frame.paragraphs[0].runs[0].text))
check('post-fix: autofit is left exactly as the source had it',
      frame.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT, f'auto_size={frame.auto_size}')
check('post-fix: wrap is left exactly as the source had it',
      frame.word_wrap is False, f'word_wrap={frame.word_wrap}')
check('no size stamp is written either',
      frame.paragraphs[0].runs[0].font.size == Pt(12.0),
      f'size={frame.paragraphs[0].runs[0].font.size.pt if frame.paragraphs[0].runs[0].font.size else None}')


print('\n[4] EN->JA scaling output is unchanged for a known input')

# Pinned to the values the tuned parameters produce (cjk_ratio 2.2, 5% tolerance,
# 0.5 floor): any edit to those numbers fails here. 'Workshop ' is 9.0 units wide
# and 'ワークショップ' (7 CJK) 15.4, so the ratio is 9/15.4.
known = paragraph_font_scale([run_of('run_3_4_2_0_17', 'Workshop ', 'ワークショップ',
                                     target='ja')])
check('EN->JA pair returns the exact original:translated ratio',
      abs(known - (9.0 / 15.4)) < 1e-9, f'scale={known}')
check('the EN->JA value equals calculate_font_scale on the same pair',
      abs(calculate_font_scale('Workshop ', 'ワークショップ') - (9.0 / 15.4)) < 1e-9)
floor = paragraph_font_scale([run_of('run_0_0_0_0_1', 'x', 'あ' * 10, target='ja')])
check('an EN->JA pair below the floor still stops at 0.5', floor == 0.5,
      f'scale={floor}')

# ...and the same computation now runs for a growing JP->EN pair — 'AI時代の経営'
# is 13.0 units wide, 'Management in the AI era' 24.0 — where the old gate
# returned an unconditional 1.0.
jp_en = paragraph_font_scale([run_of('run_0_0_0_0_1', 'AI時代の経営',
                                     'Management in the AI era', target='en')])
check('the scale gate no longer blocks non-ja targets',
      abs(jp_en - (13.0 / 24.0)) < 1e-9, f'scale={jp_en}')
check('a JP->EN translation that did not grow is still left at 1.0',
      paragraph_font_scale([run_of('run_3_9_2_0_40', 'Workshop ', 'Workshop',
                                   target='en')]) == 1.0)

# The scale has to reach the written font size, not just the number.
size = resolve_font_size(run_of('run_0_0_0_0_1', 'AI時代の経営',
                                'Management in the AI era', target='en'),
                         jp_en, Pt(20))
check('a growing JP->EN paragraph actually gets a smaller font size',
      size is not None and size < 20.0, f'{size}pt < 20.0pt')

print('\n[5] an off-slide frame is pulled inside; an on-slide frame never moves')


def offslide_frame(left_pt, width_pt, source_text, translated_text, font_pt=18.0):
    """A PDF-import-style frame placed anywhere on a default 720x540pt slide,
    injected with one run. Returns the presentation so the box can be measured."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    box = slide.shapes.add_textbox(Pt(left_pt), Pt(10), Pt(width_pt), Pt(60))
    frame = box.text_frame
    frame.word_wrap = False
    frame.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
    run = frame.paragraphs[0].add_run()
    run.text = source_text
    run.font.size = Pt(font_pt)
    inject(box, [run_of('run_0_0_0_0_1', source_text, translated_text)])
    return prs, box, frame


# 'Data platform review' (20 latin chars at 18pt = 180pt of text) cannot fit
# the ~98pt usable box the clamp leaves at left=600pt, and it does not grow
# against the 30-char JP source, so the paragraph scale stays at 1.0 — any
# shrink seen below came from the clamp, not from the scale.
prs, box, frame = offslide_frame(600, 300, 'あ' * 30, 'Data platform review')
check('the off-slide frame is clamped so its right edge lands on the limit',
      box.left + box.width == prs.slide_width - SLIDE_EDGE_MARGIN_EMU,
      f'right={(box.left + box.width) / 12700:.1f}pt '
      f'limit={(prs.slide_width - SLIDE_EDGE_MARGIN_EMU) / 12700:.1f}pt')
check('only width came off — the left edge did not move', box.left == Pt(600),
      f'left={box.left / 12700:.1f}pt')
def _residual_ratio(text_frame, shape) -> float:
    """How far past its box the widest paragraph sits (1.0 = fits exactly)."""
    sizes = [r.font.size.pt for p in text_frame.paragraphs for r in p.runs if r.font.size]
    size = max(sizes) if sizes else 18.0
    usable = (int(shape.width) / 12700
              - sum(int(getattr(text_frame, a, 0) or 0)
                    for a in ('margin_left', 'margin_right')) / 12700)
    worst = 0.0
    if usable <= 0:
        return worst
    for para in text_frame.paragraphs:
        text = ''.join(r.text for r in para.runs)
        if text.strip():
            worst = max(worst, estimate_text_width(text, size) / usable)
    return worst


clamped_run = frame.paragraphs[0].runs[0]
check('clamping was not enough, so the frame text was shrunk instead of '
      'running off',
      clamped_run.font.size is not None and Pt(9) <= clamped_run.font.size < Pt(18),
      f'size={clamped_run.font.size.pt if clamped_run.font.size else None}pt')
# The legibility floor is the stricter of the two: 18pt x 98/180 would be 9.8pt,
# but 10pt is the smallest size this pipeline will write, so the shrink stops
# there and the last two points are left to wrap and spill — a legible frame
# that is 2% over its box beats a frame nothing can read.
check('the shrink stops at the legibility floor, not below it',
      clamped_run.font.size == Pt(MIN_LEGIBLE_FONT_PT),
      f'size={clamped_run.font.size.pt:.2f}pt floor={MIN_LEGIBLE_FONT_PT}pt')
check('the residual overflow at the floor is small, not a slide-wide bleed',
      not frame_text_exceeds_box(frame, box) or _residual_ratio(frame, box) < 1.05,
      f'ratio={_residual_ratio(frame, box):.3f}')

# A frame already inside the slide must not move by a single EMU — including
# one whose right edge sits inside the margin band but still on the slide.
_, plain, _ = offslide_frame(100, 200, 'Governance framework', 'Governance')
check('a plain on-slide frame keeps its exact EMU geometry',
      plain.left == Pt(100) and plain.width == Pt(200),
      f'left={plain.left} width={plain.width}')
_, band, _ = offslide_frame(650, 68, 'Governance framework', 'Governance')
check('a frame ending inside the margin band but on the slide keeps its EMU geometry',
      band.left == Pt(650) and band.width == Pt(68),
      f'left={band.left} width={band.width} right={(band.left + band.width) / 12700:.1f}pt')

# Only when shrinking would leave a sliver does `left` move: here the left edge
# itself is past the limit, so the frame slides back whole.
prs, edge_box, _ = offslide_frame(715, 50, 'x', 'y')
check('a frame whose left edge is past the limit slides back, keeping its width',
      edge_box.left == prs.slide_width - SLIDE_EDGE_MARGIN_EMU - Pt(50)
      and edge_box.width == Pt(50),
      f'left={edge_box.left / 12700:.1f}pt width={edge_box.width / 12700:.1f}pt')


print('\n[6] a real table cell gets the neutralisation, on its own box width')


def real_table():
    """A real .pptx table (slide.shapes.add_table), 10 columns wide, whose cells
    carry the PDF-import artifacts: wrap off and spAutoFit on."""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    grid = slide.shapes.add_table(2, 10, Pt(0), Pt(40), Pt(600), Pt(160))
    for row in grid.table.rows:
        for cell in row.cells:
            cell.text_frame.word_wrap = False
            cell.text_frame.auto_size = MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
    victim = grid.table.rows[0].cells[0]
    source_run = victim.text_frame.paragraphs[0].add_run()
    source_run.text = 'グローバル戦略会議の枠組み'
    source_run.font.size = Pt(18)
    bystander = grid.table.rows[0].cells[1]
    neighbour_run = bystander.text_frame.paragraphs[0].add_run()
    neighbour_run.text = 'Anchor'
    neighbour_run.font.size = Pt(18)
    return grid, victim, bystander


grid, victim, bystander = real_table()
cell_box = CellBox(grid.table, 0, 0, grid)
check('the box measured for the cell is its column, not the table',
      cell_box.width < grid.width * 0.3,
      f'cell={cell_box.width / 12700:.1f}pt vs table={grid.width / 12700:.1f}pt')

# 28 latin chars at 18pt is ~252pt of text: far wider than this 10-column cell
# (~31pt of usable box) and far narrower than the 600pt table, so a gate that
# measured against the table's width would never fire on it — the gap.
table_runs = [run_of('run_0_0.table.0.0_0_0_1', 'グローバル戦略会議の枠組み',
                     'Data platform overview notes')]
inject(grid, table_runs)

check('the written cell is classified as exceeding its own box',
      frame_text_exceeds_box(victim.text_frame, cell_box),
      f'cell box={(cell_box.width / 12700) - 14.4:.1f}pt, '
      f'text={28 * 18 * 0.5:.1f}pt')
check('the same cell measured against the table would NOT exceed (the bug)',
      not frame_text_exceeds_box(victim.text_frame, grid),
      f'table box={(grid.width / 12700) - 14.4:.1f}pt')
check('post-fix: the written cell is off spAutoFit (normAutofit)',
      victim.text_frame.auto_size == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE,
      f'auto_size={victim.text_frame.auto_size}')
check('post-fix: the written cell has wrap on',
      victim.text_frame.word_wrap is True, f'word_wrap={victim.text_frame.word_wrap}')
check('the translation landed in the cell',
      victim.text_frame.paragraphs[0].runs[0].text == 'Data platform overview notes',
      repr(victim.text_frame.paragraphs[0].runs[0].text))
check('a cell that received nothing is left alone — autofit, wrap and text',
      bystander.text_frame.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
      and bystander.text_frame.word_wrap is False
      and bystander.text_frame.paragraphs[0].runs[0].text == 'Anchor',
      f'auto_size={bystander.text_frame.auto_size} '
      f'word_wrap={bystander.text_frame.word_wrap} '
      f'text={bystander.text_frame.paragraphs[0].runs[0].text!r}')

print()
if FAILURES:
    print(f'{len(FAILURES)} CHECK(S) FAILED: ' + ', '.join(FAILURES))
    sys.exit(1)
print('All layout-overflow checks passed.')


def test_layout_overflow() -> None:
    """The module-level checks above run at import; expose their verdict to pytest."""
    assert not FAILURES, f'layout-overflow checks failed: {FAILURES}'
