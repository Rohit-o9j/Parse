"""Upload validation and extractor dispatch.

This is the only entry point the rest of the application uses to turn raw
uploaded bytes into text. It validates before it parses so the user gets a
precise, actionable message instead of a library traceback.
"""

from __future__ import annotations

from pathlib import PurePath

from ..models import ExtractionResult
from ..settings import MAX_FILE_SIZE_BYTES, MAX_FILE_SIZE_MB, SUPPORTED_EXTENSIONS
from .docx_extractor import extract_docx
from .errors import (
    CorruptedFileError,
    EmptyFileError,
    ExtractionError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from .pdf_extractor import extract_pdf

#: Leading bytes that identify a format regardless of the file name.
_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")  # DOCX is a ZIP package
_LEGACY_DOC_MAGIC = b"\xd0\xcf\x11\xe0"  # OLE2 compound file => .doc / .xls


def file_extension(file_name: str) -> str:
    """Lowercase extension without the dot (``"resume.PDF"`` -> ``"pdf"``)."""
    return PurePath(file_name or "").suffix.lower().lstrip(".")


def validate_upload(data: bytes, file_name: str) -> str:
    """Validate an upload and return the format to parse (``"pdf"``/``"docx"``).

    The detected content signature wins over the file name, so a mislabelled
    file is still handled correctly - and a renamed ``.doc`` is rejected with a
    useful explanation rather than crashing the DOCX reader.

    Raises:
        EmptyFileError, FileTooLargeError, UnsupportedFileTypeError
    """
    if data is None or len(data) == 0:
        raise EmptyFileError("The uploaded file is empty (0 bytes).")

    if len(data) > MAX_FILE_SIZE_BYTES:
        raise FileTooLargeError(
            f"The file is {len(data) / (1024 * 1024):.1f} MB, which exceeds the "
            f"{MAX_FILE_SIZE_MB} MB limit."
        )

    extension = file_extension(file_name)
    signature = _detect_signature(data)

    if signature == "doc":
        raise UnsupportedFileTypeError(
            "Legacy Microsoft Word (.doc) files are not supported."
        )

    if signature:
        return signature

    if extension in SUPPORTED_EXTENSIONS:
        # The name claims a supported type but the content does not match.
        raise CorruptedFileError(
            f"The file is named like a {extension.upper()} but its contents do not "
            f"match that format."
        )

    supported = ", ".join(f".{ext}" for ext in SUPPORTED_EXTENSIONS)
    found = f".{extension}" if extension else "unknown"
    raise UnsupportedFileTypeError(
        f"Unsupported file type ({found}). Supported formats: {supported}."
    )


def extract_text(data: bytes, file_name: str = "") -> ExtractionResult:
    """Validate then extract text from an uploaded resume.

    Raises:
        ExtractionError: any validation or extraction failure. Every subclass
            carries a user-facing ``message`` and a remediation ``hint``.
    """
    file_format = validate_upload(data, file_name)

    if file_format == "pdf":
        result = extract_pdf(data, file_name=file_name)
    elif file_format == "docx":
        result = extract_docx(data, file_name=file_name)
    else:  # pragma: no cover - validate_upload already narrowed the options
        raise UnsupportedFileTypeError(f"No extractor available for '{file_format}'.")

    declared = file_extension(file_name)
    if declared and declared != file_format:
        result.warnings.append(
            f"File is named '.{declared}' but its contents are {file_format.upper()}; "
            f"parsed as {file_format.upper()}."
        )
    return result


def _detect_signature(data: bytes) -> str:
    """Identify the format from magic bytes, or ``""`` when unrecognised."""
    head = data[:8]
    if data[:1024].lstrip()[:5] == _PDF_MAGIC or head.startswith(_PDF_MAGIC):
        return "pdf"
    if head.startswith(_LEGACY_DOC_MAGIC):
        return "doc"
    if any(head.startswith(magic) for magic in _ZIP_MAGIC):
        # Any OOXML package looks like a ZIP; confirm it is a Word document.
        return "docx" if _is_wordprocessing_package(data) else ""
    return ""


def _is_wordprocessing_package(data: bytes) -> bool:
    """True when the ZIP package contains a Word main document part."""
    import io
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except Exception:
        return False
    return "word/document.xml" in names


__all__ = [
    "ExtractionError",
    "extract_text",
    "file_extension",
    "validate_upload",
]
