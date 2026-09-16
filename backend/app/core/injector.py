"""
Core PPTX re-injection logic.
Re-inserts translated text while preserving original styling.
"""
from pptx import Presentation
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
    """One font scale for a whole paragraph.

    Scaling each run from its own fragment gives runs in the same paragraph
    different sizes, because every fragment has its own original:translated width
    ratio. The scale has to come from the paragraph's combined text.
    """
    if not any(tr.target_language == 'ja' for tr in group):
        return 1.0
    ordered = sorted(group, key=_run_index)
    original = ''.join(tr.original_text for tr in ordered)
    translated = ''.join(tr.translated_text for tr in ordered)
    return calculate_font_scale(original, translated)


def resolve_font_size(tr: TranslatedRun, para_scale: float, orig_font_size) -> Optional[float]:
    """Smallest of the fit-derived size and the paragraph-scaled size.

    Taking the minimum stops the paragraph scale from overwriting
    adjusted_font_size (the geometry-fit result), which used to be discarded.
    """
    candidates = []
    if tr.adjusted_font_size:
        candidates.append(tr.adjusted_font_size)
    if para_scale < 1.0 and orig_font_size:
        candidates.append(orig_font_size.pt * para_scale)
    return min(candidates) if candidates else None


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
                        
            except (IndexError, ValueError) as e:
                failed_runs.append(translated_run)
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
