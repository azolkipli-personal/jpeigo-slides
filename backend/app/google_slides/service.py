"""
Google Slides API Service
==========================
Read text runs from a Google Slides presentation, translate them,
and write the translated text to a new presentation copy.

Approach:
  1. presentations.get() → extract ALL text runs with position + styling
  2. presentations.create() to make a copy (preserves original formatting)
  3. For each text element: deleteText + insertText with translated content
  4. Returns the URL of the new translated presentation
"""
import logging
import re
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.google_slides.oauth import get_credentials

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
#  Data models for extracted slide text
# ──────────────────────────────────────────────────────────────────────

class SlideTextRun:
    """A single text run extracted from Google Slides."""
    def __init__(self, presentation_id: str, slide_object_id: str,
                 page_element_id: str, text_element_index: int,
                 start_index: int, end_index: int,
                 text: str, style: dict):
        self.presentation_id = presentation_id
        self.slide_object_id = slide_object_id
        self.page_element_id = page_element_id
        self.text_element_index = text_element_index
        self.start_index = start_index
        self.end_index = end_index
        self.text = text
        self.style = style  # font size, bold, italic, color, etc.
    
    def __repr__(self):
        return f"SlideTextRun({self.text[:30]!r}, slide={self.slide_object_id})"


class SlideTextBox:
    """A text-containing shape on a slide with all its runs."""
    def __init__(self, presentation_id: str, slide_object_id: str,
                 page_element_id: str, shape_type: str,
                 runs: list[SlideTextRun]):
        self.presentation_id = presentation_id
        self.slide_object_id = slide_object_id
        self.page_element_id = page_element_id
        self.shape_type = shape_type
        self.runs = runs
    
    @property
    def full_text(self) -> str:
        return "".join(r.text for r in self.runs)


class SlideData:
    """A single slide with all its text boxes."""
    def __init__(self, presentation_id: str, slide_index: int,
                 slide_object_id: str, text_boxes: list[SlideTextBox]):
        self.presentation_id = presentation_id
        self.slide_index = slide_index
        self.slide_object_id = slide_object_id
        self.text_boxes = text_boxes


class PresentationData:
    """Full presentation structure with extracted text."""
    def __init__(self, presentation_id: str, title: str,
                 slides: list[SlideData]):
        self.presentation_id = presentation_id
        self.title = title
        self.slides = slides


# ──────────────────────────────────────────────────────────────────────
#  Helper: Build the Slides service
# ──────────────────────────────────────────────────────────────────────

def _get_slides_service():
    """Get authenticated Google Slides API service."""
    creds = get_credentials()
    if not creds:
        raise PermissionError("Not authenticated with Google. Connect first.")
    return build("slides", "v1", credentials=creds)


def _get_drive_service():
    """Get authenticated Google Drive API service."""
    creds = get_credentials()
    if not creds:
        raise PermissionError("Not authenticated with Google. Connect first.")
    return build("drive", "v3", credentials=creds)


# ──────────────────────────────────────────────────────────────────────
#  Read presentation text
# ──────────────────────────────────────────────────────────────────────

def list_presentations(max_results: int = 20) -> list[dict]:
    """
    List Google Slides presentations from Drive.
    Returns: [{"id": "...", "name": "...", "modifiedTime": "..."}, ...]
    """
    drive = _get_drive_service()
    try:
        results = drive.files().list(
            q="mimeType='application/vnd.google-apps.presentation' and trashed=false",
            pageSize=max_results,
            fields="files(id, name, modifiedTime, owners)",
            orderBy="modifiedTime desc",
        ).execute()
        return results.get("files", [])
    except HttpError as e:
        logger.error(f"Failed to list presentations: {e}")
        raise


def extract_slide_text(presentation_id: str) -> PresentationData:
    """
    Fetch a Google Slides presentation and extract all text runs
    with their position and formatting metadata.
    
    Returns a PresentationData object ready for translation.
    """
    service = _get_slides_service()
    
    # Get presentation metadata + content
    pres = service.presentations().get(presentationId=presentation_id).execute()
    
    pres_title = pres.get("title", "Untitled")
    slides_data = []
    
    for slide_index, slide in enumerate(pres.get("slides", [])):
        slide_object_id = slide.get("objectId", f"slide_{slide_index}")
        text_boxes = []
        
        page_elements = slide.get("pageElements", [])
        for elem in page_elements:
            shape = elem.get("shape")
            if not shape:
                continue
            
            text_content = shape.get("text")
            if not text_content:
                continue
            
            text_elements = text_content.get("textElements", [])
            runs = []
            
            for te_index, te in enumerate(text_elements):
                text_run = te.get("textRun")
                if not text_run:
                    continue
                
                text = text_run.get("content", "")
                style = text_run.get("style", {})
                
                run = SlideTextRun(
                    presentation_id=presentation_id,
                    slide_object_id=slide_object_id,
                    page_element_id=elem.get("objectId", ""),
                    text_element_index=te_index,
                    start_index=te.get("startIndex", 0),
                    end_index=te.get("endIndex", 0),
                    text=text,
                    style=style,
                )
                runs.append(run)
            
            if runs:
                text_box = SlideTextBox(
                    presentation_id=presentation_id,
                    slide_object_id=slide_object_id,
                    page_element_id=elem.get("objectId", ""),
                    shape_type=shape.get("shapeType", "unknown"),
                    runs=runs,
                )
                text_boxes.append(text_box)
        
        slide_data = SlideData(
            presentation_id=presentation_id,
            slide_index=slide_index,
            slide_object_id=slide_object_id,
            text_boxes=text_boxes,
        )
        slides_data.append(slide_data)
    
    return PresentationData(
        presentation_id=presentation_id,
        title=pres_title,
        slides=slides_data,
    )


# ──────────────────────────────────────────────────────────────────────
#  Write translated text to a new Google Slides presentation
# ──────────────────────────────────────────────────────────────────────

def create_translated_presentation(
    source_presentation_id: str,
    translated_runs: list[dict],
    new_title: str = None,
) -> dict:
    """
    Create a translated copy of a Google Slides presentation.
    
    Approach:
      1. Copy the original presentation (preserves ALL formatting)
      2. For each (slide_id, page_element_id, start_index, end_index, translated_text):
         delete original text + insert translated text
      3. Returns the new presentation metadata
    
    Args:
        source_presentation_id: The original presentation's ID
        translated_runs: List of {
            "slide_object_id": str,
            "page_element_id": str,
            "start_index": int,
            "end_index": int,
            "original_text": str,
            "translated_text": str,
        }
        new_title: Optional new title (defaults to "Translated - {original}")
    
    Returns:
        {"id": "...", "title": "...", "url": "..."}
    """
    drive = _get_drive_service()
    slides = _get_slides_service()
    
    # Get source presentation for metadata
    source = slides.presentations().get(
        presentationId=source_presentation_id
    ).execute()
    original_title = source.get("title", "Untitled")
    display_title = new_title or f"Translated - {original_title}"
    
    # 1. Copy the original presentation (preserves formatting)
    copied_file = drive.files().copy(
        fileId=source_presentation_id,
        body={"name": display_title},
    ).execute()
    new_presentation_id = copied_file.get("id")
    
    # 2. Prepare batchUpdate requests
    requests = []
    for tr in translated_runs:
        translated = tr.get("translated_text", tr.get("original_text", ""))
        original = tr.get("original_text", "")
        
        # Skip if translation is identical or empty
        if not original or translated == original:
            continue
        
        slide_id = tr.get("slide_object_id")
        elem_id = tr.get("page_element_id")
        start = tr.get("start_index", 0)
        end = tr.get("end_index", 0)
        
        if not slide_id or not elem_id:
            continue
        
        # Step A: Delete original text
        requests.append({
            "deleteText": {
                "objectId": elem_id,
                "cellLocation": None,  # Not a table cell
                "textRange": {
                    "type": "FIXED_RANGE",
                    "startIndex": start,
                    "endIndex": end,
                },
            }
        })
        
        # Step B: Insert translated text at the same position
        requests.append({
            "insertText": {
                "objectId": elem_id,
                "cellLocation": None,
                "text": translated,
                "insertionIndex": start,
            }
        })
    
    # 3. Execute batch update
    if requests:
        # Batch in chunks of 50 (API limit)
        for i in range(0, len(requests), 50):
            chunk = requests[i:i + 50]
            slides.presentations().batchUpdate(
                presentationId=new_presentation_id,
                body={"requests": chunk},
            ).execute()
    
    # 4. Return metadata
    new_pres = slides.presentations().get(
        presentationId=new_presentation_id
    ).execute()
    
    return {
        "id": new_presentation_id,
        "title": new_pres.get("title", display_title),
        "url": f"https://docs.google.com/presentation/d/{new_presentation_id}/edit",
    }


# ──────────────────────────────────────────────────────────────────────
#  Utility: extract all text runs as a flat list for translation
# ──────────────────────────────────────────────────────────────────────

def flatten_runs_for_translation(presentation_data: PresentationData) -> list[dict]:
    """
    Convert the PresentationData into a flat list of text runs
    that the existing translation service can handle.
    
    Returns runs in the same format as the PPTX extractor:
    {
        "run_id": str,
        "text": str,
        "style": { font_size, bold, italic, ... },
        "slide_index": int,
        # Google Slides-specific metadata for writing back
        "_slides_meta": {
            "presentation_id": str,
            "slide_object_id": str,
            "page_element_id": str,
            "start_index": int,
            "end_index": int,
        }
    }
    """
    runs = []
    run_counter = 0
    
    for slide in presentation_data.slides:
        for text_box in slide.text_boxes:
            for run in text_box.runs:
                text = run.text.strip()
                if not text:
                    continue
                
                # Map Google Slides style to our FontStyle-like format
                style = run.style
                font_size = None
                if "fontSize" in style:
                    sz = style["fontSize"]
                    if "magnitude" in sz:
                        font_size = sz["magnitude"]
                
                run_counter += 1
                runs.append({
                    "run_id": f"gs_{run_counter}",
                    "text": run.text,
                    "style": {
                        "font_size": font_size,
                        "bold": style.get("bold", False),
                        "italic": style.get("italic", False),
                        "underline": style.get("underline", False),
                    },
                    "slide_index": slide.slide_index,
                    "_slides_meta": {
                        "presentation_id": run.presentation_id,
                        "slide_object_id": run.slide_object_id,
                        "page_element_id": run.page_element_id,
                        "start_index": run.start_index,
                        "end_index": run.end_index,
                    },
                })
    
    return runs


def build_translated_runs_from_result(
    original_runs: list[dict],
    translated_results: list[dict],
) -> list[dict]:
    """
    Match translation results back to Google Slides metadata.
    
    Args:
        original_runs: The runs from flatten_runs_for_translation()
        translated_results: The results from the translation service
                           (must have the same order)
    
    Returns:
        List of dicts suitable for create_translated_presentation()
    """
    batch = []
    for orig, tr in zip(original_runs, translated_results):
        meta = orig.get("_slides_meta", {})
        batch.append({
            "slide_object_id": meta.get("slide_object_id", ""),
            "page_element_id": meta.get("page_element_id", ""),
            "start_index": meta.get("start_index", 0),
            "end_index": meta.get("end_index", 0),
            "original_text": orig.get("text", ""),
            "translated_text": tr.get("translated_text", orig.get("text", "")),
        })
    return batch
