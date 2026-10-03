"""Contact-block extraction: name, email, phone, location and profile links.

The candidate's identity sits in the few lines above the first section heading
and is the least standardised part of a resume. Each field therefore gets the
cheapest technique that is actually reliable:

================  =========================================================
email             regex - unambiguous, validated against a TLD shape
phone             scored regex candidates, rejected on date-like context
links             regex over visible text *and* embedded hyperlink targets
name              line scoring in the header, corroborated by spaCy PERSON
location          comma-separated place patterns, corroborated by spaCy GPE
================  =========================================================

Every accepted value records a short justification in
:attr:`ContactInfo.evidence` so the UI can explain *why* it believes a value.
Nothing is guessed: when the signals are weak the field is left empty.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from ..models import ContactInfo, SectionBlock
from ..processing.dates import find_years
from ..processing.nlp import NlpEngine
from ..processing.normalize import collapse_whitespace
from ..settings import HEADER_LINE_WINDOW

# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._%+\-]*[A-Za-z0-9])?@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+"
)

#: Suffixes that mean we matched a file name, not a mailbox.
_NON_EMAIL_TLDS = frozenset({"png", "jpg", "jpeg", "gif", "svg", "pdf", "docx", "doc", "webp"})

#: Obfuscations that are easy and safe to undo before matching.
_EMAIL_DEOBFUSCATION = (
    (re.compile(r"\s*\(\s*at\s*\)\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s*\[\s*at\s*\]\s*", re.IGNORECASE), "@"),
    (re.compile(r"\s+at\s+(?=[A-Za-z0-9.\-]+\s*(?:\(|\[)?\s*dot)", re.IGNORECASE), "@"),
    (re.compile(r"\s*\(\s*dot\s*\)\s*", re.IGNORECASE), "."),
    (re.compile(r"\s*\[\s*dot\s*\]\s*", re.IGNORECASE), "."),
)


def extract_emails(text: str) -> list[str]:
    """All plausible email addresses in ``text``, de-duplicated, in order."""
    if not text:
        return []

    candidate_text = text
    for pattern, replacement in _EMAIL_DEOBFUSCATION:
        candidate_text = pattern.sub(replacement, candidate_text)

    found: list[str] = []
    seen: set[str] = set()
    for match in _EMAIL_RE.finditer(candidate_text):
        address = match.group(0).strip(".,;:")
        tld = address.rsplit(".", 1)[-1].lower()
        if len(tld) < 2 or tld in _NON_EMAIL_TLDS:
            continue
        key = address.lower()
        if key not in seen:
            seen.add(key)
            found.append(address)
    return found


# --------------------------------------------------------------------------- #
# Phone
# --------------------------------------------------------------------------- #

#: ``(pattern, score)`` - higher score means a more distinctive shape.
_PHONE_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    # +91 98765 43210 / +1-415-555-2671 / +44 20 7946 0958
    (re.compile(r"\+\d{1,3}[\s.\-]?\(?\d{2,5}\)?(?:[\s.\-]?\d{2,5}){1,4}"), 10),
    # (512) 555-0188
    (re.compile(r"\(\d{3}\)\s*\d{3}[\s.\-]?\d{4}"), 9),
    # 415-555-2671 / 415.555.2671
    (re.compile(r"\b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b"), 8),
    # 98765 43210
    (re.compile(r"\b\d{5}[\s.\-]\d{5}\b"), 8),
    # 020 7946 0958
    (re.compile(r"\b\d{3,4}[\s.\-]\d{3,4}[\s.\-]\d{3,4}\b"), 6),
    # 9876543210 - valid but easily confused with an ID, so it scores low
    (re.compile(r"\b\d{10}\b"), 3),
)

_PHONE_KEYWORD_RE = re.compile(
    r"(?:phone|mobile|mob|cell|tel|telephone|contact|whatsapp|call|ph)\b",
    re.IGNORECASE,
)
#: Context words that mean a number is not a phone number.
_PHONE_DISQUALIFIER_RE = re.compile(
    r"(?:cgpa|gpa|sgpa|percentage|score|marks|aggregate|pin\s*code|zip|roll\s*no|"
    r"employee\s*id|salary|ctc|lpa|rank|version|rows|users|customers|%)",
    re.IGNORECASE,
)

_MIN_PHONE_DIGITS = 7
_MAX_PHONE_DIGITS = 15
#: Minimum score an un-keyworded candidate needs to be accepted.
_PHONE_SCORE_FLOOR = 6


def extract_phones(text: str, header_text: str = "") -> list[str]:
    """Phone numbers in ``text``, best candidate first.

    Scoring beats plain regex here because resumes are full of numbers that
    look like phone numbers (dates, CGPA, metrics, employee ids). A candidate
    is only accepted when its shape is distinctive, or when a nearby keyword
    such as "Mobile:" vouches for it.
    """
    if not text:
        return []

    header_lower = (header_text or "").lower()
    scored: list[tuple[int, int, str]] = []
    seen_digits: set[str] = set()

    for pattern, base_score in _PHONE_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(0).strip()
            digits = re.sub(r"\D", "", raw)
            if not _MIN_PHONE_DIGITS <= len(digits) <= _MAX_PHONE_DIGITS:
                continue

            line = _line_containing(text, match.start())
            if _PHONE_DISQUALIFIER_RE.search(line):
                continue
            if _looks_like_year_range(raw):
                continue

            score = base_score
            if _PHONE_KEYWORD_RE.search(line):
                score += 6
            if raw.lower() in header_lower or line.lower() in header_lower:
                score += 4
            if raw.startswith("+"):
                score += 2
            if len(digits) in (10, 11, 12):
                score += 1

            if score < _PHONE_SCORE_FLOOR:
                continue
            if digits in seen_digits:
                continue
            seen_digits.add(digits)
            scored.append((score, -match.start(), collapse_whitespace(raw)))

    scored.sort(reverse=True)
    return [value for _score, _position, value in scored]


def _looks_like_year_range(raw: str) -> bool:
    """True for things like ``2018-2022`` that match a phone shape by accident."""
    compact = re.sub(r"[\s.\-\u2013]", "", raw)
    if len(compact) == 8 and compact.isdigit():
        first, second = int(compact[:4]), int(compact[4:])
        if 1950 <= first <= 2100 and 1950 <= second <= 2100:
            return True
    years = find_years(raw)
    return len(years) >= 2


def _line_containing(text: str, position: int) -> str:
    """The full line of ``text`` that contains character ``position``."""
    start = text.rfind("\n", 0, position) + 1
    end = text.find("\n", position)
    return text[start:] if end == -1 else text[start:end]


# --------------------------------------------------------------------------- #
# Links
# --------------------------------------------------------------------------- #

#: ``label -> pattern``. Order matters: specific hosts before the generic URL.
_LINK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "LinkedIn",
        re.compile(
            r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub|profile)/[\w%\-.]+/?",
            re.IGNORECASE,
        ),
    ),
    (
        "GitHub",
        re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w\-.]+(?:/[\w\-.]+)?/?", re.IGNORECASE),
    ),
    (
        "GitLab",
        re.compile(r"(?:https?://)?(?:www\.)?gitlab\.com/[\w\-.]+/?", re.IGNORECASE),
    ),
    (
        "Stack Overflow",
        re.compile(
            r"(?:https?://)?(?:www\.)?stackoverflow\.com/users/[\w\-/]+", re.IGNORECASE
        ),
    ),
    ("Kaggle", re.compile(r"(?:https?://)?(?:www\.)?kaggle\.com/[\w\-.]+/?", re.IGNORECASE)),
    ("LeetCode", re.compile(r"(?:https?://)?(?:www\.)?leetcode\.com/[\w\-.]+/?", re.IGNORECASE)),
    (
        "HackerRank",
        re.compile(r"(?:https?://)?(?:www\.)?hackerrank\.com/[\w\-.]+/?", re.IGNORECASE),
    ),
    ("Medium", re.compile(r"(?:https?://)?(?:[\w\-]+\.)?medium\.com/[\w@\-.]+/?", re.IGNORECASE)),
    ("Behance", re.compile(r"(?:https?://)?(?:www\.)?behance\.net/[\w\-.]+/?", re.IGNORECASE)),
    ("Dribbble", re.compile(r"(?:https?://)?(?:www\.)?dribbble\.com/[\w\-.]+/?", re.IGNORECASE)),
    ("Twitter/X", re.compile(r"(?:https?://)?(?:www\.)?(?:twitter|x)\.com/[\w\-.]+/?", re.IGNORECASE)),
)

_GENERIC_URL_RE = re.compile(
    r"(?:https?://|www\.)[\w\-]+(?:\.[\w\-]+)+(?:/[\w\-./%?=&#+~]*)?", re.IGNORECASE
)

#: Hosts that are never a personal profile worth surfacing.
_IGNORED_HOSTS = (
    "example.com",
    "w3.org",
    "schemas.openxmlformats.org",
    "microsoft.com",
    "adobe.com",
    "office.com",
    "google.com/maps",
)


def extract_links(text: str, embedded_links: Iterable[str] = ()) -> dict[str, str]:
    """Profile and portfolio links found in visible text or hyperlink targets."""
    sources: list[str] = [text or ""]
    sources.extend(link for link in embedded_links if link)
    haystack = "\n".join(sources)

    links: dict[str, str] = {}
    consumed: list[str] = []

    for label, pattern in _LINK_PATTERNS:
        match = pattern.search(haystack)
        if not match:
            continue
        url = _tidy_url(match.group(0))
        if label == "GitHub" and _is_github_repo_path(url) and "GitHub" in links:
            continue
        links.setdefault(label, url)
        consumed.append(match.group(0).lower())

    # Anything else that looks like a personal site becomes the portfolio link.
    for match in _GENERIC_URL_RE.finditer(haystack):
        raw = match.group(0)
        lowered = raw.lower()
        if any(lowered in used or used in lowered for used in consumed):
            continue
        if any(host in lowered for host in _IGNORED_HOSTS):
            continue
        if lowered.startswith("mailto:"):
            continue
        links.setdefault("Portfolio", _tidy_url(raw))
        break

    return links


def _tidy_url(url: str) -> str:
    """Normalise a URL for display and linking."""
    cleaned = url.strip().strip(".,;:)]}>").rstrip("/")
    if not cleaned.lower().startswith(("http://", "https://")):
        cleaned = f"https://{cleaned.lstrip('/')}"
    return cleaned


def _is_github_repo_path(url: str) -> bool:
    """True for ``github.com/user/repo`` rather than a profile root."""
    tail = url.split("github.com/", 1)[-1]
    return tail.count("/") >= 1


# --------------------------------------------------------------------------- #
# Name
# --------------------------------------------------------------------------- #

_NAME_LABEL_RE = re.compile(
    r"^\s*(?:name|full\s*name|candidate(?:'s)?\s*name)\s*[:\-\u2013]\s*(.+)$", re.IGNORECASE
)

_HONORIFICS = frozenset({"mr", "mrs", "ms", "miss", "dr", "prof", "er", "shri", "smt"})
_CREDENTIALS = frozenset(
    {"phd", "mba", "msc", "bsc", "ba", "bs", "ms", "md", "pmp", "cfa", "cpa", "pe", "jr", "sr", "ii", "iii"}
)

#: Words that mean the line is a job title, a document label or a contact row.
_NOT_A_NAME_RE = re.compile(
    r"\b(?:resume|r[e\u00e9]sum[e\u00e9]|curriculum\s*vitae|biodata|bio\s*data|"
    r"profile|portfolio|summary|objective|about|contact|address|phone|mobile|email|"
    r"engineer|developer|programmer|analyst|manager|consultant|designer|scientist|"
    r"architect|administrator|specialist|intern|trainee|student|graduate|freelancer|"
    r"director|officer|executive|president|founder|lead|head|associate|assistant|"
    r"technician|researcher|professor|teacher|accountant|marketer|writer|editor|"
    r"full\s*stack|frontend|front\s*end|backend|back\s*end|devops|qa|sde)\b",
    re.IGNORECASE,
)

#: A single name token: a Unicode letter, then letters plus the punctuation
#: that legitimately appears inside names. ``[^\W\d_]`` means "any word
#: character that is not a digit or underscore", i.e. any Unicode letter - so
#: "Zo\u00eb", "M\u00fcller" and "\u674e" all pass, as do "Mary-Jane" and
#: "O'Brien".
_NAME_TOKEN_RE = re.compile(r"^[^\W\d_](?:[^\W\d_]|['\u2019.\-])*$")

#: Function words. A header line containing one in lower case is a sentence,
#: not a name ("Senior Engineer at Acme", "Nothing useful in this document").
_NAME_FUNCTION_WORDS = frozenset(
    {
        "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of",
        "on", "or", "the", "this", "to", "with", "my", "is", "are", "was",
    }
)

#: Minimum score required before a header line is accepted as the name.
_NAME_SCORE_FLOOR = 4


def name_candidate(text: str) -> str:
    """The part of a header line that could be a name, with casing preserved.

    Splits off trailing contact fragments, drops honorifics and trailing
    credentials, and leaves everything else exactly as written - the shape
    test below depends on the original capitalisation.
    """
    candidate = collapse_whitespace(text).strip(" .,:;|")
    # "Rahul Sharma, Bengaluru" / "Dana Whitfield - MBA" / "Jane | jane@x.com"
    candidate = re.split(r"\s*[,|\u2013/]\s*|\s{2,}", candidate)[0].strip()

    tokens = [token for token in candidate.split() if token]
    while tokens and tokens[0].lower().strip(".") in _HONORIFICS:
        tokens.pop(0)
    while tokens and tokens[-1].lower().strip(".") in _CREDENTIALS:
        tokens.pop()
    return " ".join(tokens)


def looks_like_person_name(text: str) -> bool:
    """Shape test for a human name: 1-5 capitalised, letters-only tokens."""
    candidate = collapse_whitespace(text).strip(" .,:;|")
    if not candidate or len(candidate) > 60:
        return False
    if any(char.isdigit() for char in candidate):
        return False
    if any(char in candidate for char in "@/\\()[]{}_=+*&%$#!?<>,|"):
        return False

    tokens = candidate.split()
    if not 1 <= len(tokens) <= 5:
        return False

    for token in tokens:
        if not _NAME_TOKEN_RE.match(token):
            return False
        # Names are capitalised; a lower-case token means this is prose.
        if not token[0].isupper():
            return False
        if token.lower().strip(".") in _NAME_FUNCTION_WORDS:
            return False
    return True


def clean_name(text: str) -> str:
    """Normalise a name for display: honorifics removed, capitalisation fixed."""
    tokens = name_candidate(text).split()
    if not tokens:
        return ""
    return " ".join(_titlecase_token(token) for token in tokens)


def _titlecase_token(token: str) -> str:
    """Title-case a name token while respecting Mc/Mac/O' and hyphens.

    Only applied when the token is single-case; mixed-case input such as
    "deSouza" is the author's own choice and is preserved.
    """
    if not token:
        return token
    if not (token.isupper() or token.islower()):
        return token

    def cap(part: str) -> str:
        if not part:
            return part
        lowered = part.lower()
        if lowered.startswith("mc") and len(lowered) > 2:
            return "Mc" + lowered[2:].capitalize()
        if lowered.startswith("mac") and len(lowered) > 4:
            return "Mac" + lowered[3:].capitalize()
        if lowered.startswith("o'") and len(lowered) > 2:
            return "O'" + lowered[2:].capitalize()
        return part.capitalize()

    for separator in ("-", "'"):
        if separator in token:
            return separator.join(cap(part) for part in token.split(separator))
    return cap(token)


def extract_name(
    header_lines: list[str],
    full_text: str = "",
    nlp: NlpEngine | None = None,
    nlp_doc: Any | None = None,
) -> tuple[str, str]:
    """Best-effort candidate name plus the reason it was chosen.

    Returns ``("", "")`` when no line is convincing enough.
    """
    # 1. An explicit label beats every heuristic.
    for line in header_lines:
        labelled = _NAME_LABEL_RE.match(line.strip())
        if labelled and looks_like_person_name(name_candidate(labelled.group(1))):
            name = clean_name(labelled.group(1))
            if name:
                return name, "Labelled 'Name:' field in the resume header"

    person_spans = _person_entity_texts(full_text, nlp, nlp_doc)

    best_score = 0
    best_name = ""
    best_reason = ""

    for index, raw_line in enumerate(header_lines[:HEADER_LINE_WINDOW]):
        candidate = name_candidate(raw_line)
        if not candidate or not looks_like_person_name(candidate):
            continue

        tokens = candidate.split()
        reasons: list[str] = []
        score = max(0, 8 - index * 2)
        if index == 0:
            reasons.append("first line of the resume")

        if candidate.upper() == candidate:
            score += 6
            reasons.append("typeset in capitals")
        else:
            score += 4
            reasons.append("title case")

        if 2 <= len(tokens) <= 3:
            score += 3
        elif len(tokens) == 1:
            score -= 5

        if _NOT_A_NAME_RE.search(candidate):
            score -= 14
            reasons.append("contains a job-title keyword")

        normalised = clean_name(candidate)
        if normalised and normalised.lower() in person_spans:
            score += 8
            reasons.append("spaCy tagged it as a PERSON")

        if score > best_score and normalised:
            best_score = score
            best_name = normalised
            best_reason = ", ".join(reasons) or "position in the resume header"

    if best_score >= _NAME_SCORE_FLOOR and best_name:
        return best_name, best_reason.capitalize()

    # 2. Fall back to the first PERSON entity near the top of the document.
    for entity_text in person_spans:
        candidate = name_candidate(entity_text)
        if looks_like_person_name(candidate):
            name = clean_name(candidate)
            if name:
                return name, "First PERSON entity detected by spaCy"

    return "", ""


def _person_entity_texts(
    full_text: str, nlp: NlpEngine | None, nlp_doc: Any | None
) -> list[str]:
    """Lowercased PERSON entity strings from the top of the document."""
    if nlp is None:
        return []
    entities = (
        NlpEngine.entities_from_doc(nlp_doc, ["PERSON"])
        if nlp_doc is not None
        else nlp.entities(full_text[:2000], ["PERSON"])
    )
    if nlp_doc is not None:
        entities = [entity for entity in entities if entity.start_char <= 2000]
    return [entity.text.lower() for entity in entities]


# --------------------------------------------------------------------------- #
# Location
# --------------------------------------------------------------------------- #

_US_STATE_ABBREVIATIONS = frozenset(
    """AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO
    MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split()
)

#: Countries, Indian states, and well-known cities. Pipe-separated so
#: multi-word names survive the split. This is a confidence aid, not a
#: gazetteer: an unlisted city can still be detected via spaCy or the
#: "City, ST" pattern.
_KNOWN_PLACES = frozenset(
    token.strip().lower()
    for line in """
    India|United States|USA|U.S.A|US|UK|United Kingdom|Canada|Australia|Germany|France
    Netherlands|Ireland|Singapore|Japan|China|Brazil|Mexico|Spain|Italy|Sweden|Norway
    Denmark|Finland|Poland|Portugal|Switzerland|Austria|Belgium|Israel|Remote|Hybrid
    New Zealand|South Africa|Nigeria|Kenya|Egypt|Pakistan|Bangladesh|Sri Lanka|Nepal
    Philippines|Indonesia|Malaysia|Thailand|Vietnam|South Korea|Russia|Turkey|Argentina
    Chile|Colombia|Peru|Dubai|UAE|United Arab Emirates|Qatar|Saudi Arabia|Oman|Kuwait
    Andhra Pradesh|Arunachal Pradesh|Assam|Bihar|Chhattisgarh|Goa|Gujarat|Haryana
    Himachal Pradesh|Jharkhand|Karnataka|Kerala|Madhya Pradesh|Maharashtra|Manipur
    Meghalaya|Mizoram|Nagaland|Odisha|Punjab|Rajasthan|Sikkim|Tamil Nadu|Telangana
    Tripura|Uttar Pradesh|Uttarakhand|West Bengal|Delhi|New Delhi|Jammu|Kashmir|Ladakh
    Bengaluru|Bangalore|Mumbai|Pune|Hyderabad|Chennai|Kolkata|Ahmedabad|Jaipur|Lucknow
    Noida|Gurugram|Gurgaon|Kochi|Coimbatore|Indore|Bhopal|Nagpur|Surat|Chandigarh
    Visakhapatnam|Thiruvananthapuram|Mysuru|Mysore|Vadodara|Patna|Kanpur|Guwahati
    Surathkal|Manipal|Vellore|Kharagpur|Roorkee|Warangal|Trichy|Tiruchirappalli
    London|Manchester|Birmingham|Edinburgh|Glasgow|Dublin|Berlin|Munich|Hamburg|Paris
    Lyon|Madrid|Barcelona|Lisbon|Rome|Milan|Amsterdam|Rotterdam|Brussels|Zurich|Geneva
    Vienna|Stockholm|Oslo|Copenhagen|Helsinki|Warsaw|Prague|Budapest|Athens|Istanbul
    New York|Brooklyn|San Francisco|Los Angeles|San Diego|San Jose|Seattle|Portland
    Austin|Dallas|Houston|San Antonio|Chicago|Boston|Philadelphia|Atlanta|Miami|Orlando
    Denver|Phoenix|Las Vegas|Detroit|Minneapolis|Nashville|Charlotte|Raleigh|Pittsburgh
    Columbus|Cleveland|Kansas City|St Louis|Salt Lake City|Sacramento|Toronto|Vancouver
    Montreal|Calgary|Ottawa|Sydney|Melbourne|Brisbane|Perth|Auckland|Wellington
    Tokyo|Osaka|Seoul|Beijing|Shanghai|Shenzhen|Hong Kong|Taipei|Bangkok|Jakarta
    Kuala Lumpur|Manila|Hanoi|Tel Aviv|Cairo|Lagos|Nairobi|Cape Town|Johannesburg
    Sao Paulo|Rio de Janeiro|Buenos Aires|Santiago|Bogota|Lima
    """.strip().splitlines()
    for token in line.split("|")
    if token.strip()
)

_LOCATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Austin, TX 78701 / Austin, TX
    re.compile(r"\b([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2}),\s*([A-Z]{2})\b(?:\s+\d{5}(?:-\d{4})?)?"),
    # Bengaluru, Karnataka, India
    re.compile(
        r"\b([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2}),\s*"
        r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2})"
        r"(?:,\s*([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2}))?"
    ),
)

_REMOTE_RE = re.compile(r"\b(?:remote|hybrid|work\s+from\s+home)\b", re.IGNORECASE)


def is_us_state_code(text: str) -> bool:
    """True for a two-letter US state abbreviation written in capitals."""
    candidate = collapse_whitespace(text).strip(" .,")
    return len(candidate) == 2 and candidate.isupper() and candidate in _US_STATE_ABBREVIATIONS


def is_known_place(text: str) -> bool:
    """True when ``text`` is a country, state, major city or US state code."""
    candidate = collapse_whitespace(text).strip(" .,")
    if not candidate:
        return False
    if is_us_state_code(candidate):
        return True
    return candidate.lower() in _KNOWN_PLACES


def extract_location(
    header_lines: list[str],
    nlp: NlpEngine | None = None,
    nlp_doc: Any | None = None,
) -> tuple[str, str]:
    """Candidate location plus the reason it was chosen."""
    cleaned_lines = [_strip_contact_noise(line) for line in header_lines[:HEADER_LINE_WINDOW]]

    for line in cleaned_lines:
        if not line:
            continue
        for pattern in _LOCATION_PATTERNS:
            for match in pattern.finditer(line):
                parts = [part for part in match.groups() if part]
                if not parts:
                    continue
                if any(is_known_place(part) for part in parts):
                    return (
                        ", ".join(collapse_whitespace(part) for part in parts),
                        "Matched a city/state/country pattern in the resume header",
                    )

    # A bare known place on its own line ("Bengaluru, India" handled above;
    # this catches "Remote" or a single city).
    for line in cleaned_lines:
        candidate = collapse_whitespace(line).strip(" .,|")
        if candidate and is_known_place(candidate):
            return candidate, "Recognised place name in the resume header"
        if candidate and _REMOTE_RE.fullmatch(candidate):
            return candidate.title(), "Work-location keyword in the resume header"

    # Finally, let spaCy vote.
    if nlp is not None:
        header_text = "\n".join(cleaned_lines)
        entities = (
            NlpEngine.entities_from_doc(nlp_doc, ["GPE", "LOC"])
            if nlp_doc is not None
            else nlp.entities(header_text, ["GPE", "LOC"])
        )
        geo_names: list[str] = []
        for entity in entities:
            value = collapse_whitespace(entity.text).strip(" .,")
            if value and value.lower() not in {name.lower() for name in geo_names}:
                if nlp_doc is not None and entity.start_char > len(header_text) + 200:
                    continue
                geo_names.append(value)
        if geo_names:
            return ", ".join(geo_names[:3]), "Geographic entities detected by spaCy"

    return "", ""


def _strip_contact_noise(line: str) -> str:
    """Remove emails, URLs and phone numbers so only prose is left."""
    cleaned = _EMAIL_RE.sub(" ", line or "")
    cleaned = _GENERIC_URL_RE.sub(" ", cleaned)
    for _label, pattern in _LINK_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    for pattern, _score in _PHONE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"[|\u2022\u00b7]+", " ", cleaned)
    return collapse_whitespace(cleaned)


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def extract_contact(
    text: str,
    sections: list[SectionBlock] | None = None,
    nlp: NlpEngine | None = None,
    nlp_doc: Any | None = None,
    embedded_links: Iterable[str] = (),
) -> ContactInfo:
    """Build a :class:`ContactInfo` from the resume text.

    ``sections`` is optional; when supplied, the ``header`` and ``contact``
    blocks are searched first, which materially improves name and location
    accuracy on resumes that mention cities in their job history.
    """
    header_lines = _collect_header_lines(text, sections)
    header_text = "\n".join(header_lines)

    contact = ContactInfo()
    evidence: dict[str, str] = {}

    emails = extract_emails(header_text) or extract_emails(text)
    if emails:
        contact.email = emails[0]
        evidence["email"] = (
            "Found in the resume header"
            if emails[0] in header_text
            else "Found in the document body"
        )

    phones = extract_phones(header_text, header_text) or extract_phones(text, header_text)
    if phones:
        contact.phone = phones[0]
        evidence["phone"] = (
            "Highest-confidence phone pattern in the header"
            if phones[0] in header_text
            else "Highest-confidence phone pattern in the document"
        )

    contact.links = extract_links(text, embedded_links)
    if contact.links:
        evidence["links"] = "Matched known profile hosts in text and embedded hyperlinks"

    name, name_reason = extract_name(header_lines, text, nlp, nlp_doc)
    if name:
        contact.name = name
        evidence["name"] = name_reason

    location, location_reason = extract_location(header_lines, nlp, nlp_doc)
    if location:
        contact.location = location
        evidence["location"] = location_reason

    contact.evidence = evidence
    return contact


def _collect_header_lines(text: str, sections: list[SectionBlock] | None) -> list[str]:
    """Lines that make up the contact block, in document order."""
    if sections:
        lines: list[str] = []
        for block in sections:
            if block.key in ("header", "contact"):
                lines.extend(block.lines)
        if lines:
            return [line for line in lines if line.strip()][:HEADER_LINE_WINDOW]

    return [line for line in (text or "").splitlines() if line.strip()][:HEADER_LINE_WINDOW]
