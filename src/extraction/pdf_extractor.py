"""PDF text extraction built on PyMuPDF.

Beyond a plain ``page.get_text()`` dump this module:

* orders text blocks top-to-bottom, left-to-right;
* detects two-column / sidebar layouts and reads each column in full before
  moving on, which keeps section headings attached to their content;
* harvests hyperlink annotations, because LinkedIn and GitHub URLs are very
  often a clickable label rather than visible text;
* reports a precise error when a PDF has no text layer at all (scans).
"""

from __future__ import annotations

from typing import Any, Sequence

from ..models import ExtractionResult
from ..settings import MIN_EXTRACTABLE_CHARS
from .errors import CorruptedFileError, EncryptedFileError, NoExtractableTextError

try:  # PyMuPDF >= 1.24 ships the ``pymupdf`` name; ``fitz`` is the legacy alias.
    import pymupdf as fitz
except ImportError:  # pragma: no cover - depends on installed wheel
    import fitz  # type: ignore[no-redef]


#: Block tuple layout returned by ``page.get_text("blocks")``.
_X0, _Y0, _X1, _Y1, _TEXT, _NO, _TYPE = range(7)

#: Text blocks have type 0; type 1 blocks are images.
_TEXT_BLOCK = 0

#: Vertical rounding (points) used when sorting blocks into reading order.
#: Two blocks whose tops differ by less than this are treated as one row.
_ROW_TOLERANCE = 6.0

#: A column split is only accepted when at least this many blocks sit wholly
#: inside each half of the page.
_MIN_BLOCKS_PER_COLUMN = 3

#: ...and when no more than this share of blocks straddles the centre line.
_MAX_STRADDLE_RATIO = 0.25


def extract_pdf(data: bytes, file_name: str = "") -> ExtractionResult:
    """Extract text from PDF bytes.

    Raises:
        EncryptedFileError: the document is password protected.
        CorruptedFileError: the document could not be opened or read.
        NoExtractableTextError: the document opened but holds no text layer.
    """
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises bare Exception subclasses
        raise CorruptedFileError(f"The PDF could not be opened: {exc}") from exc

    with doc:
        if doc.needs_pass and not doc.authenticate(""):
            raise EncryptedFileError("This PDF is password protected.")

        page_texts: list[str] = []
        per_page_chars: list[int] = []
        links: list[str] = []
        image_count = 0
        failed_pages: list[int] = []
        multi_column_pages: list[int] = []

        for index, page in enumerate(doc):
            try:
                text, is_multi_column = _extract_page_text(page)
                if is_multi_column:
                    multi_column_pages.append(index + 1)
                links.extend(_extract_page_links(page))
                image_count += len(page.get_images(full=True))
            except Exception:  # a single damaged page should not sink the upload
                failed_pages.append(index + 1)
                text = ""
            page_texts.append(text)
            per_page_chars.append(len(text))

        metadata: dict[str, Any] = dict(doc.metadata or {})
        page_count = doc.page_count

    text = "\n\n".join(t for t in page_texts if t.strip())

    warnings: list[str] = []
    if failed_pages:
        warnings.append(
            "Could not read "
            + ("page " if len(failed_pages) == 1 else "pages ")
            + ", ".join(str(p) for p in failed_pages)
            + "; the rest of the document was parsed."
        )
    if multi_column_pages:
        warnings.append(
            "Detected a multi-column layout on "
            + ("page " if len(multi_column_pages) == 1 else "pages ")
            + ", ".join(str(p) for p in multi_column_pages)
            + "; columns were read separately."
        )

    if len(text.strip()) < MIN_EXTRACTABLE_CHARS:
        detail = (
            f" The file holds {image_count} image(s) and almost no text, which is typical "
            "of a scanned resume."
            if image_count
            else ""
        )
        raise NoExtractableTextError(
            "No readable text could be extracted from this PDF." + detail
        )

    return ExtractionResult(
        text=text,
        file_name=file_name,
        file_type="pdf",
        file_size_bytes=len(data),
        page_count=page_count,
        embedded_links=_dedupe(links),
        warnings=warnings,
        metadata={
            "producer": (metadata.get("producer") or "").strip(),
            "creator": (metadata.get("creator") or "").strip(),
            "title": (metadata.get("title") or "").strip(),
            "chars_per_page": per_page_chars,
            "image_count": image_count,
            "multi_column_pages": multi_column_pages,
            "extractor": "PyMuPDF",
        },
    )


# --------------------------------------------------------------------------- #
# Page-level helpers
# --------------------------------------------------------------------------- #


def _extract_page_text(page: Any) -> tuple[str, bool]:
    """Return ``(text, used_column_split)`` for a single page."""
    raw_blocks = page.get_text("blocks")
    blocks = [
        b
        for b in raw_blocks
        if len(b) > _TYPE and b[_TYPE] == _TEXT_BLOCK and str(b[_TEXT]).strip()
    ]

    if not blocks:
        # Fall back to the plain text layer: some generators emit a single
        # malformed block that the filter above drops.
        return page.get_text("text").strip(), False

    page_width = float(page.rect.width) or 1.0
    columns = _split_into_columns(blocks, page_width)
    ordered: list[Sequence[Any]] = []
    for column in columns:
        ordered.extend(sorted(column, key=lambda b: (round(b[_Y0] / _ROW_TOLERANCE), b[_X0])))

    lines: list[str] = []
    for block in ordered:
        chunk = str(block[_TEXT]).strip()
        if chunk:
            lines.append(chunk)

    return "\n".join(lines), len(columns) > 1


def _split_into_columns(
    blocks: list[Sequence[Any]], page_width: float
) -> list[list[Sequence[Any]]]:
    """Group blocks into reading columns.

    Returns a single group for normal single-column pages, or ``[left, right]``
    when the page clearly uses two columns. Reading a sidebar resume as one
    flat stream interleaves unrelated lines, which badly confuses section
    detection, so this is worth getting right.
    """
    midpoint = page_width / 2.0
    tolerance = page_width * 0.04

    left: list[Sequence[Any]] = []
    right: list[Sequence[Any]] = []
    straddling: list[Sequence[Any]] = []
    for block in blocks:
        # Classify once so a narrow, centred block cannot land in two groups.
        if block[_X1] <= midpoint + tolerance:
            left.append(block)
        elif block[_X0] >= midpoint - tolerance:
            right.append(block)
        else:
            straddling.append(block)

    enough_on_both_sides = (
        len(left) >= _MIN_BLOCKS_PER_COLUMN and len(right) >= _MIN_BLOCKS_PER_COLUMN
    )
    few_straddlers = len(straddling) <= _MAX_STRADDLE_RATIO * len(blocks)

    if enough_on_both_sides and few_straddlers:
        # Straddling blocks are usually a full-width header; keep them first.
        header = sorted(straddling, key=lambda b: b[_Y0])
        if header:
            return [header, left, right]
        return [left, right]

    return [blocks]


def _extract_page_links(page: Any) -> list[str]:
    """Collect external URI targets from a page's link annotations."""
    found: list[str] = []
    try:
        for link in page.get_links():
            uri = (link or {}).get("uri")
            if uri:
                found.append(str(uri).strip())
    except Exception:  # pragma: no cover - annotation tables can be malformed
        return found
    return found


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        key = value.lower().rstrip("/")
        if value and key not in seen:
            seen.add(key)
            unique.append(value)
    return unique
