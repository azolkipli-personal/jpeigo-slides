"""Core PPTX processing module."""
from .extractor import extract_pptx, extract_slide
from .injector import inject_translations

__all__ = ['extract_pptx', 'extract_slide', 'inject_translations']