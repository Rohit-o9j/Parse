"""Download file-name construction.

Exports are named after the candidate when one was detected, because a folder
of ``resume.json`` files is useless. Names are sanitised for every major
filesystem: no path separators, no reserved Windows device names, no trailing
dots or spaces.
"""

from __future__ import annotations

import re
from datetime import date

from ..models import ParsedResume

#: Windows reserves these names regardless of extension.
_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)

_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_REPEAT_RE = re.compile(r"[_-]{2,}")

_MAX_STEM = 60


def slugify(text: str, fallback: str = "resume") -> str:
    """Reduce ``text`` to a safe, lowercase file-name stem."""
    stem = _UNSAFE_RE.sub("_", (text or "").strip()).strip("._-").lower()
    stem = _REPEAT_RE.sub("_", stem)[:_MAX_STEM].strip("._-")
    if not stem or stem.split(".")[0] in _RESERVED_NAMES:
        return fallback
    return stem


def export_filename(resume: ParsedResume, extension: str, suffix: str = "") -> str:
    """Build a download name such as ``rahul_sharma_resume_2026-10-02.json``."""
    base = slugify(resume.contact.name) if resume.contact.name else ""
    if not base:
        base = slugify(resume.extraction.file_name.rsplit(".", 1)[0] or "resume")

    parts = [base, "resume"]
    if suffix:
        parts.append(slugify(suffix, fallback=""))
    parts.append(date.today().isoformat())

    stem = "_".join(part for part in parts if part)
    return f"{stem}.{extension.lstrip('.')}"
