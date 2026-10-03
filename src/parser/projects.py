"""Project extraction.

Projects are kept strictly separate from professional experience: they come
from the ``projects`` section only, never inferred from job history.

Three layouts cover almost every resume, and all three are handled:

1. ``Project Name | Python, Flask, Docker`` followed by bullets - the tail
   after the pipe is an inline technology list.
2. ``Project Name (2023)`` followed by prose and a ``Technologies:`` line.
3. ``Project Name - one line description`` as a single bullet per project.

Technologies are resolved against the same configurable skill dictionary the
skills section uses, so a project's stack and the candidate's skill tags stay
consistent. An explicit ``Technologies:`` label always wins over inference.
"""

from __future__ import annotations

import re
from typing import Sequence

from ..models import ProjectEntry, SectionBlock
from ..processing.dates import find_date_range, strip_dates
from ..processing.normalize import collapse_whitespace, is_bullet, strip_bullet
from .blocks import is_mostly_dates, merge_wrapped_lines
from .skills import SkillDictionary, get_skill_dictionary

#: ``Technologies: Python, Flask`` / ``Tech stack - Go`` / ``Built with React``.
#: Matched with ``search`` rather than ``match`` because the label frequently
#: follows a sentence: "...tracker for Airflow DAGs. Technologies: Python".
_TECH_LABEL_RE = re.compile(
    r"\b(?:technolog(?:y|ies)|tech\s*stack|tech|stack|tools?|built\s+with|"
    r"skills?\s+used|languages?|frameworks?|libraries)\b"
    r"\s*(?:used)?\s*(?::|\u2013|\s-\s)\s*(.+)$",
    re.IGNORECASE,
)

#: A URL anywhere in the entry becomes the project link.
_URL_RE = re.compile(r"(?:https?://|www\.)[\w\-]+(?:\.[\w\-]+)+(?:/[\w\-./%?=&#+~]*)?", re.IGNORECASE)

_ITEM_SPLIT_RE = re.compile(r"[,;/|]+")

#: Longest line we will accept as a project title.
_MAX_TITLE_CHARS = 90
_MAX_TITLE_WORDS = 12

#: Trailing noise on a title line: "(2023)", "- 2023", "| Jan 2022".
_TRAILING_PARENS_RE = re.compile(r"\s*\([^)]*\)\s*$")

_ROLE_NOISE_RE = re.compile(
    r"^\s*(?:project|title|name)\s*[:\u2013-]\s*", re.IGNORECASE
)


def extract_projects(
    text: str,
    sections: Sequence[SectionBlock] | None = None,
    dictionary: SkillDictionary | None = None,
) -> list[ProjectEntry]:
    """Parse the projects section into structured entries."""
    block = _find_block(sections, "projects")
    if block is None or not block.lines:
        return []

    vocabulary = dictionary or get_skill_dictionary()
    lines = merge_wrapped_lines(block.lines)

    entries: list[ProjectEntry] = []
    for group in _group_entries(lines):
        entry = _parse_entry(group, vocabulary)
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


def _group_entries(lines: Sequence[str]) -> list[list[str]]:
    """Split project lines into one group per project.

    A blank line always separates projects. Otherwise a new group starts at a
    non-bullet title-shaped line once the current group has any body content,
    which is what distinguishes "next project" from "second line of this one".
    """
    populated = [line for line in lines if line.strip()]
    if populated and all(is_bullet(line) for line in populated):
        # "- Project A: ...", "- Project B: ..." - one project per bullet.
        return [[line] for line in populated]

    groups: list[list[str]] = []
    current: list[str] = []
    has_body = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if current:
                groups.append(current)
                current, has_body = [], False
            continue

        bullet = is_bullet(raw_line)
        if current and not bullet and has_body and _looks_like_title(line):
            groups.append(current)
            current, has_body = [], False

        current.append(raw_line)
        has_body = has_body or bullet or len(current) > 1

    if current:
        groups.append(current)
    return groups


def _looks_like_title(line: str) -> bool:
    """True when a line reads like a project title rather than prose."""
    text = collapse_whitespace(strip_bullet(line))
    if not text or len(text) > _MAX_TITLE_CHARS:
        return False
    if _TECH_LABEL_RE.match(text) or is_mostly_dates(text):
        return False
    if text.endswith((".", "!", "?")):
        return False
    words = text.split()
    if len(words) > _MAX_TITLE_WORDS:
        return False
    # Titles are capitalised; prose continuations are not.
    return bool(text[:1].isupper() or text[:1].isdigit())


# --------------------------------------------------------------------------- #
# Entry parsing
# --------------------------------------------------------------------------- #


def _parse_entry(group: Sequence[str], vocabulary: SkillDictionary) -> ProjectEntry | None:
    raw_text = "\n".join(line.strip() for line in group if line.strip())
    if not raw_text:
        return None

    entry = ProjectEntry(raw_text=raw_text)
    description: list[str] = []
    technologies: list[str] = []
    title_taken = False

    for raw_line in group:
        line = raw_line.strip()
        if not line:
            continue
        body = strip_bullet(line)

        # Lift an inline technology list out of the line, wherever it sits.
        labelled = _TECH_LABEL_RE.search(body)
        if labelled:
            technologies.extend(_split_technologies(labelled.group(1)))
            # Keep sentence-ending punctuation on the surviving prose; only
            # dangling separators are noise.
            body = body[: labelled.start()].strip(" ,;:|\u2013-")

        if not title_taken and not is_bullet(raw_line):
            name, tech_text, extra = _split_title(body)
            if name:
                entry.name = name
                title_taken = True
                if tech_text:
                    technologies.extend(_split_technologies(tech_text))
                if extra:
                    description.append(extra)
                continue

        if body:
            description.append(collapse_whitespace(body))

    # A bullet-only project ("- Name: short description") still needs a name.
    if not entry.name and description:
        name, tech_text, extra = _split_title(description[0])
        if name:
            entry.name = name
            description = ([extra] if extra else []) + description[1:]
            if tech_text and not technologies:
                technologies.extend(_split_technologies(tech_text))

    date_range = find_date_range(raw_text)
    if date_range is not None:
        entry.start_date = date_range.start_text
        entry.end_date = date_range.end_text

    url = _URL_RE.search(raw_text)
    if url:
        entry.link = _tidy_url(url.group(0))

    entry.description = description
    entry.technologies = _resolve_technologies(technologies, raw_text, vocabulary)
    return entry


def _split_title(text: str) -> tuple[str, str, str]:
    """Split a title line into ``(name, technology_text, extra_description)``.

    ``"Smart Resume Parser | Python, spaCy"``
        -> ``("Smart Resume Parser", "Python, spaCy", "")``
    ``"Campus Navigator - an offline map for new students"``
        -> ``("Campus Navigator", "", "an offline map for new students")``
    """
    candidate = _ROLE_NOISE_RE.sub("", collapse_whitespace(text)).strip()
    if not candidate:
        return "", "", ""

    tech_text = ""
    extra = ""
    separator = ""
    if "|" in candidate:
        separator = "|"
    elif "\u2013" in candidate:
        separator = "\u2013"
    elif " - " in candidate:
        separator = " - "
    elif ":" in candidate and not candidate.lower().startswith("http"):
        separator = ":"

    if separator:
        head, tail = candidate.split(separator, 1)
        head, tail = head.strip(), tail.strip()
        if head and len(head) <= _MAX_TITLE_CHARS:
            candidate = head
            if _looks_like_tech_list(tail):
                tech_text = tail
            elif tail:
                extra = tail

    candidate = _TRAILING_PARENS_RE.sub("", candidate).strip()
    candidate = strip_dates(candidate).strip(" ,;:|\u2013-")
    return collapse_whitespace(candidate), tech_text, extra


def _looks_like_tech_list(text: str) -> bool:
    """True when a fragment reads like ``"Python, Flask, Docker"``."""
    if not text or len(text) > 120 or text.endswith((".", "!", "?")):
        return False
    items = [item.strip() for item in _ITEM_SPLIT_RE.split(text) if item.strip()]
    if not items:
        return False
    return all(len(item.split()) <= 4 for item in items) and len(items) >= 2


def _split_technologies(text: str) -> list[str]:
    """Split a technology list into individual items."""
    items: list[str] = []
    for chunk in _ITEM_SPLIT_RE.split(text or ""):
        value = collapse_whitespace(chunk).strip(" .,;:|\u2013-")
        value = re.sub(r"^\band\b\s+", "", value, flags=re.IGNORECASE).strip()
        if value and len(value) <= 40 and len(value.split()) <= 4:
            items.append(value)
    return items


def _resolve_technologies(
    declared: Sequence[str], raw_text: str, vocabulary: SkillDictionary
) -> list[str]:
    """Canonicalise declared technologies, or infer them from the entry text.

    Declared items are mapped to their dictionary spelling when known and kept
    verbatim otherwise - a niche tool the dictionary has never heard of is
    still the candidate's stated technology.
    """
    resolved: list[str] = []
    seen: set[str] = set()

    for item in declared:
        definition = vocabulary.lookup(item)
        name = definition.name if definition else item
        key = name.lower()
        if key not in seen:
            seen.add(key)
            resolved.append(name)

    if resolved:
        return resolved

    # Nothing declared: fall back to dictionary matches inside the entry.
    for definition in vocabulary.definitions:
        if definition.strict:
            continue
        if definition.pattern.search(raw_text):
            key = definition.name.lower()
            if key not in seen:
                seen.add(key)
                resolved.append(definition.name)
    return resolved


def _tidy_url(url: str) -> str:
    cleaned = url.strip().strip(".,;:)]}>").rstrip("/")
    if not cleaned.lower().startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    return cleaned
