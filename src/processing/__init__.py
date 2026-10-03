"""Processing layer: plain text -> analysable structure.

Still resume-agnostic in spirit, but this is where the document's *shape* is
recovered: clean lines, labelled sections, normalised dates and an optional
spaCy document.
"""

from .dates import DateRange, find_date_range, find_years, mentions_current, strip_dates
from .nlp import Entity, NlpEngine, get_nlp_engine, reset_nlp_engine
from .normalize import (
    BULLET_PREFIX,
    collapse_whitespace,
    is_bullet,
    non_empty_lines,
    normalize_text,
    squash_separators,
    strip_bullet,
    to_lines,
)
from .sections import (
    LIST_SECTIONS,
    SECTION_ALIASES,
    looks_like_heading,
    match_section_key,
    normalize_heading,
    section_map,
    segment_sections,
)

__all__ = [
    "BULLET_PREFIX",
    "DateRange",
    "Entity",
    "LIST_SECTIONS",
    "NlpEngine",
    "SECTION_ALIASES",
    "collapse_whitespace",
    "find_date_range",
    "find_years",
    "get_nlp_engine",
    "is_bullet",
    "looks_like_heading",
    "match_section_key",
    "mentions_current",
    "non_empty_lines",
    "normalize_heading",
    "normalize_text",
    "reset_nlp_engine",
    "section_map",
    "segment_sections",
    "squash_separators",
    "strip_bullet",
    "strip_dates",
    "to_lines",
]
