"""Document extraction layer: uploaded bytes in, plain text out.

Nothing in this package knows what a resume is. Its only job is to produce the
most faithful plain-text rendering of a PDF or DOCX that it can, together with
provenance metadata and precise errors.
"""

from .dispatcher import extract_text, file_extension, validate_upload
from .docx_extractor import extract_docx
from .errors import (
    CorruptedFileError,
    EmptyFileError,
    EncryptedFileError,
    ExtractionError,
    FileTooLargeError,
    NoExtractableTextError,
    UnsupportedFileTypeError,
)
from .pdf_extractor import extract_pdf

__all__ = [
    "CorruptedFileError",
    "EmptyFileError",
    "EncryptedFileError",
    "ExtractionError",
    "FileTooLargeError",
    "NoExtractableTextError",
    "UnsupportedFileTypeError",
    "extract_docx",
    "extract_pdf",
    "extract_text",
    "file_extension",
    "validate_upload",
]
