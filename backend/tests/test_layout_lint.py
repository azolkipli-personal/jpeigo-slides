#!/usr/bin/env python3
"""Layout-linter checks: every finding class, and the false-positive floor.

Standalone — no pytest required:

    cd backend && venv/bin/python tests/test_layout_lint.py

Why these exist: the linter is the measurement half Phase 2 will drive repairs
from, so a finding has to carry the numbers it claims (points over, the edge,
both shape ids) and — the check that matters most — a clean deck must produce
zero findings. A linter that cries wolf is worse than none, so the clean case
and the decorative-filled-shape case are pinned here alongside the five
acceptance scenarios: wrap-off overflow, off-slide, overlap, 6pt type, empty.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.util import Pt

from app.qa.layout_lint import lint_presentation

FAILURES = []


def check(name, ok, detail=''):
    print(('  PASS  ' if ok else '  FAIL  ') + name + (f'  — {detail}' if detail else ''))
    if not ok:
        FAILURES.append(name)


def findings_of(report, kind):
    return [f for f in report['findings'] if f['kind'] == kind]


def text_frame(slide, left_pt, top_pt, width_pt, height_pt, text, font_pt,
               wrap=None, auto_size=None):
    box = slide.shapes.add_textbox(Pt(left_pt), Pt(top_pt),
                                   Pt(width_pt), Pt(height_pt))
    frame = box.text_frame
    if wrap is not None:
        frame.word_wrap = wrap
    if auto_size is not None:
        frame.auto_size = auto_size
    run = frame.paragraphs[0].add_run()
    run.text = text
    run.font.size = Pt(font_pt)
    return box


print('\n[1] a frame with wrap off and text too long -> exactly one overflow_width')

prs = Presentation()  # default 720x540pt slide
slide = prs.slides.add_slide(prs.slide_layouts[6])
box = text_frame(slide, 50, 50, 120, 60, 'This label is far too long for its box',
                 18.0, wrap=False)
report = lint_presentation(prs)
ow = findings_of(report, 'overflow_width')
check('exactly one finding and it is overflow_width',
      len(report['findings']) == 1 and len(ow) == 1,
      f"{len(report['findings'])} findings: {[f['kind'] for f in report['findings']]}")
if ow:
    m = ow[0]['measurements']
    check('it names the box, the text width, the overshoot and the ratio',
          abs(m['box_pt'] - 105.6) < 0.01 and m['text_pt'] > m['box_pt']
          and abs(m['over_pt'] - (m['text_pt'] - m['box_pt'])) < 0.01
          and m['ratio'] > 1.5 and m['wrap_off'] is True
          and m['autofit'] == 'spAutoFit',  # add_textbox ships wrap=none+spAutoFit
          f"box={m['box_pt']}pt text={m['text_pt']}pt over={m['over_pt']}pt "
          f"ratio={m['ratio']} wrap_off={m['wrap_off']} autofit={m['autofit']}")
    check('wrap-off overflow is reported, and says its growth is free here',
          ow[0]['severity'] == 'low'
          and ow[0]['suggested_action'] == 'wrap'
          and ow[0]['measurements'].get('growth_free') is True
          and ow[0]['slide'] == 1 and ow[0]['shape_id'] == box.shape_id,
          f"severity={ow[0]['severity']} action={ow[0]['suggested_action']} "
          f"growth_free={ow[0]['measurements'].get('growth_free')} "
          f"slide={ow[0]['slide']} shape_id={ow[0]['shape_id']}")

# The same frame, but with a neighbour sitting where the box would have to grow:
# now the growth is not free, and that is the defect worth reporting. This is the
# discrimination the whole gate exists for — on the original file every one of the
# 827 width findings was wrap-off + spAutoFit growing into empty space.
prs_blocked = Presentation()
slide_blocked = prs_blocked.slides.add_slide(prs_blocked.slide_layouts[6])
box_blocked = text_frame(slide_blocked, 50, 50, 120, 60,
                         'This label is far too long for its box', 18.0, wrap=False)
text_frame(slide_blocked, 200, 50, 200, 60, 'Neighbour', 18.0)
ow_blocked = findings_of(lint_presentation(prs_blocked), 'overflow_width')
check('the same overflow grows into a neighbour -> high severity',
      len(ow_blocked) == 1 and ow_blocked[0]['severity'] == 'high'
      and ow_blocked[0]['measurements'].get('growth_free') is False
      and ow_blocked[0]['shape_id'] == box_blocked.shape_id,
      f"findings={len(ow_blocked)} "
      f"severity={ow_blocked[0]['severity'] if ow_blocked else None} "
      f"growth_free={ow_blocked[0]['measurements'].get('growth_free') if ow_blocked else None}")


print('\n[2] a frame ending past the slide edge -> off_slide, split by whether text is lost')

prs = Presentation()  # 720pt wide
slide = prs.slides.add_slide(prs.slide_layouts[6])
# box runs 20pt past the edge (660+80=740) but 'Anchor' is 36pt of text: nothing
# is lost, so the box bleeding is not a clip.
box = text_frame(slide, 660, 50, 80, 60, 'Anchor', 12.0)
report = lint_presentation(prs)
off = findings_of(report, 'off_slide')
check('exactly one finding and it is off_slide',
      len(report['findings']) == 1 and len(off) == 1,
      f"{len(report['findings'])} findings: {[f['kind'] for f in report['findings']]}")
if off:
    m = off[0]['measurements']
    check('it names the right edge and a 20pt spill',
          m['edge'] == 'right' and abs(m['spill_pt'] - 20.0) < 0.01,
          f"edge={m['edge']} spill={m['spill_pt']}pt")
    check('a box past the edge whose text stops inside is box_only, not a clip',
          off[0]['severity'] == 'low' and m.get('box_only') is True
          and off[0]['suggested_action'] == 'clamp_to_slide'
          and off[0]['shape_id'] == box.shape_id,
          f"severity={off[0]['severity']} box_only={m.get('box_only')} "
          f"action={off[0]['suggested_action']}")

# The same box with text long enough to cross the edge: now glyphs are lost.
prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
clipped_box = text_frame(slide, 660, 50, 80, 60,
                         'this label runs off the slide', 18.0)
off_clipped = findings_of(lint_presentation(prs), 'off_slide')
check('a box past the edge whose text crosses it is high, clamp action',
      len(off_clipped) == 1 and off_clipped[0]['severity'] == 'high'
      and off_clipped[0]['shape_id'] == clipped_box.shape_id
      and off_clipped[0]['measurements'].get('box_only') is None,
      f"findings={len(off_clipped)} "
      f"severity={off_clipped[0]['severity'] if off_clipped else None}")


print('\n[3] overlapping frames: the report follows the TEXT, not the box')

# Boxes crossing while their text stays apart is the normal case in an imported
# deck — a 400pt panel holding a short label has its text in one corner. Reporting
# it as a collision is what made the pristine original come back with 658 overlaps.
prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
first = text_frame(slide, 100, 100, 200, 50, 'Alpha', 12.0)
text_frame(slide, 250, 120, 200, 50, 'Beta', 12.0)
report = lint_presentation(prs)
check('boxes crossing with their text clear are not a collision',
      len(report['findings']) == 0,
      f"{len(report['findings'])} findings: {[f['kind'] for f in report['findings']]}")

# Same geometry, but the text is long enough to reach the shared corner: now the
# two strings really do share pixels, and the finding must name both frames.
prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
first = text_frame(slide, 100, 100, 200, 50,
                   'Alpha line that reaches the far end of its box', 12.0)
second = text_frame(slide, 250, 110, 200, 50,
                    'Beta line that starts inside the crossing region', 12.0)
report = lint_presentation(prs)
overlaps = findings_of(report, 'overlap')
check('exactly one overlap finding (the long lines also overflow their boxes)',
      len(overlaps) == 1,
      f"{len(report['findings'])} findings: {[f['kind'] for f in report['findings']]}")
if overlaps:
    finding = overlaps[0]
    m = finding['measurements']
    names_both = {finding['shape_id'], finding.get('other_shape_id')} \
        == {first.shape_id, second.shape_id}
    check('it names both shape ids', names_both,
          f"ids={finding['shape_id']}/{finding.get('other_shape_id')} "
          f"expected {first.shape_id}/{second.shape_id}")
    check('it measures the shared area and its share of the smaller text rect',
          m['area_pt2'] > 0 and 0 < m['fraction'] <= 1.0,
          f"area={m['area_pt2']}pt2 fraction={m['fraction']}")
    check('the finding carries the nudge action',
          finding['suggested_action'] == 'nudge'
          and finding['severity'] in ('low', 'medium', 'high'),
          f"severity={finding['severity']} action={finding['suggested_action']}")


print('\n[4] a 6pt frame -> tiny_font, critical severity')

prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
box = text_frame(slide, 100, 300, 200, 40, 'tiny', 6.0)
report = lint_presentation(prs)
tiny = findings_of(report, 'tiny_font')
check('exactly one finding and it is tiny_font',
      len(report['findings']) == 1 and len(tiny) == 1,
      f"{len(report['findings'])} findings: {[f['kind'] for f in report['findings']]}")
if tiny:
    m = tiny[0]['measurements']
    check('it measures the effective 6pt against the 10pt floor',
          abs(m['font_pt'] - 6.0) < 0.001 and m['floor_pt'] == 10.0,
          f"font={m['font_pt']}pt floor={m['floor_pt']}pt")
    check('6pt is critical: high severity, manual action',
          tiny[0]['severity'] == 'high'
          and tiny[0]['suggested_action'] == 'manual'
          and tiny[0]['shape_id'] == box.shape_id,
          f"severity={tiny[0]['severity']} action={tiny[0]['suggested_action']}")


print('\n[5] a clean deck -> zero findings (including a decorative filled shape)')

prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
text_frame(slide, 72, 72, 300, 60, 'Governance framework review', 14.0)
# A decorative auto-shape with a fill and no text — the empty-placeholder
# check must not fire on it (it never held text; flagging it is crying wolf).
decoration = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Pt(400), Pt(300),
                                    Pt(200), Pt(80))
decoration.fill.solid()
report = lint_presentation(prs)
check('zero findings on a clean slide',
      len(report['findings']) == 0,
      f"{len(report['findings'])} findings: "
      f"{[(f['kind'], f['shape_id']) for f in report['findings']]}")
check('summary counts are all zero',
      report['summary']['findings'] == 0
      and report['summary']['high'] == 0
      and all(count == 0 for count in report['counts']['by_kind'].values()),
      f"summary={report['summary']}")
check('the decorative shape really was filled (the gate did real work)',
      decoration.fill.type is not None, f'fill={decoration.fill.type}')


print('\n[6] a wide wrapped paragraph that fits its box -> no overflow_width')

# Ratio 1.5+ (so the raw "single-line > box" rule would fire) but a wide box
# whose two wrapped lines both fit: that frame is working as designed, and
# reporting it would be the linter crying wolf on every body paragraph.
prs = Presentation()
slide = prs.slides.add_slide(prs.slide_layouts[6])
box = text_frame(slide, 50, 50, 400, 100, 'W ' * 60, 14.0, wrap=True)
report = lint_presentation(prs)
check('zero findings on a wrapping paragraph that fits',
      len(report['findings']) == 0,
      f"{len(report['findings'])} findings: "
      f"{[(f['kind'], f['shape_id']) for f in report['findings']]}")


print()
if FAILURES:
    print(f'{len(FAILURES)} CHECK(S) FAILED: ' + ', '.join(FAILURES))
    sys.exit(1)
print('All layout-lint checks passed.')


def test_layout_lint() -> None:
    """The module-level checks above run at import; expose their verdict to pytest."""
    assert not FAILURES, f'layout-lint checks failed: {FAILURES}'
