"""Smart Resume Parser.

Layered architecture, each layer depending only on the ones above it:

``src.extraction``
    Uploaded bytes -> plain text (PyMuPDF / python-docx) plus typed errors.
``src.processing``
    Plain text -> normalised lines, labelled sections, spaCy document, dates.
``src.parser``
    Labelled sections -> structured fields (contact, skills, education,
    experience, projects) and the pipeline that orchestrates them.
``src.export``
    Structured fields -> JSON / CSV payloads.
``src.ui``
    Streamlit presentation only. No parsing logic lives here.
"""

from .settings import APP_SUBTITLE, APP_TITLE, APP_VERSION

__version__ = APP_VERSION
__all__ = ["APP_SUBTITLE", "APP_TITLE", "APP_VERSION", "__version__"]
