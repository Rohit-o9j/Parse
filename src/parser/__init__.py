"""Field parsers and the pipeline that orchestrates them.

Each module here answers one question about a resume and nothing else:

``contact``     who is this and how do I reach them
``skills``      what can they do
``education``   what did they study and where
``experience``  where have they worked
``projects``    what have they built outside a job
``pipeline``    run all of the above in order and report progress
"""

from .contact import (
    extract_contact,
    extract_emails,
    extract_links,
    extract_name,
    extract_phones,
    is_known_place,
    looks_like_person_name,
)
from .education import extract_education, find_degree, looks_like_institution
from .experience import extract_experience
from .pipeline import STAGES, ResumeParser, Stage, parse_resume
from .projects import extract_projects
from .skills import (
    SkillDefinition,
    SkillDictionary,
    extract_skills,
    get_skill_dictionary,
    load_skill_dictionary,
)

__all__ = [
    "STAGES",
    "ResumeParser",
    "SkillDefinition",
    "SkillDictionary",
    "Stage",
    "extract_contact",
    "extract_education",
    "extract_emails",
    "extract_experience",
    "extract_links",
    "extract_name",
    "extract_phones",
    "extract_projects",
    "extract_skills",
    "find_degree",
    "get_skill_dictionary",
    "is_known_place",
    "load_skill_dictionary",
    "looks_like_institution",
    "looks_like_person_name",
    "parse_resume",
]
