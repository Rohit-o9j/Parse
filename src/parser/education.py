"""Education extraction.

An education entry is recognised by two anchors that are far more stable than
layout: a **degree** phrase and an **institution** phrase. The parser groups
the section's lines into entries around those anchors, then pulls the
remaining fields (field of study, years, grade, location) out of each group.

Degrees are matched through an explicit pattern table rather than a word list
because the spellings vary so much - ``B.Tech``, ``BTech``, ``B. Tech.``,
``Bachelor of Technology`` and ``Bachelors in Technology`` all mean one thing.
Any field the patterns cannot confirm is left blank; the UI shows
"Not detected" rather than a plausible-looking guess.
"""

from __future__ import annotations

import re
from typing import Sequence

from ..models import EducationEntry, SectionBlock
from ..processing.dates import find_date_range, find_years, is_valid_year
from ..processing.normalize import collapse_whitespace, is_bullet, strip_bullet
from .contact import is_known_place

# --------------------------------------------------------------------------- #
# Degree patterns
# --------------------------------------------------------------------------- #

#: Template for a written-out degree: the credential word plus an optional
#: "of <Subject>" tail that stops before " in ", " at " or a comma.
_WRITTEN_DEGREE = (
    r"\b{word}(?:\s+of\s+(?!the\b)[A-Za-z][\w.&/\-]*"
    r"(?:\s+(?!in\b|at\b|from\b)[A-Za-z][\w.&/\-]*){{0,3}})?"
)

#: ``(pattern, canonical_display)``; a ``None`` display keeps the matched text.
#: Ordered most specific first so "Master of Science" wins over "Master".
_DEGREE_PATTERNS: tuple[tuple[re.Pattern[str], str | None], ...] = (
    (re.compile(r"\bB\.?\s?Tech\b\.?", re.IGNORECASE), "B.Tech"),
    (re.compile(r"\bM\.?\s?Tech\b\.?", re.IGNORECASE), "M.Tech"),
    (re.compile(r"\bB\.?\s?E\.(?=\s|,|$)", re.IGNORECASE), "B.E."),
    (re.compile(r"\bM\.?\s?E\.(?=\s|,|$)", re.IGNORECASE), "M.E."),
    (re.compile(r"\bB\.?\s?Sc\b\.?", re.IGNORECASE), "B.Sc"),
    (re.compile(r"\bM\.?\s?Sc\b\.?", re.IGNORECASE), "M.Sc"),
    (re.compile(r"\bB\.?\s?C\.?\s?A\b\.?", re.IGNORECASE), "BCA"),
    (re.compile(r"\bM\.?\s?C\.?\s?A\b\.?", re.IGNORECASE), "MCA"),
    (re.compile(r"\bB\.?\s?B\.?\s?A\b\.?", re.IGNORECASE), "BBA"),
    (re.compile(r"\bM\.?\s?B\.?\s?A\b\.?", re.IGNORECASE), "MBA"),
    (re.compile(r"\bB\.?\s?Com\b\.?", re.IGNORECASE), "B.Com"),
    (re.compile(r"\bM\.?\s?Com\b\.?", re.IGNORECASE), "M.Com"),
    (re.compile(r"\bB\.?\s?Pharm\b\.?", re.IGNORECASE), "B.Pharm"),
    (re.compile(r"\bM\.?\s?Pharm\b\.?", re.IGNORECASE), "M.Pharm"),
    (re.compile(r"\bB\.?\s?Arch\b\.?", re.IGNORECASE), "B.Arch"),
    (re.compile(r"\bMBBS\b", re.IGNORECASE), "MBBS"),
    (re.compile(r"\bBDS\b", re.IGNORECASE), "BDS"),
    (re.compile(r"\bLL\.?\s?M\b\.?", re.IGNORECASE), "LL.M"),
    (re.compile(r"\bLL\.?\s?B\b\.?", re.IGNORECASE), "LL.B"),
    (re.compile(r"\bPh\.?\s?D\b\.?", re.IGNORECASE), "Ph.D."),
    # Written-out degrees. The "of <subject>" part belongs to the degree
    # name ("Bachelor of Science"), but an " in <subject>" part is the field
    # of study and is deliberately left outside the match so the two do not
    # end up duplicated across both columns of the card.
    (re.compile(_WRITTEN_DEGREE.format(word=r"Doctor(?:ate)?"), re.IGNORECASE), None),
    (re.compile(_WRITTEN_DEGREE.format(word=r"Bachelor(?:'?s)?"), re.IGNORECASE), None),
    (re.compile(_WRITTEN_DEGREE.format(word=r"Master(?:'?s)?"), re.IGNORECASE), None),
    (re.compile(_WRITTEN_DEGREE.format(word=r"Associate(?:'?s)?"), re.IGNORECASE), None),
    (
        re.compile(
            r"\bPost\s*Graduate\s+(?:Diploma|Programme|Program)\b", re.IGNORECASE
        ),
        None,
    ),
    (re.compile(r"\bDiploma\b", re.IGNORECASE), "Diploma"),
    (re.compile(r"\bHigher\s+Secondary(?:\s+Certificate)?\b", re.IGNORECASE), None),
    (re.compile(r"\bSenior\s+Secondary(?:\s+Certificate)?\b", re.IGNORECASE), None),
    (re.compile(r"\bSecondary\s+School(?:\s+Certificate)?\b", re.IGNORECASE), None),
    (re.compile(r"\bHigh\s+School(?:\s+Diploma)?\b", re.IGNORECASE), None),
    (re.compile(r"\bIntermediate\b", re.IGNORECASE), "Intermediate"),
    (re.compile(r"\bH\.?\s?S\.?\s?C\b\.?", re.IGNORECASE), "HSC"),
    (re.compile(r"\bS\.?\s?S\.?\s?C\b\.?", re.IGNORECASE), "SSC"),
    (
        re.compile(r"\b1[02](?:th|nd)\s*(?:grade|standard|class|std)?\b", re.IGNORECASE),
        None,
    ),
    (re.compile(r"\bC\.?B\.?S\.?E\b\.?", re.IGNORECASE), "CBSE"),
    (re.compile(r"\bI\.?C\.?S\.?E\b\.?", re.IGNORECASE), "ICSE"),
)

_INSTITUTION_KEYWORDS = (
    "university",
    "universidad",
    "college",
    "institute",
    "institution",
    "school",
    "academy",
    "polytechnic",
    "vidyalaya",
    "vidyapeeth",
    "mahavidyalaya",
    "gurukul",
    "seminary",
    "conservatory",
    "faculty of",
)

#: Matched case-sensitively and in full caps only: a lowercase "bits" is the
#: English word, "BITS" is the institute.
_INSTITUTION_ACRONYMS = (
    "IIT", "NIT", "IIIT", "IISc", "IIM", "BITS", "VIT", "SRM", "VJTI",
    "MIT", "UCLA", "NYU", "LSE", "ETH", "NUS", "NTU",
)

_INSTITUTION_RE = re.compile(r"\b(?:" + "|".join(_INSTITUTION_KEYWORDS) + r")\b", re.IGNORECASE)
_INSTITUTION_ACRONYM_RE = re.compile(r"\b(?:" + "|".join(_INSTITUTION_ACRONYMS) + r")\b")

# --------------------------------------------------------------------------- #
# Field of study / grade
# --------------------------------------------------------------------------- #

_FIELD_LABEL_RE = re.compile(
    r"\b(?:major|majors|specialis(?:ation|ed\s+in)|specializ(?:ation|ed\s+in)|branch|"
    r"stream|discipline|field\s+of\s+study|concentration)\s*[:\-\u2013]\s*([^,;|\n]{2,60})",
    re.IGNORECASE,
)

#: ``in Computer Science and Engineering`` / ``of Science``. Capitalised words
#: only, so it cannot run away into prose.
_FIELD_CONNECTOR_RE = re.compile(
    r"\b(in|of)\s+((?:[A-Z][\w.&\-]*)(?:\s+(?:[A-Z][\w.&\-]*|and|&|of|for))*)"
)

_GRADE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:CGPA|SGPA|GPA|CPI|OGPA)\b\s*(?:of\s*|:\s*|[-\u2013=]\s*)?"
        r"(\d{1,2}(?:\.\d{1,3})?)\s*(?:/\s*(\d{1,2}(?:\.\d{1,2})?))?",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:percentage|percent|marks|aggregate|score)\b\s*(?:of\s*|:\s*|[-\u2013=]\s*)?"
        r"(\d{1,3}(?:\.\d{1,2})?)\s*%?",
        re.IGNORECASE,
    ),
    re.compile(r"\b(\d{1,2}\.\d{1,2})\s*/\s*(10|10\.0|4|4\.0|5|5\.0)\b"),
    re.compile(r"\b(\d{2}(?:\.\d{1,2})?)\s*%"),
)

_HONOUR_RE = re.compile(
    r"\b(?:summa\s+cum\s+laude|magna\s+cum\s+laude|cum\s+laude|"
    r"first\s+class\s+with\s+distinction|first\s+class(?:\s+honours?)?|"
    r"second\s+class(?:\s+honours?)?|with\s+distinction|distinction|"
    r"honours?\s+degree|first\s+division|dean'?s\s+list)\b",
    re.IGNORECASE,
)

#: Course-detail lines that belong in ``details`` rather than a named field.
_DETAIL_LABEL_RE = re.compile(
    r"^\s*(?:relevant\s+)?(?:coursework|courses|subjects|modules|thesis|dissertation|"
    r"activities|societies|minor|electives)\b",
    re.IGNORECASE,
)

_LOCATION_TAIL_RE = re.compile(
    r",\s*([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2}(?:,\s*[A-Z]{2})?)\s*$"
)

#: Words that are never a field of study on their own.
#:
#: Deliberately short. Broad subject words such as "Science" or "Commerce"
#: belong here only if they can never be the real answer - and they can:
#: "Higher Secondary Certificate, Science" states Science as the stream. The
#: duplication this list used to guard against ("Bachelor of Science"
#: yielding field="Science") is now prevented structurally instead, because
#: the degree pattern absorbs its own "of <subject>" tail and only an
#: " in <subject>" phrase or a comma segment is read as the field.
_FIELD_STOPWORDS = frozenset({"the", "a", "an", "degree", "stream", "branch", "major"})


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def find_degree(text: str) -> tuple[str, tuple[int, int]] | None:
    """The earliest degree phrase in ``text`` as ``(display, span)``.

    Returns ``None`` when no pattern matches. Ties on position are broken by
    the longest match so "Bachelor of Science" beats "Bachelor".
    """
    best: tuple[int, int, str, tuple[int, int]] | None = None
    for pattern, display in _DEGREE_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue
        raw = collapse_whitespace(match.group(0)).strip(" ,.")
        if not raw:
            continue
        candidate = (
            match.start(),
            -(match.end() - match.start()),
            display or raw,
            match.span(),
        )
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    return best[2], best[3]


def looks_like_institution(text: str) -> bool:
    """True when ``text`` names an educational institution."""
    if not text:
        return False
    return bool(_INSTITUTION_RE.search(text) or _INSTITUTION_ACRONYM_RE.search(text))


def extract_education(
    text: str, sections: Sequence[SectionBlock] | None = None
) -> list[EducationEntry]:
    """Parse education entries from the resume.

    Uses the ``education`` section when one was detected, and otherwise scans
    the whole document for degree lines so the section still works on resumes
    with no headings at all.
    """
    block = _find_block(sections, "education")
    lines = list(block.lines) if block else _fallback_lines(text)
    if not lines:
        return []

    entries: list[EducationEntry] = []
    for group in _group_entries(lines):
        entry = _parse_entry(group)
        if entry is not None and not entry.is_empty():
            entries.append(entry)
    return entries


# --------------------------------------------------------------------------- #
# Grouping
# --------------------------------------------------------------------------- #


def _find_block(sections: Sequence[SectionBlock] | None, key: str) -> SectionBlock | None:
    for block in sections or []:
        if block.key == key:
            return block
    return None


def _fallback_lines(text: str) -> list[str]:
    """Lines around degree mentions, for resumes without an education heading."""
    all_lines = (text or "").splitlines()
    keep: set[int] = set()
    for index, line in enumerate(all_lines):
        if find_degree(line) or looks_like_institution(line):
            keep.update(range(max(0, index - 1), min(len(all_lines), index + 3)))
    return [all_lines[index] for index in sorted(keep)]


def _group_entries(lines: Sequence[str]) -> list[list[str]]:
    """Split education lines into one group per qualification.

    A new group starts on a blank line, or when a line introduces a degree or
    institution that the current group already has - that repetition is the
    signal a second qualification has begun.
    """
    groups: list[list[str]] = []
    current: list[str] = []
    has_degree = False
    has_institution = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current:
                groups.append(current)
                current, has_degree, has_institution = [], False, False
            continue

        line_degree = find_degree(line) is not None
        line_institution = looks_like_institution(line)
        bullet = is_bullet(raw_line)

        starts_new = bool(current) and not bullet and (
            (line_degree and has_degree) or (line_institution and has_institution)
        )
        if starts_new:
            groups.append(current)
            current, has_degree, has_institution = [], False, False

        current.append(line)
        has_degree = has_degree or line_degree
        has_institution = has_institution or line_institution

    if current:
        groups.append(current)
    return [group for group in groups if any(line.strip() for line in group)]


# --------------------------------------------------------------------------- #
# Field extraction
# --------------------------------------------------------------------------- #


def _parse_entry(group: Sequence[str]) -> EducationEntry | None:
    """Turn one group of lines into an :class:`EducationEntry`."""
    raw_text = "\n".join(group)
    entry = EducationEntry(raw_text=raw_text)

    degree_line_index = -1
    for index, line in enumerate(group):
        found = find_degree(line)
        if found:
            entry.degree = found[0]
            degree_line_index = index
            break

    # Prefer a dedicated institution line over the degree line.
    for index, line in enumerate(group):
        if index == degree_line_index and len(group) > 1:
            continue
        if looks_like_institution(line):
            institution, location = _split_location(strip_bullet(line))
            entry.institution = _clean_institution(institution)
            entry.location = location
            break

    # Degree and institution on one line: "B.Tech, NIT Surathkal".
    if not entry.institution and degree_line_index >= 0:
        degree_line = group[degree_line_index]
        remainder = _without_span(degree_line, find_degree(degree_line))
        if looks_like_institution(remainder):
            institution, location = _split_location(remainder)
            entry.institution = _clean_institution(institution)
            entry.location = location

    if not entry.institution:
        entry.institution = _guess_institution(group, degree_line_index)

    entry.field_of_study = _extract_field_of_study(group, entry.institution)
    entry.start_year, entry.end_year = _extract_years(raw_text)
    entry.grade = _extract_grade(raw_text)
    entry.details = _extract_details(group)
    return entry


def _extract_field_of_study(group: Sequence[str], institution: str) -> str:
    """Subject studied: explicit label, then "in X", then a comma segment.

    "of X" is deliberately *not* used as a source, because in
    "Bachelor of Science" the X is part of the degree name, not the subject.
    """
    joined = "\n".join(group)

    labelled = _FIELD_LABEL_RE.search(joined)
    if labelled:
        value = _clean_field(labelled.group(1))
        if _is_plausible_field(value, institution):
            return value

    degree_lines = [line for line in group if find_degree(line)]
    for line in degree_lines:
        for match in _FIELD_CONNECTOR_RE.finditer(line):
            if match.group(1).lower() != "in":
                continue
            value = _clean_field(match.group(2))
            if _is_plausible_field(value, institution):
                return value

    for line in degree_lines:
        found = find_degree(line)
        if not found:
            continue
        tail = line[found[1][1] :]
        for segment in tail.split(","):
            value = _clean_field(segment)
            if _is_plausible_field(value, institution):
                return value
    return ""


def _clean_field(text: str) -> str:
    """Tidy a candidate field of study, including "(Computer Science)" forms."""
    value = collapse_whitespace(text or "")
    bracketed = re.fullmatch(r"[(\[]\s*(.+?)\s*[)\]]", value)
    if bracketed:
        value = bracketed.group(1)
    return value.strip(" .,;:|()[]-\u2013")


def _is_plausible_field(value: str, institution: str) -> bool:
    """Reject institutions, places, dates and filler as a field of study."""
    if not value or len(value) > 70:
        return False
    if not 1 <= len(value.split()) <= 6:
        return False
    if not value[:1].isupper():
        return False
    if looks_like_institution(value) or find_degree(value):
        return False
    if is_known_place(value) or find_years(value):
        return False
    if value.lower() in _FIELD_STOPWORDS:
        return False
    if institution and value.lower() in institution.lower():
        return False
    return any(char.isalpha() for char in value)


def _extract_years(text: str) -> tuple[str, str]:
    """``(start_year, end_year)`` as plain strings, or blanks."""
    date_range = find_date_range(text)
    if date_range is not None:
        start = date_range.start_iso[:4]
        end = date_range.end_iso[:4]
        if date_range.is_current:
            return start, "Present"
        if start or end:
            return start, end

    years = sorted({year for year in find_years(text) if is_valid_year(year)})
    if len(years) >= 2:
        return str(years[0]), str(years[-1])
    if len(years) == 1:
        # A single year on an education entry is the graduation year.
        return "", str(years[0])
    return "", ""


def _extract_grade(text: str) -> str:
    """Grade, GPA or classification exactly as stated, or ``""``."""
    for pattern in _GRADE_PATTERNS:
        match = pattern.search(text or "")
        if not match:
            continue

        groups = match.groups()
        value = groups[0] if groups else ""
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue

        scale = groups[1] if len(groups) > 1 and groups[1] else ""
        label = collapse_whitespace(match.group(0))

        if scale:
            if numeric > float(scale):
                continue  # 12/10 is not a grade
            return label

        is_percentage = "%" in label or re.search(
            r"percent|marks|aggregate|score", label, re.IGNORECASE
        )
        if is_percentage:
            if not 0 < numeric <= 100:
                continue
        elif not 0 < numeric <= 10:
            continue
        return label

    honour = _HONOUR_RE.search(text or "")
    return collapse_whitespace(honour.group(0)).title() if honour else ""


def _extract_details(group: Sequence[str]) -> list[str]:
    """Supporting lines: coursework, thesis, societies."""
    details: list[str] = []
    for line in group:
        stripped = strip_bullet(line)
        if not stripped:
            continue
        if is_bullet(line) or _DETAIL_LABEL_RE.match(stripped):
            if find_degree(stripped) or looks_like_institution(stripped):
                continue
            details.append(collapse_whitespace(stripped))
    return details


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _guess_institution(group: Sequence[str], degree_line_index: int) -> str:
    """Last-resort guess: a title-case line that is nothing else we recognise."""
    for index, line in enumerate(group):
        if index == degree_line_index or is_bullet(line):
            continue
        candidate = strip_bullet(line)
        if not candidate or len(candidate) > 90:
            continue
        if find_degree(candidate) or _DETAIL_LABEL_RE.match(candidate):
            continue
        if _extract_grade(candidate):
            continue
        # Lines that are only dates or numbers are not institutions.
        if len(re.sub(r"[^A-Za-z]", "", candidate)) < 4:
            continue
        words = [word for word in candidate.split() if word[:1].isalpha()]
        if words and sum(word[:1].isupper() for word in words) >= max(1, len(words) - 1):
            institution, _location = _split_location(candidate)
            return _clean_institution(institution)
    return ""


def _split_location(text: str) -> tuple[str, str]:
    """Separate a trailing place name from an institution line."""
    candidate = collapse_whitespace(text).strip(" ,;|")
    match = _LOCATION_TAIL_RE.search(candidate)
    if match:
        tail = collapse_whitespace(match.group(1))
        head = candidate[: match.start()].strip(" ,;|")
        last_part = tail.split(",")[-1].strip()
        if head and (is_known_place(tail) or is_known_place(last_part)):
            return head, tail
    return candidate, ""


def _clean_institution(text: str) -> str:
    """Drop dates, grades and separators from an institution string."""
    candidate = collapse_whitespace(text)
    candidate = re.sub(
        r"\(?\b(?:19|20)\d{2}\b\s*(?:[\u2013-]\s*(?:(?:19|20)\d{2}|present))?\)?",
        " ",
        candidate,
        flags=re.IGNORECASE,
    )
    for pattern in _GRADE_PATTERNS:
        candidate = pattern.sub(" ", candidate)
    candidate = re.sub(r"\s*[|\u2022\u00b7]\s*", " ", candidate)
    return collapse_whitespace(candidate).strip(" ,;|-\u2013")


def _without_span(line: str, found: tuple[str, tuple[int, int]] | None) -> str:
    """``line`` with a matched degree span removed."""
    if not found:
        return line
    start, end = found[1]
    return collapse_whitespace(line[:start] + " " + line[end:]).strip(" ,;|-\u2013")
