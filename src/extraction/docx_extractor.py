"""DOCX text extraction built on python-docx.

Resumes authored in Word routinely use features that a naive
``"\\n".join(p.text for p in doc.paragraphs)`` silently drops:

* **Tables** are used for layout, so contact blocks and skill grids vanish.
* **Headers / footers** often hold the candidate's name and phone number.
* **Hyperlinks** carry the real LinkedIn or GitHub URL while the visible text
  is just "LinkedIn".
* **List paragraphs** lose their bullet marker, which the section parser needs
  to tell a heading apart from a responsibility line.

This module walks the document body in true document order and handles all of
the above.
"""

from __future__ import annotations

from typing import Any, Iterator

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from ..models import ExtractionResult
from ..settings import MIN_EXTRACTABLE_CHARS
from .errors import CorruptedFileError, NoExtractableTextError

#: Cell separator used when flattening table rows; the normaliser later turns
#: this into a structural delimiter the field parsers understand.
_CELL_SEPARATOR = " | "


def extract_docx(data: bytes, file_name: str = "") -> ExtractionResult:
    """Extract text from DOCX bytes.

    Raises:
        CorruptedFileError: the file is not a readable Office Open XML package.
        NoExtractableTextError: the document opened but holds no usable text.
    """
    import io

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise CorruptedFileError(f"The DOCX file could not be opened: {exc}") from exc

    warnings: list[str] = []
    body_lines: list[str] = []
    paragraph_count = 0
    table_count = 0

    try:
        for block in _iter_block_items(document):
            if isinstance(block, Paragraph):
                paragraph_count += 1
                line = _render_paragraph(block)
                if line:
                    body_lines.append(line)
            else:  # Table
                table_count += 1
                body_lines.extend(_render_table(block))
    except Exception as exc:
        # Keep whatever was read before the failure rather than losing the upload.
        warnings.append(f"Document body was only partially readable: {exc}")

    header_footer_lines = _render_headers_and_footers(document, warnings)
    links = _collect_hyperlinks(document, warnings)

    # Header/footer content is positioned before the body: the candidate's name
    # living in a Word header should still be treated as the resume header.
    all_lines = header_footer_lines + body_lines
    text = "\n".join(all_lines)

    if len(text.strip()) < MIN_EXTRACTABLE_CHARS:
        raise NoExtractableTextError(
            "No readable text could be extracted from this DOCX file. "
            "It may be empty or contain only images."
        )

    if table_count:
        warnings.append(
            f"Read {table_count} layout table(s); cells were flattened into text rows."
        )

    return ExtractionResult(
        text=text,
        file_name=file_name,
        file_type="docx",
        file_size_bytes=len(data),
        page_count=0,  # DOCX has no fixed pagination before rendering.
        embedded_links=links,
        warnings=warnings,
        metadata={
            "paragraph_count": paragraph_count,
            "table_count": table_count,
            "header_footer_lines": len(header_footer_lines),
            "extractor": "python-docx",
        },
    )


# --------------------------------------------------------------------------- #
# Document traversal
# --------------------------------------------------------------------------- #


def _iter_block_items(parent: Any) -> Iterator[Paragraph | Table]:
    """Yield paragraphs and tables of ``parent`` in true document order.

    Works for ``Document``, ``_Cell``, ``_Header`` and ``_Footer`` parents.
    Uses python-docx's own ``iter_inner_content`` when available and falls back
    to walking the XML children otherwise.
    """
    iter_inner = getattr(parent, "iter_inner_content", None)
    if callable(iter_inner):
        for item in iter_inner():
            if isinstance(item, (Paragraph, Table)):
                yield item
        return

    parent_element = _body_element(parent)
    if parent_element is None:  # pragma: no cover - unknown container type
        return

    for child in parent_element.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, parent)
        elif child.tag == qn("w:tbl"):
            yield Table(child, parent)


def _body_element(parent: Any) -> Any | None:
    """Resolve the XML element whose children are block-level items."""
    if isinstance(parent, _Cell):
        return parent._tc
    element = getattr(parent, "element", None)
    body = getattr(element, "body", None)
    if body is not None:
        return body
    if element is not None:
        return element
    return getattr(parent, "_element", None)


def _render_paragraph(paragraph: Paragraph) -> str:
    """Return a paragraph's text, re-attaching a bullet marker for list items."""
    text = paragraph.text.strip()
    if not text:
        return ""

    style_name = ""
    try:
        style_name = (paragraph.style.name or "").lower()
    except Exception:  # pragma: no cover - broken style references
        style_name = ""

    is_list = "list" in style_name or _has_numbering(paragraph)
    if is_list and not text.startswith(("-", "\u2022", "*")):
        return f"- {text}"
    return text


def _has_numbering(paragraph: Paragraph) -> bool:
    """True when the paragraph carries Word numbering (bullets/numbers)."""
    try:
        p_pr = paragraph._p.pPr
        return p_pr is not None and p_pr.numPr is not None
    except Exception:  # pragma: no cover
        return False


def _render_table(table: Table) -> list[str]:
    """Flatten a table into one text line per row.

    Single-column tables (a very common "sidebar" trick) are emitted as plain
    lines so they read like normal paragraphs.
    """
    lines: list[str] = []
    for row in table.rows:
        cells: list[str] = []
        try:
            row_cells = row.cells
        except Exception:  # pragma: no cover - merged-cell edge cases
            continue
        for cell in row_cells:
            cell_lines: list[str] = []
            for block in _iter_block_items(cell):
                if isinstance(block, Paragraph):
                    rendered = _render_paragraph(block)
                    if rendered:
                        cell_lines.append(rendered)
                else:
                    cell_lines.extend(_render_table(block))
            cell_text = " ".join(cell_lines).strip()
            if cell_text:
                cells.append(cell_text)

        # Drop duplicates produced by horizontally merged cells.
        deduped: list[str] = []
        for cell_text in cells:
            if not deduped or deduped[-1] != cell_text:
                deduped.append(cell_text)

        if not deduped:
            continue
        lines.append(deduped[0] if len(deduped) == 1 else _CELL_SEPARATOR.join(deduped))
    return lines


def _render_headers_and_footers(document: Any, warnings: list[str]) -> list[str]:
    """Collect text from every section header and footer, in order."""
    lines: list[str] = []
    try:
        for section in document.sections:
            for container in (section.header, section.footer):
                if container is None:
                    continue
                for block in _iter_block_items(container):
                    if isinstance(block, Paragraph):
                        rendered = _render_paragraph(block)
                        if rendered:
                            lines.append(rendered)
                    else:
                        lines.extend(_render_table(block))
    except Exception as exc:  # pragma: no cover
        warnings.append(f"Headers and footers could not be read: {exc}")

    # Word repeats the same header on every section; keep one copy.
    seen: set[str] = set()
    unique: list[str] = []
    for line in lines:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique


def _collect_hyperlinks(document: Any, warnings: list[str]) -> list[str]:
    """Return external hyperlink targets from the document's relationships."""
    targets: list[str] = []
    seen: set[str] = set()
    parts = [document.part]
    try:
        parts.extend(
            section.header.part
            for section in document.sections
            if section.header is not None
        )
        parts.extend(
            section.footer.part
            for section in document.sections
            if section.footer is not None
        )
    except Exception:  # pragma: no cover
        pass

    for part in parts:
        try:
            relationships = part.rels
        except Exception:  # pragma: no cover
            continue
        for rel in relationships.values():
            try:
                if rel.reltype != RT.HYPERLINK or not rel.is_external:
                    continue
                target = str(rel.target_ref).strip()
            except Exception:  # pragma: no cover
                continue
            key = target.lower().rstrip("/")
            if target and key not in seen:
                seen.add(key)
                targets.append(target)

    if not targets:
        return []
    if len(targets) > 40:
        warnings.append("Document contains an unusually high number of hyperlinks.")
    return targets
