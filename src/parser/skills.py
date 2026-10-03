"""Skill extraction: dictionary matching, regex and spaCy, in that order.

Three complementary passes run over the resume:

1. **Dictionary pass (regex).** ``data/skills.json`` maps a canonical display
   name to its aliases and category. Matching is done with word-boundary
   regexes built per alias, which is the only approach that handles ``C++``,
   ``C#``, ``.NET``, ``Node.js`` and ``scikit-learn`` correctly - all of them
   break naive tokenisation.
2. **Ambiguity guard.** One- and two-character names (``C``, ``R``, ``Go``)
   are flagged ``strict`` in the dictionary and only accepted inside a skills
   section or an explicit technology list, where a bare token genuinely means
   the language.
3. **Discovery pass (spaCy).** Inside the skills section, delimiter-separated
   items and short noun chunks that are *not* in the dictionary are kept as
   "Other", so a niche tool still shows up. A spaCy ``PhraseMatcher`` run
   confirms multi-word dictionary hits, which is recorded as evidence.

Every skill carries where it was found and how confident the match is, so the
UI can explain itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..models import SectionBlock, Skill
from ..processing.nlp import NlpEngine
from ..processing.normalize import collapse_whitespace, strip_bullet
from ..settings import SKILL_CATEGORY_ORDER, SKILL_DICTIONARY_PATH

#: Characters that separate items in a skills list.
_ITEM_SPLIT_RE = re.compile(r"[,;/|\u2022\u00b7\u2023\u25aa\u25cf\t]+|\s{3,}")

#: ``Languages: Python, Java`` - a sub-heading inside the skills section.
_SUBHEADING_RE = re.compile(r"^\s*([A-Za-z][A-Za-z&+/ .'\-]{1,44}?)\s*[:\u2013]\s*(\S.*)$")

#: Proficiency noise to strip from a discovered item.
_QUALIFIER_RE = re.compile(
    r"\b(?:proficient(?:\s+in)?|experienced(?:\s+in|\s+with)?|familiar(?:\s+with)?|"
    r"knowledge(?:\s+of)?|working\s+knowledge(?:\s+of)?|exposure(?:\s+to)?|"
    r"hands[\s-]on(?:\s+experience)?(?:\s+(?:in|with))?|expertise(?:\s+in)?|"
    r"skilled(?:\s+in)?|advanced|intermediate|beginner|basic|expert|fluent|"
    r"strong|good|excellent|basics(?:\s+of)?)\b",
    re.IGNORECASE,
)

#: Parenthetical levels: "Python (Advanced)" -> "Python".
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*")

#: URLs and email addresses are removed before dictionary matching. Without
#: this, "github.com/jane" tags the candidate with GitHub and
#: "jane@oracle.com" tags them with Oracle - neither is a claimed skill.
_URL_OR_EMAIL_RE = re.compile(
    r"(?:https?://|www\.)\S+|\b[\w.+-]+@[\w-]+\.[\w.-]*\w|\b[\w-]+\.(?:com|org|net|io|dev|ai|co|me)\b(?:/\S*)?",
    re.IGNORECASE,
)

#: An explicit technology list, wherever it appears.
_TECH_LABEL_RE = re.compile(
    r"^\s*(?:tech(?:nologies)?|tech\s*stack|stack|tools|built\s+with|"
    r"skills|languages|frameworks|libraries)\b\s*(?:used)?\s*[:\u2013-]",
    re.IGNORECASE,
)

#: Longest discovered item we will accept as a skill name.
_MAX_DISCOVERED_WORDS = 4
_MAX_DISCOVERED_CHARS = 40

#: Items that are structural noise rather than skills.
_DISCOVERY_STOPWORDS = frozenset(
    {
        "and", "or", "etc", "etc.", "others", "other", "various", "including",
        "skills", "skill", "tools", "technologies", "technology", "frameworks",
        "framework", "languages", "language", "databases", "database", "libraries",
        "library", "concepts", "platforms", "platform", "software", "systems",
        "methodologies", "soft skills", "technical skills", "programming",
        "programming languages", "web technologies", "operating systems", "os",
        "years", "year", "experience", "n a", "na", "nil", "none",
    }
)

#: Sub-heading text inside a skills block -> dictionary category.
_SUBHEADING_CATEGORY_HINTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:programming|coding|language)", re.IGNORECASE), "Programming Languages"),
    (re.compile(r"\b(?:framework|librar|web\s*tech)", re.IGNORECASE), "Frameworks"),
    (re.compile(r"\b(?:database|datastore|dbms|storage)", re.IGNORECASE), "Databases"),
    (re.compile(r"\b(?:cloud|devops|infrastructure|platform|deployment)", re.IGNORECASE), "Cloud"),
    (re.compile(r"\b(?:data|machine\s*learning|ml|ai|analytics|science)", re.IGNORECASE), "Data & ML"),
    (re.compile(r"\b(?:tool|ide|software|utilit)", re.IGNORECASE), "Tools"),
    (re.compile(r"\b(?:soft|interpersonal|personal|behaviou?ral)", re.IGNORECASE), "Soft Skills"),
)


@dataclass(slots=True, frozen=True)
class SkillDefinition:
    """One entry of the configurable dictionary, compiled for matching."""

    name: str
    category: str
    aliases: tuple[str, ...]
    #: Only match inside a skills section or an explicit technology list.
    strict: bool
    #: The name is also an ordinary English word ("react", "express", "rust").
    #: Outside a skills section such a match must carry the technology's own
    #: capitalisation, so the verb in "I react quickly" is not a skill.
    common_word: bool
    pattern: re.Pattern[str]
    cased_pattern: re.Pattern[str]


class SkillDictionary:
    """The configurable skill vocabulary loaded from ``data/skills.json``."""

    def __init__(self, definitions: Sequence[SkillDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._by_lookup: dict[str, SkillDefinition] = {}
        for definition in self._definitions:
            for alias in (definition.name, *definition.aliases):
                self._by_lookup.setdefault(_lookup_key(alias), definition)

    def __len__(self) -> int:
        return len(self._definitions)

    @property
    def definitions(self) -> tuple[SkillDefinition, ...]:
        return self._definitions

    @property
    def categories(self) -> list[str]:
        ordered = [c for c in SKILL_CATEGORY_ORDER if any(d.category == c for d in self._definitions)]
        extra = sorted({d.category for d in self._definitions} - set(ordered))
        return ordered + extra

    def lookup(self, text: str) -> SkillDefinition | None:
        """Exact (normalised) lookup of a skill name or alias."""
        return self._by_lookup.get(_lookup_key(text))

    def phrase_terms(self, min_words: int = 2) -> list[str]:
        """Multi-word names and aliases, for the spaCy PhraseMatcher pass."""
        terms: list[str] = []
        for definition in self._definitions:
            for alias in (definition.name, *definition.aliases):
                if len(alias.split()) >= min_words:
                    terms.append(alias)
        return terms


def _lookup_key(text: str) -> str:
    """Normalise a skill string for dictionary lookup."""
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _build_alias_pattern(aliases: Iterable[str], ignore_case: bool = True) -> re.Pattern[str]:
    """Compile a word-boundary regex that matches any of ``aliases``.

    Standard ``\\b`` boundaries fail for names that start or end with a symbol:
    ``\\bC++\\b`` never matches because there is no word character after ``+``.
    Boundaries are therefore chosen per alias based on its first and last
    character.
    """
    parts: list[str] = []
    for alias in sorted(set(aliases), key=len, reverse=True):
        alias = alias.strip()
        if not alias:
            continue
        # Allow any whitespace or a hyphen where the alias has a space, so
        # "Spring Boot" also matches "Spring-Boot" and a line-wrapped variant.
        body = r"[\s\-]+".join(re.escape(word) for word in alias.split())
        prefix = r"(?<![\w+#])" if alias[0].isalnum() else r"(?<!\w)"
        suffix = r"(?![\w+#])" if alias[-1].isalnum() else r"(?!\w)"
        parts.append(f"{prefix}{body}{suffix}")
    if not parts:
        return re.compile(r"(?!x)x")  # never matches
    return re.compile("|".join(parts), re.IGNORECASE if ignore_case else 0)


def load_skill_dictionary(path: Path | None = None) -> SkillDictionary:
    """Load and compile the skill dictionary.

    Raises:
        FileNotFoundError: the dictionary file is missing.
        ValueError: the file is present but not valid JSON in the expected shape.
    """
    target = Path(path) if path else SKILL_DICTIONARY_PATH
    try:
        raw: Any = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except json.JSONDecodeError as exc:
        raise ValueError(f"{target.name} is not valid JSON: {exc}") from exc

    categories = raw.get("categories") if isinstance(raw, dict) else None
    if not isinstance(categories, dict):
        raise ValueError(f"{target.name} must contain a top-level 'categories' object.")

    definitions: list[SkillDefinition] = []
    for category, entries in categories.items():
        if not isinstance(entries, dict):
            continue
        options = entries.get("_options") if isinstance(entries.get("_options"), dict) else {}
        category_strict = bool(options.get("strict", False))

        for name, config in entries.items():
            if name == "_options":
                continue
            config = config if isinstance(config, dict) else {}
            aliases = tuple(
                str(alias) for alias in config.get("aliases", []) if str(alias).strip()
            )
            definitions.append(
                SkillDefinition(
                    name=str(name).strip(),
                    category=str(category).strip() or "Other",
                    aliases=aliases,
                    strict=bool(config.get("strict", category_strict)),
                    common_word=bool(config.get("common_word", False)),
                    pattern=_build_alias_pattern((name, *aliases)),
                    cased_pattern=_build_alias_pattern(
                        (name, *aliases), ignore_case=False
                    ),
                )
            )
    if not definitions:
        raise ValueError(f"{target.name} contains no skill definitions.")
    return SkillDictionary(definitions)


@lru_cache(maxsize=4)
def get_skill_dictionary(path: str | None = None) -> SkillDictionary:
    """Cached accessor for the skill dictionary."""
    return load_skill_dictionary(Path(path) if path else None)


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def extract_skills(
    text: str,
    sections: Sequence[SectionBlock] | None = None,
    dictionary: SkillDictionary | None = None,
    nlp: NlpEngine | None = None,
) -> list[Skill]:
    """Extract categorised skills from a resume.

    Args:
        text: the full normalised resume text.
        sections: labelled blocks; the ``skills`` and ``projects`` blocks make
            strict matches and discovery possible.
        dictionary: override the vocabulary (tests, custom deployments).
        nlp: optional spaCy engine for the discovery and confirmation passes.

    Returns:
        Skills ordered by category (per :data:`SKILL_CATEGORY_ORDER`) then by
        name, de-duplicated on canonical name.
    """
    vocabulary = dictionary or get_skill_dictionary()
    blocks = list(sections or [])

    skills_text = _section_text(blocks, "skills")
    #: Regions where a bare "C" or "R" really does mean the language.
    strict_text = "\n".join(
        part for part in (skills_text, _technology_lines(blocks)) if part
    )
    open_text = _URL_OR_EMAIL_RE.sub(" ", text or "")

    found: dict[str, Skill] = {}

    # Pass 1 + 2: dictionary matching with the ambiguity guards.
    for definition in vocabulary.definitions:
        match = _match_definition(definition, strict_text, open_text)
        if match is None:
            continue
        where = _locate_section(blocks, match, definition.strict, skills_text)
        found[_lookup_key(definition.name)] = Skill(
            name=definition.name,
            category=definition.category,
            source="dictionary",
            found_in=where,
            confidence="high" if (definition.strict or where == "skills") else "medium",
        )

    # Pass 3: discovery inside the skills section only.
    if skills_text:
        for name, category in _discover_skills(skills_text, vocabulary, nlp):
            key = _lookup_key(name)
            if key in found:
                continue
            found[key] = Skill(
                name=name,
                category=category,
                source="section",
                found_in="skills",
                confidence="medium",
            )

    # Confirmation pass: note which multi-word hits spaCy also saw in context.
    if nlp is not None and nlp.available and text:
        confirmed = {
            _lookup_key(phrase) for phrase in nlp.phrase_matches(vocabulary.phrase_terms(), text)
        }
        for skill in found.values():
            if _lookup_key(skill.name) in confirmed:
                skill.confidence = "high"

    return _sort_skills(found.values(), vocabulary)


def _match_definition(
    definition: SkillDefinition, strict_text: str, open_text: str
) -> str | None:
    """Find a skill in the resume, returning the matched text or ``None``.

    Applies the two ambiguity guards:

    * ``strict`` skills are searched only in the skills section and explicit
      technology lists, which is where a bare "C" or "Go" is unambiguous.
    * ``common_word`` skills are matched case-insensitively inside those same
      lists, but case-sensitively everywhere else - so "React" in a sentence
      counts and "react" does not.
    """
    if strict_text:
        found = definition.pattern.search(strict_text)
        if found:
            return found.group(0)
    if definition.strict or not open_text:
        return None

    pattern = definition.cased_pattern if definition.common_word else definition.pattern
    found = pattern.search(open_text)
    return found.group(0) if found else None


def _sort_skills(skills: Iterable[Skill], vocabulary: SkillDictionary) -> list[Skill]:
    """Order skills by category precedence, then alphabetically."""
    order = {category: index for index, category in enumerate(SKILL_CATEGORY_ORDER)}
    fallback = len(order) + 1
    for category in vocabulary.categories:
        order.setdefault(category, fallback)
    return sorted(
        skills,
        key=lambda skill: (order.get(skill.category, fallback), skill.name.lower()),
    )


def _section_text(blocks: Sequence[SectionBlock], key: str) -> str:
    """Text of the first block with ``key``, or ``""``."""
    for block in blocks:
        if block.key == key:
            return block.text
    return ""


def _technology_lines(blocks: Sequence[SectionBlock]) -> str:
    """Explicit technology lists found outside the skills section.

    Project entries commonly carry ``Technologies: Python, Go`` or
    ``Project Name | Python, Go``; those are as authoritative as a skills
    section, so strict matches are allowed there too.
    """
    collected: list[str] = []
    for block in blocks:
        if block.key not in ("projects", "experience", "summary", "certifications"):
            continue
        for line in block.lines:
            stripped = strip_bullet(line)
            if _TECH_LABEL_RE.match(stripped):
                collected.append(stripped)
            elif block.key == "projects" and "|" in stripped and len(stripped) <= 140:
                # "Smart Resume Parser | Python, spaCy, Streamlit"
                collected.append(stripped.split("|", 1)[1])
    return "\n".join(collected)


def _locate_section(
    blocks: Sequence[SectionBlock], matched: str, strict: bool, skills_text: str
) -> str:
    """Which section a matched skill came from (best effort, for evidence)."""
    if strict or (skills_text and matched.lower() in skills_text.lower()):
        return "skills"
    for block in blocks:
        if block.key != "header" and matched.lower() in block.text.lower():
            return block.key
    for block in blocks:
        if block.key == "header" and matched.lower() in block.text.lower():
            return "header"
    return ""


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #


def _discover_skills(
    skills_text: str, vocabulary: SkillDictionary, nlp: NlpEngine | None
) -> list[tuple[str, str]]:
    """Find skills-section items that are not in the dictionary.

    Returns ``(display_name, category)`` pairs. The category comes from the
    nearest sub-heading when there is one ("Databases: ...") and defaults to
    "Other".
    """
    discovered: list[tuple[str, str]] = []
    seen: set[str] = set()
    current_category = "Other"

    for raw_line in skills_text.splitlines():
        line = strip_bullet(raw_line).strip()
        if not line:
            continue

        subheading = _SUBHEADING_RE.match(line)
        if subheading:
            current_category = _category_from_subheading(subheading.group(1))
            line = subheading.group(2)

        for item in _ITEM_SPLIT_RE.split(line):
            name = _clean_item(item)
            if not name:
                continue
            key = _lookup_key(name)
            if key in seen or vocabulary.lookup(name) is not None:
                continue
            seen.add(key)
            discovered.append((name, current_category))

    # Let spaCy contribute noun chunks for prose-style skills sections
    # ("Experienced with distributed tracing and chaos engineering").
    #
    # Deliberately per line, and only for lines that are *not* a structured
    # "Label: a, b, c" list. Running the parser across a whole block of such
    # lists makes it bridge the line break and invent phrases like
    # "JavaScript Frameworks" out of the tail of one line and the label of
    # the next.
    if nlp is not None and nlp.available and len(discovered) < 3:
        for raw_line in skills_text.splitlines():
            line = strip_bullet(raw_line).strip()
            if not line or _SUBHEADING_RE.match(line):
                continue
            if len(_ITEM_SPLIT_RE.split(line)) > 2:
                continue  # already a delimited list; nothing for NLP to add
            for chunk in nlp.noun_chunks(line, max_words=_MAX_DISCOVERED_WORDS):
                name = _clean_item(chunk)
                if not name:
                    continue
                key = _lookup_key(name)
                if key in seen or vocabulary.lookup(name) is not None:
                    continue
                seen.add(key)
                discovered.append((name, "Other"))

    return discovered


def _category_from_subheading(label: str) -> str:
    """Map a skills sub-heading to a dictionary category."""
    for pattern, category in _SUBHEADING_CATEGORY_HINTS:
        if pattern.search(label):
            return category
    return "Other"


def _clean_item(item: str) -> str:
    """Normalise one list item into a skill name, or ``""`` if it is noise."""
    text = _PARENTHETICAL_RE.sub(" ", item or "")
    text = _QUALIFIER_RE.sub(" ", text)
    text = re.sub(r"^\s*(?:and|or|&|plus|also)\b\s*", "", text, flags=re.IGNORECASE)
    text = collapse_whitespace(text).strip(" .,:;|*\u2013\u2022-")

    if not text or len(text) > _MAX_DISCOVERED_CHARS:
        return ""

    words = text.split()
    if len(words) > _MAX_DISCOVERED_WORDS:
        return ""
    if _lookup_key(text) in _DISCOVERY_STOPWORDS:
        return ""

    # Needs real letters and must not be mostly digits or punctuation.
    letters = sum(char.isalpha() for char in text)
    if letters < 2 or letters < len(text) / 2:
        return ""

    # Prose fragments ("a strong understanding of distributed systems") are
    # not skill names.
    if len(words) > 1 and text[0].islower() and re.search(r"\b(?:of|the|a|an|to|with|in)\b", text, re.IGNORECASE):
        return ""
    return text
