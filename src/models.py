"""Typed result objects shared across the extraction, parsing and export layers.

These dataclasses are the contract between layers. Every field defaults to an
empty value so a partially parsed resume is still a valid object: the parser
never invents data, it simply leaves fields empty and the UI renders
"Not detected".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .settings import APP_VERSION, COMPLETENESS_FIELDS

# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ExtractionResult:
    """Raw text pulled out of an uploaded document, plus provenance."""

    text: str = ""
    file_name: str = ""
    file_type: str = ""
    file_size_bytes: int = 0
    page_count: int = 0
    #: Hyperlink targets embedded in the document (PDF annotations, DOCX rels).
    embedded_links: list[str] = field(default_factory=list)
    #: Non-fatal problems worth surfacing to the user.
    warnings: list[str] = field(default_factory=list)
    #: Extractor-specific details (producer, table count, per-page chars...).
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


# --------------------------------------------------------------------------- #
# Structured sections
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ContactInfo:
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: dict[str, str] = field(default_factory=dict)
    #: field name -> short human readable justification (explainability).
    evidence: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Skill:
    name: str
    category: str = "Other"
    #: "dictionary" (known skill) or "section" (discovered in a skills block).
    source: str = "dictionary"
    #: Resume section the skill was found in, e.g. "skills", "experience".
    found_in: str = ""
    confidence: str = "medium"

    def __post_init__(self) -> None:
        self.name = self.name.strip()


@dataclass(slots=True)
class EducationEntry:
    degree: str = ""
    institution: str = ""
    field_of_study: str = ""
    start_year: str = ""
    end_year: str = ""
    grade: str = ""
    location: str = ""
    details: list[str] = field(default_factory=list)
    raw_text: str = ""

    def is_empty(self) -> bool:
        return not any((self.degree, self.institution, self.field_of_study, self.grade))


@dataclass(slots=True)
class ExperienceEntry:
    job_title: str = ""
    company: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    description: list[str] = field(default_factory=list)
    raw_text: str = ""
    #: Sortable key, "YYYY-MM" or "YYYY"; empty when no date was found.
    _sort_key: str = ""

    def is_empty(self) -> bool:
        return not any((self.job_title, self.company, self.description))

    @property
    def date_range(self) -> str:
        if self.start_date and self.end_date:
            return f"{self.start_date} \u2013 {self.end_date}"
        return self.start_date or self.end_date or ""


@dataclass(slots=True)
class ProjectEntry:
    name: str = ""
    description: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    link: str = ""
    start_date: str = ""
    end_date: str = ""
    raw_text: str = ""

    def is_empty(self) -> bool:
        return not any((self.name, self.description, self.technologies))

    @property
    def date_range(self) -> str:
        if self.start_date and self.end_date:
            return f"{self.start_date} \u2013 {self.end_date}"
        return self.start_date or self.end_date or ""


@dataclass(slots=True)
class SectionBlock:
    """A contiguous labelled region of the resume."""

    key: str
    heading: str
    lines: list[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #


@dataclass(slots=True)
class ParsedResume:
    """Everything the pipeline managed to learn about one resume."""

    contact: ContactInfo = field(default_factory=ContactInfo)
    summary: str = ""
    skills: list[Skill] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    experience: list[ExperienceEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)

    raw_text: str = ""
    extraction: ExtractionResult = field(default_factory=ExtractionResult)
    sections: list[SectionBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    parsed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )
    parser_version: str = APP_VERSION

    # -- derived helpers ---------------------------------------------------- #

    @property
    def detected_section_keys(self) -> list[str]:
        return [s.key for s in self.sections if s.key != "header"]

    def skills_by_category(self) -> dict[str, list[Skill]]:
        grouped: dict[str, list[Skill]] = {}
        for skill in self.skills:
            grouped.setdefault(skill.category, []).append(skill)
        return grouped

    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]

    def field_presence(self) -> dict[str, bool]:
        """Which headline fields were successfully detected."""
        return {
            "name": bool(self.contact.name),
            "email": bool(self.contact.email),
            "phone": bool(self.contact.phone),
            "location": bool(self.contact.location),
            "links": bool(self.contact.links),
            "skills": bool(self.skills),
            "education": bool(self.education),
            "experience": bool(self.experience),
            "projects": bool(self.projects),
        }

    def completeness(self) -> int:
        """Percentage of headline fields that were detected (0-100)."""
        presence = self.field_presence()
        tracked = [presence.get(name, False) for name in COMPLETENESS_FIELDS]
        if not tracked:
            return 0
        return round(100 * sum(tracked) / len(tracked))

    def to_dict(self) -> dict[str, Any]:
        """Plain-dict view (used by the exporters)."""
        return asdict(self)
