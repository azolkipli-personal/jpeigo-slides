"""
Core PPTX re-injection logic.
Re-inserts translated text while preserving original styling.
"""
from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.shapes.base import BaseShape as Shape
from pptx.shapes.group import GroupShape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.text.text import TextFrame
from pptx.util import Pt, Emu
from typing import Optional
import copy
import os
from lxml import etree

from app.models import TranslatedRun, TranslationJob, SpatialConstraints
from app.core.smartart import (
    find_diagram_part,
    is_smartart_graphic_frame,
    iter_text_nodes,
)


SMARTART_REL_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData'
SMARTART_DGM_URI = 'http://schemas.openxmlformats.org/drawingml/2006/diagram'
PPTX_NS = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'dgm': 'http://schemas.openxmlformats.org/drawingml/2006/diagram',
}

A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'

# Typeface written for Japanese output. python-pptx's font.name only sets
# <a:latin>, which does not drive CJK glyph selection, so the previous override
# was cosmetic for Japanese text. Override with JP_FONT_FAMILY when the machine
# that renders previews lacks the family; core/fonts.py checks that and
# /api/health reports it, because fontconfig substitutes silently.
JP_FONT_FAMILY = os.environ.get('JP_FONT_FAMILY', 'Yu Gothic')

# Per-shape and per-paragraph trace lines run to hundreds of lines on a real deck
# (one line per shape per slide), which buries the one line per job that a log is
# for. Off unless PPTX_VERBOSE=1; the end-of-run summary and the error lines stay on.
VERBOSE = os.environ.get('PPTX_VERBOSE', '') not in ('', '0', 'false', 'False')


# Average character widths for font size estimation
# These are approximations for common fonts
CHAR_WIDTH_RATIOS = {
    'ja': 1.0,   # Japanese characters (full-width)
    'en': 0.5,   # English characters (half-width)
}

# Used only when a frame carries no explicit run size anywhere, so the
# wrap gate still has a size to measure with. check_text_fit() falls back
# to the same value.
DEFAULT_FONT_PT = 12.0

# A frame whose box sits past the slide edge is clipped at the boundary whatever
# its wrap/autofit does, so the box itself has to come back first (gap 1). The
# margin is 0.1in — PowerPoint's own default text inset — because LibreOffice's
# PDF import writes lIns=rIns=0 on every frame it creates: with no inset left
# inside the frame, this margin is the only gap between its text and the
# physical edge of the slide.
SLIDE_EDGE_MARGIN_EMU = 91440  # 0.1in

# No clamped frame is left narrower than this; a box that would shrink past it
# slides back whole instead (see clamp_frame_to_slide).
MIN_CLAMPED_WIDTH_EMU = 91440  # 0.1in

# shrink_frame_text_to_fit() stops here — the same floor calculate_font_scale
# applies to paragraph scaling. Text that still does not fit wraps instead of
# shrinking into illegibility, and apply_frame_layout() has already turned
# wrap on for the frame by then.
FIT_SHRINK_FLOOR = 0.5

# Type never shrinks below this, whatever the box demands: 6pt body text is
# unreadable in a meeting room, and a deck full of it is worse than a frame that
# spills a few points. Measured on the deck that motivated this: 6.0pt is exactly
# 12pt x the 0.5 floor, and 5.25pt is 10.5pt x 0.5, so the floor was being reached
# on ~29 frames and passed on others. A limit on shrinking only — a frame the
# source already set at or below this (the 8.1pt Hitachi footer) never changes.
MIN_LEGIBLE_FONT_PT = float(os.environ.get('PPTX_MIN_FONT_PT', '10'))


def legibility_floor_scale(size_pt: Optional[float]) -> float:
    """Smallest scale allowed for text that starts at `size_pt`.

    1.0 for text already at or below the floor, i.e. it may not shrink at all;
    MIN_LEGIBLE_FONT_PT/size_pt above it. The floor is a point size, not a
    fraction of an original nobody can see, so it means the same thing on a 12pt
    bullet and a 32pt title.
    """
    if not size_pt or size_pt <= MIN_LEGIBLE_FONT_PT:
        return 1.0
    return MIN_LEGIBLE_FONT_PT / size_pt



def estimate_visual_width(text: str) -> float:
    """Estimate visual width of text. CJK chars are ~2.2x width of Latin chars in practice."""
    cjk = sum(1 for c in text if '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff' or '\uff00' <= c <= '\uffef')
    latin = len(text) - cjk
    return cjk * 2.2 + latin * 1.0


def calculate_font_scale(original_text: str, translated_text: str) -> float:
    """
    Calculate font scale factor to prevent overflow.
    If translated text is visually wider than original, scale down proportionally.
    Caps at 0.5x (don't make text too small).
    """
    orig_width = estimate_visual_width(original_text)
    trans_width = estimate_visual_width(translated_text)
    
    if trans_width <= orig_width * 1.05:
        return 1.0  # No scaling needed (within 5% tolerance)
    
    scale = orig_width / trans_width
    return max(scale, 0.5)  # Don't go below 50%


def _run_index(tr: TranslatedRun) -> int:
    """Run index within its paragraph, from the run_id layout
    run_<slide>_<shape path>_<paragraph>_<run>_<counter>."""
    parts = tr.run_id.split('_')
    return int(parts[4]) if len(parts) > 4 else 0


def _paragraph_key(tr: TranslatedRun) -> str:
    """Identity of the paragraph a run belongs to.

    parts[2] is the shape path and parts[3] the paragraph index, so this groups
    table-cell runs too — their path encodes shape.table.row.col.
    """
    parts = tr.run_id.split('_')
    return f"{parts[2] if len(parts) > 2 else '0'}|{parts[3] if len(parts) > 3 else '0'}"


def paragraph_font_scale(group: list[TranslatedRun]) -> float:
    """One font scale for a whole paragraph, computed for any target language.

    Scaling each run from its own fragment gives runs in the same paragraph
    different sizes, because every fragment has its own original:translated width
    ratio. The scale has to come from the paragraph's combined text.

    This used to return 1.0 unless the target was Japanese, so JP->EN — the
    direction that actually grows (an English translation of a Japanese line is
    markedly longer) — got no length mitigation at all. The width model and its
    tuned parameters (cjk_ratio 2.2, 5% tolerance, 0.5 floor) are unchanged;
    only the gate is gone, so EN->JA output is byte-identical.
    """
    ordered = sorted(group, key=_run_index)
    original = ''.join(tr.original_text for tr in ordered)
    translated = ''.join(tr.translated_text for tr in ordered)
    return calculate_font_scale(original, translated)


def resolve_font_size(tr: TranslatedRun, para_scale: float, orig_font_size) -> Optional[float]:
    """Smallest of the fit-derived size and the paragraph-scaled size.

    Taking the minimum stops the paragraph scale from overwriting
    adjusted_font_size (the geometry-fit result), which used to be discarded.
    The result is then raised to the legibility floor (gap: 8.1pt footers and
    6pt bullets both shipped) — a frame that cannot hold its text at a legible
    size is allowed to spill instead, which is what the reader can still read.
    """
    candidates = []
    if tr.adjusted_font_size:
        candidates.append(tr.adjusted_font_size)
    if para_scale < 1.0 and orig_font_size:
        candidates.append(orig_font_size.pt * para_scale)
    if not candidates:
        return None
    size = min(candidates)
    if orig_font_size:
        size = max(size, min(orig_font_size.pt, MIN_LEGIBLE_FONT_PT))
    return size


def estimate_text_width(text: str, font_size: float) -> float:
    """
    Estimate text width based on character content.
    Japanese characters are typically wider than English.
    """
    # Count Japanese vs English characters
    ja_count = sum(1 for c in text if '\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff')
    en_count = len(text) - ja_count
    
    # Estimate width
    ja_width = ja_count * font_size * CHAR_WIDTH_RATIOS['ja']
    en_width = en_count * font_size * CHAR_WIDTH_RATIOS['en']
    
    return ja_width + en_width


def frame_text_grew(runs: list[TranslatedRun]) -> bool:
    """True when a frame's combined translated text is wider than its source.

    Widths come from estimate_visual_width — the same model calculate_font_scale
    scales against — so "grew" and "shrank the font" can never disagree about a
    frame. Language-agnostic: it counts CJK and Latin at their real relative
    widths, which is what makes it usable for every target language.
    """
    original = ''.join(tr.original_text for tr in runs)
    translated = ''.join(tr.translated_text for tr in runs)
    return estimate_visual_width(translated) > estimate_visual_width(original)


def _usable_box_pt(text_frame, width_emu: int) -> float:
    """Box width in points, minus the frame's own left and right insets."""
    margins = 0
    for attr in ('margin_left', 'margin_right'):
        try:
            margins += int(getattr(text_frame, attr) or 0)
        except Exception:
            pass
    return (width_emu - margins) / 12700


def _fallback_font_pt(text_frame) -> float:
    """Largest explicit run size in the frame; DEFAULT_FONT_PT when there is none."""
    sizes = [run.font.size.pt for para in text_frame.paragraphs
             for run in para.runs if run.font.size]
    return max(sizes) if sizes else DEFAULT_FONT_PT


def frame_text_exceeds_box(text_frame, shape) -> bool:
    """True when any paragraph of the frame needs more than one line to fit.

    This is the gate for word_wrap: a frame whose translation still fits its box
    width keeps whatever wrap setting it arrived with, because turning wrap on
    for a single-line label changes the layout for no reason.
    """
    try:
        width_emu = int(shape.width)
    except (TypeError, ValueError):
        return False
    box_pt = _usable_box_pt(text_frame, width_emu)
    if box_pt <= 0:
        return False

    fallback = _fallback_font_pt(text_frame)

    for para in text_frame.paragraphs:
        text = ''.join(run.text for run in para.runs)
        if not text.strip():
            continue
        sizes = [run.font.size.pt for run in para.runs if run.font.size]
        size = max(sizes) if sizes else fallback
        if estimate_text_width(text, size) > box_pt:
            return True
    return False


def apply_frame_layout(shape, text_frame, runs: list[TranslatedRun]) -> tuple[bool, bool]:
    """Neutralise the PDF-import autofit/wrap artifacts on an injected frame.

    LibreOffice's PDF import writes `spAutoFit` (SHAPE_TO_FIT_TEXT) and
    `wrap="none"` on every text frame it creates. Once a translation outgrows the
    source, `spAutoFit` grows the box over its neighbour — the "two sentences
    printed on top of each other" defect — and wrap off sends the overflow
    straight off the slide edge. Both are replaced, each behind its own gate so a
    frame the translation did not disturb is left exactly as it was:

      * text grew or no longer fits the box -> normAutofit (TEXT_TO_FIT_SHAPE),
        the PowerPoint-native "shrink text to fit" answer. A frame that neither
        grew nor overflowed cannot grow into anything, so it keeps its autofit.
      * text no longer fits the box          -> word_wrap = True.

    Returns (autofit_changed, wrap_changed).
    """
    autofit_changed = wrap_changed = False
    try:
        needs_wrap = frame_text_exceeds_box(text_frame, shape)
        grows_box = text_frame.auto_size == MSO_AUTO_SIZE.SHAPE_TO_FIT_TEXT
        if grows_box and (frame_text_grew(runs) or needs_wrap):
            text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
            autofit_changed = True
        if needs_wrap and text_frame.word_wrap is False:
            text_frame.word_wrap = True
            wrap_changed = True
    except Exception as exc:
        print(f"  [INJECTOR] frame layout fix failed (shape {getattr(shape, 'shape_id', '?')}): {exc}")
    return autofit_changed, wrap_changed


def slide_width_emu(shape) -> Optional[int]:
    """Width of the slide `shape` sits on, or None when it cannot be resolved."""
    try:
        return int(shape.part.package.presentation_part.presentation.slide_width)
    except Exception:
        return None


def clamp_frame_to_slide(shape) -> bool:
    """Pull a frame that sits past the slide's right edge back inside the slide.

    LibreOffice's PDF import recreates some text boxes off-slide (up to 213pt
    past the edge on the deck this was written for), and a frame out there is
    clipped at the slide boundary whatever its wrap or autofit does — no
    wrap/autofit change can rescue a box that is not on the page. Only the box
    is touched, and only when it is actually off-slide:

      * a frame already inside the slide does not move by a single EMU;
      * otherwise `width` comes off first, so the frame keeps its left edge and
        the narrowed box is a subset of the old one — it cannot come to rest on
        anything the source did not already cover;
      * `left` moves only when the left edge itself is past the limit, i.e. when
        shrinking would leave a sliver (no such frame in the deck under test).

    Grouped children are never passed here: their coordinates live in the
    group's child space, so a clamp in EMUs would not land them on the slide.

    Returns True when the frame moved.
    """
    slide_width = slide_width_emu(shape)
    if slide_width is None:
        return False
    limit = slide_width - SLIDE_EDGE_MARGIN_EMU
    if limit <= 0:
        return False
    try:
        left = int(shape.left)
        width = int(shape.width)
    except (TypeError, ValueError):
        return False

    if left + width <= slide_width:
        return False  # inside the slide — not one EMU moves

    if left < limit and limit - left >= MIN_CLAMPED_WIDTH_EMU:
        shape.width = limit - left
        return True

    # The left edge is (nearly) past the limit too: taking width off would leave
    # a sliver, so the frame slides back whole, capped at the usable slide width.
    new_width = min(width, limit)
    if new_width != width:
        shape.width = new_width
    shape.left = limit - new_width
    return True


def shrink_frame_text_to_fit(text_frame, box_width_emu) -> Optional[float]:
    """Shrink a frame's text until its widest paragraph fits the box.

    Only for frames clamp_frame_to_slide() had to pull back: clamping can leave
    a box narrower than the text the paragraph scale fitted to the old box (the
    213pt case), and a frame that cannot hold its text on the slide gives up
    font size rather than run off the edge. One scale for the whole frame — the
    rule paragraph_font_scale applies per paragraph — floored at
    FIT_SHRINK_FLOOR; whatever still does not fit wraps, because
    apply_frame_layout() has already run for this frame and turned wrap on.

    Returns the scale applied, or None when nothing was written.
    """
    try:
        width_emu = int(box_width_emu)
    except (TypeError, ValueError):
        return None
    box_pt = _usable_box_pt(text_frame, width_emu)
    if box_pt <= 0:
        return None

    fallback = _fallback_font_pt(text_frame)
    scale = 1.0
    frame_sizes = []
    for para in text_frame.paragraphs:
        text = ''.join(run.text for run in para.runs)
        if not text.strip():
            continue
        sizes = [run.font.size.pt for run in para.runs if run.font.size]
        size = max(sizes) if sizes else fallback
        frame_sizes.append(size)
        width = estimate_text_width(text, size)
        if width > box_pt:
            scale = min(scale, box_pt / width)
    if scale >= 1.0:
        return None
    # Two floors, the stricter wins: the old hard 0.5, and the legibility floor
    # expressed against this frame's own largest size.
    reference_pt = max(frame_sizes) if frame_sizes else fallback
    scale = max(scale, FIT_SHRINK_FLOOR, legibility_floor_scale(reference_pt))

    shrunk = False
    for para in text_frame.paragraphs:
        for run in para.runs:
            if run.font.size:
                run.font.size = Pt(run.font.size.pt * scale)
                shrunk = True
    if shrunk:
        # Tell the renderer the size we decided; without it PowerPoint recomputes
        # its own shrink-to-fit on open and can drop straight back below the floor.
        pin_font_scale(text_frame, scale)
    return scale if shrunk else None


def pin_font_scale(text_frame, scale: float) -> bool:
    """Write an explicit fontScale into a frame's existing normAutofit.

    Only frames already on normAutofit are touched — this never introduces
    autofit, it only stops a renderer from re-deciding a size we already
    corrected. Returns True when a value was written.
    """
    try:
        body_pr = text_frame._txBody.find(f'{{{A_NS}}}bodyPr')
        if body_pr is None:
            return False
        norm = body_pr.find(f'{{{A_NS}}}normAutofit')
        if norm is None:
            return False
        norm.set('fontScale', str(int(round(scale * 100000))))
        return True
    except Exception:
        return False


class CellBox:
    """What apply_frame_layout() needs to know about one table cell.

    The wrap gate measures against `shape.width`, and for a cell that width is
    its column's — minus the cell's own margins — never the table's: a cell in
    a 10-column table is about ten times narrower than the frame around it, and
    the table's width would keep needs_wrap from ever firing on it. The cell
    body's own insets come off inside frame_text_exceeds_box(), exactly as they
    do for an ordinary text frame.
    """

    def __init__(self, table, row: int, col: int, shape=None):
        cell = table.rows[row].cells[col]
        self.width = (int(table.columns[col].width)
                      - int(cell.margin_left or 0)
                      - int(cell.margin_right or 0))
        self.shape_id = f'{getattr(shape, "shape_id", "?")}[{row},{col}]'


def check_text_fit(
    original_text: str,
    translated_text: str,
    constraints: SpatialConstraints,
    font_size: Optional[float],
) -> tuple[bool, Optional[float], Optional[str]]:
    """
    Check if translated text fits in the original text box.
    
    Returns:
        (fits, adjusted_font_size, reason)
    """
    if not font_size:
        font_size = 12.0  # Default font size
    
    box_width_emu = constraints.width
    box_width_pt = box_width_emu / 12700  # Convert EMU to points (rough approximation)
    
    original_width = estimate_text_width(original_text, font_size)
    translated_width = estimate_text_width(translated_text, font_size)
    
    # Check if translated text exceeds box width by more than 10%
    if translated_width > box_width_pt * 1.1:
        # Try reducing font size by up to 20%
        max_reduction = 0.2
        for reduction in [0.05, 0.1, 0.15, 0.2]:
            adjusted_size = font_size * (1 - reduction)
            adjusted_width = estimate_text_width(translated_text, adjusted_size)
            if adjusted_width <= box_width_pt:
                return True, adjusted_size, "overflow"
        return False, None, "overflow"
    
    # Check if text is significantly smaller (more than 50% smaller)
    if translated_width < original_width * 0.5 and translated_width < box_width_pt * 0.3:
        # Consider increasing font size (optional)
        return True, font_size, None
    
    return True, None, None


def set_run_typefaces(run, typeface: str) -> None:
    """Apply a typeface to the latin, east-asian and complex-script slots.

    CT_TextCharacterProperties requires the order latin < ea < cs, so each
    element is inserted directly after the previous one.
    """
    run.font.name = typeface  # creates <a:latin> in the schema-correct position
    rPr = run._r.get_or_add_rPr()
    prev = rPr.find(f'{{{A_NS}}}latin')
    for tag in ('ea', 'cs'):
        el = rPr.find(f'{{{A_NS}}}{tag}')
        if el is None:
            el = rPr.makeelement(f'{{{A_NS}}}{tag}', {})
            if prev is not None:
                prev.addnext(el)
            else:
                rPr.append(el)
        el.set('typeface', typeface)
        prev = el


def set_run_text_safe(run, new_text: str, target_language: str = 'en'):
    """
    Safely set text on a run, preserving all formatting.
    Applies the configured Japanese typeface when the target is Japanese.
    """
    # Store original properties
    original_font = run.font
    
    # Set the new text
    run.text = new_text
    
    # Restore font properties (they should be preserved, but let's be safe)
    try:
        if original_font.name:
            run.font.name = original_font.name
        if original_font.size:
            run.font.size = original_font.size
        if original_font.bold is not None:
            run.font.bold = original_font.bold
        if original_font.italic is not None:
            run.font.italic = original_font.italic
        if original_font.underline is not None:
            run.font.underline = original_font.underline
        if original_font.strike is not None:
            run.font.strike = original_font.strike
        if original_font.color and original_font.color.rgb:
            run.font.color.rgb = original_font.color.rgb
    except Exception:
        pass  # Some properties might not be settable

    # Override the typeface for Japanese target text, including the East Asian
    # slot — <a:latin> alone does not control CJK glyph selection.
    if target_language == 'ja':
        try:
            set_run_typefaces(run, JP_FONT_FAMILY)
        except Exception:
            pass


def find_shape_by_index(shape, shape_idx: str) -> Optional[Shape]:
    """
    Find a shape by its index, handling nested groups.
    shape_idx can be like "0", "1_0", "1_table_0_0"
    """
    parts = str(shape_idx).split('.')
    
    # Handle table cells
    if 'table' in shape_idx:
        # This is a table cell, handled separately
        return None
    
    try:
        # Handle grouped shapes
        if isinstance(shape, GroupShape):
            first_idx = int(parts[0])
            sub_shape = list(shape.shapes)[first_idx]
            if len(parts) > 1:
                return find_shape_by_index(sub_shape, '.'.join(parts[1:]))
            return sub_shape
    except (IndexError, ValueError):
        pass
    
    return None


def resolve_shape_path(slide, index_parts):
    """Resolve a shape index path ("3", or "3.1" for a group child) to a shape.

    Returns None when a step does not resolve; the caller then decides whether to
    guess or to report the run as failed.
    """
    container = slide
    shape = None
    for part in index_parts:
        if not str(part).isdigit():
            return None
        shapes = getattr(container, 'shapes', None)
        if shapes is None:
            return None
        shapes = list(shapes)
        idx = int(part)
        if idx < 0 or idx >= len(shapes):
            return None
        shape = shapes[idx]
        container = shape
    return shape


def inject_smartart_text(
    shape: GraphicFrame,
    translated_runs: list[TranslatedRun],
    slide_idx: int,
) -> list[TranslatedRun]:
    """Inject translated text into a SmartArt diagram via its XML."""
    failed_runs = []
    try:
        # Shared resolution: one place decides what a SmartArt text node is, so
        # extraction and injection cannot disagree (see core/smartart.py).
        dgm_part, dgm_xml = find_diagram_part(shape, None)
        if dgm_part is None or dgm_xml is None:
            # Only SmartArt run ids are routed here, so an unresolvable diagram
            # is a real failure. Returning the runs unchanged would hide it.
            return list(translated_runs)
        
        # Snapshot the nodes once, through the shared enumerator (document order,
        # empties skipped) — the same list extraction numbered its runs from.
        # Snapshotting also stops the indices from shifting mid-loop.
        a_t_elements = iter_text_nodes(dgm_xml)
        placed = 0
        
        for tr in translated_runs:
            try:
                # The ordinal sits in the second-to-last slot. Parsing by
                # position from the front breaks when the shape index is a group
                # path ("3_1") and adds underscores to the id.
                run_parts = tr.run_id.split('_')
                run_idx = int(run_parts[-2]) if len(run_parts) >= 2 else 0
                
                if run_idx < 0 or run_idx >= len(a_t_elements):
                    failed_runs.append(tr)
                    continue
                
                node = a_t_elements[run_idx]
                # Integrity gate: the ordinal is only trustworthy while the node
                # still holds the text extraction saw. If it does not, the two
                # sides have diverged — refuse the write and report it, because
                # the alternative is overwriting another node's text silently.
                expected = (tr.original_text or '').strip()
                if expected and (node.text or '').strip() != expected:
                    failed_runs.append(tr)
                    continue
                
                node.text = tr.translated_text
                placed += 1
            except Exception:
                failed_runs.append(tr)
        
        # Write back modified XML
        if placed:
            dgm_part._blob = etree.tostring(dgm_xml, xml_declaration=True, encoding='UTF-8')
        
    except Exception as e:
        print(f"[INJECTOR] SmartArt injection error: {e}")
        failed_runs.extend(translated_runs)
    
    return failed_runs


def clear_run_text(run) -> None:
    """Empty a run's text while keeping the <a:r> element and its rPr intact.

    Coalescing writes a whole translation into the first run of a span; the other
    runs of that span are blanked rather than removed so every run index used by
    other lookups in the same paragraph stays valid.
    """
    for t in run._r.findall(f'{{{A_NS}}}t'):
        t.text = ''


def span_targets(paragraph_runs: list, tr: TranslatedRun) -> tuple:
    """Resolve which runs a translated unit should occupy.

    Returns (first_run, extra_runs_to_blank). Returns (None, []) when the span
    cannot be honoured, so the caller records an injection failure instead of
    blanking text it cannot account for.
    """
    first_idx = _run_index(tr)
    if first_idx >= len(paragraph_runs):
        return None, []

    first_run = paragraph_runs[first_idx]

    span = tr.merged_span
    if not span or len(span) < 2:
        return first_run, []

    last_idx = int(span[1])
    if last_idx <= first_idx or last_idx >= len(paragraph_runs):
        return None, []

    span_runs = paragraph_runs[first_idx:last_idx + 1]
    joined = ''.join(r.text for r in span_runs)
    if joined != tr.original_text:
        print(
            f"  [INJECTOR] refusing merged span {span} on {tr.run_id}: source text "
            f"does not match ({joined!r} != {tr.original_text!r})"
        )
        return None, []

    return first_run, span_runs[1:]


def replace_text_in_shape(
    shape: Shape,
    translated_runs: list[TranslatedRun],
    slide_idx: int,
    shape_idx: str,
    clamp_to_slide: bool = True,
) -> list[TranslatedRun]:
    """
    Replace text in a shape with translated text.
    
    Returns list of runs that couldn't be replaced.
    """
    failed_runs = []
    
    # Handle grouped shapes
    if isinstance(shape, GroupShape):
        for sub_idx, sub_shape in enumerate(shape.shapes):
            runs = replace_text_in_shape(
                sub_shape,
                translated_runs,
                slide_idx,
                f"{shape_idx}.{sub_idx}",
                # A grouped child's left/width are in the group's child
                # coordinate space, not slide EMUs: clamping them would not
                # put the frame on the slide, so the off-slide fix (gap 1)
                # applies to top-level frames only.
                clamp_to_slide=False,
            )
            failed_runs.extend(runs)
        return failed_runs
    
    # Handle tables
    if isinstance(shape, GraphicFrame) and shape.has_table:
        table = shape.table
        
        # Resolve one scale per cell-paragraph up front (see paragraph_font_scale).
        para_groups: dict[str, list[TranslatedRun]] = {}
        for translated_run in translated_runs:
            para_groups.setdefault(_paragraph_key(translated_run), []).append(translated_run)
        para_scales = {key: paragraph_font_scale(group) for key, group in para_groups.items()}

        # Cells that actually received text — only they get the layout fix, for
        # the same reason apply_frame_layout() is gated on the frame path: a
        # cell the injector could not write must stay as the source had it.
        written_cells: dict[tuple[int, int], list[TranslatedRun]] = {}

        for translated_run in translated_runs:
            try:
                run_parts = translated_run.run_id.split('_')
                shape_segments = run_parts[2].split('.') if len(run_parts) > 2 else []
                
                table_row = 0
                table_col = 0
                if len(shape_segments) >= 4 and 'table' in shape_segments:
                    table_row = int(shape_segments[2])
                    table_col = int(shape_segments[3])
                
                cell = table.rows[table_row].cells[table_col]
                paragraph_idx = int(run_parts[3]) if len(run_parts) > 3 else 0
                
                para = list(cell.text_frame.paragraphs)[paragraph_idx]
                para_runs = list(para.runs)
                run, extra_runs = span_targets(para_runs, translated_run)
                if run is None:
                    failed_runs.append(translated_run)
                    continue
                
                try:
                    orig_font_size = run.font.size
                except Exception:
                    orig_font_size = None
                
                para_scale = para_scales.get(_paragraph_key(translated_run), 1.0)
                
                set_run_text_safe(run, translated_run.translated_text, translated_run.target_language)
                for blank_run in extra_runs:
                    clear_run_text(blank_run)
                
                adjusted_size = resolve_font_size(translated_run, para_scale, orig_font_size)
                if adjusted_size:
                    run.font.size = Pt(adjusted_size)

                written_cells.setdefault((table_row, table_col), []).append(translated_run)

            except (IndexError, ValueError) as e:
                failed_runs.append(translated_run)

        # Same neutralisation as an ordinary frame (gap 2), measured on the
        # CELL's box — its column minus the cell margins — instead of the
        # table's: this branch returns before the frame path's
        # apply_frame_layout(), so without this a real table keeps spAutoFit
        # and wrap="none" and goes on growing over its neighbours.
        for (table_row, table_col), cell_runs in written_cells.items():
            cell = table.rows[table_row].cells[table_col]
            apply_frame_layout(CellBox(table, table_row, table_col, shape),
                               cell.text_frame, cell_runs)

        return failed_runs
    
    # Handle SmartArt diagrams
    if isinstance(shape, GraphicFrame) and 'smartart' in str(translated_runs[0].run_id if translated_runs else ''):
        return inject_smartart_text(shape, translated_runs, slide_idx)
    
    # Handle regular shapes with text frames
    if not hasattr(shape, 'text_frame') or shape.text_frame is None:
        return failed_runs
    
    text_frame = shape.text_frame
    
    # Group runs by paragraph
    runs_by_paragraph = {}
    for tr in translated_runs:
        para_parts = tr.run_id.split('_')
        para_idx = para_parts[3] if len(para_parts) > 3 else '0'
        if para_idx not in runs_by_paragraph:
            runs_by_paragraph[para_idx] = []
        runs_by_paragraph[para_idx].append(tr)
    
    # Replace text in each paragraph
    paragraphs = list(text_frame.paragraphs)
    if VERBOSE:
        print(f"  [INJECTOR] shape {shape_idx}: {len(paragraphs)} paragraphs, {len(runs_by_paragraph)} run groups")
    
    for para_idx_str, runs in runs_by_paragraph.items():
        try:
            para_idx = int(para_idx_str)
            if para_idx >= len(paragraphs):
                continue
            
            paragraph = paragraphs[para_idx]
            paragraph_runs = list(paragraph.runs)
            
            # One scale for the whole paragraph — per-run scaling made runs of the
            # same paragraph different sizes.
            para_scale = paragraph_font_scale(runs)
            if para_scale < 1.0 and VERBOSE:
                print(f"  [INJECTOR] paragraph-level scale {para_scale:.3f} on para {para_idx_str} of shape {shape_idx}")
            
            for tr in runs:
                run, extra_runs = span_targets(paragraph_runs, tr)
                
                if run is not None:
                    # Read original font size to preserve
                    orig_font_size = None
                    try:
                        if run.font.size:
                            orig_font_size = run.font.size
                    except Exception:
                        pass
                    
                    set_run_text_safe(run, tr.translated_text, tr.target_language)
                    # Coalesced unit: the rest of the span is blanked on purpose.
                    for blank_run in extra_runs:
                        clear_run_text(blank_run)
                    
                    adjusted_size = resolve_font_size(tr, para_scale, orig_font_size)
                    if adjusted_size:
                        run.font.size = Pt(adjusted_size)
                else:
                    failed_runs.append(tr)
                    
        except (IndexError, ValueError) as e:
            failed_runs.extend(runs)
    
    # Only frames that actually received text get their PDF-import layout
    # artifacts reworked — a frame the injector could not write must stay as the
    # source had it, and one that received nothing has nothing to re-fit.
    if len(translated_runs) > len(failed_runs):
        # Order matters (gap 1): clamp first, so the wrap/autofit gates below
        # measure the on-slide width; apply_frame_layout before the shrink, so a
        # frame that needed wrap keeps it — the shrink only ever makes text
        # narrower, never changes a gate the other way round.
        clamped = clamp_frame_to_slide(shape) if clamp_to_slide else False
        apply_frame_layout(shape, text_frame, translated_runs)
        if clamped:
            shrink_frame_text_to_fit(text_frame, int(shape.width))

    return failed_runs


def inject_translations(
    input_path: str,
    output_path: str,
    translated_runs: list[TranslatedRun],
    original_document,  # PPTXDocument from extractor
) -> tuple[bool, list[TranslatedRun]]:
    """
    Inject translated text into a PPTX file.
    
    Args:
        input_path: Path to original PPTX
        output_path: Path for translated PPTX
        translated_runs: List oftranslated text runs
        original_document: Original PPTXDocument with spatial constraints
        
    Returns:
        (success, failed_runs) - list of runs that couldn't be replaced
    """
    # Open the original presentation
    prs = Presentation(input_path)
    
    failed_runs = []
    
    # Group runs by slide
    runs_by_slide = {}
    for tr in translated_runs:
        slide_idx = tr.run_id.split('_')[1] if '_' in tr.run_id else '0'
        if slide_idx not in runs_by_slide:
            runs_by_slide[slide_idx] = []
        runs_by_slide[slide_idx].append(tr)
    
    # Process each slide
    for slide_idx_str, slide_runs in runs_by_slide.items():
        try:
            slide_idx = int(slide_idx_str)
            slide = prs.slides[slide_idx]
            
            # Group runs by shape
            runs_by_shape = {}
            for tr in slide_runs:
                rid_parts = tr.run_id.split('_')
                shape_idx = rid_parts[2] if len(rid_parts) > 2 else '0'
                if shape_idx not in runs_by_shape:
                    runs_by_shape[shape_idx] = []
                runs_by_shape[shape_idx].append(tr)
            
            # Process each shape
            for shape_idx_str, shape_runs in runs_by_shape.items():
                try:
                    shape_idx_parts = shape_idx_str.split('.')
                    
                    # Handle SmartArt shapes
                    is_smartart = 'smartart' in shape_idx_str
                    
                    # Find the shape
                    shape = None
                    if is_smartart:
                        # Resolve by the extractor's own shape index instead of
                        # taking the first GraphicFrame: when a slide held a table
                        # and a diagram (or two diagrams) every SmartArt run went
                        # to the wrong shape and the write landed in the wrong
                        # node. Nested diagrams carry a path ("smartart.3.1").
                        shape = resolve_shape_path(slide, shape_idx_parts[1:])
                        if shape is not None and not is_smartart_graphic_frame(shape):
                            shape = None
                        if shape is None:
                            # Guess only when the slide holds exactly one diagram;
                            # with two, guessing is how text moves between them.
                            frames = [s for s in slide.shapes if is_smartart_graphic_frame(s)]
                            shape = frames[0] if len(frames) == 1 else None
                    elif len(shape_idx_parts) == 1:
                        # Simple index
                        idx = int(shape_idx_parts[0])
                        shape = slide.shapes[idx]
                    else:
                        # Nested or special shape
                        first_idx = int(shape_idx_parts[0])
                        shape = slide.shapes[first_idx]
                        
                        if 'table' in shape_idx_str and isinstance(shape, GraphicFrame):
                            # Table cell - handled in replace_text_in_shape
                            pass
                        elif isinstance(shape, GroupShape):
                            # Nested group — use '.' separator to match find_shape_by_index
                            shape = find_shape_by_index(shape, '.'.join(shape_idx_parts[1:]))
                    
                    if shape:
                        failed = replace_text_in_shape(shape, shape_runs, slide_idx, shape_idx_str)
                        failed_runs.extend(failed)
                    elif is_smartart:
                        # Never leave a SmartArt run unaccounted for: it surfaces
                        # as an injection failure instead of a silent no-op.
                        failed_runs.extend(shape_runs)
                    else:
                        # Try to find by iterating all shapes
                        for s_idx, s in enumerate(slide.shapes):
                            if f"_{s_idx}_" in shape_idx_str or shape_idx_str == str(s_idx):
                                failed = replace_text_in_shape(s, shape_runs, slide_idx, str(s_idx))
                                failed_runs.extend(failed)
                                break
                                
                except Exception as e:
                    failed_runs.extend(shape_runs)
                    
        except Exception as e:
            failed_runs.extend(slide_runs)
    
    # Save the translated presentation
    print(f"[INJECTOR] Processed {len(translated_runs)} runs, {len(failed_runs)} failed")
    prs.save(output_path)
    
    if failed_runs:
        print(f"[INJECTOR] Failed runs:")
        for fr in failed_runs[:10]:
            print(f"  {fr.run_id}: {fr.original_text[:30]} -> {fr.translated_text[:30]}")
    
    return len(failed_runs) == 0, failed_runs
