"""Smart Resume Parser - Streamlit application.

This module is presentation and orchestration only. It decides *when* to
parse and *how* to display the result; every extraction decision lives under
``src/``. The page follows the user's journey top to bottom:

    Upload -> Processing -> Overview -> Skills -> Education -> Experience
           -> Projects -> Extracted text -> Export

Run with::

    streamlit run app.py
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import streamlit as st

from src.export import (
    export_filename,
    to_csv,
    to_csv_bytes,
    to_json,
    to_json_bytes,
)
from src.extraction import ExtractionError
from src.models import ParsedResume
from src.parser import STAGES, ResumeParser
from src.processing.nlp import get_nlp_engine
from src.settings import (
    APP_SUBTITLE,
    APP_TITLE,
    MAX_FILE_SIZE_MB,
    NOT_DETECTED,
    SAMPLE_RESUME_DIR,
    SUPPORTED_EXTENSIONS,
)
from src.ui import components as ui
from src.ui.theme import stylesheet

# --------------------------------------------------------------------------- #
# Page setup
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title=APP_TITLE,
    page_icon="\U0001f4c4",
    layout="wide",
    initial_sidebar_state="expanded",
)

#: How long the staged checklist dwells on each step, in seconds. Enough to be
#: legible, short enough not to feel like theatre.
_STAGE_DWELL = 0.18


# --------------------------------------------------------------------------- #
# Cached resources
# --------------------------------------------------------------------------- #


@st.cache_resource(show_spinner=False)
def get_parser() -> ResumeParser:
    """One parser (and therefore one spaCy model) per server process."""
    return ResumeParser()


@st.cache_resource(show_spinner=False)
def nlp_status() -> dict[str, Any]:
    """Model availability, read once and reused for the sidebar badge."""
    return get_nlp_engine().status()


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #


def init_state() -> None:
    defaults: dict[str, Any] = {
        "appearance": "light",
        "show_evidence": True,
        "csv_layout": "detailed",
        "resume": None,
        "error": None,
        "source_name": "",
        "pending": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def reset_results() -> None:
    st.session_state.resume = None
    st.session_state.error = None
    st.session_state.source_name = ""
    st.session_state.pending = None


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            f'<div class="srp-sidebar-brand">{ui.esc(APP_TITLE)}</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        st.caption("APPEARANCE")
        st.radio(
            "Appearance",
            options=("light", "dark"),
            format_func=str.title,
            key="appearance",
            horizontal=True,
            label_visibility="collapsed",
        )

        st.caption("DISPLAY")
        st.toggle(
            "Show match evidence",
            key="show_evidence",
            help=(
                "Adds the reason each value was chosen, and a tooltip on every "
                "skill tag explaining how it was matched."
            ),
        )

        st.divider()
        st.caption("ANALYSIS MODE")
        status = nlp_status()
        if status.get("available"):
            # The model's package name is provenance, not product copy; it
            # lives in the diagnostics panel with the rest of the audit trail.
            st.markdown(
                '<div class="srp-sidebar-note"><b>Full analysis.</b> Language '
                "understanding is active, so names, locations and employers are "
                "recognised in context as well as by pattern."
                "</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="srp-sidebar-note"><b>Pattern matching only.</b> '
                "Parsing works, but name and location detection are less "
                "accurate without the language model."
                "</div>",
                unsafe_allow_html=True,
            )
            st.caption("Setup: python -m spacy download en_core_web_sm")

        st.divider()
        st.caption("HOW IT WORKS")
        st.markdown(
            '<div class="srp-sidebar-note">'
            "<b>1. Read</b> &mdash; the document's text is extracted, including "
            "multi-column layouts, tables, headers and embedded links.<br><br>"
            "<b>2. Analyse</b> &mdash; the text is cleaned and split into "
            "labelled sections.<br><br>"
            "<b>3. Structure</b> &mdash; every field is parsed with the most "
            "reliable method available for it: pattern rules for contact "
            "details and dates, a curated dictionary for skills, and entity "
            "recognition for names, places and employers.<br><br>"
            "<b>Nothing is invented.</b> Anything the parser cannot determine "
            f"is reported as &ldquo;{ui.esc(NOT_DETECTED)}&rdquo; rather than "
            "guessed."
            "</div>",
            unsafe_allow_html=True,
        )

        if st.session_state.resume is not None:
            st.divider()
            if st.button("Parse another resume", use_container_width=True):
                reset_results()
                st.rerun()


# --------------------------------------------------------------------------- #
# 1. Upload
# --------------------------------------------------------------------------- #


def sample_files() -> list[Path]:
    if not SAMPLE_RESUME_DIR.exists():
        return []
    return sorted(
        path
        for path in SAMPLE_RESUME_DIR.iterdir()
        if path.suffix.lower().lstrip(".") in SUPPORTED_EXTENSIONS
    )


def render_upload() -> None:
    ui.section_header("Upload resume", "Step 1 of 3")

    formats = ", ".join(extension.upper() for extension in SUPPORTED_EXTENSIONS)
    ui.note(
        "Upload your resume to automatically extract skills, education, "
        "experience and contact information."
    )
    st.write("")

    upload = st.file_uploader(
        "Drag and drop your resume here",
        type=list(SUPPORTED_EXTENSIONS),
        accept_multiple_files=False,
        help=f"Supported formats: {formats}. Maximum size: {MAX_FILE_SIZE_MB} MB.",
    )
    st.caption(
        f"Supported formats: {formats}  \u00b7  Maximum file size: {MAX_FILE_SIZE_MB} MB"
        "  \u00b7  Your file is processed in memory and never stored."
    )

    left, right = st.columns([1, 2.4])
    with left:
        analyze = st.button(
            "Analyze Resume",
            type="primary",
            use_container_width=True,
            disabled=upload is None,
        )
    with right:
        if upload is not None:
            size_kb = len(upload.getvalue()) / 1024
            st.caption(f"Ready: **{upload.name}** ({size_kb:,.0f} KB)")
        else:
            st.caption("Select a PDF or DOCX file to enable analysis.")

    if analyze and upload is not None:
        st.session_state.pending = (upload.getvalue(), upload.name)
        st.rerun()

    samples = sample_files()
    if samples:
        with st.expander("Or try a sample resume", expanded=False):
            st.caption(
                "Real PDF and DOCX files, parsed live when you pick one. "
                "Nothing here is pre-computed."
            )
            columns = st.columns(min(len(samples), 4))
            for index, path in enumerate(samples):
                with columns[index % len(columns)]:
                    label = f"{path.stem.replace('_', ' ').title()} ({path.suffix.lstrip('.')})"
                    if st.button(label, key=f"sample-{path.name}", use_container_width=True):
                        st.session_state.pending = (path.read_bytes(), path.name)
                        st.rerun()


# --------------------------------------------------------------------------- #
# 2. Processing
# --------------------------------------------------------------------------- #


def run_parse(data: bytes, file_name: str) -> None:
    """Parse with a staged progress view, storing the result in session state."""
    ui.section_header("Processing", "Step 2 of 3")

    labels = [stage.label for stage in STAGES]
    placeholder = st.empty()
    progress = st.progress(0.0, text="Starting\u2026")

    placeholder.markdown(ui.stage_list(labels, 0), unsafe_allow_html=True)

    state = {"done": 0}

    def on_stage(_key: str, index: int, total: int) -> None:
        state["done"] = index
        placeholder.markdown(ui.stage_list(labels, index), unsafe_allow_html=True)
        progress.progress(index / total, text=labels[min(index, total - 1)])
        time.sleep(_STAGE_DWELL)

    try:
        parser = get_parser()
        resume = parser.parse_file(data, file_name=file_name, progress=on_stage)
    except ExtractionError as error:
        placeholder.markdown(ui.stage_list(labels, state["done"]), unsafe_allow_html=True)
        progress.empty()
        st.session_state.error = {"message": error.message, "hint": error.hint}
        st.session_state.resume = None
    except Exception as error:  # unexpected: show it, do not crash the page
        progress.empty()
        st.session_state.error = {
            "message": "An unexpected error occurred while parsing this document.",
            "hint": f"{type(error).__name__}: {error}",
        }
        st.session_state.resume = None
    else:
        placeholder.markdown(ui.stage_list(labels, len(labels)), unsafe_allow_html=True)
        progress.progress(1.0, text="Done")
        st.session_state.resume = resume
        st.session_state.source_name = file_name
        st.session_state.error = None
    finally:
        st.session_state.pending = None

    time.sleep(0.15)
    st.rerun()


def render_error() -> None:
    error = st.session_state.error or {}
    ui.section_header("Could not read this file")
    ui.note(
        f"<b>{ui.esc(error.get('message', 'Unknown error'))}</b>", kind="danger"
    )
    if error.get("hint"):
        st.write("")
        ui.note(ui.esc(error["hint"]))
    st.write("")
    if st.button("Try another file", type="primary"):
        reset_results()
        st.rerun()


# --------------------------------------------------------------------------- #
# 3. Results
# --------------------------------------------------------------------------- #


def render_metrics(resume: ParsedResume) -> None:
    diagnostics = resume.diagnostics
    columns = st.columns(5)
    with columns[0]:
        ui.metric("Profile completeness", f"{resume.completeness()}%", percent=resume.completeness())
    with columns[1]:
        ui.metric("Skills detected", len(resume.skills))
    with columns[2]:
        ui.metric("Roles", len(resume.experience))
    with columns[3]:
        ui.metric("Sections recognised", len(resume.detected_section_keys))
    with columns[4]:
        ui.metric("Words extracted", f"{diagnostics.get('word_count', 0):,}")


def render_overview(resume: ParsedResume) -> None:
    contact = resume.contact
    evidence = contact.evidence if st.session_state.show_evidence else {}

    ui.section_header("Resume overview", f"Source: {resume.extraction.file_name}")

    top = st.columns([1.3, 1.3, 1])
    with top[0]:
        ui.field_card("Candidate", contact.name, evidence.get("name", ""), large=True)
    with top[1]:
        ui.field_card(
            "Email",
            contact.email,
            evidence.get("email", ""),
            link=f"mailto:{contact.email}" if contact.email else "",
        )
    with top[2]:
        ui.field_card("Phone", contact.phone, evidence.get("phone", ""))

    st.write("")
    bottom = st.columns([1.3, 1.3, 1])
    with bottom[0]:
        ui.field_card("Location", contact.location, evidence.get("location", ""))
    with bottom[1]:
        if contact.links:
            label, url = next(iter(contact.links.items()))
            ui.field_card(label, url.replace("https://", ""), evidence.get("links", ""), link=url)
        else:
            ui.field_card("LinkedIn / GitHub", "")
    with bottom[2]:
        headline = resume.experience[0].job_title if resume.experience else ""
        ui.field_card("Current role", headline)

    if len(contact.links) > 1:
        st.write("")
        remaining = list(contact.links.items())[1:]
        links = "  \u00b7  ".join(f"[{label}]({url})" for label, url in remaining)
        st.caption(f"Other profiles: {links}")

    if resume.summary:
        st.write("")
        ui.note(f"<b>Summary</b><br>{ui.esc(resume.summary)}")


def render_skills(resume: ParsedResume) -> None:
    meta = ""
    if resume.skills:
        categories = len(resume.skills_by_category())
        noun = "category" if categories == 1 else "categories"
        meta = f"{len(resume.skills)} detected across {categories} {noun}"
    ui.section_header("Skills", meta)
    ui.skills_panel(resume.skills, show_evidence=st.session_state.show_evidence)


def render_education(resume: ParsedResume) -> None:
    ui.section_header("Education", f"{len(resume.education)} entries" if resume.education else "")
    if not resume.education:
        ui.empty_state(
            "No education entries were detected. The resume may use an unusual "
            "heading or omit the section."
        )
        return
    for entry in resume.education:
        ui.education_card(entry)


def render_experience(resume: ParsedResume) -> None:
    current = sum(1 for entry in resume.experience if entry.is_current)
    meta = f"{len(resume.experience)} roles" if resume.experience else ""
    if current:
        meta += f"  \u00b7  {current} current"
    ui.section_header("Experience", meta)
    ui.experience_timeline(resume.experience)


def render_projects(resume: ParsedResume) -> None:
    ui.section_header("Projects", f"{len(resume.projects)} detected" if resume.projects else "")
    if not resume.projects:
        ui.empty_state(
            "No projects section was detected. Projects are read only from a "
            "dedicated section, never inferred from work experience."
        )
        return
    for entry in resume.projects:
        ui.project_card(entry)


def render_additional(resume: ParsedResume) -> None:
    groups = [
        ("Certifications", resume.certifications),
        ("Achievements", resume.achievements),
        ("Languages", resume.languages),
    ]
    present = [(title, items) for title, items in groups if items]
    if not present:
        return

    ui.section_header("Additional sections", f"{len(present)} found")
    columns = st.columns(len(present))
    for column, (title, items) in zip(columns, present):
        with column:
            ui.simple_list_card(title, items)


def render_transparency(resume: ParsedResume) -> None:
    ui.section_header("Transparency", "How this result was produced")

    ui.warning_list(resume.warnings)

    with st.expander("Extracted text", expanded=False):
        st.caption(
            "The exact text read out of your document, before any parsing. "
            "Everything above is derived only from this."
        )
        st.text_area(
            "Extracted text",
            value=resume.raw_text,
            height=340,
            label_visibility="collapsed",
        )
        st.download_button(
            "Download extracted text",
            data=resume.raw_text.encode("utf-8"),
            file_name=export_filename(resume, "txt", suffix="text"),
            mime="text/plain",
        )

    with st.expander("Field evidence", expanded=False):
        st.caption("Why the parser chose each contact value.")
        ui.evidence_table(resume)

    with st.expander("Parser diagnostics", expanded=False):
        diagnostics = resume.diagnostics
        left, right = st.columns(2)
        with left:
            st.caption("DOCUMENT")
            st.json(
                {
                    key: diagnostics.get(key)
                    for key in (
                        "file_name",
                        "file_type",
                        "file_size_kb",
                        "page_count",
                        "word_count",
                        "line_count",
                        "bullet_count",
                        "embedded_link_count",
                    )
                },
                expanded=True,
            )
        with right:
            st.caption("PARSE")
            st.json(
                {
                    "sections_detected": diagnostics.get("sections_detected"),
                    "section_headings": diagnostics.get("section_headings"),
                    "counts": diagnostics.get("counts"),
                    "fields_detected": diagnostics.get("field_presence"),
                    "nlp": diagnostics.get("nlp"),
                },
                expanded=True,
            )
        st.caption("EXTRACTION METADATA")
        st.json(diagnostics.get("extraction_metadata", {}), expanded=False)


def render_export(resume: ParsedResume) -> None:
    ui.section_header("Export", "Step 3 of 3")
    ui.note(
        "Structured output is generated from the parsed fields above. Fields the "
        "parser could not determine are exported as empty values, never as a guess."
    )
    st.write("")

    left, right = st.columns(2)

    with left:
        st.markdown("**JSON** &mdash; full nested record")
        include_meta = st.checkbox(
            "Include parse metadata",
            value=True,
            help="Adds a 'meta' object with provenance, warnings and field evidence.",
        )
        payload = to_json_bytes(resume, include_meta=include_meta)
        st.download_button(
            "Download JSON",
            data=payload,
            file_name=export_filename(resume, "json"),
            mime="application/json",
            type="primary",
            use_container_width=True,
        )
        st.caption(f"{len(payload) / 1024:,.1f} KB")

    with right:
        st.markdown("**CSV** &mdash; flattened for spreadsheets")
        layout = st.radio(
            "CSV layout",
            options=("detailed", "summary"),
            format_func=lambda value: (
                "Detailed \u2014 one row per item (lossless)"
                if value == "detailed"
                else "Summary \u2014 one row per candidate"
            ),
            key="csv_layout",
            label_visibility="collapsed",
        )
        csv_payload = to_csv_bytes(resume, layout=layout)
        st.download_button(
            "Download CSV",
            data=csv_payload,
            file_name=export_filename(resume, "csv", suffix=layout),
            mime="text/csv",
            type="primary",
            use_container_width=True,
        )
        st.caption(f"{len(csv_payload) / 1024:,.1f} KB")

    with st.expander("Preview export", expanded=False):
        json_tab, csv_tab = st.tabs(["JSON", "CSV"])
        with json_tab:
            st.code(to_json(resume, include_meta=False), language="json")
        with csv_tab:
            st.code(to_csv(resume, layout=st.session_state.csv_layout), language="text")


def render_results(resume: ParsedResume) -> None:
    render_metrics(resume)
    render_overview(resume)
    render_skills(resume)
    render_education(resume)
    render_experience(resume)
    render_projects(resume)
    render_additional(resume)
    render_transparency(resume)
    render_export(resume)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    init_state()
    st.markdown(stylesheet(st.session_state.appearance), unsafe_allow_html=True)
    render_sidebar()

    resume: ParsedResume | None = st.session_state.resume

    # The badge only earns its place when it says something the title does
    # not: which document is currently loaded.
    eyebrow = ""
    if resume is not None:
        eyebrow = f"{resume.extraction.file_type.upper()} parsed"

    ui.hero(APP_TITLE, APP_SUBTITLE, eyebrow=eyebrow)

    pending = st.session_state.pending
    if pending is not None:
        run_parse(pending[0], pending[1])
        return

    if st.session_state.error is not None:
        render_error()
        return

    if resume is None:
        render_upload()
        return

    render_results(resume)


if __name__ == "__main__":
    main()
