"""Shared line-shape helpers for entry grouping.

Both the experience and project parsers split a section into entries by
reading the *shape* of each line. Two concerns are common to both and live
here:

* **Wrapped lines.** A PDF preserves the visual line breaks of the original
  document, so one bullet routinely arrives as two or three lines. Treating
  the continuation as a new line would start a spurious entry, so wrapped
  fragments are re-joined before grouping.
* **Date-only lines.** Templates often put the period on its own line. That
  line is a header, never a continuation, and recognising it is what lets the
  grouper tell "new role" from "sentence continues".
"""

from __future__ import annotations

import re
from typing import Sequence

from ..processing.dates import find_date_range, strip_dates
from ..processing.normalize import is_bullet

#: Trailing words that mean the sentence is unfinished.
_UNFINISHED_TAIL_RE = re.compile(
    r"(?:[,;:]|\b(?:and|or|but|to|of|with|the|for|in|on|at|a|an|by|from|that|as|"
    r"into|using|per|than|across|over|under|via|while|which|who)\s*)$",
    re.IGNORECASE,
)

#: Characters a continuation line may legitimately start with.
_CONTINUATION_OPENERS = "(\"'\u2018\u201c"


def is_mostly_dates(line: str) -> bool:
    """True when a line carries little more than a date or date range."""
    text = (line or "").strip()
    if not text:
        return False
    if find_date_range(text) is None:
        return False
    residue = strip_dates(text).strip(" .,;:|\u2013-()")
    return len(residue) <= 2


def looks_like_continuation(line: str, previous: str) -> bool:
    """True when ``line`` is the wrapped remainder of ``previous``."""
    if not previous or not previous.strip():
        return False
    text = (line or "").strip()
    if not text or is_bullet(line):
        return False
    # A standalone period is a header element in its own right.
    if is_mostly_dates(text):
        return False

    first = text[0]
    if first.isalpha():
        if first.islower():
            return True
    elif first.isdigit() or first in _CONTINUATION_OPENERS:
        return True

    return bool(_UNFINISHED_TAIL_RE.search(previous.strip()))


def merge_wrapped_lines(lines: Sequence[str]) -> list[str]:
    """Re-join lines that were split by the document's visual line wrapping.

    Blank lines are preserved, since they are a meaningful entry separator.
    """
    merged: list[str] = []
    for raw_line in lines:
        if not raw_line.strip():
            merged.append("")
            continue

        previous = merged[-1] if merged else ""
        if previous.strip() and looks_like_continuation(raw_line, previous):
            merged[-1] = f"{previous.rstrip()} {raw_line.strip()}"
            continue
        merged.append(raw_line.rstrip())
    return merged
