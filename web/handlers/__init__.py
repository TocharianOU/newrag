"""Handlers package for document processing logic"""

from .document_processor import (
    extract_matched_bboxes_from_file,
    process_document_background
)

__all__ = [
    'extract_matched_bboxes_from_file',
    'process_document_background'
]

