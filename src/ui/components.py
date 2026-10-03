"""Presentation components.

Every renderer here takes already-parsed data and writes markup. None of them
parse, infer or fall back to a guess: when a value is missing they render
"Not detected" in a muted style, which is the one place that string is allowed
to exist.

All user-derived text passes through :func:`esc` before it reaches
``unsafe_allow_html``, so a resume containing ``<script>`` or stray angle
brackets cannot break the page or inject markup.
"""

from __future__ import annotations

import html
from typing import Any, Iterable, Sequence

import streamlit as st

from ..models import (
    EducationEntry,
    ExperienceEntry,
    ParsedResume,
    ProjectEntry,
    Skill,
)
from ..settings import NOT_DETECTED, SKILL_CATEGORY_ORDER


def esc(value: Any) -> str:
    """HTML-escape a value for safe inclusion in custom markup."""
    return html.escape("" if value is None else str(value), quote=True)


def _write(markup: str) -> None:
    """Emit custom markup through Streamlit.

    Indentation is stripped from every line first. Streamlit renders markdown,
    where a block indented by four or more spaces becomes a literal code
    block - so a nicely formatted HTML template would otherwise show up on the
    page as source text. Collapsing to a single line also stops the markdown
    processor from inserting stray paragraph tags between elements.
    """
    compact = "".join(line.strip() for line in markup.strip().splitlines())
    st.markdown(compact, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# Chrome
# --------------------------------------------------------------------------- #


def hero(title: str, subtitle: str, eyebrow: str = "") -> None:
    """Page header."""
    eyebrow_markup = (
        f'<div class="srp-eyebrow"><span class="srp-tag-dot"></span>{esc(eyebrow)}</div>'
        if eyebrow
        else ""
    )
    _write(
        f"""
        <div class="srp-hero">
          {eyebrow_markup}
          <h1 class="srp-title">{esc(title)}</h1>
          <p class="srp-subtitle">{esc(subtitle)}</p>
        </div>
        """
    )


def section_header(title: str, meta: str = "") -> None:
    """Divider with a title and an optional right-aligned count."""
    meta_markup = f'<span class="srp-section-meta">{esc(meta)}</span>' if meta else ""
    _write(
        f"""
        <div class="srp-section">
          <span class="srp-section-title">{esc(title)}</span>
          {meta_markup}
        </div>
        """
    )


def note(text: str, kind: str = "info") -> None:
    """Callout box. ``kind`` is one of info / success / warning / danger."""
    suffix = "" if kind == "info" else f" is-{esc(kind)}"
    _write(f'<div class="srp-note{suffix}">{text}</div>')


def empty_state(message: str) -> None:
    """Placeholder shown when a section produced nothing."""
    _write(f'<div class="srp-empty">{esc(message)}</div>')


# --------------------------------------------------------------------------- #
# Cards and metrics
# --------------------------------------------------------------------------- #


def field_card(
    label: str,
    value: str,
    note_text: str = "",
    large: bool = False,
    link: str = "",
) -> None:
    """A labelled value card; renders "Not detected" when ``value`` is empty."""
    missing = not (value or "").strip()
    classes = "srp-card-value"
    if large:
        classes += " is-large"
    if missing:
        classes += " is-missing"

    if missing:
        body = esc(NOT_DETECTED)
    elif link:
        body = f'<a href="{esc(link)}" target="_blank" rel="noopener noreferrer">{esc(value)}</a>'
    else:
        body = esc(value)

    note_markup = (
        f'<div class="srp-card-note">{esc(note_text)}</div>'
        if note_text and not missing
        else ""
    )
    _write(
        f"""
        <div class="srp-card">
          <div class="srp-card-label">{esc(label)}</div>
          <div class="{classes}">{body}</div>
          {note_markup}
        </div>
        """
    )


def metric(label: str, value: Any, percent: int | None = None) -> None:
    """Compact statistic, optionally with a progress meter underneath."""
    meter = ""
    if percent is not None:
        width = max(0, min(100, int(percent)))
        meter = f'<div class="srp-meter"><span style="width:{width}%"></span></div>'
    _write(
        f"""
        <div class="srp-metric">
          <div class="srp-metric-value">{esc(value)}</div>
          <div class="srp-metric-label">{esc(label)}</div>
          {meter}
        </div>
        """
    )


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #


def tag_group(labels: Iterable[str], accent: bool = False) -> None:
    """A row of pill tags."""
    suffix = " is-accent" if accent else ""
    tags = "".join(
        f'<span class="srp-tag{suffix}">{esc(label)}</span>' for label in labels if label
    )
    if tags:
        _write(f'<div class="srp-tag-group">{tags}</div>')


def skills_panel(skills: Sequence[Skill], show_evidence: bool = False) -> None:
    """Skills grouped by category, rendered as tag rows."""
    if not skills:
        empty_state(
            "No skills were detected. The resume may not list them in a recognisable "
            "skills section."
        )
        return

    grouped: dict[str, list[Skill]] = {}
    for skill in skills:
        grouped.setdefault(skill.category, []).append(skill)

    ordered = [category for category in SKILL_CATEGORY_ORDER if category in grouped]
    ordered += sorted(category for category in grouped if category not in ordered)

    for category in ordered:
        items = grouped[category]
        _write(
            f'<div class="srp-category">{esc(category)} '
            f'<span style="opacity:.6">({len(items)})</span></div>'
        )
        if show_evidence:
            tags = "".join(
                '<span class="srp-tag" title="{tip}">{name}</span>'.format(
                    tip=esc(_skill_tooltip(skill)), name=esc(skill.name)
                )
                for skill in items
            )
            _write(f'<div class="srp-tag-group">{tags}</div>')
        else:
            tag_group(skill.name for skill in items)


def _skill_tooltip(skill: Skill) -> str:
    """Explain where a skill came from, for the hover title."""
    source = "skill dictionary" if skill.source == "dictionary" else "skills section list"
    where = f", found in the {skill.found_in} section" if skill.found_in else ""
    return f"Matched via {source}{where} - {skill.confidence} confidence"


# --------------------------------------------------------------------------- #
# Entry cards
# --------------------------------------------------------------------------- #


def _field(label: str, value: str) -> str:
    """One label/value pair inside an entry card's meta row."""
    missing = not (value or "").strip()
    css = ' class="srp-field is-missing"' if missing else ' class="srp-field"'
    shown = NOT_DETECTED if missing else value
    return f"<span{css}>{esc(label)}: <b>{esc(shown)}</b></span>"


def _bullets(items: Sequence[str]) -> str:
    if not items:
        return ""
    entries = "".join(f"<li>{esc(item)}</li>" for item in items)
    return f'<ul class="srp-bullets">{entries}</ul>'


def education_card(entry: EducationEntry) -> None:
    """Structured education entry."""
    years = " \u2013 ".join(part for part in (entry.start_year, entry.end_year) if part)
    dates = f'<span class="srp-entry-dates">{esc(years)}</span>' if years else ""

    title = entry.degree or entry.institution or "Qualification"
    subtitle = entry.institution if entry.degree else ""

    meta = "".join(
        (
            _field("Field of study", entry.field_of_study),
            _field("Grade", entry.grade),
            _field("Location", entry.location),
        )
    )
    _write(
        f"""
        <div class="srp-entry">
          <div class="srp-entry-head">
            <div>
              <div class="srp-entry-title">{esc(title)}</div>
              {f'<div class="srp-entry-sub">{esc(subtitle)}</div>' if subtitle else ''}
            </div>
            {dates}
          </div>
          <div class="srp-entry-meta">{meta}</div>
          {_bullets(entry.details)}
        </div>
        """
    )


def experience_card_markup(entry: ExperienceEntry) -> str:
    """Markup for one work-experience entry as a timeline item."""
    dates = entry.date_range
    date_class = "srp-entry-dates is-current" if entry.is_current else "srp-entry-dates"
    dates_markup = f'<span class="{date_class}">{esc(dates)}</span>' if dates else ""

    title = entry.job_title or entry.company or "Role"
    subtitle_parts = [
        part for part in (entry.company if entry.job_title else "", entry.location) if part
    ]
    subtitle = "  \u00b7  ".join(subtitle_parts)
    subtitle_markup = f'<div class="srp-entry-sub">{esc(subtitle)}</div>' if subtitle else ""

    # Only surface the raw fields when one of them could not be determined,
    # so a clean entry stays visually quiet.
    missing_meta = ""
    if not entry.job_title or not entry.company:
        missing_meta = (
            '<div class="srp-entry-meta">'
            + _field("Job title", entry.job_title)
            + _field("Company", entry.company)
            + "</div>"
        )

    item_class = "srp-timeline-item is-current" if entry.is_current else "srp-timeline-item"
    return (
        f'<div class="{item_class}"><div class="srp-entry">'
        f'<div class="srp-entry-head"><div>'
        f'<div class="srp-entry-title">{esc(title)}</div>{subtitle_markup}'
        f"</div>{dates_markup}</div>"
        f"{missing_meta}{_bullets(entry.description)}"
        f"</div></div>"
    )


def experience_timeline(entries: Sequence[ExperienceEntry]) -> None:
    """Chronological timeline of roles, newest first.

    The whole timeline is emitted as a single markup string: Streamlit closes
    the container after every ``st.markdown`` call, so an opening wrapper
    written on its own would never contain the cards that follow.
    """
    if not entries:
        empty_state("No work experience was detected in this resume.")
        return
    items = "".join(experience_card_markup(entry) for entry in entries)
    _write(f'<div class="srp-timeline">{items}</div>')


def project_card(entry: ProjectEntry) -> None:
    """Structured project entry."""
    dates = entry.date_range
    dates_markup = f'<span class="srp-entry-dates">{esc(dates)}</span>' if dates else ""

    link_markup = ""
    if entry.link:
        link_markup = (
            f'<div class="srp-entry-sub"><a href="{esc(entry.link)}" target="_blank" '
            f'rel="noopener noreferrer">{esc(entry.link)}</a></div>'
        )

    tech_markup = ""
    if entry.technologies:
        tags = "".join(
            f'<span class="srp-tag is-accent">{esc(name)}</span>'
            for name in entry.technologies
        )
        tech_markup = f'<div class="srp-tag-group" style="margin-top:.7rem">{tags}</div>'
    else:
        tech_markup = f'<div class="srp-entry-meta">{_field("Technologies", "")}</div>'

    _write(
        f"""
        <div class="srp-entry">
          <div class="srp-entry-head">
            <div>
              <div class="srp-entry-title">{esc(entry.name or 'Untitled project')}</div>
              {link_markup}
            </div>
            {dates_markup}
          </div>
          {_bullets(entry.description)}
          {tech_markup}
        </div>
        """
    )


def simple_list_card(title: str, items: Sequence[str]) -> None:
    """Card for a flat list section (certifications, achievements, languages)."""
    _write(
        f"""
        <div class="srp-entry">
          <div class="srp-entry-title">{esc(title)}</div>
          {_bullets(items)}
        </div>
        """
    )


# --------------------------------------------------------------------------- #
# Processing view
# --------------------------------------------------------------------------- #


def stage_list(labels: Sequence[str], completed: int) -> str:
    """Markup for the staged checklist.

    ``completed`` is the number of finished stages: those render with a tick,
    the next one with a filled dot, and the remainder with a hollow dot. The
    exact glyph sequence the brief asked for, no animation.
    """
    rows: list[str] = []
    for index, label in enumerate(labels):
        if index < completed:
            icon, css = "\u2713", "srp-stage is-done"
        elif index == completed:
            icon, css = "\u25cf", "srp-stage is-active"
        else:
            icon, css = "\u25cb", "srp-stage"
        rows.append(
            f'<div class="{css}"><span class="srp-stage-icon">{icon}</span>'
            f"<span>{esc(label)}</span></div>"
        )
    return f'<div class="srp-stages">{"".join(rows)}</div>'


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #


def warning_list(warnings: Sequence[str]) -> None:
    """Render parse warnings, or a success note when there are none."""
    if not warnings:
        note(
            "<b>Clean parse.</b> Every expected section was recognised and no "
            "extraction issues were reported.",
            kind="success",
        )
        return
    items = "".join(f"<li>{esc(warning)}</li>" for warning in warnings)
    note(
        f"<b>{len(warnings)} note{'s' if len(warnings) > 1 else ''} from the parser"
        f"</b><ul class='srp-bullets' style='margin-top:.4rem'>{items}</ul>",
        kind="warning",
    )


def evidence_table(resume: ParsedResume) -> None:
    """Why the parser chose each contact value."""
    evidence = resume.contact.evidence
    if not evidence:
        empty_state("No contact fields were detected, so there is nothing to explain.")
        return
    rows = "".join(
        f"<li><b>{esc(field.title())}</b> &mdash; {esc(reason)}</li>"
        for field, reason in evidence.items()
    )
    _write(f'<ul class="srp-bullets">{rows}</ul>')
