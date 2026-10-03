"""Text normalisation.

PDF and DOCX extraction produces text that is *almost* usable. The artefacts
that actually break downstream regexes are, in rough order of importance:

* typographic look-alikes (curly quotes, en/em dashes, non-breaking spaces,
  ``ﬁ``-style ligatures) that defeat literal character classes;
* bullet glyphs that differ per template, so "is this line a bullet?" becomes
  unanswerable;
* words split across a line break with a hyphen;
* spaced-out headings such as ``E D U C A T I O N`` emitted by some templates;
* runs of blank lines and trailing whitespace.

Everything here is lossless with respect to meaning: no content is dropped,
only standardised. The original text is always kept separately so the UI can
show exactly what came out of the document.
"""

from __future__ import annotations

import re
import unicodedata

#: Glyphs that resume templates use as a bullet marker. Word and PowerPoint
#: export Symbol/Wingdings bullets into the Unicode private-use area, hence the
#: ``\uf0xx`` entries.
BULLET_CHARS = "".join(
    (
        "\u2022\u2023\u2043\u204c\u204d\u2219\u00b7",  # bullet / triangular bullet / hyphen bullet
        "\u25aa\u25ab\u25cf\u25cb\u25e6\u25a0\u25a1\u25b6\u25b8",  # geometric shapes
        "\u2756\u2794\u27a2\u279c\u2192\u00bb\u29bf",  # ornaments and arrows
        "\u2718\u2714\u2751",  # ballot / check marks
        "\u002d\u002a\u00ac\u2013",  # hyphen, asterisk, negation, en dash
        "\uf0a7\uf0b7\uf076\uf0d8",  # Symbol/Wingdings private-use bullets
    )
)

#: Normalised bullet prefix used throughout the parser.
BULLET_PREFIX = "- "

_LIGATURES = {
    "\ufb00": "ff",
    "\ufb01": "fi",
    "\ufb02": "fl",
    "\ufb03": "ffi",
    "\ufb04": "ffl",
    "\ufb05": "st",
    "\ufb06": "st",
    "\u0153": "oe",
    "\u0152": "OE",
    "\u00e6": "ae",
    "\u00c6": "AE",
}

_PUNCTUATION_MAP = {
    # quotes
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u2032": "'",
    "\u00b4": "'",
    "\u0060": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2033": '"',
    # dashes: keep en dash, it is a meaningful date-range separator
    "\u2012": "\u2013",
    "\u2014": "\u2013",
    "\u2015": "\u2013",
    "\u2212": "-",
    "\uff0d": "-",
    # spaces
    "\u00a0": " ",
    "\u1680": " ",
    "\u2000": " ",
    "\u2001": " ",
    "\u2002": " ",
    "\u2003": " ",
    "\u2004": " ",
    "\u2005": " ",
    "\u2006": " ",
    "\u2007": " ",
    "\u2008": " ",
    "\u2009": " ",
    "\u200a": " ",
    "\u202f": " ",
    "\u205f": " ",
    "\u3000": " ",
    # invisible / control
    "\u200b": "",
    "\u200c": "",
    "\u200d": "",
    "\ufeff": "",
    "\u00ad": "",
    # misc
    "\u2026": "...",
    "\u2044": "/",
    "\uff1a": ":",
    "\uff0c": ",",
}

_TRANSLATION_TABLE = str.maketrans({**_LIGATURES, **_PUNCTUATION_MAP})

_BULLET_LINE_RE = re.compile(rf"^[{re.escape(BULLET_CHARS)}\s]*[{re.escape(BULLET_CHARS)}]\s+")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_BLANK_RUN_RE = re.compile(r"\n{3,}")
_HYPHEN_WRAP_RE = re.compile(r"(\w)-\n([a-z])")
#: ``E D U C A T I O N`` / ``S K I L L S`` - single letters separated by spaces.
_SPACED_CAPS_RE = re.compile(r"^(?:[A-Z]\s){2,}[A-Z]$")


def normalize_text(text: str) -> str:
    """Return a cleaned, parser-friendly version of ``text``."""
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_TRANSLATION_TABLE)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HYPHEN_WRAP_RE.sub(r"\1\2", text)

    lines = [_normalize_line(line) for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def _normalize_line(line: str) -> str:
    """Normalise one line: bullets, spacing, spaced-out capitals."""
    line = line.replace("\t", " ").rstrip()
    if not line.strip():
        return ""

    stripped = line.strip()

    # Re-join headings typeset with a space between every letter.
    if _SPACED_CAPS_RE.match(stripped):
        return stripped.replace(" ", "")

    bullet_match = _BULLET_LINE_RE.match(stripped)
    if bullet_match:
        body = stripped[bullet_match.end() :].strip()
        # A lone dash with nothing after it carries no information.
        return f"{BULLET_PREFIX}{body}" if body else ""

    return _MULTI_SPACE_RE.sub("  ", stripped)


def to_lines(text: str) -> list[str]:
    """Split normalised text into lines, preserving blank-line separators."""
    return text.split("\n") if text else []


def non_empty_lines(text: str) -> list[str]:
    """Split text into lines, dropping blanks."""
    return [line for line in to_lines(text) if line.strip()]


def is_bullet(line: str) -> bool:
    """True when a normalised line is a bullet point."""
    return line.lstrip().startswith(BULLET_PREFIX.strip() + " ") or line.lstrip().startswith(
        BULLET_PREFIX
    )


def strip_bullet(line: str) -> str:
    """Remove the leading bullet marker from a normalised line."""
    text = line.strip()
    if text.startswith(BULLET_PREFIX):
        return text[len(BULLET_PREFIX) :].strip()
    if text.startswith("-"):
        return text[1:].strip()
    return text


def collapse_whitespace(text: str) -> str:
    """Collapse all whitespace runs (including newlines) to single spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def squash_separators(text: str) -> str:
    """Tidy dangling separators left behind after removing a matched substring.

    ``"Senior Engineer |  | Acme Corp,"`` -> ``"Senior Engineer | Acme Corp"``
    """
    text = collapse_whitespace(text)
    text = re.sub(r"(?:\s*[|\u2013\u2022,;:/]\s*){2,}", " | ", text)
    text = text.strip(" \t|,;:\u2013-\u2022")
    return collapse_whitespace(text)
