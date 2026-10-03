"""The parsing pipeline.

Single entry point for the UI and for tests. It runs five named stages and
reports progress through a callback, which is what drives the staged
processing view in the app:

====  ========================  =================================================
1     ``upload``                validate the file (type, size, emptiness)
2     ``extract``               PDF/DOCX -> raw text
3     ``analyze``               normalise text, segment sections, run spaCy
4     ``structure``             contact, skills, education, experience, projects
5     ``finalize``              diagnostics, warnings, completeness
====  ========================  =================================================

The pipeline never raises for a *parsing* problem: a resume with no detectable
education simply produces an empty list and a warning. It only raises
:class:`~src.extraction.errors.ExtractionError` when the document itself
cannot be read, because that is the one case the user must act on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from ..extraction import extract_text
from ..models import ExtractionResult, ParsedResume, SectionBlock
from ..processing.nlp import NlpEngine, get_nlp_engine
from ..processing.normalize import collapse_whitespace, normalize_text, strip_bullet
from ..processing.sections import LIST_SECTIONS, section_map, segment_sections
from ..settings import NLP_CHAR_BUDGET
from .contact import extract_contact
from .education import extract_education
from .experience import extract_experience
from .projects import extract_projects
from .skills import SkillDictionary, extract_skills, get_skill_dictionary


@dataclass(frozen=True, slots=True)
class Stage:
    """One user-visible step of the pipeline."""

    key: str
    label: str


#: Ordered, and rendered verbatim by the processing view.
STAGES: tuple[Stage, ...] = (
    Stage("upload", "File uploaded"),
    Stage("extract", "Extracting text"),
    Stage("analyze", "Analyzing content"),
    Stage("structure", "Structuring information"),
    Stage("finalize", "Preparing results"),
)

#: ``callback(stage_key, index, total)`` - called as each stage *completes*.
ProgressCallback = Callable[[str, int, int], None]

_SUMMARY_MAX_CHARS = 900


class ResumeParser:
    """Reusable parser. Construct once and parse many documents.

    The spaCy engine and skill dictionary are loaded once and shared, which
    matters because model loading dominates the cost of a single parse.
    """

    def __init__(
        self,
        nlp: NlpEngine | None = None,
        dictionary: SkillDictionary | None = None,
        use_nlp: bool = True,
    ) -> None:
        self._explicit_nlp = nlp
        self._use_nlp = use_nlp
        self._dictionary = dictionary

    # -- lazy resources ----------------------------------------------------- #

    @property
    def nlp(self) -> NlpEngine | None:
        if not self._use_nlp:
            return None
        if self._explicit_nlp is None:
            self._explicit_nlp = get_nlp_engine()
        return self._explicit_nlp

    @property
    def dictionary(self) -> SkillDictionary:
        if self._dictionary is None:
            self._dictionary = get_skill_dictionary()
        return self._dictionary

    # -- public API --------------------------------------------------------- #

    def parse_file(
        self,
        data: bytes,
        file_name: str = "",
        progress: ProgressCallback | None = None,
    ) -> ParsedResume:
        """Parse uploaded bytes end to end.

        Raises:
            ExtractionError: the document could not be read at all.
        """
        total = len(STAGES)
        _report(progress, "upload", 1, total)

        extraction = extract_text(data, file_name)
        _report(progress, "extract", 2, total)

        return self._parse_extraction(extraction, progress=progress, total=total)

    def parse_text(
        self,
        text: str,
        file_name: str = "pasted-text.txt",
        progress: ProgressCallback | None = None,
    ) -> ParsedResume:
        """Parse text that has already been extracted (tests, plain-text input)."""
        extraction = ExtractionResult(
            text=text or "",
            file_name=file_name,
            file_type="txt",
            file_size_bytes=len((text or "").encode("utf-8")),
            metadata={"extractor": "plain text"},
        )
        total = len(STAGES)
        _report(progress, "upload", 1, total)
        _report(progress, "extract", 2, total)
        return self._parse_extraction(extraction, progress=progress, total=total)

    # -- internals ---------------------------------------------------------- #

    def _parse_extraction(
        self,
        extraction: ExtractionResult,
        progress: ProgressCallback | None,
        total: int,
    ) -> ParsedResume:
        # Stage 3: analyse.
        normalised = normalize_text(extraction.text)
        sections = segment_sections(normalised)
        nlp = self.nlp
        nlp_doc = nlp.analyze(normalised) if nlp is not None and nlp.available else None
        _report(progress, "analyze", 3, total)

        # Stage 4: structure.
        resume = ParsedResume(
            raw_text=extraction.text,
            extraction=extraction,
            sections=sections,
        )
        resume.contact = extract_contact(
            normalised,
            sections=sections,
            nlp=nlp,
            nlp_doc=nlp_doc,
            embedded_links=extraction.embedded_links,
        )
        resume.summary = _extract_summary(sections)
        resume.skills = extract_skills(
            normalised, sections=sections, dictionary=self.dictionary, nlp=nlp
        )
        resume.education = extract_education(normalised, sections=sections)
        resume.experience = extract_experience(
            normalised, sections=sections, nlp=nlp, nlp_doc=nlp_doc
        )
        resume.projects = extract_projects(
            normalised, sections=sections, dictionary=self.dictionary
        )
        for key in LIST_SECTIONS:
            items = _extract_list_section(sections, key)
            if key == "certifications":
                resume.certifications = items
            elif key == "achievements":
                resume.achievements = items
            elif key == "languages":
                resume.languages = items
        _report(progress, "structure", 4, total)

        # Stage 5: finalise.
        resume.warnings = _collect_warnings(resume, extraction, normalised, nlp)
        resume.diagnostics = _build_diagnostics(resume, extraction, normalised, nlp)
        _report(progress, "finalize", 5, total)
        return resume


def parse_resume(
    data: bytes, file_name: str = "", progress: ProgressCallback | None = None
) -> ParsedResume:
    """Convenience wrapper around :class:`ResumeParser` for one-off parses."""
    return ResumeParser().parse_file(data, file_name=file_name, progress=progress)


# --------------------------------------------------------------------------- #
# Stage helpers
# --------------------------------------------------------------------------- #


def _report(callback: ProgressCallback | None, key: str, index: int, total: int) -> None:
    if callback is None:
        return
    try:
        callback(key, index, total)
    except Exception:  # pragma: no cover - UI callbacks must never break parsing
        pass


def _extract_summary(sections: Sequence[SectionBlock]) -> str:
    """The professional summary / objective text, trimmed for display."""
    mapping = section_map(list(sections))
    block = mapping.get("summary")
    if block is None or not block.lines:
        return ""
    text = collapse_whitespace(" ".join(strip_bullet(line) for line in block.lines))
    if len(text) > _SUMMARY_MAX_CHARS:
        text = text[:_SUMMARY_MAX_CHARS].rsplit(" ", 1)[0] + "\u2026"
    return text


def _extract_list_section(sections: Sequence[SectionBlock], key: str) -> list[str]:
    """Flatten a simple list section (certifications, awards, languages)."""
    mapping = section_map(list(sections))
    block = mapping.get(key)
    if block is None:
        return []

    items: list[str] = []
    for line in block.lines:
        body = strip_bullet(line).strip()
        if not body:
            continue
        # One-per-line is the norm; comma lists appear for languages.
        if key == "languages" and "," in body:
            items.extend(
                collapse_whitespace(part) for part in body.split(",") if part.strip()
            )
        else:
            items.append(collapse_whitespace(body))

    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        marker = item.lower()
        if marker not in seen:
            seen.add(marker)
            unique.append(item)
    return unique


def _collect_warnings(
    resume: ParsedResume,
    extraction: ExtractionResult,
    normalised: str,
    nlp: NlpEngine | None,
) -> list[str]:
    """Non-fatal issues worth telling the user about."""
    warnings = list(extraction.warnings)

    detected = set(resume.detected_section_keys)
    if not detected:
        warnings.append(
            "No section headings were recognised, so fields were extracted from the "
            "document as a whole. Results may be less precise."
        )
    else:
        for key, label in (
            ("skills", "skills"),
            ("experience", "work experience"),
            ("education", "education"),
        ):
            if key not in detected:
                warnings.append(f"No {label} section was found in this resume.")

    if not resume.contact.name:
        warnings.append("Could not identify the candidate's name with confidence.")
    if not resume.contact.email and not resume.contact.phone:
        warnings.append("No email address or phone number was detected.")

    word_count = len(normalised.split())
    if word_count < 80:
        warnings.append(
            f"Only {word_count} words of text were extracted; the document may be "
            "mostly images or very sparse."
        )

    if nlp is None:
        warnings.append("NLP analysis was disabled; only regex extraction was used.")
    elif not nlp.available:
        warnings.append(
            "spaCy model unavailable, so name and location detection fell back to "
            "pattern matching. Run: python -m spacy download en_core_web_sm"
        )

    if len(normalised) > NLP_CHAR_BUDGET:
        warnings.append(
            f"Document is long ({len(normalised):,} characters); NLP analysis was "
            f"limited to the first {NLP_CHAR_BUDGET:,} characters."
        )

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for warning in warnings:
        if warning not in seen:
            seen.add(warning)
            unique.append(warning)
    return unique


def _build_diagnostics(
    resume: ParsedResume,
    extraction: ExtractionResult,
    normalised: str,
    nlp: NlpEngine | None,
) -> dict[str, Any]:
    """Everything the explainability panel needs."""
    return {
        "file_name": extraction.file_name,
        "file_type": extraction.file_type,
        "file_size_kb": round(extraction.file_size_bytes / 1024, 1),
        "page_count": extraction.page_count,
        "character_count": len(normalised),
        "word_count": len(normalised.split()),
        "line_count": len([line for line in normalised.splitlines() if line.strip()]),
        "bullet_count": len(re.findall(r"^-\s", normalised, re.MULTILINE)),
        "sections_detected": resume.detected_section_keys,
        "section_headings": {
            block.key: block.heading for block in resume.sections if block.heading
        },
        "counts": {
            "skills": len(resume.skills),
            "education": len(resume.education),
            "experience": len(resume.experience),
            "projects": len(resume.projects),
            "certifications": len(resume.certifications),
            "achievements": len(resume.achievements),
            "languages": len(resume.languages),
        },
        "field_presence": resume.field_presence(),
        "completeness": resume.completeness(),
        "nlp": nlp.status() if nlp is not None else {"available": False, "model": None},
        "extraction_metadata": extraction.metadata,
        "embedded_link_count": len(extraction.embedded_links),
    }
