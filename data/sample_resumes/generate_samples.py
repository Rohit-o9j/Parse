"""Build PDF and DOCX sample resumes from the plain-text sources.

Run from the project root::

    python data/sample_resumes/generate_samples.py

The ``.txt`` files in this folder are the single source of truth. This script
renders each of them into a realistic ``.pdf`` (via PyMuPDF) and ``.docx`` (via
python-docx) so the parser can be exercised end to end on real binary
documents rather than on strings.

The rendering deliberately mimics common resume conventions - bold capitalised
section headings, indented bullets, a right-aligned date column in the DOCX
tables - because those are exactly the features the parser has to cope with.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pymupdf
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

SAMPLE_DIR = Path(__file__).resolve().parent

# --- PDF layout constants -------------------------------------------------- #
PAGE_WIDTH, PAGE_HEIGHT = pymupdf.paper_size("letter")
MARGIN_X = 54.0
MARGIN_TOP = 56.0
MARGIN_BOTTOM = 56.0
BODY_SIZE = 9.5
HEADING_SIZE = 10.5
NAME_SIZE = 17.0
LINE_HEIGHT = 13.2
BULLET_INDENT = 14.0

#: A heading line: all capitals (plus punctuation) or Title Case and short.
_HEADING_RE = re.compile(r"^[A-Z][A-Z&/ .'\-]{2,40}$")


def is_heading(line: str) -> bool:
    return bool(_HEADING_RE.match(line.strip()))


def is_bullet(line: str) -> bool:
    return line.lstrip().startswith("- ")


def render_pdf(lines: list[str], destination: Path) -> None:
    """Write ``lines`` to a multi-page PDF with resume-like typography."""
    document = pymupdf.open()
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    cursor_y = MARGIN_TOP
    first_text_line = True

    for raw_line in lines:
        line = raw_line.rstrip()

        if cursor_y > PAGE_HEIGHT - MARGIN_BOTTOM:
            page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            cursor_y = MARGIN_TOP

        if not line.strip():
            cursor_y += LINE_HEIGHT * 0.55
            continue

        if first_text_line:
            font, size = "hebo", NAME_SIZE
            first_text_line = False
        elif is_heading(line):
            cursor_y += LINE_HEIGHT * 0.35
            font, size = "hebo", HEADING_SIZE
        else:
            font, size = "helv", BODY_SIZE

        indent = BULLET_INDENT if is_bullet(line) else 0.0
        text = f"\u2022 {line.lstrip()[2:]}" if is_bullet(line) else line.strip()

        page.insert_text(
            (MARGIN_X + indent, cursor_y),
            text,
            fontname=font,
            fontsize=size,
            color=(0.1, 0.1, 0.1),
        )
        cursor_y += LINE_HEIGHT if size <= HEADING_SIZE else LINE_HEIGHT * 1.5

        if is_heading(line):
            # A thin rule under each section heading, as most templates do.
            page.draw_line(
                pymupdf.Point(MARGIN_X, cursor_y - LINE_HEIGHT + 3),
                pymupdf.Point(PAGE_WIDTH - MARGIN_X, cursor_y - LINE_HEIGHT + 3),
                color=(0.75, 0.75, 0.78),
                width=0.6,
            )

    document.save(destination)
    document.close()


def render_docx(lines: list[str], destination: Path) -> None:
    """Write ``lines`` to a DOCX with real heading styles and list bullets."""
    document = Document()
    base = document.styles["Normal"]
    base.font.name = "Calibri"
    base.font.size = Pt(10)

    first_text_line = True
    for raw_line in lines:
        line = raw_line.rstrip()

        if not line.strip():
            continue

        if first_text_line:
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = paragraph.add_run(line.strip())
            run.bold = True
            run.font.size = Pt(18)
            first_text_line = False
            continue

        if is_heading(line):
            paragraph = document.add_paragraph()
            run = paragraph.add_run(line.strip())
            run.bold = True
            run.font.size = Pt(11)
            run.font.color.rgb = RGBColor(0x1F, 0x29, 0x37)
            paragraph.paragraph_format.space_before = Pt(10)
            paragraph.paragraph_format.space_after = Pt(2)
            continue

        if is_bullet(line):
            document.add_paragraph(line.lstrip()[2:], style="List Bullet")
            continue

        document.add_paragraph(line.strip())

    document.save(destination)


def main(argv: list[str] | None = None) -> int:
    sources = sorted(SAMPLE_DIR.glob("*.txt"))
    if not sources:
        print(f"No .txt sources found in {SAMPLE_DIR}", file=sys.stderr)
        return 1

    for source in sources:
        lines = source.read_text(encoding="utf-8").splitlines()
        pdf_path = source.with_suffix(".pdf")
        docx_path = source.with_suffix(".docx")
        render_pdf(lines, pdf_path)
        render_docx(lines, docx_path)
        print(f"{source.name:28} -> {pdf_path.name}, {docx_path.name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
