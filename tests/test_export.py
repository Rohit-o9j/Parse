"""Export layer: JSON schema conformance, CSV layouts and file naming."""

from __future__ import annotations

import csv
import io
import json

import pytest

from src.export import (
    build_payload,
    export_filename,
    to_csv,
    to_csv_bytes,
    to_json,
    to_json_bytes,
)
from src.models import ParsedResume
from src.parser import ResumeParser

#: The keys the agreed candidate schema promises.
REQUIRED_KEYS = ("name", "email", "phone", "skills", "education", "experience", "projects")


class TestJsonExport:
    def test_matches_the_agreed_schema(self, rahul_from_pdf: ParsedResume) -> None:
        payload = build_payload(rahul_from_pdf)
        for key in REQUIRED_KEYS:
            assert key in payload, key
        assert isinstance(payload["skills"], list)
        assert all(isinstance(name, str) for name in payload["skills"])
        assert isinstance(payload["education"], list)
        assert isinstance(payload["experience"], list)
        assert isinstance(payload["projects"], list)

    def test_values_are_correct(self, rahul_from_pdf: ParsedResume) -> None:
        payload = build_payload(rahul_from_pdf)
        assert payload["name"] == "Rahul Sharma"
        assert payload["email"] == "rahul.sharma@example.com"
        assert payload["phone"] == "+91 98765 43210"
        assert payload["location"] == "Bengaluru, Karnataka, India"
        assert payload["links"]["GitHub"].endswith("rahulsharma")
        assert "Python" in payload["skills"]

    def test_nested_entry_shapes(self, rahul_from_pdf: ParsedResume) -> None:
        payload = build_payload(rahul_from_pdf)

        education = payload["education"][0]
        assert set(education) == {
            "degree",
            "institution",
            "field_of_study",
            "start_year",
            "end_year",
            "grade",
            "location",
            "details",
        }
        assert education["degree"] == "B.Tech"

        experience = payload["experience"][0]
        assert set(experience) == {
            "job_title",
            "company",
            "location",
            "start_date",
            "end_date",
            "is_current",
            "description",
        }
        assert experience["is_current"] is True

        project = payload["projects"][0]
        assert set(project) == {
            "name",
            "description",
            "technologies",
            "link",
            "start_date",
            "end_date",
        }

    def test_meta_is_optional(self, rahul_from_pdf: ParsedResume) -> None:
        assert "meta" in build_payload(rahul_from_pdf, include_meta=True)
        assert "meta" not in build_payload(rahul_from_pdf, include_meta=False)

    def test_meta_carries_provenance(self, rahul_from_pdf: ParsedResume) -> None:
        meta = build_payload(rahul_from_pdf)["meta"]
        assert meta["source_type"] == "pdf"
        assert meta["completeness_percent"] == 100
        assert meta["sections_detected"]
        assert meta["nlp"]["available"] is True

    def test_output_is_valid_json(self, rahul_from_pdf: ParsedResume) -> None:
        parsed = json.loads(to_json(rahul_from_pdf))
        assert parsed["name"] == "Rahul Sharma"
        assert json.loads(to_json_bytes(rahul_from_pdf).decode("utf-8"))["email"]

    def test_missing_values_are_empty_strings_not_placeholders(self) -> None:
        resume = ResumeParser(use_nlp=False).parse_text("Nothing useful in this document.")
        payload = build_payload(resume)
        assert payload["name"] == ""
        assert payload["phone"] == ""
        assert "Not detected" not in to_json(resume)

    def test_accented_names_survive_the_round_trip(self) -> None:
        resume = ResumeParser(use_nlp=False).parse_text(
            "Zo\u00eb M\u00fcller\nzoe@example.com\n\nSKILLS\nPython\n"
        )
        payload = json.loads(to_json(resume))
        assert payload["name"] == "Zo\u00eb M\u00fcller"
        assert payload["email"] == "zoe@example.com"
        assert "M\u00fcller" in to_json_bytes(resume).decode("utf-8")

    def test_embedded_markup_does_not_become_a_name(self) -> None:
        """A line polluted with markup is unparseable, so no name is claimed."""
        resume = ResumeParser(use_nlp=False).parse_text(
            "Zo\u00eb M\u00fcller <script>alert(1)</script>\nzoe@example.com\n"
        )
        assert resume.contact.name == ""
        assert resume.contact.email == "zoe@example.com"


class TestCsvExport:
    def test_summary_layout_is_one_row(self, rahul_from_pdf: ParsedResume) -> None:
        rows = list(csv.reader(io.StringIO(to_csv(rahul_from_pdf, layout="summary"))))
        assert len(rows) == 2
        header, values = rows
        record = dict(zip(header, values))

        assert record["name"] == "Rahul Sharma"
        assert record["email"] == "rahul.sharma@example.com"
        assert record["latest_job_title"] == "Senior Software Engineer"
        assert record["latest_company"] == "Zeta Payments Pvt Ltd"
        assert record["highest_degree"] == "B.Tech"
        assert record["graduation_year"] == "2020"
        assert record["completeness_percent"] == "100"
        assert "Python" in record["skills"]

    def test_summary_picks_the_most_senior_degree(self, dana_from_pdf: ParsedResume) -> None:
        rows = list(csv.reader(io.StringIO(to_csv(dana_from_pdf, layout="summary"))))
        record = dict(zip(rows[0], rows[1]))
        assert record["highest_degree"] == "Master of Science"

    def test_detailed_layout_is_tidy_data(self, rahul_from_pdf: ParsedResume) -> None:
        rows = list(csv.reader(io.StringIO(to_csv(rahul_from_pdf, layout="detailed"))))
        assert rows[0] == ["section", "index", "field", "value"]

        sections = {row[0] for row in rows[1:]}
        assert {
            "contact",
            "skills",
            "education",
            "experience",
            "projects",
            "meta",
        } <= sections

        values = {(row[0], row[2], row[3]) for row in rows[1:]}
        assert ("contact", "name", "Rahul Sharma") in values
        assert ("education", "degree", "B.Tech") in values
        assert ("experience", "job_title", "Senior Software Engineer") in values
        assert ("skills", "Programming Languages", "Python") in values

    def test_detailed_layout_keeps_every_item(self, rahul_from_pdf: ParsedResume) -> None:
        rows = list(csv.reader(io.StringIO(to_csv(rahul_from_pdf, layout="detailed"))))
        skill_rows = [row for row in rows[1:] if row[0] == "skills"]
        assert len(skill_rows) == len(rahul_from_pdf.skills)

        experience_indexes = {row[1] for row in rows[1:] if row[0] == "experience"}
        assert experience_indexes == {"1", "2", "3"}

    def test_empty_values_are_omitted_from_detail_rows(self) -> None:
        resume = ResumeParser(use_nlp=False).parse_text("EDUCATION\nB.Tech\nA College\n")
        rows = list(csv.reader(io.StringIO(to_csv(resume, layout="detailed"))))
        assert not any(row[2] == "grade" for row in rows[1:])

    def test_bytes_carry_a_bom_for_excel(self, rahul_from_pdf: ParsedResume) -> None:
        payload = to_csv_bytes(rahul_from_pdf)
        assert payload.startswith(b"\xef\xbb\xbf")
        assert b"\r\n" in payload

    def test_values_with_commas_are_quoted(self, rahul_from_pdf: ParsedResume) -> None:
        text = to_csv(rahul_from_pdf, layout="detailed")
        reparsed = list(csv.reader(io.StringIO(text)))
        assert all(len(row) == 4 for row in reparsed)


class TestFilenames:
    def test_named_after_the_candidate(self, rahul_from_pdf: ParsedResume) -> None:
        name = export_filename(rahul_from_pdf, "json")
        assert name.startswith("rahul_sharma_resume_")
        assert name.endswith(".json")

    def test_suffix_is_included(self, rahul_from_pdf: ParsedResume) -> None:
        assert "_summary_" in export_filename(rahul_from_pdf, "csv", suffix="summary")

    def test_falls_back_to_the_source_name(self) -> None:
        resume = ResumeParser(use_nlp=False).parse_text("no name here", file_name="upload.pdf")
        assert export_filename(resume, "json").startswith("upload_resume_")

    @pytest.mark.parametrize("hostile", ["../../etc/passwd", "CON", "a/b\\c:d*e?f"])
    def test_hostile_names_are_sanitised(self, hostile: str) -> None:
        resume = ResumeParser(use_nlp=False).parse_text("nothing", file_name=f"{hostile}.pdf")
        name = export_filename(resume, "json")
        assert "/" not in name and "\\" not in name and ":" not in name
        assert not name.startswith(".")
