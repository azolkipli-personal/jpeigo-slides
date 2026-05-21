"""
Data models for PPTX translation.
"""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class FontStyle(BaseModel):
    """Font styling attributes for a text run."""
    font_size: Optional[float] = None  # in points
    font_color: Optional[str] = None  # hex color
    font_name: Optional[str] = None  # typeface
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strike_through: bool = False
    
    # Vertical text support
    vertical: bool = False  # tategaki (vertical text)


class SpatialConstraints(BaseModel):
    """Spatial constraints for a text box."""
    left: int  # EMU (English Metric Units)
    top: int
    width: int
    height: int
    anchor_x: str = "left"  # horizontal alignment: left, center, right
    anchor_y: str = "top"   # vertical alignment: top, middle, bottom


class TextRun(BaseModel):
    """A single text run with styling."""
    run_id: str  # unique identifier
    text: str    # original text
    style: FontStyle
    
    # Location within the PPTX
    slide_index: int
    shape_index: int
    paragraph_index: int
    run_index: int
    
    # XML path for re-injection
    xml_path: str


class TextBox(BaseModel):
    """A text box containing multiple runs."""
    box_id: str
    shape_type: str  # 'shape', 'table_cell', 'group_shape'
    slide_index: int
    shape_index: int
    
    # All runs inthis text box
    runs: list[TextRun]
    
    # Spatial constraints
    constraints: SpatialConstraints
    
    # Translation context
    context: Optional[str] = None  # Additional context for translation


class Slide(BaseModel):
    """A single slide with all its text boxes."""
    slide_index: int
    slide_id: int  # internal PPTX slide ID
    text_boxes: list[TextBox]
    
    # Preview image (base64)
    preview_base64: Optional[str] = None


class PPTXDocument(BaseModel):
    """Complete PPTX document structure."""
    filename: str
    slides: list[Slide]
    total_runs: int
    extraction_metadata: dict


class TranslationRequest(BaseModel):
    """Request to translate text runs."""
    runs: list[TextRun]
    source_language: str = "ja"  # japanese default
    target_language: str = "en"  # english default
    model: str = "auto"  # auto, glm, kimi, minimax, qwen, ollama
    context: Optional[str] = None
    job_id: Optional[str] = None  # upload job_id to track progress


class TranslatedRun(BaseModel):
    """A translated text run."""
    run_id: str
    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    model_used: str
    
    # Font size adjustment if needed
    adjusted_font_size: Optional[float] = None
    adjustment_reason: Optional[str] = None  # "overflow" or "underflow"


class TranslationJob(BaseModel):
    """A translation job with multiple runs."""
    job_id: str
    filename: str
    status: str  # pending, processing, completed, failed
    total_runs: int
    translated_runs: list[TranslatedRun] = []
    progress: float = 0.0
    error: Optional[str] = None


class TranslationMemoryEntry(BaseModel):
    """Cached translation for reuse."""
    source_text: str
    source_language: str
    translated_text: str
    target_language: str
    model_used: str
    frequency: int = 1  # number of times used


class ExportRequest(BaseModel):
    """Request to export translated PPTX."""
    job_id: str
    filename: Optional[str] = None