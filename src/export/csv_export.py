"""CSV export.

A resume is a nested document and CSV is flat, so there is no single correct
flattening. Both useful ones are provided:

``summary`` (one row)
    One candidate per row, repeated values collapsed into ``;``-joined cells.
    This is the shape you want when appending many resumes to one sheet and
    filtering or pivoting across candidates.

``detailed`` (one row per item)
    Tidy data: ``section, index, field, value``. Nothing is lost, every nested
    item keeps its own row, and the result pivots cleanly in a spreadsheet.
    This is the default because it is lossless.

Both writers use ``csv.writer`` with ``\\r\\n`` line endings and a UTF-8 BOM,
which is what makes the file open correctly in Excel on Windows without a
manual import step.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Iterable, Literal

from ..models import ParsedResume
from ..settings import SKILL_CATEGORY_ORDER

CsvLayout = Literal["summary", "detailed"]

#: Multi-value cells in the summary layout are joined with this.
_JOIN = "; "

#: Byte-order mark so Excel detects UTF-8 automatically.
_BOM = "\ufeff"

_SUMMARY_COLUMNS: tuple[str, ...] = (
    "name",
    "email",
    "phone",
    "location",
    "linkedin",
    "github",
    "portfolio",
    "summary",
    "skills",
    "skill_count",
    "education_count",
    "experience_count",
    "project_count",
    "latest_job_title",
    "latest_company",
    "latest_start_date",
    "latest_end_date",
    "highest_degree",
    "highest_institution",
    "highest_field_of_study",
    "highest_grade",
    "graduation_year",
    "certifications",
    "achievements",
    "languages",
    "source_file",
    "source_type",
    "completeness_percent",
    "parsed_at",
)

_DETAIL_COLUMNS: tuple[str, ...] = ("section", "index", "field", "value")


def to_csv(resume: ParsedResume, layout: CsvLayout = "detailed") -> str:
    """Render a parsed resume as CSV text."""
    if layout == "summary":
        rows = [_SUMMARY_COLUMNS, _summary_row(resume)]
    else:
        rows = [_DETAIL_COLUMNS, *_detail_rows(resume)]
    return _write(rows)


def to_csv_bytes(resume: ParsedResume, layout: CsvLayout = "detailed") -> bytes:
    """UTF-8 (BOM) encoded CSV, ready for a Streamlit download button."""
    return (_BOM + to_csv(resume, layout=layout)).encode("utf-8")


def _write(rows: Iterable[Iterable[Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for row in rows:
        writer.writerow(["" if value is None else str(value) for value in row])
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Summary layout
# --------------------------------------------------------------------------- #


def _summary_row(resume: ParsedResume) -> list[Any]:
    contact = resume.contact
    links = {key.lower(): value for key, value in contact.links.items()}

    latest = resume.experience[0] if resume.experience else None
    highest = _highest_qualification(resume)

    return [
        contact.name,
        contact.email,
        contact.phone,
        contact.location,
        links.get("linkedin", ""),
        links.get("github", ""),
        links.get("portfolio", ""),
        resume.summary,
        _JOIN.join(resume.skill_names()),
        len(resume.skills),
        len(resume.education),
        len(resume.experience),
        len(resume.projects),
        latest.job_title if latest else "",
        latest.company if latest else "",
        latest.start_date if latest else "",
        latest.end_date if latest else "",
        highest.degree if highest else "",
        highest.institution if highest else "",
        highest.field_of_study if highest else "",
        highest.grade if highest else "",
        highest.end_year if highest else "",
        _JOIN.join(resume.certifications),
        _JOIN.join(resume.achievements),
        _JOIN.join(resume.languages),
        resume.extraction.file_name,
        resume.extraction.file_type,
        resume.completeness(),
        resume.parsed_at,
    ]


#: Rough seniority ranking, highest first, used to pick the headline degree.
_DEGREE_RANK: tuple[tuple[str, int], ...] = (
    ("ph.d", 6), ("phd", 6), ("doctor", 6),
    ("master", 5), ("m.tech", 5), ("m.sc", 5), ("mba", 5), ("mca", 5),
    ("m.com", 5), ("m.e.", 5), ("ll.m", 5), ("m.pharm", 5),
    ("bachelor", 4), ("b.tech", 4), ("b.sc", 4), ("b.e.", 4), ("bca", 4),
    ("bba", 4), ("b.com", 4), ("mbbs", 4), ("ll.b", 4), ("b.arch", 4),
    ("b.pharm", 4), ("bds", 4),
    ("associate", 3), ("diploma", 2),
    ("higher secondary", 1), ("senior secondary", 1), ("intermediate", 1),
    ("hsc", 1), ("high school", 1), ("secondary", 1), ("ssc", 1),
)


def _highest_qualification(resume: ParsedResume):
    """The most senior education entry, falling back to the first one."""
    if not resume.education:
        return None

    def rank(entry: Any) -> tuple[int, str]:
        degree = (entry.degree or "").lower()
        score = 0
        for marker, value in _DEGREE_RANK:
            if marker in degree:
                score = max(score, value)
        return score, entry.end_year or ""

    return max(resume.education, key=rank)


# --------------------------------------------------------------------------- #
# Detailed layout
# --------------------------------------------------------------------------- #


def _detail_rows(resume: ParsedResume) -> list[list[Any]]:
    rows: list[list[Any]] = []

    def add(section: str, index: int | str, field: str, value: Any) -> None:
        if value in (None, "", [], {}):
            return
        rows.append([section, index, field, value])

    contact = resume.contact
    add("contact", 1, "name", contact.name)
    add("contact", 1, "email", contact.email)
    add("contact", 1, "phone", contact.phone)
    add("contact", 1, "location", contact.location)
    for label, url in contact.links.items():
        add("contact", 1, f"link:{label.lower()}", url)

    add("summary", 1, "text", resume.summary)

    ordered_categories = [
        category
        for category in SKILL_CATEGORY_ORDER
        if category in resume.skills_by_category()
    ]
    extra_categories = [
        category
        for category in resume.skills_by_category()
        if category not in ordered_categories
    ]
    position = 0
    for category in [*ordered_categories, *extra_categories]:
        for skill in resume.skills_by_category()[category]:
            position += 1
            rows.append(["skills", position, category, skill.name])

    for index, entry in enumerate(resume.education, start=1):
        add("education", index, "degree", entry.degree)
        add("education", index, "institution", entry.institution)
        add("education", index, "field_of_study", entry.field_of_study)
        add("education", index, "start_year", entry.start_year)
        add("education", index, "end_year", entry.end_year)
        add("education", index, "grade", entry.grade)
        add("education", index, "location", entry.location)
        for detail in entry.details:
            add("education", index, "detail", detail)

    for index, entry in enumerate(resume.experience, start=1):
        add("experience", index, "job_title", entry.job_title)
        add("experience", index, "company", entry.company)
        add("experience", index, "location", entry.location)
        add("experience", index, "start_date", entry.start_date)
        add("experience", index, "end_date", entry.end_date)
        add("experience", index, "is_current", "yes" if entry.is_current else "no")
        for bullet in entry.description:
            add("experience", index, "description", bullet)

    for index, entry in enumerate(resume.projects, start=1):
        add("projects", index, "name", entry.name)
        add("projects", index, "link", entry.link)
        add("projects", index, "start_date", entry.start_date)
        add("projects", index, "end_date", entry.end_date)
        for technology in entry.technologies:
            add("projects", index, "technology", technology)
        for bullet in entry.description:
            add("projects", index, "description", bullet)

    for label, values in (
        ("certifications", resume.certifications),
        ("achievements", resume.achievements),
        ("languages", resume.languages),
    ):
        for index, value in enumerate(values, start=1):
            add(label, index, "item", value)

    diagnostics = resume.diagnostics or {}
    add("meta", 1, "source_file", resume.extraction.file_name)
    add("meta", 1, "source_type", resume.extraction.file_type)
    add("meta", 1, "page_count", resume.extraction.page_count or "")
    add("meta", 1, "word_count", diagnostics.get("word_count", ""))
    add("meta", 1, "completeness_percent", resume.completeness())
    add("meta", 1, "sections_detected", _JOIN.join(resume.detected_section_keys))
    add("meta", 1, "parser_version", resume.parser_version)
    add("meta", 1, "parsed_at", resume.parsed_at)

    return rows
