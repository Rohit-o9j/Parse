"""Work-experience extraction.

Experience blocks are the most visually driven part of a resume: the date
range is usually right-aligned, and title / company / location are separated
by whatever glyph the template author liked. Extraction therefore runs in a
fixed order that removes ambiguity one step at a time:

1. **Split into entries.** A non-bullet line carrying a date range starts a new
   role; so does a new title-looking line once the current role already has
   bullets. Bullets always belong to the role above them.
2. **Lift the dates out** of the entry's header lines and remember them. What
   remains is pure title/company/location text.
3. **Split the remainder** on ``|``, ``-``, ``,``, ``at`` and ``@``.
4. **Classify each fragment** using legal-entity suffixes (Inc, Pvt Ltd, GmbH),
   a job-title vocabulary, and location shapes. spaCy's ``ORG`` tags break
   remaining ties.
5. **Order chronologically**, newest first, with ongoing roles at the top.

Description bullets are preserved as a list so the UI can render them as a
timeline without re-parsing text.
"""

from __future__ import annotations

import re
from typing import Any, Sequence

from ..models import ExperienceEntry, SectionBlock
from ..processing.dates import DateRange, find_date_range, strip_dates
from ..processing.nlp import NlpEngine
from ..processing.normalize import collapse_whitespace, is_bullet, squash_separators, strip_bullet
from .blocks import merge_wrapped_lines
from .contact import is_known_place, is_us_state_code

# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #

#: Words that identify a fragment as a job title.
_TITLE_KEYWORDS = (
    "engineer", "developer", "programmer", "analyst", "scientist", "architect",
    "administrator", "consultant", "designer", "manager", "director", "officer",
    "executive", "president", "founder", "co-founder", "lead", "head", "chief",
    "specialist", "coordinator", "supervisor", "technician", "researcher",
    "associate", "assistant", "intern", "trainee", "apprentice", "fellow",
    "volunteer", "teacher", "professor", "lecturer", "tutor", "instructor",
    "accountant", "auditor", "recruiter", "marketer", "strategist", "writer",
    "editor", "copywriter", "producer", "operator", "representative", "agent",
    "advisor", "adviser", "partner", "principal", "owner", "freelancer",
    "sde", "sdet", "swe", "devops", "sre", "qa", "cto", "ceo", "cfo", "coo",
    "vp", "evp", "svp", "pm", "tpm", "em",
)
_TITLE_MODIFIERS = (
    "senior", "junior", "sr", "jr", "staff", "principal", "lead", "chief",
    "graduate", "trainee", "summer", "winter", "software", "full", "stack",
    "frontend", "backend", "front", "back", "data", "machine", "learning",
    "cloud", "mobile", "web", "product", "project", "program", "business",
    "systems", "network", "security", "quality", "technical", "ii", "iii", "i",
)

_TITLE_RE = re.compile(r"\b(?:" + "|".join(_TITLE_KEYWORDS) + r")s?\b", re.IGNORECASE)

#: Legal-entity markers. Unambiguous wherever they appear in a fragment.
#: Deliberately excludes short foreign forms that collide with English words
#: ("as", "ab", "sa", "oy", "co"), which would otherwise fire inside prose.
_LEGAL_SUFFIXES = (
    "inc", "llc", "l.l.c", "ltd", "limited", "pvt", "private", "plc", "corp",
    "corporation", "co.", "company", "gmbh", "aps", "srl", "s.p.a", "pty", "llp",
)

#: Descriptive organisation words. These only indicate a company when they
#: *end* the fragment: "Brightline Analytics" is an employer, but
#: "Senior Software Engineer" is a job title that merely contains one.
_DESCRIPTIVE_SUFFIXES = (
    "group", "holdings", "ventures", "technologies", "technology", "solutions",
    "systems", "software", "labs", "laboratories", "consulting", "consultancy",
    "services", "studio", "studios", "agency", "partners", "associates",
    "industries", "enterprises", "bank", "capital", "foundation", "trust",
    "institute", "university", "college", "hospital", "clinic", "media",
    "networks", "analytics", "innovations", "infotech", "informatics",
)

_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(suffix) for suffix in _LEGAL_SUFFIXES) + r")\b\.?",
    re.IGNORECASE,
)
_DESCRIPTIVE_TAIL_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(suffix) for suffix in _DESCRIPTIVE_SUFFIXES) + r")\b\.?\s*$",
    re.IGNORECASE,
)


def _has_company_marker(fragment: str) -> bool:
    """True when a fragment carries any organisation signal."""
    return bool(_LEGAL_SUFFIX_RE.search(fragment) or _DESCRIPTIVE_TAIL_RE.search(fragment))

#: Fragment separators, in priority order.
_PRIMARY_SPLIT_RE = re.compile(r"\s*[|\u2022\u00b7]\s*|\s+[\u2013]\s+|\s+-\s+")
_SECONDARY_SPLIT_RE = re.compile(r"\s*,\s*")
_AT_SPLIT_RE = re.compile(r"\s+(?:at|@|with|for)\s+", re.IGNORECASE)

_REMOTE_RE = re.compile(r"^\s*(?:remote|hybrid|on[\s-]?site|work\s+from\s+home)\s*$", re.IGNORECASE)
_CITY_STATE_RE = re.compile(r"^[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2},\s*[A-Z]{2}$")
_EMPLOYMENT_TYPE_RE = re.compile(
    r"^\s*(?:full[\s-]?time|part[\s-]?time|contract|freelance|internship|intern|"
    r"temporary|permanent|seasonal|co[\s-]?op)\s*$",
    re.IGNORECASE,
)

#: Maximum leading non-bullet lines treated as an entry's header.
_MAX_HEADER_LINES = 3


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def extract_experience(
    text: str,
    sections: Sequence[SectionBlock] | None = None,
    nlp: NlpEngine | None = None,
    nlp_doc: Any | None = None,
) -> list[ExperienceEntry]:
    """Parse work-experience entries, newest first."""
    block = _find_block(sections, "experience")
    if block is None or not block.lines:
        return []

    org_names = _org_names(block.text, nlp, nlp_doc)
    lines = merge_wrapped_lines(block.lines)

    entries: list[ExperienceEntry] = []
    for group in _group_entries(lines):
        entry = _parse_entry(group, org_names)
        if entry is not None and not entry.is_empty():
            entries.append(entry)

    return _sort_chronologically(entries)


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #


def _find_block(sections: Sequence[SectionBlock] | None, key: str) -> SectionBlock | None:
    for block in sections or []:
        if block.key == key:
            return block
    return None


def _group_entries(lines: Sequence[str]) -> list[list[str]]:
    """Split experience lines into one group per role."""
    groups: list[list[str]] = []
    current: list[str] = []
    seen_bullet = False
    seen_dates = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        bullet = is_bullet(raw_line)
        has_dates = not bullet and find_date_range(line) is not None

        if current and not bullet:
            # A second date range, or a header line after the bullets have
            # started, means the previous role has ended.
            if (has_dates and seen_dates) or seen_bullet:
                groups.append(current)
                current, seen_bullet, seen_dates = [], False, False

        current.append(raw_line)
        seen_bullet = seen_bullet or bullet
        seen_dates = seen_dates or has_dates

    if current:
        groups.append(current)
    return groups


# --------------------------------------------------------------------------- #
# Entry parsing
# --------------------------------------------------------------------------- #


def _parse_entry(group: Sequence[str], org_names: set[str]) -> ExperienceEntry | None:
    """Turn one group of lines into an :class:`ExperienceEntry`."""
    raw_text = "\n".join(line.strip() for line in group if line.strip())
    if not raw_text:
        return None

    header_lines: list[str] = []
    description: list[str] = []
    for raw_line in group:
        line = raw_line.strip()
        if not line:
            continue
        if is_bullet(raw_line) or description or len(header_lines) >= _MAX_HEADER_LINES:
            body = strip_bullet(line)
            if body:
                description.append(collapse_whitespace(body))
        else:
            header_lines.append(line)

    entry = ExperienceEntry(raw_text=raw_text, description=description)

    date_range = _first_date_range(header_lines) or find_date_range(raw_text)
    if date_range is not None:
        entry.start_date = date_range.start_text
        entry.end_date = date_range.end_text
        entry.is_current = date_range.is_current
        entry._sort_key = date_range.sort_key

    fragments = _fragments(header_lines)
    _assign_fragments(entry, fragments, org_names)
    return entry


def _first_date_range(header_lines: Sequence[str]) -> DateRange | None:
    for line in header_lines:
        found = find_date_range(line)
        if found is not None:
            return found
    return None


def _fragments(header_lines: Sequence[str]) -> list[str]:
    """Date-free title/company/location fragments from the header lines."""
    fragments: list[str] = []
    for line in header_lines:
        cleaned = squash_separators(strip_dates(strip_bullet(line)))
        if not cleaned:
            continue
        for part in _split_fragment(cleaned):
            value = collapse_whitespace(part).strip(" .,;:|-\u2013")
            if value:
                fragments.append(value)
    return fragments


def _split_fragment(text: str) -> list[str]:
    """Split one header line into candidate fragments."""
    parts: list[str] = []
    for primary in _PRIMARY_SPLIT_RE.split(text):
        primary = primary.strip()
        if not primary:
            continue
        for secondary in _AT_SPLIT_RE.split(primary):
            secondary = secondary.strip()
            if not secondary:
                continue
            pieces = [p.strip() for p in _SECONDARY_SPLIT_RE.split(secondary) if p.strip()]
            parts.extend(_rejoin_city_state(pieces))
    return parts


def _rejoin_city_state(pieces: Sequence[str]) -> list[str]:
    """Undo a comma split that broke "Austin, TX" or "Pune, India" apart.

    Only joins when the left-hand piece is itself place-like, so
    "Zeta Payments Pvt Ltd, Bengaluru" is left as two fragments: the employer
    and its city.
    """
    result: list[str] = []
    index = 0
    while index < len(pieces):
        piece = pieces[index]
        nxt = pieces[index + 1] if index + 1 < len(pieces) else ""
        no_company_suffix = not _has_company_marker(piece)
        left_is_place = is_known_place(piece) and no_company_suffix
        right_is_place = bool(nxt) and is_known_place(nxt)
        # "Bellevue, WA": an unlisted city is still unambiguous next to a
        # US state code.
        city_state_shape = (
            is_us_state_code(nxt)
            and no_company_suffix
            and piece[:1].isupper()
            and 1 <= len(piece.split()) <= 3
        )

        if (left_is_place and right_is_place) or city_state_shape:
            combined = f"{piece}, {nxt}"
            # Absorb a third component ("Bengaluru, Karnataka, India").
            after = pieces[index + 2] if index + 2 < len(pieces) else ""
            if after and is_known_place(after):
                combined = f"{combined}, {after}"
                index += 1
            result.append(combined)
            index += 2
            continue
        result.append(piece)
        index += 1
    return result


def _assign_fragments(
    entry: ExperienceEntry, fragments: Sequence[str], org_names: set[str]
) -> None:
    """Classify fragments into job title, company and location.

    Scoring rather than a chain of ``if`` tests, because the signals overlap:
    "Senior Software Engineer" contains an organisation word ("Software") and
    "Engineering Solutions Ltd" contains a title word ("Engineering"). The
    stronger signal has to win, not whichever test happens to run first.
    """
    remaining: list[str] = []

    for fragment in fragments:
        if _EMPLOYMENT_TYPE_RE.match(fragment):
            continue
        if not entry.location and _is_location(fragment):
            entry.location = fragment
            continue
        remaining.append(fragment)

    titles: list[str] = []
    companies: list[str] = []
    unknown: list[str] = []
    for fragment in remaining:
        title_score = _title_score(fragment)
        company_score = _company_score(fragment, org_names)
        if title_score > company_score:
            titles.append(fragment)
        elif company_score > title_score:
            companies.append(fragment)
        else:
            unknown.append(fragment)

    if titles:
        entry.job_title = titles[0]
    if companies:
        entry.company = companies[0]

    # Resumes overwhelmingly write title before company, so document order
    # fills whichever slot is still empty.
    leftovers = unknown + titles[1:] + companies[1:]
    if not entry.job_title and leftovers:
        entry.job_title = leftovers.pop(0)
    if not entry.company and leftovers:
        entry.company = leftovers.pop(0)
    if not entry.location and leftovers and _is_location(leftovers[0]):
        entry.location = leftovers[0]


def _title_score(fragment: str) -> int:
    """How strongly a fragment reads like a job title (0 = not at all)."""
    if not fragment or len(fragment) > 70:
        return 0
    words = [word.lower().strip(".,") for word in fragment.split()]
    if not words or len(words) > 7:
        return 0

    score = 0
    if _TITLE_RE.search(fragment):
        score += 4
    # A title word at the end ("... Engineer", "... Intern") is the strongest
    # shape; a company name rarely ends in a role noun.
    if words and _TITLE_RE.fullmatch(words[-1]):
        score += 3
    score += sum(1 for word in words if word in _TITLE_MODIFIERS)
    return score if score >= 4 else 0


def _company_score(fragment: str, org_names: set[str]) -> int:
    """How strongly a fragment reads like an employer name (0 = not at all)."""
    if not fragment or len(fragment) > 80:
        return 0
    if _is_location(fragment):
        return 0

    score = 0
    if _LEGAL_SUFFIX_RE.search(fragment):
        score += 7
    if _DESCRIPTIVE_TAIL_RE.search(fragment):
        score += 5
    if fragment.lower() in org_names:
        score += 4

    words = [word for word in fragment.split() if word[:1].isalpha()]
    if words and len(words) <= 6 and all(word[:1].isupper() for word in words):
        # A capitalised proper-noun phrase with no role vocabulary at all.
        score += 1 if _TITLE_RE.search(fragment) else 4
    return score


def _is_location(fragment: str) -> bool:
    """True when a fragment is a place rather than an organisation."""
    if not fragment or len(fragment) > 60:
        return False
    if _REMOTE_RE.match(fragment):
        return True
    if _CITY_STATE_RE.match(fragment):
        return True
    if _has_company_marker(fragment):
        return False
    parts = [part.strip() for part in fragment.split(",") if part.strip()]
    if not parts:
        return False
    return all(is_known_place(part) for part in parts)


def _org_names(text: str, nlp: NlpEngine | None, nlp_doc: Any | None) -> set[str]:
    """Lowercased ORG entity strings, used as a tie-breaker."""
    if nlp is None:
        return set()
    entities = (
        NlpEngine.entities_from_doc(nlp_doc, ["ORG"])
        if nlp_doc is not None
        else nlp.entities(text, ["ORG"])
    )
    return {entity.text.strip().lower() for entity in entities if entity.text.strip()}


def _sort_chronologically(entries: Sequence[ExperienceEntry]) -> list[ExperienceEntry]:
    """Newest first; entries without dates keep their document order at the end."""
    dated = [entry for entry in entries if entry._sort_key]
    undated = [entry for entry in entries if not entry._sort_key]
    dated.sort(key=lambda entry: entry._sort_key, reverse=True)
    return dated + undated
