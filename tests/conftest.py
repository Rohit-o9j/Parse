"""Shared fixtures.

The suite deliberately parses the **real** generated PDF and DOCX samples
rather than only strings, because the bugs that matter in a resume parser live
in the gap between "text I wrote in a test" and "text a PDF actually produces"
(lost blank lines, wrapped bullets, glyph substitutions, column ordering).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.parser import ResumeParser  # noqa: E402
from src.settings import SAMPLE_RESUME_DIR  # noqa: E402

SAMPLE_STEMS = ("rahul_sharma", "dana_whitfield")


@pytest.fixture(scope="session")
def parser() -> ResumeParser:
    """One parser for the whole session; loading spaCy is the slow part."""
    return ResumeParser()


@pytest.fixture(scope="session")
def regex_only_parser() -> ResumeParser:
    """Parser with NLP disabled, to prove the regex path stands alone."""
    return ResumeParser(use_nlp=False)


def sample_path(stem: str, suffix: str) -> Path:
    path = SAMPLE_RESUME_DIR / f"{stem}.{suffix.lstrip('.')}"
    if not path.exists():
        pytest.skip(
            f"{path.name} is missing. Generate it with "
            "`python data/sample_resumes/generate_samples.py`."
        )
    return path


@pytest.fixture(scope="session")
def rahul_text() -> str:
    return sample_path("rahul_sharma", "txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def dana_text() -> str:
    return sample_path("dana_whitfield", "txt").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def rahul_pdf_bytes() -> bytes:
    return sample_path("rahul_sharma", "pdf").read_bytes()


@pytest.fixture(scope="session")
def rahul_docx_bytes() -> bytes:
    return sample_path("rahul_sharma", "docx").read_bytes()


@pytest.fixture(scope="session")
def rahul_from_pdf(parser: ResumeParser, rahul_pdf_bytes: bytes):
    return parser.parse_file(rahul_pdf_bytes, file_name="rahul_sharma.pdf")


@pytest.fixture(scope="session")
def rahul_from_docx(parser: ResumeParser, rahul_docx_bytes: bytes):
    return parser.parse_file(rahul_docx_bytes, file_name="rahul_sharma.docx")


@pytest.fixture(scope="session")
def dana_from_pdf(parser: ResumeParser):
    data = sample_path("dana_whitfield", "pdf").read_bytes()
    return parser.parse_file(data, file_name="dana_whitfield.pdf")


@pytest.fixture(scope="session")
def dana_from_docx(parser: ResumeParser):
    data = sample_path("dana_whitfield", "docx").read_bytes()
    return parser.parse_file(data, file_name="dana_whitfield.docx")
