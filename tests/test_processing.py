"""Processing layer: normalisation, section segmentation and date parsing."""

from __future__ import annotations

import pytest

from src.processing.dates import find_date_range, find_years, mentions_current, strip_dates
from src.processing.normalize import (
    collapse_whitespace,
    is_bullet,
    normalize_text,
    squash_separators,
    strip_bullet,
)
from src.processing.sections import (
    match_section_key,
    normalize_heading,
    section_map,
    segment_sections,
)


class TestNormalize:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("\u2022 Built a thing", "- Built a thing"),
            ("\u25cf  Shipped it", "- Shipped it"),
            ("\uf0b7 Symbol-font bullet", "- Symbol-font bullet"),
            ("*  Starred item", "- Starred item"),
            ("-   Dashed item", "- Dashed item"),
        ],
    )
    def test_bullets_are_unified(self, raw: str, expected: str) -> None:
        assert normalize_text(raw) == expected

    def test_typographic_characters_are_folded(self) -> None:
        result = normalize_text("Caf\u00e9 \u201cteam\u201d \u2013 it\u2019s ef\ufb01cient\u00a0now")
        assert "\u201c" not in result and "\u2019" not in result
        assert "efficient" in result
        assert "\u00a0" not in result

    def test_hyphenated_line_wrap_is_rejoined(self) -> None:
        assert "optimisation" in normalize_text("We drove optimi-\nsation across teams")

    def test_letter_spaced_heading_is_rejoined(self) -> None:
        assert normalize_text("E D U C A T I O N") == "EDUCATION"

    def test_blank_runs_are_collapsed(self) -> None:
        assert normalize_text("A\n\n\n\n\nB") == "A\n\nB"

    def test_empty_input_is_safe(self) -> None:
        assert normalize_text("") == ""
        assert normalize_text(None) == ""  # type: ignore[arg-type]

    def test_bullet_helpers(self) -> None:
        assert is_bullet("- Did a thing")
        assert not is_bullet("Did a thing")
        assert strip_bullet("- Did a thing") == "Did a thing"

    def test_squash_separators(self) -> None:
        assert squash_separators("Senior Engineer |  | Acme Corp,") == "Senior Engineer | Acme Corp"

    def test_collapse_whitespace(self) -> None:
        assert collapse_whitespace("  a \n b\t c ") == "a b c"


class TestSectionKeys:
    @pytest.mark.parametrize(
        ("heading", "expected"),
        [
            ("WORK EXPERIENCE", "experience"),
            ("Professional Experience", "experience"),
            ("Employment History", "experience"),
            ("EDUCATION", "education"),
            ("Academic Qualifications", "education"),
            ("Technical Skills", "skills"),
            ("Core Competencies", "skills"),
            ("Tools & Technologies", "skills"),
            ("PROJECTS", "projects"),
            ("Selected Projects", "projects"),
            ("Certifications", "certifications"),
            ("Awards and Achievements", "achievements"),
            ("Languages", "languages"),
            ("Objective", "summary"),
            ("3. PROFESSIONAL SUMMARY:", "summary"),
            ("Education & Certifications", "education"),
        ],
    )
    def test_recognised_headings(self, heading: str, expected: str) -> None:
        assert match_section_key(heading) == expected

    @pytest.mark.parametrize(
        "label",
        [
            # Skill-list labels that merely contain a sectional word. Treating
            # these as headings used to swallow the real sections below them.
            "Programming Languages",
            "Technologies Used",
            "Frameworks",
            "Databases",
            "Cloud & DevOps",
            "Tools",
            "Work Authorization",
            "Led the experience team",
        ],
    )
    def test_rejected_headings(self, label: str) -> None:
        assert match_section_key(label) is None

    def test_normalize_heading_strips_decoration(self) -> None:
        assert normalize_heading("  2) TECHNICAL SKILLS :  ") == "technical skills"


class TestSegmentation:
    def test_splits_a_full_resume(self, rahul_text: str) -> None:
        blocks = segment_sections(normalize_text(rahul_text))
        mapping = section_map(blocks)

        assert blocks[0].key == "header"
        for key in ("summary", "skills", "experience", "education", "projects"):
            assert key in mapping, f"missing {key}"

        assert "RAHUL SHARMA" in mapping["header"].text
        assert "Programming Languages: Python" in mapping["skills"].text
        assert "Zeta Payments Pvt Ltd" in mapping["experience"].text
        assert "National Institute of Technology" in mapping["education"].text
        # The skills labels must stay inside the skills block.
        assert "Python" not in mapping["education"].text

    def test_inline_heading_is_split(self) -> None:
        blocks = section_map(segment_sections("Jane Doe\nSkills: Python, SQL\n"))
        assert "skills" in blocks
        assert blocks["skills"].lines == ["Python, SQL"]

    def test_repeated_sections_are_merged(self) -> None:
        text = (
            "Jane Doe\n\nEXPERIENCE\nRole A\n\nEDUCATION\nB.Tech\n\n"
            "EXPERIENCE\nRole B\n"
        )
        blocks = section_map(segment_sections(text))
        assert "Role A" in blocks["experience"].text
        assert "Role B" in blocks["experience"].text

    def test_resume_without_headings_yields_header_only(self) -> None:
        blocks = segment_sections("Jane Doe\njane@example.com\nI build software.")
        assert [block.key for block in blocks] == ["header"]


class TestDates:
    @pytest.mark.parametrize(
        ("text", "start_iso", "end_iso", "current"),
        [
            ("Mar 2022 - Present", "2022-03", "", True),
            ("January 2020 to Present", "2020-01", "", True),
            ("Jan 2020 - Mar 2022", "2020-01", "2022-03", False),
            ("2019 - 2023", "2019", "2023", False),
            ("05/2018 \u2013 08/2020", "2018-05", "2020-08", False),
            ("Aug '19 - Dec '21", "2019-08", "2021-12", False),
            ("2021 \u2013 Current", "2021", "", True),
            ("Nov 2019 till date", "2019-11", "", True),
            ("Since 2020", "2020", "", True),
            ("Sept 2015 - June 2019", "2015-09", "2019-06", False),
        ],
    )
    def test_ranges(self, text: str, start_iso: str, end_iso: str, current: bool) -> None:
        found = find_date_range(text)
        assert found is not None, text
        assert found.start_iso == start_iso
        assert found.end_iso == end_iso
        assert found.is_current is current

    def test_single_date_becomes_the_end(self) -> None:
        found = find_date_range("University of Texas at Austin, 2019")
        assert found is not None
        assert (found.start_iso, found.end_iso) == ("", "2019")

    @pytest.mark.parametrize(
        "text",
        [
            "Reduced latency from 820 ms to 240 ms",
            "Served 2.5 million customers",
            "CGPA 8.7/10",
            "",
        ],
    )
    def test_non_dates_are_ignored(self, text: str) -> None:
        assert find_date_range(text) is None

    def test_reversed_range_is_not_treated_as_a_range(self) -> None:
        """A backwards range is never reported as a period.

        The parser falls back to the single date it can see rather than
        inventing a start that precedes the end.
        """
        found = find_date_range("2023 - 2019")
        assert found is not None
        assert found.start_iso == ""
        assert found.end_iso == "2023"

    def test_strip_dates_leaves_the_rest(self) -> None:
        cleaned = strip_dates("Data Engineer II, Brightline Analytics  2021 - Present")
        assert cleaned == "Data Engineer II, Brightline Analytics"

    def test_find_years_filters_implausible_values(self) -> None:
        assert find_years("1899 1950 2019 2400") == [1950, 2019]

    def test_mentions_current(self) -> None:
        assert mentions_current("Jan 2020 - Present")
        assert not mentions_current("Jan 2020 - Mar 2021")

    def test_sort_key_puts_current_first(self) -> None:
        current = find_date_range("Mar 2022 - Present")
        past = find_date_range("Jan 2020 - Mar 2022")
        assert current is not None and past is not None
        assert current.sort_key > past.sort_key
