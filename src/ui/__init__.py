"""Presentation layer. Streamlit lives here and nowhere else.

``theme``       the stylesheet and its light/dark palettes
``components``  stateless renderers for cards, tags, timelines and callouts
"""

from .components import (
    education_card,
    empty_state,
    esc,
    evidence_table,
    experience_timeline,
    field_card,
    hero,
    metric,
    note,
    project_card,
    section_header,
    simple_list_card,
    skills_panel,
    stage_list,
    tag_group,
    warning_list,
)
from .theme import Appearance, stylesheet

__all__ = [
    "Appearance",
    "education_card",
    "empty_state",
    "esc",
    "evidence_table",
    "experience_timeline",
    "field_card",
    "hero",
    "metric",
    "note",
    "project_card",
    "section_header",
    "simple_list_card",
    "skills_panel",
    "stage_list",
    "stylesheet",
    "tag_group",
    "warning_list",
]
