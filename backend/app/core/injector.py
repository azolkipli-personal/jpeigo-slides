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

from app.models import TranslatedRun, TranslationJob, SpatialConstraints


# Average character widths for font size estimation
# These are approximations for common fonts
CHAR_WIDTH_RATIOS = {
    'ja': 1.0,   # Japanese characters (full-width)
    'en': 0.5,   # English characters (half-width)
}


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


def set_run_text_safe(run, new_text: str):
    """
    Safely set text on a run, preserving all formatting.
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


def find_shape_by_index(shape, shape_idx: str) -> Optional[Shape]:
    """
    Find a shape by its index, handling nested groups.
    shape_idx can be like "0", "1_0", "1_table_0_0"
    """
    parts = str(shape_idx).split('_')
    
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
                return find_shape_by_index(sub_shape, '_'.join(parts[1:]))
            return sub_shape
    except (IndexError, ValueError):
        pass
    
    return None


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
                f"{shape_idx}_{sub_idx}",
            )
            failed_runs.extend(runs)
        return failed_runs
    
    # Handle tables
    if isinstance(shape, GraphicFrame) and shape.has_table:
        table = shape.table
        for translated_run in translated_runs:
            # Parse shape_idx like "0_table_0_0" for row 0, col 0
            parts = str(translated_run.run_id).split('_')
            try:
                # Find position from run_id
                run_parts = translated_run.run_id.replace('run_', '').split('_')
                table_row = int(run_parts[3]) if len(run_parts) > 3 else 0
                table_col = int(run_parts[4]) if len(run_parts) > 4 else 0
                
                cell = table.rows[table_row].cells[table_col]
                # Find and replace the specific run
                paragraph_idx = translated_run.run_id.split('_')[-2] if '_' in translated_run.run_id else 0
                try:
                    para = list(cell.text_frame.paragraphs)[int(paragraph_idx)]
                    run_offset = int(run_parts[-1]) if len(run_parts) > 5 else 0
                    run = list(para.runs)[run_offset]
                    set_run_text_safe(run, translated_run.translated_text)
                    if translated_run.adjusted_font_size:
                        run.font.size = Pt(translated_run.adjusted_font_size)
                except (IndexError, ValueError):
                    failed_runs.append(translated_run)
            except (IndexError, ValueError):
                failed_runs.append(translated_run)
        return failed_runs
    
    # Handle regular shapes with text frames
    if not hasattr(shape, 'text_frame') or shape.text_frame is None:
        return failed_runs
    
    text_frame = shape.text_frame
    
    # Group runs by paragraph
    runs_by_paragraph = {}
    for tr in translated_runs:
        para_idx = tr.run_id.split('_')[-2] if '_' in tr.run_id else '0'
        if para_idx not in runs_by_paragraph:
            runs_by_paragraph[para_idx] = []
        runs_by_paragraph[para_idx].append(tr)
    
    # Replace text in each paragraph
    paragraphs = list(text_frame.paragraphs)
    
    for para_idx_str, runs in runs_by_paragraph.items():
        try:
            para_idx = int(para_idx_str)
            if para_idx >= len(paragraphs):
                continue
            
            paragraph = paragraphs[para_idx]
            paragraph_runs = list(paragraph.runs)
            
            for tr in runs:
                run_parts = tr.run_id.split('_')
                run_idx = int(run_parts[-1]) if len(run_parts) >= 4 else 0
                
                if run_idx < len(paragraph_runs):
                    run = paragraph_runs[run_idx]
                    set_run_text_safe(run, tr.translated_text)
                    
                    # Apply font size adjustment if needed
                    if tr.adjusted_font_size:
                        run.font.size = Pt(tr.adjusted_font_size)
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
                shape_idx = '_'.join(tr.run_id.split('_')[2:4]) if '_' in tr.run_id else '0'
                if shape_idx not in runs_by_shape:
                    runs_by_shape[shape_idx] = []
                runs_by_shape[shape_idx].append(tr)
            
            # Process each shape
            for shape_idx_str, shape_runs in runs_by_shape.items():
                try:
                    shape_idx_parts = shape_idx_str.split('_')
                    
                    # Find the shape
                    shape = None
                    if len(shape_idx_parts) == 1:
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
                            # Nested group
                            shape = find_shape_by_index(shape, '_'.join(shape_idx_parts[1:]))
                    
                    if shape:
                        failed = replace_text_in_shape(shape, shape_runs, slide_idx, shape_idx_str)
                        failed_runs.extend(failed)
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
    prs.save(output_path)
    
    return len(failed_runs) == 0, failed_runs