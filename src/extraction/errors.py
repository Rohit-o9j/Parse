"""Typed extraction failures.

Each error carries a short, user-facing ``message`` and an optional ``hint``
describing what the user can do about it. The UI renders both, so no stack
traces leak into the interface.
"""

from __future__ import annotations


class ExtractionError(Exception):
    """Base class for every recoverable document-extraction failure."""

    #: Default guidance shown under the error message.
    default_hint: str = ""

    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint if hint is not None else self.default_hint

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class UnsupportedFileTypeError(ExtractionError):
    default_hint = "Upload a PDF or DOCX file. Legacy .doc files must be re-saved as .docx."


class EmptyFileError(ExtractionError):
    default_hint = "The file contains no data. Check that the upload completed and try again."


class FileTooLargeError(ExtractionError):
    default_hint = "Compress the document or remove embedded images, then upload again."


class CorruptedFileError(ExtractionError):
    default_hint = (
        "The file structure could not be read. Try re-exporting the resume from the "
        "original application."
    )


class EncryptedFileError(ExtractionError):
    default_hint = "Remove the password protection and upload the document again."


class NoExtractableTextError(ExtractionError):
    default_hint = (
        "The document appears to be a scan or image-only export, so there is no text "
        "layer to read. Upload a text-based PDF or a DOCX file."
    )
