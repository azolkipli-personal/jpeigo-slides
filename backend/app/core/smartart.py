"""One source of truth for SmartArt (diagram) text nodes.

Extraction and injection must agree, element for element, on which `<a:t>` node
carries which run. They used to each rebuild that list with their own copy of the
same expression, and the two copies drifted: extraction skipped empty nodes while
injection did not, so on a real client deck every node past the first empty
placeholder received *another node's* translation — silently, because a wrong
write is not a failure.

`iter_text_nodes()` is therefore the only place that decides node order and the
empty-node rule. Both sides call it, so they cannot diverge by construction.
"""
from lxml import etree

A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
DGM_NS = 'http://schemas.openxmlformats.org/drawingml/2006/diagram'
R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

SMARTART_DGM_URI = DGM_NS

_GRAPHIC_DATA = f'.//{{{A_NS}}}graphicData'
_REL_IDS = f'.//{{{DGM_NS}}}relIds'
_R_DM = f'{{{R_NS}}}dm'
_R_ID = f'{{{R_NS}}}id'
_A_T = f'{{{A_NS}}}t'


def _graphic_data(shape):
    try:
        return shape._element.find(_GRAPHIC_DATA)
    except AttributeError:
        return None


def is_smartart_graphic_frame(shape) -> bool:
    """True when the GraphicFrame holds a SmartArt diagram (not a chart/table)."""
    graphic_data = _graphic_data(shape)
    if graphic_data is None:
        return False
    return SMARTART_DGM_URI in (graphic_data.get('uri') or '')


def _relationship_id(graphic_data) -> str | None:
    rel_ids_el = graphic_data.find(_REL_IDS)
    if rel_ids_el is not None:
        rel_id = rel_ids_el.get(_R_DM)
        if rel_id:
            return rel_id
    for child in graphic_data:
        rel_id = child.get(_R_ID)
        if rel_id:
            return rel_id
    return None


def find_diagram_part(shape, slide_part=None):
    """Resolve a SmartArt frame to its diagram-data part.

    Returns `(dgm_part, dgm_root)` — the part (so the caller can write it back)
    and the parsed `<dgm:dataModel>` root. `(None, None)` when the shape is not a
    resolvable SmartArt diagram.
    """
    graphic_data = _graphic_data(shape)
    if graphic_data is None or SMARTART_DGM_URI not in (graphic_data.get('uri') or ''):
        return None, None
    rel_id = _relationship_id(graphic_data)
    if not rel_id:
        return None, None
    part = slide_part if slide_part is not None else getattr(shape, 'part', None)
    if part is None:
        return None, None
    try:
        dgm_part = part.related_part(rel_id)
        return dgm_part, etree.fromstring(dgm_part.blob)
    except (KeyError, AttributeError, ValueError):
        return None, None


def iter_text_nodes(dgm_root):
    """Non-empty `<a:t>` elements in document order — the canonical node list.

    Order is document order, and empty nodes are skipped, because SmartArt
    layouts carry empty placeholder points that would otherwise shift every
    index after them.
    """
    return [t for t in dgm_root.iter(_A_T) if (t.text or '').strip()]


def node_path(node) -> str:
    """Tag path of a node, e.g. `dataModel/ptLst/pt/t/a:p/a:r/a:t`.

    Diagnostics only — the injector addresses nodes by their ordinal in
    `iter_text_nodes()`, never by path.
    """
    parts = []
    elem = node
    while elem is not None:
        tag = elem.tag
        if isinstance(tag, str) and '}' in tag:
            tag = tag.split('}')[1]
        parts.append(tag)
        elem = elem.getparent()
    return '/'.join(reversed(parts))
