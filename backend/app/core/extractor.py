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
from pptx.oxml.ns import qn
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
from app.core.smartart import find_diagram_part, iter_text_nodes, node_path


# XML namespaces for PPTX
PPTX_NAMESPACES = {
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'dgm': 'http://schemas.openxmlformats.org/drawingml/2006/diagram',
}

SMARTART_REL_TYPE = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/diagramData'


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


_run_counter: int = 0
_box_counter: int = 0


def generate_run_id(slide_idx: int, shape_idx: int | str, para_idx: int, run_idx: int) -> str:
    """Generate a unique ID for a text run."""
    global _run_counter
    # Use '.' to join compound shape paths so the run_id remains parseable
    shape_str = str(shape_idx).replace('_', '.')
    run_id = f"run_{slide_idx}_{shape_str}_{para_idx}_{run_idx}_{_run_counter}"
    _run_counter += 1
    return run_id


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


# Run attributes that do not affect how text renders. PowerPoint writes them
# unevenly across the runs of one sentence ('Workshop ' carries no lang while 'R'
# carries lang="en-US"), and comparing them verbatim blocked every merge.
# dirty/smtClean/err are editing hygiene; lang/altLang stop mattering once the
# injector sets the latin/ea typefaces for the target language.
IGNORED_RUN_ATTRS = frozenset({'dirty', 'smtClean', 'err', 'lang', 'altLang'})


def _rpr_signature(run) -> str:
    """Fingerprint a run's <a:rPr>, ignoring edit hygiene.

    An absent rPr is a real state (the run inherits everything), so it gets its
    own sentinel instead of comparing equal to an empty element.
    """
    try:
        rPr = run._r.find(qn('a:rPr'))
    except Exception:
        return '<unreadable>'
    if rPr is None:
        return '<inherited>'

    attrs = ' '.join(
        f'{key}={value}'
        for key, value in sorted(rPr.attrib.items())
        if key not in IGNORED_RUN_ATTRS
    )
    children = ''.join(
        etree.tostring(child, with_tail=False).decode('utf-8', 'replace')
        for child in rPr
    )
    return f'<{attrs}>{children}'


def _xml_adjacent(left, right) -> bool:
    """True when nothing sits between two runs in the paragraph XML.

    <a:br> and <a:fld> are not exposed as runs by python-pptx, so runs on either
    side of a line break look consecutive in `paragraph.runs`. Merging them would
    collapse the break, so adjacency is checked on the XML child list.
    """
    try:
        kids = list(left._r.getparent())
        return kids.index(right._r) - kids.index(left._r) == 1
    except (AttributeError, ValueError):
        return False


def _padding_between(left, right) -> bool:
    """True when merging these runs would collapse deliberate spacing.

    Table cells pad columns with runs of spaces, so spacing there is layout and
    not prose. A model handed one whole string may normalise whitespace inside it,
    which would move the columns; keeping those runs apart leaves them as-is.
    """
    if '  ' in left.text or '  ' in right.text:
        return True
    return left.text.endswith((' ', '\t')) and right.text.startswith((' ', '\t'))


def _coalesce_groups(para_runs):
    """Group runs with identical formatting so a sentence is translated whole.

    PowerPoint and copy/paste split one sentence into several <a:r> runs the
    author never saw ('W' + 'orking'), and every run used to be its own model job,
    so 'W' came back untranslated. Runs that are XML-adjacent, hold non-whitespace
    text and share a formatting fingerprint merge into one unit; the merge cannot
    change the look because the formatting was already the same. Whitespace-only
    runs are never merged, so padding stays where the author put it.
    """
    groups = []
    first = None
    sig = None
    for idx, run in enumerate(para_runs):
        if not run.text.strip():
            if first is not None:
                groups.append((first, idx - 1))
                first = None
                sig = None
            continue
        cur = _rpr_signature(run)
        if (first is not None and cur == sig
                and _xml_adjacent(para_runs[idx - 1], run)
                and not _padding_between(para_runs[idx - 1], run)):
            continue
        if first is not None:
            groups.append((first, idx - 1))
        first = idx
        sig = cur
    if first is not None:
        groups.append((first, len(para_runs) - 1))
    return groups


def extract_runs_from_text_frame(
    text_frame: TextFrame,
    slide_idx: int,
    shape_idx: int | str,
    shape_type: str,
    run_id_shape_idx: int | str | None = None,
) -> list[TextRun]:
    """Extract all text runs from a text frame.
    
    Args:
        text_frame: The text frame to extract from
        slide_idx: Slide index
        shape_idx: Shape index stored in the model (must be int-compatible)
        shape_type: Type of shape
        run_id_shape_idx: If different from shape_idx (e.g., table cell path),
                          used for run_id generation only. Defaults to shape_idx.
    """
    runs = []
    effective_run_id_idx = run_id_shape_idx if run_id_shape_idx is not None else shape_idx
    
    for para_idx, paragraph in enumerate(text_frame.paragraphs):
        para_runs = list(paragraph.runs)
        for first_idx, last_idx in _coalesce_groups(para_runs):
            run = para_runs[first_idx]
            # One translation unit per run group: the concatenated text goes to
            # the model as a whole sentence instead of word fragments.
            text = "".join(r.text for r in para_runs[first_idx:last_idx + 1])

            style = extract_style_from_run(run)
            xml_path = get_xml_path(run)
            run_id = generate_run_id(slide_idx, effective_run_id_idx, para_idx, first_idx)

            text_run = TextRun(
                run_id=run_id,
                text=text,
                style=style,
                slide_index=slide_idx,
                shape_index=shape_idx,
                paragraph_index=para_idx,
                run_index=first_idx,
                xml_path=xml_path,
                merged_span=[first_idx, last_idx] if last_idx > first_idx else None,
            )
            runs.append(text_run)
    
    return runs


# SmartArt text extraction
SMARTART_DGM_URI = 'http://schemas.openxmlformats.org/drawingml/2006/diagram'


def extract_smartart_text(
    shape: GraphicFrame,
    slide_part,
    slide_idx: int,
    shape_idx: int | str,
) -> list[TextRun]:
    """Extract text from a SmartArt diagram shape."""
    runs = []
    try:
        # Resolution lives in core/smartart.py: extraction and injection must
        # agree on which node is which, so neither side owns that decision.
        dgm_part, dgm_xml = find_diagram_part(shape, slide_part)
        if dgm_part is None or dgm_xml is None:
            return runs
        
        # Node order and the empty-node rule come from the shared enumerator, so
        # extraction and injection cannot disagree. Ordinals are 0-based and are
        # exactly the injector's index into the same list.
        for ordinal, t_elem in enumerate(iter_text_nodes(dgm_xml)):
            runs.append(TextRun(
                run_id=generate_run_id(slide_idx, f"smartart_{shape_idx}", 0, ordinal),
                text=(t_elem.text or '').strip(),
                style=FontStyle(),
                slide_index=slide_idx,
                shape_index=shape_idx,
                paragraph_index=0,
                run_index=ordinal,
                xml_path=node_path(t_elem),  # diagnostics only, never used to resolve
            ))
    except Exception as e:
        print(f"[EXTRACTOR] SmartArt extraction error: {e}")
    
    return runs


def extract_from_shape(
    shape: Shape,
    slide_idx: int,
    shape_idx: int | str,
    slide_part=None,  # pptx.opc.package.Part for accessing relationships
) -> list[TextBox]:
    """Extract text boxes from a shape (recursive for groups)."""
    text_boxes = []

    # Handle group shapes recursively
    if isinstance(shape, GroupShape):
        for sub_idx, sub_shape in enumerate(shape.shapes):
            nested_shape_path = f"{shape_idx}_{sub_idx}"
            text_boxes.extend(extract_from_shape(sub_shape, slide_idx, nested_shape_path, slide_part))
        return text_boxes

    # Handle graphic frames (charts, diagrams, tables)
    if isinstance(shape, GraphicFrame):
        # Check for tables first
        if shape.has_table:
            table: Table = shape.table
            for row_idx, row in enumerate(table.rows):
                for col_idx, cell in enumerate(row.cells):
                    if cell.text_frame:
                        # Use compound ID so run_id encodes row/col position
                        table_id = f"{shape_idx}_table_{row_idx}_{col_idx}"
                        runs = extract_runs_from_text_frame(
                            cell.text_frame,
                            slide_idx,
                            shape_idx,  # int for the model
                            "table_cell",
                            run_id_shape_idx=table_id,  # compound ID for run_id only
                        )
                        if runs:
                            constraints = get_spatial_constraints(shape)
                            tb_shape_idx = int(shape_idx) if isinstance(shape_idx, (int, str)) and str(shape_idx).isdigit() else 0
                            text_boxes.append(TextBox(
                                box_id=f"box_{slide_idx}_{table_id}",
                                shape_type="table_cell",
                                slide_index=slide_idx,
                                shape_index=tb_shape_idx,  # int for model
                                runs=runs,
                                constraints=constraints,
                            ))
        # SmartArt diagrams
        if slide_part is not None:
            smartart_texts = extract_smartart_text(shape, slide_part, slide_idx, shape_idx)
            if smartart_texts:
                text_boxes.append(TextBox(
                    box_id=f"box_{slide_idx}_smartart_{shape_idx}",
                    shape_type="smartart",
                    slide_index=slide_idx,
                    shape_index=shape_idx,
                    runs=smartart_texts,
                    constraints=get_spatial_constraints(shape),
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
        global _box_counter
        tb = TextBox(
            box_id=f"box_{slide_idx}_{_box_counter}",
            shape_type="shape",
            slide_index=slide_idx,
            shape_index=shape_idx,
            runs=runs,
            constraints=constraints,
        )
        _box_counter += 1
        text_boxes.append(tb)
    
    return text_boxes


def extract_slide(pptx: Presentation, slide_idx: int) -> Slide:
    """Extract all text from a single slide."""
    slide = pptx.slides[slide_idx]
    slide_id = slide.slide_id
    slide_part = slide.part  # For accessing relationships (SmartArt, etc.)
    
    text_boxes = []
    
    for shape_idx, shape in enumerate(slide.shapes):
        text_boxes.extend(extract_from_shape(shape, slide_idx, shape_idx, slide_part))
    
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