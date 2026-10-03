"""Application-wide configuration for the Smart Resume Parser.

Everything tunable lives here so the extraction behaviour can be adjusted
without touching parser logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #

PACKAGE_ROOT: Final[Path] = Path(__file__).resolve().parent
PROJECT_ROOT: Final[Path] = PACKAGE_ROOT.parent
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
SKILL_DICTIONARY_PATH: Final[Path] = DATA_DIR / "skills.json"
SAMPLE_RESUME_DIR: Final[Path] = DATA_DIR / "sample_resumes"

# --------------------------------------------------------------------------- #
# Upload constraints
# --------------------------------------------------------------------------- #

SUPPORTED_EXTENSIONS: Final[tuple[str, ...]] = ("pdf", "docx")
MAX_FILE_SIZE_MB: Final[int] = 10
MAX_FILE_SIZE_BYTES: Final[int] = MAX_FILE_SIZE_MB * 1024 * 1024

#: Below this many characters we assume extraction failed (scanned / image PDF).
MIN_EXTRACTABLE_CHARS: Final[int] = 60

#: Resumes longer than this are truncated for NLP work to keep the UI snappy.
NLP_CHAR_BUDGET: Final[int] = 60_000

# --------------------------------------------------------------------------- #
# NLP
# --------------------------------------------------------------------------- #

#: Tried in order. The first model that loads wins.
SPACY_MODEL_PREFERENCE: Final[tuple[str, ...]] = (
    "en_core_web_sm",
    "en_core_web_md",
    "en_core_web_lg",
)

#: Number of leading lines treated as the resume "header" (contact block).
HEADER_LINE_WINDOW: Final[int] = 18

#: Sanity bounds used when validating parsed years.
MIN_VALID_YEAR: Final[int] = 1950
MAX_YEAR_LOOKAHEAD: Final[int] = 8

# --------------------------------------------------------------------------- #
# Display
# --------------------------------------------------------------------------- #

NOT_DETECTED: Final[str] = "Not detected"

APP_TITLE: Final[str] = "Smart Resume Parser"
APP_SUBTITLE: Final[str] = "Turn unstructured resumes into structured candidate data."
APP_VERSION: Final[str] = "1.0.0"

#: Order in which skill categories are rendered. Unknown categories append after.
SKILL_CATEGORY_ORDER: Final[tuple[str, ...]] = (
    "Programming Languages",
    "Frameworks",
    "Databases",
    "Tools",
    "Cloud",
    "Data & ML",
    "Soft Skills",
    "Other",
)

#: Fields that count towards the "profile completeness" indicator.
COMPLETENESS_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "email",
    "phone",
    "location",
    "links",
    "skills",
    "education",
    "experience",
    "projects",
)
