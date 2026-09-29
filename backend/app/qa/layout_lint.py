#!/usr/bin/env python3
"""Deterministic layout linter: layout damage as numbers, per slide, per frame.

Read-only analysis — no model calls, no network, no deck is ever modified. This
is the measurement half of the layout work: Phase 2 will drive repair passes off
this report, so every finding carries the numbers a fix needs (points over,
spill, intersection area, effective font size) and a `suggested_action` category
label from a fixed enum — never a geometry this pass guessed.

Checks (measurements in points; `slide` is the 1-based absolute slide number):

  overflow_width    single-line text wider than the usable box width (box minus
                    the frame's own side insets). With wrap off, any overshoot
                    is damage — the text runs out of the box sideways. With
                    wrap on it is damage only when the frame is also label-sized
                    (box under NARROW_BOX_PT: a label forced into paragraph
                    duty, the `bad_wrap` shape) or the wrapped result does not
                    fit the box's height either — a wide box whose text merely
                    wraps to two fitting lines is the height check's business,
                    not a width emergency. Reports box, text width, points over,
                    ratio, the worst paragraph, wrap and autofit state.
  overflow_height   needed lines x line height > usable box height. Line height
                    is font x LINE_HEIGHT_FACTOR; a paragraph counts as many
                    lines as its single-line width needs when wrap is on and one
                    line when wrap is off. Reports points/lines over. Severity is
                    medium while the frame sits on normAutofit (PowerPoint can
                    still shrink the text itself) and high otherwise.
  off_slide         a frame edge past the slide edge by more than
                    OFF_SLIDE_EPSILON_PT, one finding per offending edge,
                    reporting which edge and the spill. Applies to empty frames
                    too: a box out there is clipped whatever its text does.
  overlap           pairs of text-bearing frames whose boxes intersect by more
                    than OVERLAP_MIN_PT on both axes (a shared border is not an
                    overlap). Reports both shape ids, the intersection area in
                    pt^2 and its fraction of the smaller box.
  tiny_font         smallest effective run size in the frame below TINY_FONT_PT:
                    the explicit size (or the frame's fallback when a run has
                    none), times the normAutofit fontScale when written.
  empty_placeholder a frame with no text whose shape carries a visible fill or
                    border. Gated on TEXT_BOX/placeholder shapes only — the
                    deck's decorative filled FREEFORM frames are not frames that
                    were ever meant to hold text, and flagging them would bury
                    the real findings.

Every finding: slide, shape_id, kind, severity (high|medium|low),
suggested_action (wrap|grow_box|shrink_font|clamp_to_slide|nudge|manual), and a
`measurements` dict with that check's numbers. Overlap findings also carry
`other_shape_id`.

Measured through the injector's own width model (estimate_text_width,
_usable_box_pt, _fallback_font_pt), so this linter and the injector can never
disagree about whether a frame fits. Known limits — all deliberate, all on the
side of fewer false positives:

  * top-level shapes only: group children and table cells are not descended
    into (this deck has none of either), and rotation is not modeled — a
    rotated frame is measured as its axis-aligned box;
  * wrapping is counted at character level, a lower bound on PowerPoint's word
    wrapping, and empty paragraphs contribute no height;
  * heights assume font x LINE_HEIGHT_FACTOR per line; explicit line/paragraph
    spacing in the deck is not read.

Usage:
    venv/bin/python -m app.qa.layout_lint <deck.pptx> [--slides 2,6,7] [--json out.json]
    venv/bin/python -m app.qa.layout_lint --from-job JOB_ID

`--from-job` re-injects the job store's stored translations into that job's deck
(no API spend) and lints the result, writing the injected copy under ./tmp-lint/.
Exit codes: 0 = no high-severity finding, 1 = high-severity findings present
(so CI can gate on it), 2 = the run could not happen (bad arguments, missing
job or deck).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
from collections import Counter
from pathlib import Path

from pptx import Presentation
from pptx.enum.dml import MSO_FILL
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.oxml.ns import qn

from app.config import get_settings
from app.core.injector import (
    _fallback_font_pt,
    _usable_box_pt,
    estimate_text_width,
    inject_translations,
)
from app.job_store import get_job_store

EMU_PER_PT = 12700

# Legibility floor: a shrink-based fix must never take a run below this.
TINY_FONT_PT = 10.0
# At or below this the type is not just small, it is unreadable -> high.
CRITICAL_FONT_PT = 6.0

# Points of text height per line, relative to font size — PowerPoint's normal
# single-spacing factor for a default body.
LINE_HEIGHT_FACTOR = 1.2

# Sub-point height differences are inside this model's own error (line height
# is an estimate), so they are not findings.
HEIGHT_OVERFLOW_MIN_PT = 1.0

# With wrap on, a frame only reports overflow_width once the single-line text is
# this many times the box: below that, wrapping to two lines is the height
# check's business, not a bad-wrap emergency.
WIDTH_OVERFLOW_RATIO = 1.5

# ...and only when the box is label-sized (the `bad_wrap` class: a label forced
# into paragraph duty) or the height is over too. A wide box whose text wraps to
# fitting lines is working as designed. The real deck's narrow bad_wrap frames
# all sit under 120pt and the nearest wide borderline frame is over 220pt, so
# this line is not a knife edge.
NARROW_BOX_PT = 120.0

# Empty background frames sit ~0.01pt past the edge on every slide of the real
# deck; real off-slide frames spill at least 0.46pt. Nothing between matters.
OFF_SLIDE_EPSILON_PT = 0.1

# Overlap: intersection must exceed this on BOTH axes — a shared border is not
# an overlap — and the fraction of the smaller box sets the severity.
OVERLAP_MIN_PT = 1.0
OVERLAP_MEDIUM_FRACTION = 0.1
OVERLAP_HIGH_FRACTION = 0.5

KINDS = ('empty_placeholder', 'off_slide', 'overlap', 'overflow_height',
         'overflow_width', 'tiny_font')
SEVERITIES = ('high', 'medium', 'low')

THRESHOLDS = {
    'tiny_font_pt': TINY_FONT_PT,
    'critical_font_pt': CRITICAL_FONT_PT,
    'line_height_factor': LINE_HEIGHT_FACTOR,
    'height_overflow_min_pt': HEIGHT_OVERFLOW_MIN_PT,
    'width_overflow_ratio': WIDTH_OVERFLOW_RATIO,
    'narrow_box_pt': NARROW_BOX_PT,
    'off_slide_epsilon_pt': OFF_SLIDE_EPSILON_PT,
    'overlap_min_pt': OVERLAP_MIN_PT,
    'overlap_medium_fraction': OVERLAP_MEDIUM_FRACTION,
    'overlap_high_fraction': OVERLAP_HIGH_FRACTION,
}


def _round(value):
    return round(value, 4) if isinstance(value, float) else value


def _finding(slide, shape_id, kind, severity, action, measurements, **extra):
    finding = {
        'slide': slide,
        'shape_id': shape_id,
        'kind': kind,
        'severity': severity,
        'suggested_action': action,
    }
    finding.update({key: _round(value) for key, value in extra.items()})
    finding['measurements'] = {key: _round(value)
                               for key, value in measurements.items()}
    return finding


def _frame_text(text_frame) -> str:
    return ''.join(run.text for para in text_frame.paragraphs for run in para.runs)


def _autofit_name(text_frame) -> str:
    auto = text_frame.auto_size
    if auto == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT:
        return 'spAutoFit'
    if auto == MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE:
        return 'normAutofit'
    return 'none'


def _font_scale(text_frame) -> float:
    """normAutofit's fontScale as PowerPoint stores it (ST_Percentage: 75000 = 75%)."""
    try:
        body_pr = text_frame._txBody.find(qn('a:bodyPr'))
        norm = body_pr.find(qn('a:normAutofit')) if body_pr is not None else None
        raw = norm.get('fontScale') if norm is not None else None
        if not raw:
            return 1.0
        return max(0.0, int(raw)) / 100000.0
    except (AttributeError, TypeError, ValueError):
        return 1.0


def _line_count(text: str, wrap_off: bool, box_w_pt: float, font_pt: float) -> int:
    """Lines one paragraph needs. Character-level greedy fill — a lower bound on
    real word wrapping, deliberately: it can miss a wrap, never invent one."""
    if wrap_off or box_w_pt <= 0:
        return 1
    width = estimate_text_width(text, font_pt)
    return max(1, math.ceil(width / box_w_pt - 1e-6))


def _visible_fill(shape) -> bool:
    try:
        fill_type = shape.fill.type
    except Exception:
        return False
    return fill_type is not None and fill_type != MSO_FILL.BACKGROUND


def _visible_line(shape) -> bool:
    try:
        line_type = shape.line.fill.type
    except Exception:
        return False
    return line_type is not None and line_type != MSO_FILL.BACKGROUND


def _is_text_box_shape(shape) -> bool:
    """True for shapes that exist to hold text (vs. decorative filled shapes)."""
    if shape.shape_type == MSO_SHAPE_TYPE.TEXT_BOX:
        return True
    return bool(getattr(shape, 'is_placeholder', False))


def _text_extent(text_frame, box_w_pt: float, box_h_pt: float, wrap_off: bool,
                 font_pt: float) -> tuple:
    """Estimated (width, height) the frame's own text actually occupies, in pt.

    The box is what the importer drew; this is what the words need inside it. The
    difference is the whole reason a deck full of overlapping boxes can render
    cleanly: a wide box holding a short line has text in one corner, and two such
    boxes can intersect without a single glyph colliding.
    """
    widest = 0.0
    lines = 0
    for para in text_frame.paragraphs:
        text = ''.join(run.text for run in para.runs)
        if not text.strip():
            continue
        widest = max(widest, estimate_text_width(text, font_pt))
        lines += _line_count(text, wrap_off, box_w_pt, font_pt) if box_w_pt > 0 else 1
    if not wrap_off and box_w_pt > 0:
        widest = min(widest, box_w_pt)   # wrap off does not mean it fits
    text_h = lines * font_pt * LINE_HEIGHT_FACTOR
    if box_h_pt > 0:
        text_h = min(text_h, box_h_pt)
    return widest, text_h


def _text_rect(frame: dict) -> tuple:
    """The rectangle a frame's TEXT occupies: its position, the text's extent.

    Not clamped to the box: with wrap off the text runs past the box's edge, and
    an unwrapped line crossing another frame's text is exactly the collision worth
    reporting.
    """
    return (frame['l'], frame['t'], frame['tw'] or frame['w'], frame['th'] or frame['h'])


def _free_growth(l_pt: float, t_pt: float, w_pt: float, h_pt: float,
                 add_w_pt: float, add_h_pt: float, slide_w_pt: float,
                 slide_h_pt: float, neighbours, self_id,
                 text_w_pt: float = 0.0, text_h_pt: float = 0.0) -> bool:
    """True when a box on spAutoFit grows to fit its text and lands on nothing.

    A frame on spAutoFit grows to fit its text, so 'the text is wider than the
    box' is only damage when the growth costs something. Two costs count:

      * the text itself ends past the slide edge (clipped, whatever the box does);
      * the grown box lands on another frame's text — that is the "two sentences
        printed on top of each other" defect.

    A grown *box* reaching past the slide edge is not a cost on its own: the text
    stays inside. On the deck this was written for, every one of the 827 width
    findings on the original file was wrap-off + spAutoFit, and the render is
    clean — the boxes simply grow into space nobody else is using.
    """
    if add_w_pt <= 0 and add_h_pt <= 0:
        return False
    if text_w_pt and l_pt + text_w_pt > slide_w_pt + OVERLAP_MIN_PT:
        return False
    if text_h_pt and t_pt + text_h_pt > slide_h_pt + OVERLAP_MIN_PT:
        return False
    grown = (l_pt, t_pt, w_pt + max(add_w_pt, 0.0), h_pt + max(add_h_pt, 0.0))
    gl, gt, gw, gh = grown
    for other in neighbours or ():
        if other['id'] == self_id:
            continue
        ox, oy, ow, oh = _text_rect(other)
        if (min(gl + gw, ox + ow) - max(gl, ox) > OVERLAP_MIN_PT
                and min(gt + gh, oy + oh) - max(gt, oy) > OVERLAP_MIN_PT):
            return False
    return True


def check_frame(slide_no: int, shape, slide_w_emu: int, slide_h_emu: int,
                neighbours=None) -> list:
    """Findings for one top-level shape that has a text frame.

    Runs off_slide (also for empty frames), then — only when the frame really
    carries text — overflow_width, overflow_height and tiny_font; an empty frame
    may instead be an empty_placeholder.

    `neighbours` is the slide's other text-bearing frame rects (see
    lint_presentation); it is what tells a frame that cannot hold its text apart
    from a frame that simply grows into empty space.
    """
    findings = []
    text_frame = shape.text_frame
    try:
        left, top = int(shape.left), int(shape.top)
        width, height = int(shape.width), int(shape.height)
    except (TypeError, ValueError):
        return findings  # unpositioned shape: nothing to measure against
    shape_id = shape.shape_id

    slide_w_pt = slide_w_emu / EMU_PER_PT
    slide_h_pt = slide_h_emu / EMU_PER_PT
    l_pt, t_pt = left / EMU_PER_PT, top / EMU_PER_PT
    w_pt, h_pt = width / EMU_PER_PT, height / EMU_PER_PT

    for edge, spill_pt in (
        ('left', -l_pt),
        ('top', -t_pt),
        ('right', (l_pt + w_pt - slide_w_pt)),
        ('bottom', (t_pt + h_pt - slide_h_pt)),
    ):
        if spill_pt > OFF_SLIDE_EPSILON_PT:
            findings.append(_finding(slide_no, shape_id, 'off_slide', 'high',
                                     'clamp_to_slide',
                                     {'edge': edge, 'spill_pt': spill_pt}))

    if not _frame_text(text_frame).strip():
        if _is_text_box_shape(shape) and (
                _visible_fill(shape) or _visible_line(shape)):
            findings.append(_finding(
                slide_no, shape_id, 'empty_placeholder', 'medium', 'manual',
                {'box_w_pt': w_pt, 'box_h_pt': h_pt}))
        return findings

    wrap_off = text_frame.word_wrap is False
    autofit = _autofit_name(text_frame)
    box_w_pt = _usable_box_pt(text_frame, width) if width else 0.0
    # vertical twin of the injector's _usable_box_pt: box minus the frame's own
    # top/bottom insets
    box_h_pt = 0.0
    if height:
        box_h_pt = (h_pt
                    - sum(int(getattr(text_frame, attr, 0) or 0)
                          for attr in ('margin_top', 'margin_bottom'))
                    / EMU_PER_PT)
    font_pt = _fallback_font_pt(text_frame)
    text_w_pt, text_h_pt = _text_extent(text_frame, box_w_pt, box_h_pt,
                                        wrap_off, font_pt)

    # off_slide above reported the box. Only keep 'high' where that box also puts
    # TEXT off the slide — template furniture bleeding an inch past the edge (an
    # identical 5 findings on each of the last four slides of the original) is a
    # design decision, and a repair engine told to chase it would move furniture.
    for finding in findings:
        if finding['kind'] != 'off_slide' or not text_w_pt:
            continue
        edge = finding['measurements']['edge']
        clipped = {
            # measured against the text, not the box: a box whose right edge is
            # past the slide edge but whose text stops short loses nothing
            'right': l_pt + text_w_pt > slide_w_pt + OFF_SLIDE_EPSILON_PT,
            'bottom': t_pt + text_h_pt > slide_h_pt + OFF_SLIDE_EPSILON_PT,
            'left': l_pt < 0 and wrap_off,
            'top': t_pt < 0 and box_h_pt <= 0,
        }.get(edge, True)
        if not clipped:
            finding['severity'] = 'low'
            finding['measurements']['box_only'] = True

    # overflow_height first: the width gate below needs to know whether the
    # wrapped result also fails vertically.
    height_over_pt = 0.0
    if box_h_pt > 0:
        lines_needed = 0
        for para in text_frame.paragraphs:
            para_text = ''.join(run.text for run in para.runs)
            if not para_text.strip():
                continue  # empty paragraphs take space, but counting them would
                          # over-report; this is the lower bound we chose
            lines_needed += _line_count(para_text, wrap_off, box_w_pt, font_pt)
        line_height_pt = font_pt * LINE_HEIGHT_FACTOR
        needed_h_pt = lines_needed * line_height_pt
        height_over_pt = needed_h_pt - box_h_pt
        if height_over_pt > HEIGHT_OVERFLOW_MIN_PT:
            lines_fit = math.floor(box_h_pt / line_height_pt)
            growth_free = (autofit == 'spAutoFit'
                           and _free_growth(l_pt, t_pt, w_pt, h_pt, 0.0,
                                            height_over_pt, slide_w_pt, slide_h_pt,
                                            neighbours, shape_id,
                                            text_w_pt, text_h_pt))
            findings.append(_finding(
                slide_no, shape_id, 'overflow_height',
                'low' if growth_free else
                ('medium' if autofit == 'normAutofit' else 'high'), 'grow_box',
                {'box_h_pt': box_h_pt, 'needed_h_pt': needed_h_pt,
                 'over_pt': height_over_pt, 'lines_needed': lines_needed,
                 'lines_over': max(0, lines_needed - lines_fit),
                 'autofit': autofit, 'growth_free': growth_free}))

    # overflow_width: the worst paragraph that cannot fit on one line.
    worst = None
    for index, para in enumerate(text_frame.paragraphs):
        para_text = ''.join(run.text for run in para.runs)
        if not para_text.strip() or box_w_pt <= 0:
            continue
        single_line_pt = estimate_text_width(para_text, font_pt)
        if single_line_pt <= box_w_pt:
            continue
        ratio = single_line_pt / box_w_pt
        if worst is None or ratio > worst[0]:
            worst = (ratio, index, single_line_pt)
    if worst is not None:
        ratio, para_index, single_line_pt = worst
        # wrap off: always damage. wrap on: only when the box is label-sized
        # (bad_wrap) or the height is over as well — a wide box wrapping to
        # fitting lines is not a width problem.
        wrap_damage = (ratio >= WIDTH_OVERFLOW_RATIO
                       and (box_w_pt < NARROW_BOX_PT
                            or height_over_pt > HEIGHT_OVERFLOW_MIN_PT))
        if wrap_off or wrap_damage:
            over_pt = single_line_pt - box_w_pt
            growth_free = (autofit == 'spAutoFit'
                           and _free_growth(l_pt, t_pt, w_pt, h_pt, over_pt, 0.0,
                                            slide_w_pt, slide_h_pt, neighbours,
                                            shape_id, text_w_pt, text_h_pt))
            severity, action = (('high', 'wrap') if wrap_off
                                else ('medium', 'grow_box'))
            findings.append(_finding(
                slide_no, shape_id, 'overflow_width',
                'low' if growth_free else severity, action,
                {'box_pt': box_w_pt, 'text_pt': single_line_pt,
                 'over_pt': over_pt, 'ratio': ratio,
                 'paragraph': para_index, 'wrap_off': wrap_off,
                 'autofit': autofit, 'growth_free': growth_free}))

    # tiny_font: smallest effective run size (fontScale applied when written).
    scale = _font_scale(text_frame)
    sizes = [(run.font.size.pt if run.font.size else font_pt) * scale
             for para in text_frame.paragraphs for run in para.runs]
    if sizes:
        smallest = min(sizes)
        if smallest < TINY_FONT_PT:
            findings.append(_finding(
                slide_no, shape_id, 'tiny_font',
                'high' if smallest <= CRITICAL_FONT_PT else 'medium', 'manual',
                {'font_pt': smallest, 'floor_pt': TINY_FONT_PT,
                 'font_scale': scale, 'autofit': autofit}))

    return findings


def check_overlaps(slide_no: int, frames: list) -> list:
    """Pairwise overlap findings for one slide's text-bearing frames.

    `frames` is a list of dicts: {'id', 'l', 't', 'w', 'h', 'tw', 'th'} in slide
    order — the box rectangle and the rectangle the frame's TEXT occupies (see
    _text_extent). Two boxes can cross without a glyph touching: a 400pt box
    holding a 90pt label has its text in one corner, and the report should not
    call that a collision. The pair's finding names the earlier shape as
    shape_id.
    """
    findings = []
    for index, first in enumerate(frames):
        for second in frames[index + 1:]:
            fx, fy, fw, fh = _text_rect(first)
            sx, sy, sw, sh = _text_rect(second)
            overlap_w = min(fx + fw, sx + sw) - max(fx, sx)
            overlap_h = min(fy + fh, sy + sh) - max(fy, sy)
            if overlap_w <= OVERLAP_MIN_PT or overlap_h <= OVERLAP_MIN_PT:
                continue  # contact or a hairline: not an overlap
            smaller_area = min(fw * fh, sw * sh)
            if smaller_area <= 0:
                continue
            area_pt2 = overlap_w * overlap_h
            fraction = area_pt2 / smaller_area
            if fraction >= OVERLAP_HIGH_FRACTION:
                severity = 'high'
            elif fraction >= OVERLAP_MEDIUM_FRACTION:
                severity = 'medium'
            else:
                severity = 'low'
            findings.append(_finding(slide_no, first['id'], 'overlap', severity,
                                     'nudge',
                                     {'area_pt2': area_pt2,
                                      'fraction': fraction},
                                     other_shape_id=second['id']))
    return findings


def _select_slides(slides, slide_count: int) -> list:
    if slides is None:
        return list(range(1, slide_count + 1))
    bad = [n for n in slides if n < 1 or n > slide_count]
    if bad:
        raise ValueError(f'slides out of range 1..{slide_count}: {bad}')
    return sorted(set(slides))


def lint_presentation(prs, slides=None, deck=None) -> dict:
    """Lint a loaded presentation; returns the full report dict."""
    slide_count = len(prs.slides)
    wanted = _select_slides(slides, slide_count)
    slide_w_emu, slide_h_emu = int(prs.slide_width), int(prs.slide_height)

    findings = []
    for slide_no in wanted:
        slide = prs.slides[slide_no - 1]
        # Two passes: every text frame's rect first, so each frame can be told
        # what it would grow into (check_frame) and so overlaps can be measured
        # against the text rather than the box (check_overlaps).
        shapes = [sh for sh in slide.shapes
                  if getattr(sh, 'has_text_frame', False)]
        frames = []
        for shape in shapes:
            text_frame = shape.text_frame
            try:
                l_pt = shape.left / EMU_PER_PT
                t_pt = shape.top / EMU_PER_PT
                w_pt = shape.width / EMU_PER_PT
                h_pt = shape.height / EMU_PER_PT
            except (TypeError, ValueError):
                continue
            if not _frame_text(text_frame).strip():
                continue
            wrap_off = text_frame.word_wrap is False
            box_w_pt = _usable_box_pt(text_frame, int(shape.width)) if shape.width else 0.0
            font_pt = _fallback_font_pt(text_frame)
            tw, th = _text_extent(text_frame, box_w_pt, h_pt, wrap_off, font_pt)
            frames.append({'id': shape.shape_id, 'l': l_pt, 't': t_pt,
                           'w': w_pt, 'h': h_pt, 'tw': tw, 'th': th})
        for shape in shapes:
            findings.extend(check_frame(slide_no, shape,
                                        slide_w_emu, slide_h_emu,
                                        neighbours=frames))
        findings.extend(check_overlaps(slide_no, frames))

    findings.sort(key=lambda f: (f['slide'], f['kind'], f['shape_id'],
                                 f.get('other_shape_id', -1)))

    by_kind = Counter(f['kind'] for f in findings)
    by_severity = Counter(f['severity'] for f in findings)
    slides_with_findings = len({f['slide'] for f in findings})
    report = {
        'deck': deck,
        'slide_count': slide_count,
        'slides_linted': wanted,
        'slide_size_pt': {'width': round(slide_w_emu / EMU_PER_PT, 2),
                          'height': round(slide_h_emu / EMU_PER_PT, 2)},
        'thresholds': THRESHOLDS,
        'findings': findings,
        'counts': {
            'by_kind': {kind: by_kind[kind] for kind in KINDS},
            'by_severity': {sev: by_severity[sev] for sev in SEVERITIES},
        },
        'summary': {
            'findings': len(findings),
            'high': by_severity['high'],
            'medium': by_severity['medium'],
            'low': by_severity['low'],
            'slides_with_findings': slides_with_findings,
            'slides_linted': len(wanted),
        },
    }
    return report


def _worst(finding_list):
    """(points_over, kind) of the finding with the largest point measurement."""
    worst = None
    for finding in finding_list:
        measurements = finding['measurements']
        value = measurements.get('over_pt', measurements.get('spill_pt'))
        if value is not None and (worst is None or value > worst[0]):
            worst = (value, finding['kind'])
    return worst


def _print_report(report, out=sys.stdout) -> None:
    size = report['slide_size_pt']
    linted = report['slides_linted']
    if len(linted) == report['slide_count']:
        scope = f'all {len(linted)}'
    else:
        scope = ','.join(str(n) for n in linted)
    print(f"layout lint: {report['deck']}", file=out)
    print(f"  {report['slide_count']} slides, {size['width']:g}x{size['height']:g}pt, "
          f"linting {scope}", file=out)
    t = report['thresholds']
    print(f"  thresholds: off_slide spill > {t['off_slide_epsilon_pt']}pt | "
          f"overlap > {t['overlap_min_pt']}pt both axes "
          f"(fraction >= {t['overlap_medium_fraction']} medium, "
          f">= {t['overlap_high_fraction']} high) | "
          f"tiny_font < {t['tiny_font_pt']}pt "
          f"(critical <= {t['critical_font_pt']}pt) | "
          f"overflow_width when wrap is off, or ratio >= {t['width_overflow_ratio']} "
          f"with box < {t['narrow_box_pt']}pt or height over | "
          f"overflow_height over > {t['height_overflow_min_pt']}pt at "
          f"{t['line_height_factor']}x line height", file=out)

    per_slide = {}
    for finding in report['findings']:
        per_slide.setdefault(finding['slide'], []).append(finding)
    for slide_no in linted:
        slide_findings = per_slide.get(slide_no)
        if not slide_findings:
            print(f'  slide {slide_no:>2}: no findings', file=out)
            continue
        counts = Counter(f['kind'] for f in slide_findings)
        kinds_str = ', '.join(f'{kind} {counts[kind]}' for kind in
                              sorted(counts, key=lambda k: (-counts[k], k)))
        worst = _worst(slide_findings)
        worst_str = f'  worst {worst[1]} +{worst[0]:.2f}pt' if worst else ''
        print(f'  slide {slide_no:>2}: {len(slide_findings):>3} findings  '
              f'{kinds_str}{worst_str}', file=out)

    summary = report['summary']
    print('', file=out)
    if not report['findings']:
        print('deck clean: no findings', file=out)
        return
    print(f"deck: {summary['findings']} findings on "
          f"{summary['slides_with_findings']}/{summary['slides_linted']} linted "
          f"slides (high {summary['high']}, medium {summary['medium']}, "
          f"low {summary['low']})", file=out)
    by_kind = report['counts']['by_kind']
    ordered = sorted(by_kind, key=lambda k: (-by_kind[k], k))
    print('  by kind: ' + ', '.join(f'{k} {by_kind[k]}' for k in ordered),
          file=out)


def _job_deck(job_id: str):
    """(injected deck path, None) or (None, error message) for --from-job.

    Re-injects the job store's stored runs into the job's input deck — no model
    calls, no API spend — and leaves the injected copy under ./tmp-lint/.
    """
    job = get_job_store().load(job_id)
    if job is None:
        return None, f'job {job_id} not found in the job store'
    upload_dir = Path(get_settings().upload_dir)
    if getattr(job, 'source_format', None) == 'pdf':
        # Path().name re-bases the recorded upload name (same as main.py).
        original = Path(job.source_filename or job.filename).name
        source = upload_dir / f'{job_id}_{original}.pptx'
        if not source.exists():
            return None, f'converted PPTX for this PDF not found: {source}'
    else:
        candidates = sorted(upload_dir.glob(f'{job_id}_*.pptx'))
        if not candidates:
            return None, f'no uploaded deck found for job {job_id} in {upload_dir}/'
        source = candidates[0]
    scratch = Path('tmp-lint')
    scratch.mkdir(parents=True, exist_ok=True)
    injected = scratch / f'{job_id}.injected.pptx'
    chatter = io.StringIO()
    with contextlib.redirect_stdout(chatter):  # injector prints -> stderr only
        ok, failed = inject_translations(str(source), str(injected),
                                          job.translated_runs, None)
    print(f'injected {ok} runs ({len(failed)} failed) from {source.name} '
          f'-> {injected}', file=sys.stderr)
    if failed:
        sys.stderr.write(chatter.getvalue())
    if not injected.exists():
        return None, f'injection wrote no deck: {injected}'
    return injected, None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='python -m app.qa.layout_lint',
        description='Deterministic layout linter — measures overflow, off-slide '
                    'frames, overlaps, tiny type and empty frames as numbers. '
                    'No model calls, no network.',
        epilog='exit codes: 0 no high-severity finding, 1 high-severity '
               'findings present, 2 the run could not happen')
    parser.add_argument('deck', nargs='?', help='path to a .pptx file')
    parser.add_argument('--from-job', metavar='JOB_ID',
                        help="inject that job's stored translations into its "
                             'deck, then lint the result')
    parser.add_argument('--slides', metavar='LIST',
                        help='comma-separated 1-based slide numbers '
                             '(default: all)')
    parser.add_argument('--json', metavar='PATH',
                        help='also write the full report as JSON to PATH')
    args = parser.parse_args(argv)

    if bool(args.deck) == bool(args.from_job):
        parser.error('give a deck path or --from-job JOB_ID (exactly one)')
    slides = None
    if args.slides:
        try:
            slides = sorted({int(part) for part in args.slides.split(',')
                             if part.strip()})
        except ValueError:
            parser.error(f'--slides must be comma-separated numbers, '
                         f'got {args.slides!r}')
        if not slides or slides[0] < 1:
            parser.error(f'--slides must be 1-based, got {args.slides!r}')

    if args.deck:
        deck_path = Path(args.deck)
        if not deck_path.exists():
            print(f'no such deck: {deck_path}', file=sys.stderr)
            return 2
    else:
        deck_path, error = _job_deck(args.from_job)
        if error:
            print(error, file=sys.stderr)
            return 2
    try:
        prs = Presentation(str(deck_path))
    except Exception as exc:
        print(f'cannot open deck {deck_path}: {exc}', file=sys.stderr)
        return 2
    if slides and slides[-1] > len(prs.slides):
        print(f'--slides: deck has {len(prs.slides)} slides', file=sys.stderr)
        return 2

    report = lint_presentation(prs, slides=slides, deck=str(deck_path))
    _print_report(report)
    if args.json:
        json_path = Path(args.json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + '\n',
            encoding='utf-8')
        print(f'json report: {json_path}')
    return 1 if report['summary']['high'] else 0


if __name__ == '__main__':
    sys.exit(main())
