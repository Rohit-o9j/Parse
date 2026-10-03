"""Date and date-range parsing for resume text.

Resumes express the same period a dozen different ways::

    Jan 2020 - Mar 2022      January 2020 to Present     05/2018 - 08/2020
    2019 - 2023              Aug '19 - Dec '21           Since 2021
    Mar-2020 - May-2021      2021 - Current              Nov 2019 - Till date

This module recognises all of the above, normalises them to ``YYYY-MM`` /
``YYYY`` for sorting, and reports the character span of the match so callers
can remove the dates from a line before parsing the job title out of what is
left. Anything it is not confident about is simply not returned - a blank field
is always preferable to a wrong one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..settings import MAX_YEAR_LOOKAHEAD, MIN_VALID_YEAR

_MONTH_NUMBERS: dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

_MONTH_NAMES: tuple[str, ...] = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)

#: Words meaning "this role has not ended". Ordered longest-first so the
#: regex alternation prefers "till date" over a bare "till".
CURRENT_WORDS: tuple[str, ...] = (
    "present day",
    "till present",
    "till date",
    "til date",
    "to date",
    "till now",
    "until now",
    "currently",
    "present",
    "current",
    "ongoing",
    "today",
    "now",
)

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?"
    r"|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_YEAR = r"(?:19|20)\d{2}"
_CURRENT = r"(?:" + "|".join(word.replace(" ", r"\s+") for word in CURRENT_WORDS) + r")"

#: One date, in any of the spellings we accept. Ordered longest-first so the
#: alternation does not stop at a shorter prefix.
_DATE_TOKEN = (
    r"(?:"
    rf"\d{{1,2}}[/.\-]\d{{1,2}}[/.\-]{_YEAR}"          # 15/01/2020
    rf"|{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s*{_YEAR}"  # Jan 15, 2020
    rf"|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\.?,?\s*{_YEAR}"  # 15 Jan 2020
    rf"|{_MONTH}\.?[\s,\-/]*{_YEAR}"                    # Jan 2020 / Jan-2020
    rf"|{_MONTH}\.?\s*'\s*\d{{2}}"                       # Aug '19
    rf"|\d{{1,2}}\s*[/\-]\s*{_YEAR}"                     # 05/2018
    rf"|{_YEAR}\s*[/\-]\s*(?:0[1-9]|1[0-2])\b"           # 2018-05
    rf"|{_YEAR}"                                         # 2018
    r")"
)

_RANGE_SEPARATOR = r"(?:\s*(?:\u2013|-|to|until|untill|through|thru|till|~|\u2192)\s*)"

#: Accepted *after* a date and a separator, where a bare "date" or "now" can
#: only mean "ongoing". This is what lets "Nov 2019 till date" work: the
#: separator consumes "till" and this pattern recognises the remaining "date".
_END_CURRENT = r"(?:" + _CURRENT + r"|date|now|present|today|onwards?)"

_RANGE_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN}){_RANGE_SEPARATOR}(?P<end>{_DATE_TOKEN}|{_END_CURRENT})",
    re.IGNORECASE,
)
_END_CURRENT_RE = re.compile(rf"\b{_END_CURRENT}\b", re.IGNORECASE)
#: ``Nov 2019 till date`` / ``2021 onwards`` - an ongoing period written
#: without a range separator.
_TRAILING_CURRENT_RE = re.compile(
    rf"(?P<start>{_DATE_TOKEN})\s*[\u2013-]?\s*(?P<end>{_CURRENT}|onwards?)",
    re.IGNORECASE,
)
_OPEN_RANGE_RE = re.compile(
    rf"\b(?:since|from)\s+(?P<start>{_DATE_TOKEN})(?!{_RANGE_SEPARATOR})",
    re.IGNORECASE,
)
_SINGLE_RE = re.compile(_DATE_TOKEN, re.IGNORECASE)
_YEAR_RE = re.compile(_YEAR)
_CURRENT_RE = re.compile(rf"\b{_CURRENT}\b", re.IGNORECASE)

_MONTH_LOOKUP_RE = re.compile(_MONTH, re.IGNORECASE)
_SHORT_YEAR_RE = re.compile(r"'\s*(\d{2})")


@dataclass(slots=True)
class DateRange:
    """A parsed period. Empty strings mean "not detected"."""

    start_text: str = ""
    end_text: str = ""
    start_iso: str = ""
    end_iso: str = ""
    is_current: bool = False
    matched_text: str = ""
    span: tuple[int, int] | None = field(default=None)

    @property
    def found(self) -> bool:
        return bool(self.start_text or self.end_text)

    @property
    def sort_key(self) -> str:
        """Descending-sortable key; ongoing roles sort first."""
        if self.is_current:
            return "9999-99"
        if self.start_iso:
            return self.start_iso if "-" in self.start_iso else f"{self.start_iso}-00"
        return ""


def max_valid_year() -> int:
    """Upper bound for a plausible resume year."""
    return date.today().year + MAX_YEAR_LOOKAHEAD


def is_valid_year(value: int | str) -> bool:
    """True when ``value`` is a plausible year for a resume."""
    try:
        year = int(value)
    except (TypeError, ValueError):
        return False
    return MIN_VALID_YEAR <= year <= max_valid_year()


def find_date_range(text: str) -> DateRange | None:
    """Find the most likely period expressed in ``text``.

    Tries an explicit range first ("Jan 2020 - Mar 2022"), then an open-ended
    range ("Since 2021"), then a single date. Returns ``None`` when nothing
    plausible is present.
    """
    if not text:
        return None

    for match in _RANGE_RE.finditer(text):
        start_raw, end_raw = match.group("start"), match.group("end")
        start_iso = _to_iso(start_raw)
        if not start_iso:
            continue

        if _END_CURRENT_RE.fullmatch(end_raw.strip()):
            return DateRange(
                start_text=_pretty(start_raw),
                end_text="Present",
                start_iso=start_iso,
                end_iso="",
                is_current=True,
                matched_text=match.group(0),
                span=match.span(),
            )

        end_iso = _to_iso(end_raw)
        if not end_iso:
            continue
        # A range must move forward in time; otherwise we matched two
        # unrelated numbers that merely look like a range.
        if end_iso[:4] < start_iso[:4]:
            continue
        return DateRange(
            start_text=_pretty(start_raw),
            end_text=_pretty(end_raw),
            start_iso=start_iso,
            end_iso=end_iso,
            is_current=False,
            matched_text=match.group(0),
            span=match.span(),
        )

    trailing = _TRAILING_CURRENT_RE.search(text)
    if trailing:
        start_iso = _to_iso(trailing.group("start"))
        if start_iso:
            return DateRange(
                start_text=_pretty(trailing.group("start")),
                end_text="Present",
                start_iso=start_iso,
                end_iso="",
                is_current=True,
                matched_text=trailing.group(0),
                span=trailing.span(),
            )

    open_match = _OPEN_RANGE_RE.search(text)
    if open_match:
        start_iso = _to_iso(open_match.group("start"))
        if start_iso:
            return DateRange(
                start_text=_pretty(open_match.group("start")),
                end_text="Present",
                start_iso=start_iso,
                end_iso="",
                is_current=True,
                matched_text=open_match.group(0),
                span=open_match.span(),
            )

    for match in _SINGLE_RE.finditer(text):
        iso = _to_iso(match.group(0))
        if iso:
            return DateRange(
                start_text="",
                end_text=_pretty(match.group(0)),
                start_iso="",
                end_iso=iso,
                matched_text=match.group(0),
                span=match.span(),
            )
    return None


def find_years(text: str) -> list[int]:
    """All plausible four-digit years in ``text``, in order of appearance."""
    return [int(m.group(0)) for m in _YEAR_RE.finditer(text or "") if is_valid_year(m.group(0))]


def mentions_current(text: str) -> bool:
    """True when the text says the period is ongoing."""
    return bool(text) and bool(_CURRENT_RE.search(text))


def strip_dates(text: str) -> str:
    """Remove every date expression from ``text``.

    Used before title/company extraction so a right-aligned date column does
    not end up glued onto the employer name.
    """
    if not text:
        return ""
    cleaned = _RANGE_RE.sub(" ", text)
    cleaned = _TRAILING_CURRENT_RE.sub(" ", cleaned)
    cleaned = _OPEN_RANGE_RE.sub(" ", cleaned)
    cleaned = _SINGLE_RE.sub(" ", cleaned)
    cleaned = _CURRENT_RE.sub(" ", cleaned)
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def format_year_span(start_iso: str, end_iso: str) -> tuple[str, str]:
    """Reduce ISO dates to plain years for the education card."""
    return (start_iso[:4] if start_iso else "", end_iso[:4] if end_iso else "")


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _to_iso(raw: str) -> str:
    """Convert one date expression to ``YYYY-MM`` or ``YYYY``.

    Returns ``""`` when the value is implausible, which is how callers learn
    to ignore a false-positive match.
    """
    if not raw:
        return ""
    text = raw.strip().strip(",.")
    if not text:
        return ""

    month = _extract_month(text)
    year = _extract_year(text)
    if year is None:
        return ""
    if not is_valid_year(year):
        return ""
    if month is not None and 1 <= month <= 12:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}"


def _extract_month(text: str) -> int | None:
    """Month number from a date expression, or ``None``."""
    name_match = _MONTH_LOOKUP_RE.search(text)
    if name_match:
        return _MONTH_NUMBERS.get(name_match.group(0).lower().rstrip("."))

    # 15/01/2020 or 01/2020 -> the component that cannot be the year.
    numeric = re.findall(r"\d{1,4}", text)
    if len(numeric) == 3:
        first, second, _third = (int(n) for n in numeric[:3])
        # Day-first and month-first both appear; prefer the unambiguous reading.
        if first > 12 and second <= 12:
            return second
        if second > 12 and first <= 12:
            return first
        return first if first <= 12 else None
    if len(numeric) == 2:
        first, second = int(numeric[0]), int(numeric[1])
        if is_valid_year(first) and 1 <= second <= 12:
            return second
        if is_valid_year(second) and 1 <= first <= 12:
            return first
    return None


def _extract_year(text: str) -> int | None:
    """Year from a date expression, expanding two-digit forms."""
    full = _YEAR_RE.search(text)
    if full:
        return int(full.group(0))

    short = _SHORT_YEAR_RE.search(text)
    if short:
        value = int(short.group(1))
        # '98 -> 1998, '19 -> 2019. Anything beyond next year is last century.
        century_guess = 2000 + value
        return century_guess if century_guess <= max_valid_year() else 1900 + value

    trailing = re.search(r"\b(\d{2})\b\s*$", text)
    if trailing:
        value = int(trailing.group(1))
        candidate = 2000 + value
        return candidate if is_valid_year(candidate) else None
    return None


def _pretty(raw: str) -> str:
    """Tidy a raw date for display: ``"jan-2020"`` -> ``"Jan 2020"``."""
    text = re.sub(r"\s+", " ", (raw or "").strip().strip(",.")).strip()
    if not text:
        return ""
    if _CURRENT_RE.fullmatch(text):
        return "Present"

    iso = _to_iso(text)
    if not iso:
        return text
    if "-" in iso:
        year, month = iso.split("-")
        # Keep purely numeric input numeric; only prettify name-based months.
        if _MONTH_LOOKUP_RE.search(text):
            return f"{_MONTH_NAMES[int(month) - 1][:3]} {year}"
        return f"{month}/{year}"
    return iso
