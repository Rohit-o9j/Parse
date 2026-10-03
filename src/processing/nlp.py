"""spaCy integration, wrapped so the parser never hard-depends on it.

Why a wrapper at all? Two reasons.

* **Availability.** ``en_core_web_sm`` is a separate download. If a reviewer
  clones the repo and forgets ``python -m spacy download en_core_web_sm`` the
  application must still run: every regex-driven field keeps working and the
  UI explains which capability is reduced. :class:`NlpEngine` turns a missing
  model into a boolean flag instead of an ImportError at start-up.
* **Cost.** Loading a pipeline takes a second or two and resumes can be long.
  The engine is a singleton, the parser only feeds it the regions it needs,
  and the unused ``lemmatizer``/``tagger`` components are disabled.

What spaCy is actually used for here:

``PERSON``  corroborating the candidate name found in the header
``GPE``/``LOC``  locating the city/country line
``ORG``  distinguishing an employer from a job title
noun chunks  discovering skills that are not in the dictionary
``PhraseMatcher``  confirming multi-word dictionary skills in context
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..settings import NLP_CHAR_BUDGET, SPACY_MODEL_PREFERENCE


@dataclass(slots=True, frozen=True)
class Entity:
    """A named entity, decoupled from spaCy's own objects."""

    text: str
    label: str
    start_char: int
    end_char: int


class NlpEngine:
    """Lazy, fault-tolerant façade over a spaCy pipeline.

    All methods are safe to call when no model is installed; they return empty
    results and :attr:`available` reports ``False``.
    """

    #: Components we never read from. The tagger and parser are deliberately
    #: kept: ``doc.noun_chunks`` needs both POS tags and dependencies.
    _DISABLED = ("lemmatizer",)

    def __init__(self, model_names: Iterable[str] = SPACY_MODEL_PREFERENCE) -> None:
        self._model_names = tuple(model_names)
        self._nlp: Any | None = None
        self._blank: Any | None = None
        self._model_name: str = ""
        self._load_error: str = ""
        self._spacy: Any | None = None
        self._load()

    # -- lifecycle ---------------------------------------------------------- #

    def _load(self) -> None:
        try:
            import spacy
        except Exception as exc:  # pragma: no cover - spaCy is a hard requirement
            self._load_error = f"spaCy is not installed ({exc})."
            return

        self._spacy = spacy
        try:
            self._blank = spacy.blank("en")
        except Exception:  # pragma: no cover
            self._blank = None

        attempts: list[str] = []
        for name in self._model_names:
            try:
                self._nlp = spacy.load(name, disable=list(self._DISABLED))
                self._model_name = name
                return
            except Exception as exc:
                attempts.append(f"{name}: {type(exc).__name__}")

        self._load_error = (
            "No spaCy language model could be loaded ("
            + "; ".join(attempts)
            + "). Run: python -m spacy download en_core_web_sm"
        )

    # -- introspection ------------------------------------------------------ #

    @property
    def available(self) -> bool:
        """True when a statistical model is loaded and usable."""
        return self._nlp is not None

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def load_error(self) -> str:
        return self._load_error

    def status(self) -> dict[str, Any]:
        """Short description of the engine for the diagnostics panel."""
        return {
            "available": self.available,
            "model": self._model_name or None,
            "error": self._load_error or None,
            "sentencizer_only": self._nlp is None and self._blank is not None,
        }

    # -- analysis ----------------------------------------------------------- #

    def analyze(self, text: str) -> Any | None:
        """Run the full pipeline over ``text`` (truncated to the char budget)."""
        if not self.available or not text:
            return None
        try:
            return self._nlp(text[:NLP_CHAR_BUDGET])  # type: ignore[misc]
        except Exception:  # pragma: no cover - pipeline errors must not crash parsing
            return None

    def entities(self, text: str, labels: Iterable[str] | None = None) -> list[Entity]:
        """Named entities in ``text``, optionally filtered by label."""
        doc = self.analyze(text)
        return self.entities_from_doc(doc, labels)

    @staticmethod
    def entities_from_doc(doc: Any | None, labels: Iterable[str] | None = None) -> list[Entity]:
        """Entity list from an already-analysed document."""
        if doc is None:
            return []
        wanted = {label.upper() for label in labels} if labels else None
        found: list[Entity] = []
        try:
            for ent in doc.ents:
                if wanted and ent.label_.upper() not in wanted:
                    continue
                text = ent.text.strip()
                if text:
                    found.append(Entity(text, ent.label_, ent.start_char, ent.end_char))
        except Exception:  # pragma: no cover
            return found
        return found

    def noun_chunks(self, text: str, max_words: int = 5) -> list[str]:
        """Noun phrases in ``text``, used to discover skills off-dictionary."""
        doc = self.analyze(text)
        if doc is None:
            return []
        chunks: list[str] = []
        try:
            for chunk in doc.noun_chunks:
                phrase = chunk.text.strip()
                if phrase and len(phrase.split()) <= max_words:
                    chunks.append(phrase)
        except Exception:
            # ``noun_chunks`` needs a parser; models without one raise here.
            return []
        return chunks

    def phrase_matches(self, terms: Iterable[str], text: str) -> set[str]:
        """Case-insensitive phrase lookup via spaCy's :class:`PhraseMatcher`.

        Works off a blank English pipeline, so it stays available even when no
        statistical model is installed.
        """
        vocab_source = self._nlp or self._blank
        if vocab_source is None or self._spacy is None or not text:
            return set()

        term_list = [term for term in terms if term and term.strip()]
        if not term_list:
            return set()

        try:
            from spacy.matcher import PhraseMatcher

            matcher = PhraseMatcher(vocab_source.vocab, attr="LOWER")
            matcher.add("SKILL", [vocab_source.make_doc(term) for term in term_list])
            doc = vocab_source.make_doc(text[:NLP_CHAR_BUDGET])
            return {doc[start:end].text for _match_id, start, end in matcher(doc)}
        except Exception:  # pragma: no cover
            return set()

    def sentences(self, text: str) -> list[str]:
        """Sentence split, falling back to a blank pipeline + sentencizer."""
        doc = self.analyze(text)
        if doc is not None:
            try:
                return [s.text.strip() for s in doc.sents if s.text.strip()]
            except Exception:
                pass
        return [line.strip() for line in (text or "").splitlines() if line.strip()]


# --------------------------------------------------------------------------- #
# Singleton access
# --------------------------------------------------------------------------- #

_ENGINE: NlpEngine | None = None


def get_nlp_engine() -> NlpEngine:
    """Return the process-wide :class:`NlpEngine`, constructing it on first use."""
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = NlpEngine()
    return _ENGINE


def reset_nlp_engine() -> None:
    """Drop the cached engine (used by tests)."""
    global _ENGINE
    _ENGINE = None
