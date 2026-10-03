"""Section segmentation.

Everything downstream depends on knowing *where* the education block ends and
the experience block begins, so this is the most important heuristic in the
project. A resume has no markup, only visual convention, and the convention we
can still see in extracted text is:

1. a short line,
2. containing a recognisable section word,
3. not written as a sentence,
4. optionally typeset in capitals or followed by a colon.

``segment_sections`` scores every line against those signals and splits the
document at the winners. Text above the first heading becomes the ``header``
block, which is where contact details live.

The alias table is deliberately data - adding a new heading spelling is a
one-line change and needs no code.
"""

from __future__ import annotations

import re

from ..models import SectionBlock
from .normalize import collapse_whitespace, is_bullet, to_lines

#: canonical key -> heading spellings seen in the wild.
SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "summary": (
        "summary",
        "professional summary",
        "career summary",
        "executive summary",
        "profile",
        "professional profile",
        "career profile",
        "personal profile",
        "about",
        "about me",
        "objective",
        "career objective",
        "professional objective",
        "summary of qualifications",
        "overview",
        "introduction",
    ),
    "skills": (
        "skills",
        "skill",
        "technical skills",
        "technical skill set",
        "technical skillset",
        "key skills",
        "core skills",
        "relevant skills",
        "professional skills",
        "it skills",
        "computer skills",
        "software skills",
        "technical expertise",
        "technical proficiency",
        "technical proficiencies",
        "technologies",
        "technology stack",
        "tech stack",
        "tools and technologies",
        "tools & technologies",
        "skills and tools",
        "skills & tools",
        "areas of expertise",
        "core competencies",
        "competencies",
        "expertise",
        "proficiencies",
        "skills summary",
        "skill highlights",
    ),
    "experience": (
        "experience",
        "work experience",
        "working experience",
        "professional experience",
        "employment",
        "employment history",
        "employment experience",
        "work history",
        "career history",
        "career experience",
        "relevant experience",
        "industry experience",
        "professional background",
        "work",
        "internship",
        "internships",
        "internship experience",
        "internships and experience",
        "experience and internships",
        "positions held",
        "professional experience and internships",
    ),
    "education": (
        "education",
        "educations",
        "academic",
        "academics",
        "academic background",
        "academic history",
        "academic qualifications",
        "academic qualification",
        "educational qualifications",
        "educational qualification",
        "educational background",
        "education and training",
        "education & training",
        "education details",
        "qualifications",
        "scholastic record",
        "academic details",
        "academic profile",
    ),
    "projects": (
        "projects",
        "project",
        "project work",
        "personal projects",
        "academic projects",
        "college projects",
        "key projects",
        "selected projects",
        "notable projects",
        "major projects",
        "side projects",
        "project experience",
        "projects undertaken",
        "technical projects",
        "portfolio",
        "capstone project",
    ),
    "certifications": (
        "certifications",
        "certification",
        "certificates",
        "certificate",
        "licenses",
        "licenses and certifications",
        "licenses & certifications",
        "certifications and licenses",
        "courses",
        "courses and certifications",
        "online courses",
        "relevant coursework",
        "coursework",
        "training",
        "trainings",
        "professional development",
        "professional certifications",
    ),
    "achievements": (
        "achievements",
        "achievement",
        "accomplishments",
        "key achievements",
        "awards",
        "awards and honors",
        "awards & honors",
        "awards and achievements",
        "honors",
        "honours",
        "honors and awards",
        "honours and awards",
        "recognition",
        "recognitions",
        "scholarships",
    ),
    "publications": (
        "publications",
        "publication",
        "papers",
        "research",
        "research experience",
        "research papers",
        "patents",
        "conferences",
    ),
    "languages": (
        "languages",
        "language",
        "languages known",
        "language proficiency",
        "languages and proficiency",
        "spoken languages",
    ),
    "interests": (
        "interests",
        "interest",
        "hobbies",
        "hobbies and interests",
        "hobbies & interests",
        "personal interests",
        "activities",
        "extracurricular",
        "extracurricular activities",
        "extra curricular activities",
        "co-curricular activities",
        "volunteering",
        "volunteer experience",
        "volunteer work",
        "community involvement",
        "leadership",
        "leadership and activities",
        "positions of responsibility",
    ),
    "contact": (
        "contact",
        "contact information",
        "contact details",
        "personal details",
        "personal information",
        "personal data",
        "details",
    ),
    "references": (
        "references",
        "reference",
        "referees",
    ),
    "declaration": (
        "declaration",
        "declarations",
    ),
}

#: Sections whose body is a simple list we surface verbatim.
LIST_SECTIONS: tuple[str, ...] = ("certifications", "achievements", "languages", "interests")

#: Longest heading we will consider, in words. Real headings are terse.
_MAX_HEADING_WORDS = 6

#: Longest heading we will consider, in characters.
_MAX_HEADING_CHARS = 60

#: Single words strong enough to label a section on their own. Used when
#: resolving compound headings like "Education & Certifications"; it keeps
#: unrelated headings such as "Work Authorization" from matching "work".
_STRONG_SINGLE_WORDS: frozenset[str] = frozenset(
    {
        "summary",
        "objective",
        "profile",
        "skills",
        "technologies",
        "expertise",
        "competencies",
        "experience",
        "employment",
        "internship",
        "internships",
        "education",
        "academics",
        "qualifications",
        "projects",
        "project",
        "portfolio",
        "certifications",
        "certificates",
        "courses",
        "coursework",
        "training",
        "achievements",
        "accomplishments",
        "awards",
        "honors",
        "honours",
        "publications",
        "patents",
        "research",
        "languages",
        "interests",
        "hobbies",
        "activities",
        "extracurricular",
        "volunteering",
        "leadership",
        "references",
        "declaration",
    }
)

#: Filler words that carry no sectional meaning of their own.
_CONNECTOR_WORDS: frozenset[str] = frozenset(
    {"and", "or", "of", "the", "my", "a", "an", "in", "details", "section", "info"}
)

_NON_ALNUM_RE = re.compile(r"[^a-z0-9&+ ]+")
_SPACE_RE = re.compile(r"\s+")
#: ``SKILLS: Python, Java`` - heading and content share a line.
_INLINE_HEADING_RE = re.compile(r"^\s*([A-Za-z][A-Za-z&/ .'\-]{1,40}?)\s*[:\u2013-]\s*(\S.*)$")
#: Decorative heading underlines such as ``=====`` or ``-----``.
_RULE_LINE_RE = re.compile(r"^[\s=_~*\u2013.\u2022\u00b7-]{3,}$")


def _canonical_form(text: str) -> str:
    """Lowercase, de-punctuate and de-decorate a heading candidate."""
    candidate = collapse_whitespace(text).lower()
    candidate = re.sub(r"^[\s\d.)\]}>#*\u2022\u00b7-]+", "", candidate)
    candidate = _NON_ALNUM_RE.sub(" ", candidate)
    candidate = candidate.replace("&", " and ").replace("+", " ")
    return _SPACE_RE.sub(" ", candidate).strip()


#: Built once from :data:`SECTION_ALIASES`, keyed by canonical form so the
#: table can be written in natural spelling ("Tools & Technologies").
_ALIAS_LOOKUP: dict[str, str] = {}
for _key, _aliases in SECTION_ALIASES.items():
    for _alias in _aliases:
        _ALIAS_LOOKUP.setdefault(_canonical_form(_alias), _key)
del _key, _aliases, _alias


def normalize_heading(text: str) -> str:
    """Reduce a line to its comparable heading form.

    Strips bullets, numbering, punctuation and decoration so that
    ``"3. TECHNICAL SKILLS:"`` and ``"Technical Skills"`` both become
    ``"technical skills"``. Trailing plurals are folded when that yields a
    known alias, so "Educations" resolves like "Education".
    """
    candidate = _canonical_form(text)
    if candidate and candidate not in _ALIAS_LOOKUP and candidate.endswith("s"):
        singular = candidate[:-1]
        if singular in _ALIAS_LOOKUP:
            return singular
    return candidate


def match_section_key(text: str) -> str | None:
    """Return the canonical section key for a heading line, or ``None``."""
    candidate = normalize_heading(text)
    if not candidate:
        return None

    direct = _ALIAS_LOOKUP.get(candidate)
    if direct:
        return direct

    words = candidate.split()
    if not 1 < len(words) <= _MAX_HEADING_WORDS:
        return None

    # Compound headings ("Education & Certifications", "Skills and Tools")
    # resolve to their longest recognised component.
    for size in range(len(words) - 1, 1, -1):
        for start in range(0, len(words) - size + 1):
            fragment = " ".join(words[start : start + size])
            if fragment in _ALIAS_LOOKUP:
                return _ALIAS_LOOKUP[fragment]

    # A single sectional word only wins when every *other* word is a
    # connector or is itself sectional. That is the difference between
    # "Education and Certifications" (a real compound heading) and
    # "Programming Languages" or "Technologies Used", which are skill-list
    # labels that merely contain a sectional word.
    sectional = [word for word in words if word in _STRONG_SINGLE_WORDS and word in _ALIAS_LOOKUP]
    if not sectional:
        return None
    unexplained = [
        word
        for word in words
        if word not in _CONNECTOR_WORDS and word not in _ALIAS_LOOKUP
    ]
    if unexplained:
        return None
    return _ALIAS_LOOKUP[sectional[0]]


def looks_like_heading(line: str) -> bool:
    """Shape test: could this line plausibly be a section heading?

    Independent of the alias table, so it can also guard other heuristics.
    """
    text = line.strip()
    if not text or is_bullet(line):
        return False
    if len(text) > _MAX_HEADING_CHARS:
        return False
    if len(text.split()) > _MAX_HEADING_WORDS:
        return False
    # Sentences and prose are not headings.
    if text.endswith((".", "!", "?", ",", ";")):
        return False
    if "@" in text or "http" in text.lower():
        return False
    # A heading is overwhelmingly letters; dates and metrics are not headings.
    letters = sum(char.isalpha() for char in text)
    digits = sum(char.isdigit() for char in text)
    if letters < 3 or digits > letters:
        return False
    return True


def segment_sections(text: str) -> list[SectionBlock]:
    """Split normalised resume text into labelled :class:`SectionBlock` items.

    The first block is always ``header`` (possibly empty) so callers can rely
    on its presence. Repeated headings of the same kind are merged, which
    handles templates that restart "Experience (continued)" on page two.
    """
    lines = to_lines(text)
    headings = _find_headings(lines)

    blocks: list[SectionBlock] = []
    header_end = headings[0][0] if headings else len(lines)
    blocks.append(
        SectionBlock(
            key="header",
            heading="",
            lines=_trim(lines[:header_end]),
            start_line=0,
            end_line=max(header_end - 1, 0),
        )
    )

    for position, (index, key, heading, inline_body) in enumerate(headings):
        next_index = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        body = list(lines[index + 1 : next_index])
        if inline_body:
            body.insert(0, inline_body)
        blocks.append(
            SectionBlock(
                key=key,
                heading=heading,
                lines=_trim(body),
                start_line=index,
                end_line=max(next_index - 1, index),
            )
        )

    return _merge_repeated(blocks)


def section_map(blocks: list[SectionBlock]) -> dict[str, SectionBlock]:
    """Index blocks by canonical key (first occurrence wins)."""
    mapping: dict[str, SectionBlock] = {}
    for block in blocks:
        mapping.setdefault(block.key, block)
    return mapping


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _find_headings(lines: list[str]) -> list[tuple[int, str, str, str]]:
    """Locate headings as ``(line_index, key, heading_text, inline_body)``."""
    found: list[tuple[int, str, str, str]] = []

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line or _RULE_LINE_RE.match(line):
            continue

        # Case 1: the whole line is a heading.
        if looks_like_heading(line):
            key = match_section_key(line)
            if key and _is_confident_heading(line, key, lines, index):
                found.append((index, key, line.rstrip(":").strip(), ""))
                continue

        # Case 2: heading and content share a line ("Skills: Python, SQL").
        inline = _INLINE_HEADING_RE.match(line)
        if inline:
            label, body = inline.group(1), inline.group(2)
            key = match_section_key(label)
            if key and len(label.split()) <= _MAX_HEADING_WORDS:
                found.append((index, key, label.strip(), body.strip()))

    return found


def _is_confident_heading(line: str, key: str, lines: list[str], index: int) -> bool:
    """Reject alias matches that are really body text.

    ``"Skills"`` on its own line is a heading. The same word inside
    ``"Skills were applied to reduce latency"`` is not - that case is already
    excluded by the word-count test, but single-word aliases such as ``"work"``
    or ``"details"`` still need a second opinion, which we take from
    typography and surrounding blank lines.
    """
    text = line.rstrip(":").strip()
    words = text.split()

    is_upper = text.upper() == text and any(char.isalpha() for char in text)
    is_title = all(word[:1].isupper() or not word[:1].isalpha() for word in words)
    had_colon = line.rstrip().endswith(":")
    blank_before = index == 0 or not lines[index - 1].strip()
    blank_after = index + 1 >= len(lines) or not lines[index + 1].strip()

    # Unambiguous multi-word headings ("Professional Experience") are safe.
    if len(words) > 1 and (is_upper or is_title or had_colon):
        return True

    # Single generic words need a stronger typographic signal.
    generic = {"work", "details", "about", "overview", "experience", "education",
               "skills", "projects", "summary", "profile", "languages", "interests",
               "activities", "training", "research", "contact"}
    if text.lower() in generic:
        return is_upper or had_colon or blank_before or blank_after or is_title

    return is_upper or is_title or had_colon


def _merge_repeated(blocks: list[SectionBlock]) -> list[SectionBlock]:
    """Fold later occurrences of a section into the first one."""
    merged: list[SectionBlock] = []
    index_by_key: dict[str, int] = {}

    for block in blocks:
        if block.key in index_by_key and block.key != "header":
            target = merged[index_by_key[block.key]]
            if block.lines:
                if target.lines:
                    target.lines.append("")
                target.lines.extend(block.lines)
                target.end_line = block.end_line
            continue
        index_by_key[block.key] = len(merged)
        merged.append(block)

    return merged


def _trim(lines: list[str]) -> list[str]:
    """Drop leading/trailing blank lines and decorative rules."""
    cleaned = [line for line in lines if not _RULE_LINE_RE.match(line.strip())]
    start, end = 0, len(cleaned)
    while start < end and not cleaned[start].strip():
        start += 1
    while end > start and not cleaned[end - 1].strip():
        end -= 1
    return cleaned[start:end]
