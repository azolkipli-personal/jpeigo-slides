"""
Core PPTX extraction logic.
Extracts text runs while preserving XML styling attributes.
"""
from pptx import Presentation
from pptx.shapes.base import BaseShape as Shape
from pptx.shapes.group import GroupShape
from pptx.shapes.graphfrm import GraphicFrame
from pptx.table import Table
from pptx.text.text import TextFrame
from pptx.util import Pt
from lxml import etree
from typing import Optional
import uuid

from app.models import (
    FontStyle,
    SpatialConstraints,
    TextRun,
    TextBox,
    Slide,
    PPTXDocument,
)


# XML namespaces for PPTX
PPTX_NAMESPACES = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
}


def get_shape_id(shape: Shape) -> int:
    """Get the unique ID of a shape."""
    return shape.shape_id


def extract_font_size(run) -> Optional[float]:
    """Extract font size from run XML, handling None case."""
    try:
        if run.font.size:
            return run.font.size.pt
        # Try to get from XML directly
        rPr = run._r.get_or_add_rPr()
        sz = rPr.get('{http://schemas.openxmlformats.org/drawingml/2006/main}sz')
        if sz:
            return int(sz) / 100  # XML stores in hundredths of a point
    except Exception:
        pass
    return None


def extract_font_color(run) -> Optional[str]:
    """Extract font color as hex string."""
    try:
        if run.font.color.rgb:
            return f"#{run.font.color.rgb}"
        # Check for theme color
        if run.font.color.theme_color:
            return f"theme:{run.font.color.theme_color}"
    except Exception:
        # Try XML extraction
        try:
            rPr = run._r.get_or_add_rPr()
            solidFill = rPr.find('.//a:solidFill', PPTX_NAMESPACES)
            if solidFill is not None:
                srgbClr = solidFill.find('a:srgbClr', PPTX_NAMESPACES)
                if srgbClr is not None:
                    return f"#{srgbClr.get('val')}"
        except Exception:
            pass
    return None


def extract_font_name(run) -> Optional[str]:
    """Extract font name/typeface."""
    try:
        if run.font.name:
            return run.font.name
        # Try XML extraction
        rPr = run._r.get_or_add_rPr()
        latin = rPr.find('a:latin', PPTX_NAMESPACES)
        if latin is not None:
            return latin.get('typeface')
    except Exception:
        pass
    return None


def extract_style_from_run(run) -> FontStyle:
    """Extract all styling attributes from a text run."""
    style = FontStyle(
        font_size=extract_font_size(run),
        font_color=extract_font_color(run),
        font_name=extract_font_name(run),
        bold=run.font.bold if run.font.bold else False,
        italic=run.font.italic if run.font.italic else False,
        underline=bool(run.font.underline) if run.font.underline else False,
        strike_through=False,  # Not available in python-pptx
    )
    
    # Check for vertical text (tategaki)
    try:
        rPr = run._r.get_or_add_rPr()
        # Vertical text is indicated by the 'vert' attribute
        if rPr.get('{http://schemas.openxmlformats.org/drawingml/2006/main}vert') == 'vert':
            style.vertical = True
    except Exception:
        pass
    
    return style


def get_spatial_constraints(shape: Shape) -> SpatialConstraints:
    """Get spatial constraints for a shape."""
    try:
        left = int(shape.left)
        top = int(shape.top)
        width = int(shape.width)
        height = int(shape.height)
        
        # Try to get anchor/alignment
        anchor_x = "left"
        anchor_y = "top"
        
        if hasattr(shape, 'text_frame') and shape.text_frame:
            paragraphs = list(shape.text_frame.paragraphs)
            if paragraphs:
                first_para = paragraphs[0]
                if first_para.alignment:
                    align_map = {
                        'LEFT': 'left',
                        'CENTER': 'center',
                        'RIGHT': 'right',
                    }
                    anchor_x = align_map.get(str(first_para.alignment), 'left')
        
        if hasattr(shape, 'vertical_anchor'):
            vert_map = {
                'TOP': 'top',
                'MIDDLE': 'middle',
                'BOTTOM': 'bottom',
            }
            anchor_y = vert_map.get(str(shape.vertical_anchor), 'top')
        
        return SpatialConstraints(
            left=left,
            top=top,
            width=width,
            height=height,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
        )
    except Exception:
        # Return defaults
        return SpatialConstraints(left=0, top=0, width=0, height=0)


def generate_run_id(slide_idx: int, shape_idx: int, para_idx: int, run_idx: int) -> str:
    """Generate a unique ID for a text run."""
    return f"run_{slide_idx}_{shape_idx}_{para_idx}_{run_idx}"


def get_xml_path(run) -> str:
    """Get the XML path for a run for later re-injection."""
    try:
        # Build a path like: /p:sld/p:sp/p:txBody/a:p/a:r
        parts = []
        element = run._r
        while element is not None:
            tag = element.tag
            # Extract local name
            if '}' in tag:
                tag = tag.split('}')[1]
            parts.append(tag)
            element = element.getparent()
        return '/'.join(reversed(parts))
    except Exception:
        return ""


def extract_runs_from_text_frame(
    text_frame: TextFrame,
    slide_idx: int,
    shape_idx: int,
    shape_type: str,
) -> list[TextRun]:
    """Extract all text runs from a text frame."""
    runs = []
    
    for para_idx, paragraph in enumerate(text_frame.paragraphs):
        for run_idx, run in enumerate(paragraph.runs):
            # Skip empty runs
            if not run.text.strip():
                continue
            
            style = extract_style_from_run(run)
            xml_path = get_xml_path(run)
            run_id = generate_run_id(slide_idx, shape_idx, para_idx, run_idx)
            
            text_run = TextRun(
                run_id=run_id,
                text=run.text,
                style=style,
                slide_index=slide_idx,
                shape_index=shape_idx,
                paragraph_index=para_idx,
                run_index=run_idx,
                xml_path=xml_path,
            )
            runs.append(text_run)
    
    return runs


def extract_from_shape(
    shape: Shape,
    slide_idx: int,
    shape_idx: int,
) -> list[TextBox]:
    """Extract text boxes from a shape (recursive for groups)."""
    text_boxes = []
    
    # Handle group shapes recursively
    if isinstance(shape, GroupShape):
        for sub_idx, sub_shape in enumerate(shape.shapes):
            text_boxes.extend(extract_from_shape(sub_shape, slide_idx, f"{shape_idx}_{sub_idx}"))
        return text_boxes
    
    # Handle graphic frames (charts, diagrams, tables)
    if isinstance(shape, GraphicFrame):
        if shape.has_table:
            table: Table = shape.table
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    if cell.text_frame:
                        runs = extract_runs_from_text_frame(
                            cell.text_frame,
                            slide_idx,
                            f"{shape_idx}_table_{row_idx}_{col_idx}",
                            "table_cell",
                        )
                        if runs:
                            constraints = get_spatial_constraints(shape)
                            text_boxes.append(TextBox(
                                box_id=f"box_{slide_idx}_{shape_idx}_table_{row_idx}_{col_idx}",
                                shape_type="table_cell",
                                slide_index=slide_idx,
                                shape_index=shape_idx,
                                runs=runs,
                                constraints=constraints,
                            ))
        return text_boxes
    
    # Regular shapes with text frames
    if not hasattr(shape, 'text_frame'):
        return text_boxes
    
    if shape.text_frame is None:
        return text_boxes
    
    runs = extract_runs_from_text_frame(
        shape.text_frame,
        slide_idx,
        shape_idx,
        "shape",
    )
    
    if runs:
        constraints = get_spatial_constraints(shape)
        text_boxes.append(TextBox(
            box_id=f"box_{slide_idx}_{shape_idx}",
            shape_type="shape",
            slide_index=slide_idx,
            shape_index=shape_idx,
            runs=runs,
            constraints=constraints,
        ))
    
    return text_boxes


def extract_slide(pptx: Presentation, slide_idx: int) -> Slide:
    """Extract all text from a single slide."""
    slide = pptx.slides[slide_idx]
    slide_id = slide.slide_id
    
    text_boxes = []
    
    for shape_idx, shape in enumerate(slide.shapes):
        text_boxes.extend(extract_from_shape(shape, slide_idx, shape_idx))
    
    # Calculate total runs
    total_runs = sum(len(tb.runs) for tb in text_boxes)
    
    return Slide(
        slide_index=slide_idx,
        slide_id=slide_id,
        text_boxes=text_boxes,
        preview_base64=None,  # Will be generated if requested
    )


def extract_pptx(file_path: str, generate_preview: bool = False) -> PPTXDocument:
    """
    Extract all text runs from a PPTX file.
    
    Args:
        file_path: Path to the PPTX file
        generate_preview: Whether to generate base64 preview images
        
    Returns:
        PPTXDocument with all extracted text runs
    """
    pptx = Presentation(file_path)
    
    slides = []
    total_runs = 0
    
    for slide_idx in range(len(pptx.slides)):
        slide = extract_slide(pptx, slide_idx)
        slides.append(slide)
        total_runs += sum(len(tb.runs) for tb in slide.text_boxes)
    
    filename = file_path.split('/')[-1] if '/' in file_path else file_path.split('\\')[-1]
    
    return PPTXDocument(
        filename=filename,
        slides=slides,
        total_runs=total_runs,
        extraction_metadata={
            "total_slides": len(slides),
            "total_text_boxes": sum(len(s.text_boxes) for s in slides),
            "extraction_method": "python-pptx",
        },
    )