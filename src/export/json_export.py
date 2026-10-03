"""JSON export.

The top level matches the agreed candidate schema exactly::

    {"name": "", "email": "", "phone": "", "skills": [],
     "education": [], "experience": [], "projects": []}

Additional keys (``location``, ``links``, ``summary``, ``skills_by_category``,
``meta``) sit alongside it, so a consumer that only knows the base schema can
ignore them while a richer consumer gets the full picture.

Two conventions worth knowing:

* A field the parser could not determine is an **empty string**, never a
  guess and never the literal "Not detected". ``"Not detected"`` is a
  presentation choice and belongs in the UI, not in the data.
* ``meta`` carries the provenance needed to reproduce or audit a parse: the
  source file, parser version, spaCy model and which sections were found.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import (
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
    ProjectEntry,
)
from ..settings import APP_VERSION


def build_payload(resume: ParsedResume, include_meta: bool = True) -> dict[str, Any]:
    """Build the JSON-serialisable candidate record."""
    contact = resume.contact

    payload: dict[str, Any] = {
        "name": contact.name,
        "email": contact.email,
        "phone": contact.phone,
        "location": contact.location,
        "links": dict(contact.links),
        "summary": resume.summary,
        "skills": resume.skill_names(),
        "education": [_education_dict(entry) for entry in resume.education],
        "experience": [_experience_dict(entry) for entry in resume.experience],
        "projects": [_project_dict(entry) for entry in resume.projects],
        "certifications": list(resume.certifications),
        "achievements": list(resume.achievements),
        "languages": list(resume.languages),
        "skills_by_category": {
            category: [skill.name for skill in skills]
            for category, skills in resume.skills_by_category().items()
        },
    }

    if include_meta:
        payload["meta"] = _meta_dict(resume)
    return payload


def to_json(resume: ParsedResume, include_meta: bool = True, indent: int = 2) -> str:
    """Serialise a parsed resume as a JSON document."""
    return json.dumps(
        build_payload(resume, include_meta=include_meta),
        indent=indent,
        ensure_ascii=False,
    )


def to_json_bytes(resume: ParsedResume, include_meta: bool = True) -> bytes:
    """UTF-8 encoded JSON, ready for a Streamlit download button."""
    return to_json(resume, include_meta=include_meta).encode("utf-8")


# --------------------------------------------------------------------------- #
# Per-entry shapes
# --------------------------------------------------------------------------- #


def _education_dict(entry: EducationEntry) -> dict[str, Any]:
    return {
        "degree": entry.degree,
        "institution": entry.institution,
        "field_of_study": entry.field_of_study,
        "start_year": entry.start_year,
        "end_year": entry.end_year,
        "grade": entry.grade,
        "location": entry.location,
        "details": list(entry.details),
    }


def _experience_dict(entry: ExperienceEntry) -> dict[str, Any]:
    return {
        "job_title": entry.job_title,
        "company": entry.company,
        "location": entry.location,
        "start_date": entry.start_date,
        "end_date": entry.end_date,
        "is_current": entry.is_current,
        "description": list(entry.description),
    }


def _project_dict(entry: ProjectEntry) -> dict[str, Any]:
    return {
        "name": entry.name,
        "description": list(entry.description),
        "technologies": list(entry.technologies),
        "link": entry.link,
        "start_date": entry.start_date,
        "end_date": entry.end_date,
    }


def _meta_dict(resume: ParsedResume) -> dict[str, Any]:
    diagnostics = resume.diagnostics or {}
    extraction = resume.extraction
    return {
        "parser_version": APP_VERSION,
        "parsed_at": resume.parsed_at,
        "source_file": extraction.file_name,
        "source_type": extraction.file_type,
        "page_count": extraction.page_count,
        "word_count": diagnostics.get("word_count", extraction.word_count),
        "sections_detected": resume.detected_section_keys,
        "completeness_percent": resume.completeness(),
        "fields_detected": resume.field_presence(),
        "nlp": diagnostics.get("nlp", {}),
        "extraction_warnings": list(extraction.warnings),
        "parse_warnings": list(resume.warnings),
        "field_evidence": dict(resume.contact.evidence),
    }
