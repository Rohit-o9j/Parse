"""Field parsers: contact, skills, education, experience and projects."""

from __future__ import annotations

import pytest

from src.parser import (
    extract_contact,
    extract_education,
    extract_emails,
    extract_experience,
    extract_links,
    extract_name,
    extract_phones,
    extract_projects,
    extract_skills,
    find_degree,
    get_skill_dictionary,
    looks_like_institution,
    looks_like_person_name,
)
from src.parser.skills import load_skill_dictionary
from src.processing.normalize import normalize_text
from src.processing.sections import segment_sections


def prepare(text: str):
    """Normalise and segment a snippet the way the pipeline does."""
    normalised = normalize_text(text)
    return normalised, segment_sections(normalised)


# --------------------------------------------------------------------------- #
# Contact
# --------------------------------------------------------------------------- #


class TestEmail:
    def test_finds_plain_addresses(self) -> None:
        assert extract_emails("Reach me at jane.doe+jobs@sub.example.co.uk today") == [
            "jane.doe+jobs@sub.example.co.uk"
        ]

    def test_strips_trailing_punctuation(self) -> None:
        assert extract_emails("Email: jane@example.com.") == ["jane@example.com"]

    def test_undoes_simple_obfuscation(self) -> None:
        assert extract_emails("jane (at) example (dot) com") == ["jane@example.com"]

    def test_ignores_image_filenames(self) -> None:
        assert extract_emails("logo@2x.png") == []

    def test_no_false_positive(self) -> None:
        assert extract_emails("No contact details here") == []


class TestPhone:
    @pytest.mark.parametrize(
        "text",
        [
            "+91 98765 43210",
            "(512) 555-0188",
            "415-555-2671",
            "+1-415-555-2671",
            "98765 43210",
            "+44 20 7946 0958",
        ],
    )
    def test_recognised_formats(self, text: str) -> None:
        assert extract_phones(f"Mobile: {text}"), text

    @pytest.mark.parametrize(
        "text",
        [
            "Worked there 2018 - 2022",
            "CGPA: 8.7/10 in 2020",
            "Percentage: 92.4%",
            "Served 2.5 million customers",
        ],
    )
    def test_numbers_that_are_not_phones(self, text: str) -> None:
        assert extract_phones(text) == []

    def test_bare_ten_digits_need_a_keyword(self) -> None:
        assert extract_phones("Employee reference 9876543210") == []
        assert extract_phones("Phone 9876543210") == ["9876543210"]

    def test_best_candidate_comes_first(self) -> None:
        text = "Roll no 1234567890\nMobile: +91 98765 43210"
        assert extract_phones(text, text)[0] == "+91 98765 43210"


class TestLinks:
    def test_finds_known_profiles(self) -> None:
        links = extract_links(
            "linkedin.com/in/rahulsharma | github.com/rahulsharma | kaggle.com/rahul"
        )
        assert links["LinkedIn"] == "https://linkedin.com/in/rahulsharma"
        assert links["GitHub"] == "https://github.com/rahulsharma"
        assert links["Kaggle"] == "https://kaggle.com/rahul"

    def test_uses_embedded_hyperlink_targets(self) -> None:
        links = extract_links(
            "LinkedIn", embedded_links=["https://www.linkedin.com/in/dana-w/"]
        )
        assert links["LinkedIn"] == "https://www.linkedin.com/in/dana-w"

    def test_other_sites_become_the_portfolio(self) -> None:
        assert extract_links("https://danabuilds.dev/work")["Portfolio"] == (
            "https://danabuilds.dev/work"
        )

    def test_boilerplate_hosts_are_ignored(self) -> None:
        assert extract_links("see http://schemas.openxmlformats.org/x") == {}


class TestName:
    @pytest.mark.parametrize(
        "value", ["Rahul Sharma", "DANA WHITFIELD", "Mary-Jane O'Brien", "Li Wei"]
    )
    def test_accepts_name_shapes(self, value: str) -> None:
        assert looks_like_person_name(value)

    @pytest.mark.parametrize(
        "value",
        [
            "rahul@example.com",
            "+91 98765 43210",
            "Senior Software Engineer at Acme",
            "linkedin.com/in/x",
            "",
            "A B C D E F",
        ],
    )
    def test_rejects_non_names(self, value: str) -> None:
        assert not looks_like_person_name(value)

    def test_prefers_the_header_line(self) -> None:
        header = ["RAHUL SHARMA", "Senior Software Engineer", "rahul@example.com"]
        name, reason = extract_name(header)
        assert name == "Rahul Sharma"
        assert reason

    def test_explicit_label_wins(self) -> None:
        header = ["Curriculum Vitae", "Name: Priya Nair", "Bengaluru"]
        assert extract_name(header)[0] == "Priya Nair"

    def test_strips_honorifics_and_credentials(self) -> None:
        assert extract_name(["Dr. Anita Rao, PhD"])[0] == "Anita Rao"

    def test_returns_blank_when_unsure(self) -> None:
        assert extract_name(["CURRICULUM VITAE", "Phone: 123456789"])[0] == ""


class TestContactOrchestration:
    def test_full_header(self, rahul_text: str) -> None:
        text, sections = prepare(rahul_text)
        contact = extract_contact(text, sections)
        assert contact.name == "Rahul Sharma"
        assert contact.email == "rahul.sharma@example.com"
        assert contact.phone == "+91 98765 43210"
        assert contact.location == "Bengaluru, Karnataka, India"
        assert set(contact.links) == {"LinkedIn", "GitHub"}
        assert set(contact.evidence) >= {"name", "email", "phone", "location"}

    def test_us_style_header(self, dana_text: str) -> None:
        text, sections = prepare(dana_text)
        contact = extract_contact(text, sections)
        assert contact.name == "Dana Whitfield"
        assert contact.phone == "(512) 555-0188"
        assert contact.location == "Austin, TX"

    def test_sparse_resume_leaves_fields_blank(self) -> None:
        text, sections = prepare("Some notes about a job search.\nNothing useful here.")
        contact = extract_contact(text, sections)
        assert contact.email == ""
        assert contact.phone == ""
        assert contact.links == {}


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #


class TestSkillDictionary:
    def test_loads_and_indexes(self) -> None:
        dictionary = get_skill_dictionary()
        assert len(dictionary) > 150
        assert dictionary.lookup("postgres").name == "PostgreSQL"
        assert dictionary.lookup("PYTHON3").name == "Python"
        assert dictionary.lookup("not a real skill") is None

    def test_rejects_malformed_file(self, tmp_path) -> None:
        bad = tmp_path / "skills.json"
        bad.write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError):
            load_skill_dictionary(bad)

    def test_soft_skills_are_section_only(self) -> None:
        dictionary = get_skill_dictionary()
        leadership = next(d for d in dictionary.definitions if d.name == "Leadership")
        assert leadership.strict, "category-level strict flag was not applied"


class TestSkills:
    def test_categorised_extraction(self, rahul_text: str) -> None:
        text, sections = prepare(rahul_text)
        skills = extract_skills(text, sections)
        names = {skill.name for skill in skills}

        assert {"Python", "Java", "Go", "SQL", "JavaScript"} <= names
        assert {"Django", "FastAPI", "React", "Flask"} <= names
        assert {"PostgreSQL", "MongoDB", "Redis"} <= names
        assert {"AWS", "Docker", "Kubernetes", "Terraform"} <= names
        assert {"Git", "Jira", "Postman", "Grafana"} <= names

        by_name = {skill.name: skill for skill in skills}
        assert by_name["Python"].category == "Programming Languages"
        assert by_name["PostgreSQL"].category == "Databases"
        assert by_name["Docker"].category == "Cloud"
        assert by_name["Python"].found_in == "skills"

    def test_symbol_names_match_correctly(self) -> None:
        text, sections = prepare("SKILLS\nC, C++, C#, .NET, Node.js, scikit-learn\n")
        names = {skill.name for skill in extract_skills(text, sections)}
        assert {"C", "C++", "C#", "Node.js", "scikit-learn"} <= names

    def test_ambiguous_short_names_need_a_skills_section(self) -> None:
        text, sections = prepare(
            "EXPERIENCE\nSoftware Engineer\n- Shipped a feature that users loved.\n"
        )
        assert {s.name for s in extract_skills(text, sections)} & {"C", "R", "Go"} == set()

    def test_react_does_not_match_inside_a_word(self) -> None:
        text, sections = prepare("SUMMARY\nI react quickly and reactivate old systems.\n")
        assert "React" not in {skill.name for skill in extract_skills(text, sections)}

    def test_discovers_unlisted_skills_from_the_section(self) -> None:
        text, sections = prepare("SKILLS\nTools: Quarkus, Dagster, Unleash\n")
        names = {skill.name for skill in extract_skills(text, sections)}
        assert {"Quarkus", "Dagster", "Unleash"} <= names

    def test_subheading_sets_the_category_for_discoveries(self) -> None:
        text, sections = prepare("SKILLS\nDatabases: FoundationDB\n")
        found = next(s for s in extract_skills(text, sections) if s.name == "FoundationDB")
        assert found.category == "Databases"
        assert found.source == "section"

    def test_urls_do_not_create_skills(self) -> None:
        text, sections = prepare(
            "Jane Doe\ngithub.com/jane | jane@oracle.com\n\nSUMMARY\nI write code.\n"
        )
        assert {s.name for s in extract_skills(text, sections)} == set()

    def test_no_skills_section_is_not_an_error(self) -> None:
        text, sections = prepare("Jane Doe\n\nEXPERIENCE\nAnalyst at a bank\n")
        assert isinstance(extract_skills(text, sections), list)


# --------------------------------------------------------------------------- #
# Education
# --------------------------------------------------------------------------- #


class TestDegreeDetection:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("B.Tech in Computer Science", "B.Tech"),
            ("BTech, Mechanical", "B.Tech"),
            ("M.Tech", "M.Tech"),
            ("MBA, Finance", "MBA"),
            ("Ph.D. in Physics", "Ph.D."),
            ("Bachelor of Science in Statistics", "Bachelor of Science"),
            ("Master of Science, Information Systems", "Master of Science"),
            ("Higher Secondary Certificate", "Higher Secondary Certificate"),
            ("Diploma in Web Development", "Diploma"),
        ],
    )
    def test_degrees(self, text: str, expected: str) -> None:
        found = find_degree(text)
        assert found is not None, text
        assert found[0] == expected

    def test_no_degree_returns_none(self) -> None:
        assert find_degree("Senior Software Engineer at Acme") is None

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("National Institute of Technology", True),
            ("Delhi Public School", True),
            ("University of Texas at Austin", True),
            ("IIT Bombay", True),
            ("Reduced bits transferred per request", False),
            ("Zeta Payments Pvt Ltd", False),
        ],
    )
    def test_institution_detection(self, text: str, expected: bool) -> None:
        assert looks_like_institution(text) is expected


class TestEducation:
    def test_indian_format(self, rahul_text: str) -> None:
        text, sections = prepare(rahul_text)
        entries = extract_education(text, sections)
        assert len(entries) == 2

        first = entries[0]
        assert first.degree == "B.Tech"
        assert first.institution == "National Institute of Technology"
        assert first.field_of_study == "Computer Science and Engineering"
        assert (first.start_year, first.end_year) == ("2016", "2020")
        assert "8.7" in first.grade
        assert first.location == "Surathkal"

        second = entries[1]
        assert second.degree == "Higher Secondary Certificate"
        assert "92.4" in second.grade
        # A broad subject word is still the real answer when it is the stated
        # stream, so it must not be filtered out as filler.
        assert second.field_of_study == "Science"
        assert second.institution == "Delhi Public School"

    def test_us_format(self, dana_text: str) -> None:
        text, sections = prepare(dana_text)
        entries = extract_education(text, sections)
        assert len(entries) == 2

        masters = entries[0]
        assert masters.degree == "Master of Science"
        assert masters.institution == "University of Texas at Austin"
        assert masters.field_of_study == "Information Systems"
        assert masters.end_year == "2019"
        assert "3.8" in masters.grade

        bachelors = entries[1]
        assert bachelors.degree == "Bachelor of Science"
        assert bachelors.field_of_study == "Statistics"
        # The field must not be duplicated into the degree string.
        assert "Statistics" not in bachelors.degree

    def test_missing_fields_stay_blank(self) -> None:
        text, sections = prepare("EDUCATION\nB.Tech\nSome College\n")
        entry = extract_education(text, sections)[0]
        assert entry.grade == ""
        assert entry.start_year == ""
        assert entry.field_of_study == ""

    def test_degree_subject_is_not_duplicated_as_the_field(self) -> None:
        """"Bachelor of Science" alone must not report Science twice."""
        text, sections = prepare("EDUCATION\nBachelor of Science\nA University\n2019\n")
        entry = extract_education(text, sections)[0]
        assert entry.degree == "Bachelor of Science"
        assert entry.field_of_study == ""

    def test_stream_after_a_comma_is_read_as_the_field(self) -> None:
        text, sections = prepare("EDUCATION\nIntermediate, Commerce\nA Junior College\n2016\n")
        entry = extract_education(text, sections)[0]
        assert entry.field_of_study == "Commerce"

    def test_grade_scale_is_validated(self) -> None:
        text, sections = prepare("EDUCATION\nB.Tech\nA College\nCGPA: 42/10\n")
        assert extract_education(text, sections)[0].grade == ""

    def test_works_without_a_heading(self) -> None:
        entries = extract_education(
            *prepare("Jane Doe\nB.Tech in Information Technology\nAnna University\n2015 - 2019\n")
        )
        assert entries and entries[0].degree == "B.Tech"

    def test_no_education_section_returns_empty(self) -> None:
        assert extract_education(*prepare("Jane Doe\nI write code for a living.\n")) == []


# --------------------------------------------------------------------------- #
# Experience
# --------------------------------------------------------------------------- #


class TestExperience:
    def test_stacked_layout(self, rahul_text: str) -> None:
        text, sections = prepare(rahul_text)
        entries = extract_experience(text, sections)
        assert len(entries) == 3

        first = entries[0]
        assert first.job_title == "Senior Software Engineer"
        assert first.company == "Zeta Payments Pvt Ltd"
        assert first.location == "Bengaluru, India"
        assert first.start_date == "Mar 2022"
        assert first.end_date == "Present"
        assert first.is_current
        assert len(first.description) == 3
        assert first.description[0].startswith("Led the migration")
        # A wrapped bullet must arrive as one sentence, not two fragments.
        assert first.description[0].endswith("240 ms.")

        assert [entry.company for entry in entries] == [
            "Zeta Payments Pvt Ltd",
            "Infosys Limited",
            "Freshworks",
        ]

    def test_inline_layout_with_trailing_dates(self, dana_text: str) -> None:
        text, sections = prepare(dana_text)
        entries = extract_experience(text, sections)
        assert len(entries) == 2

        first = entries[0]
        assert first.job_title == "Data Engineer II"
        assert first.company == "Brightline Analytics"
        assert first.location == "Austin, TX"
        assert first.is_current

        assert entries[1].job_title == "Data Analyst"
        assert entries[1].company == "Northbend Retail Group"
        assert entries[1].location == "Dallas, TX"

    def test_newest_role_is_first(self, rahul_text: str) -> None:
        entries = extract_experience(*prepare(rahul_text))
        keys = [entry._sort_key for entry in entries if entry._sort_key]
        assert keys == sorted(keys, reverse=True)

    def test_title_at_company_form(self) -> None:
        text, sections = prepare(
            "EXPERIENCE\nBackend Developer at Hashline Labs, Remote\n2021 - 2023\n"
            "- Built services.\n"
        )
        entry = extract_experience(text, sections)[0]
        assert entry.job_title == "Backend Developer"
        assert entry.company == "Hashline Labs"
        assert entry.location == "Remote"

    def test_pipe_separated_form(self) -> None:
        text, sections = prepare(
            "EXPERIENCE\nQA Analyst | Northwind Systems | Bellevue, WA | 2019 - 2021\n"
        )
        entry = extract_experience(text, sections)[0]
        assert entry.job_title == "QA Analyst"
        assert entry.company == "Northwind Systems"
        assert entry.location == "Bellevue, WA"

    def test_no_experience_section_returns_empty(self) -> None:
        assert extract_experience(*prepare("Jane Doe\nEDUCATION\nB.Tech\n")) == []


# --------------------------------------------------------------------------- #
# Projects
# --------------------------------------------------------------------------- #


class TestProjects:
    def test_pipe_delimited_technology_list(self, rahul_text: str) -> None:
        text, sections = prepare(rahul_text)
        entries = extract_projects(text, sections)
        assert len(entries) == 2

        first = entries[0]
        assert first.name == "Smart Resume Parser"
        assert first.technologies == ["Python", "spaCy", "Streamlit", "PyMuPDF"]
        assert len(first.description) == 2

        assert entries[1].name == "Ledger Reconciliation Engine"
        assert "Apache Kafka" in entries[1].technologies

    def test_labelled_technology_list(self, dana_text: str) -> None:
        entries = extract_projects(*prepare(dana_text))
        assert [entry.name for entry in entries] == [
            "Pipeline Observability Toolkit",
            "Open Data Austin",
        ]
        assert entries[0].technologies == ["Python", "Airflow", "Neo4j", "FastAPI"]
        assert entries[1].technologies == ["Python", "PostgreSQL", "Docker"]

    def test_bullet_per_project(self) -> None:
        text, sections = prepare(
            "PROJECTS\n- Campus Navigator: offline maps for new students\n"
            "- Mess Menu Bot: a Telegram bot in Python\n"
        )
        entries = extract_projects(text, sections)
        assert [entry.name for entry in entries] == ["Campus Navigator", "Mess Menu Bot"]
        assert entries[0].description == ["offline maps for new students"]

    def test_link_is_captured(self) -> None:
        text, sections = prepare(
            "PROJECTS\nResume Parser\nhttps://github.com/jane/resume-parser\n"
        )
        assert extract_projects(text, sections)[0].link == (
            "https://github.com/jane/resume-parser"
        )

    def test_technologies_are_inferred_when_not_declared(self) -> None:
        text, sections = prepare(
            "PROJECTS\nChat Service\nA realtime chat backend written with Django and Redis.\n"
        )
        technologies = extract_projects(text, sections)[0].technologies
        assert {"Django", "Redis"} <= set(technologies)

    def test_projects_are_never_taken_from_experience(self, rahul_text: str) -> None:
        text, sections = prepare(rahul_text)
        names = {entry.name for entry in extract_projects(text, sections)}
        assert "Senior Software Engineer" not in names

    def test_no_projects_section_returns_empty(self) -> None:
        assert extract_projects(*prepare("Jane Doe\nEDUCATION\nB.Tech\n")) == []
