"""Pipeline behaviour: stages, warnings, diagnostics and robustness.

The important property tested here is **format independence**: a PDF and a
DOCX rendered from the same source must yield the same structured record. If
that ever stops holding, the extraction layer has started leaking layout into
the result.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from src.extraction import ExtractionError
from src.models import ParsedResume
from src.parser import STAGES, ResumeParser


class TestStages:
    def test_all_stages_report_in_order(self, parser: ResumeParser, rahul_pdf_bytes: bytes) -> None:
        seen: list[tuple[str, int, int]] = []
        parser.parse_file(
            rahul_pdf_bytes,
            file_name="r.pdf",
            progress=lambda key, index, total: seen.append((key, index, total)),
        )
        assert [key for key, _i, _t in seen] == [stage.key for stage in STAGES]
        assert [index for _k, index, _t in seen] == [1, 2, 3, 4, 5]
        assert {total for _k, _i, total in seen} == {len(STAGES)}

    def test_a_broken_callback_cannot_break_parsing(
        self, parser: ResumeParser, rahul_pdf_bytes: bytes
    ) -> None:
        def explode(*_args: object) -> None:
            raise RuntimeError("UI blew up")

        resume = parser.parse_file(rahul_pdf_bytes, file_name="r.pdf", progress=explode)
        assert resume.contact.name == "Rahul Sharma"


class TestFormatIndependence:
    @pytest.mark.parametrize("field", ["name", "email", "phone", "location"])
    def test_contact_matches_across_formats(
        self, rahul_from_pdf: ParsedResume, rahul_from_docx: ParsedResume, field: str
    ) -> None:
        assert getattr(rahul_from_pdf.contact, field) == getattr(
            rahul_from_docx.contact, field
        )

    def test_skills_match_across_formats(
        self, rahul_from_pdf: ParsedResume, rahul_from_docx: ParsedResume
    ) -> None:
        assert set(rahul_from_pdf.skill_names()) == set(rahul_from_docx.skill_names())

    def test_structured_sections_match_across_formats(
        self, rahul_from_pdf: ParsedResume, rahul_from_docx: ParsedResume
    ) -> None:
        def shape(resume: ParsedResume) -> tuple:
            return (
                [(e.degree, e.institution, e.end_year) for e in resume.education],
                [(x.job_title, x.company, x.start_date) for x in resume.experience],
                [(p.name, tuple(p.technologies)) for p in resume.projects],
            )

        assert shape(rahul_from_pdf) == shape(rahul_from_docx)

    def test_dana_matches_across_formats(
        self, dana_from_pdf: ParsedResume, dana_from_docx: ParsedResume
    ) -> None:
        assert dana_from_pdf.contact.name == dana_from_docx.contact.name
        assert [x.company for x in dana_from_pdf.experience] == [
            x.company for x in dana_from_docx.experience
        ]


class TestResultQuality:
    def test_rahul_is_fully_parsed(self, rahul_from_pdf: ParsedResume) -> None:
        resume = rahul_from_pdf
        assert resume.completeness() == 100
        assert resume.contact.name == "Rahul Sharma"
        assert len(resume.experience) == 3
        assert len(resume.education) == 2
        assert len(resume.projects) == 2
        assert len(resume.certifications) == 2
        assert len(resume.achievements) == 2
        assert resume.languages == [
            "English (fluent)",
            "Hindi (native)",
            "Kannada (conversational)",
        ]
        assert resume.summary.startswith("Backend engineer with 4 years")

    def test_detected_sections_are_reported(self, rahul_from_pdf: ParsedResume) -> None:
        detected = set(rahul_from_pdf.detected_section_keys)
        assert {"summary", "skills", "experience", "education", "projects"} <= detected
        assert "header" not in rahul_from_pdf.detected_section_keys

    def test_diagnostics_are_populated(self, rahul_from_pdf: ParsedResume) -> None:
        diagnostics = rahul_from_pdf.diagnostics
        assert diagnostics["file_type"] == "pdf"
        assert diagnostics["word_count"] > 200
        assert diagnostics["bullet_count"] >= 8
        assert diagnostics["counts"]["skills"] == len(rahul_from_pdf.skills)
        assert diagnostics["nlp"]["available"] is True
        assert all(diagnostics["field_presence"].values())

    def test_clean_resume_has_no_warnings(self, rahul_from_pdf: ParsedResume) -> None:
        assert rahul_from_pdf.warnings == []

    def test_raw_text_is_preserved(self, rahul_from_pdf: ParsedResume) -> None:
        assert "RAHUL SHARMA" in rahul_from_pdf.raw_text


class TestDegradedInput:
    def test_resume_without_sections_still_parses_contacts(
        self, parser: ResumeParser
    ) -> None:
        resume = parser.parse_text(
            "Priya Nair\nKochi, Kerala, India\npriya.nair@example.com | +91 90000 11111\n"
            "I have been building data platforms since 2019.\n"
        )
        assert resume.contact.name == "Priya Nair"
        assert resume.contact.email == "priya.nair@example.com"
        assert any("No section headings" in w for w in resume.warnings)

    def test_missing_sections_are_reported_not_invented(self, parser: ResumeParser) -> None:
        resume = parser.parse_text(
            "Priya Nair\npriya@example.com\n\nEDUCATION\nB.Tech, Anna University\n2015 - 2019\n"
        )
        assert resume.experience == []
        assert resume.skills == []
        assert any("work experience section" in w for w in resume.warnings)
        assert any("skills section" in w for w in resume.warnings)

    def test_anonymous_resume_leaves_name_blank(self, parser: ResumeParser) -> None:
        resume = parser.parse_text(
            "CURRICULUM VITAE\n\nEXPERIENCE\nAnalyst\nA Bank\n2020 - 2022\n"
        )
        assert resume.contact.name == ""
        assert any("name" in w.lower() for w in resume.warnings)

    def test_very_short_document_is_flagged(self, parser: ResumeParser) -> None:
        resume = parser.parse_text("Jane Doe\njane@example.com")
        assert any("words of text were extracted" in w for w in resume.warnings)

    def test_regex_only_mode_still_works(
        self, regex_only_parser: ResumeParser, rahul_pdf_bytes: bytes
    ) -> None:
        resume = regex_only_parser.parse_file(rahul_pdf_bytes, file_name="r.pdf")
        assert resume.contact.name == "Rahul Sharma"
        assert resume.contact.email == "rahul.sharma@example.com"
        assert len(resume.experience) == 3
        assert len(resume.skills) > 20
        assert any("NLP analysis was disabled" in w for w in resume.warnings)

    def test_unicode_and_markup_are_handled(self, parser: ResumeParser) -> None:
        resume = parser.parse_text(
            "Zo\u00eb M\u00fcller <script>alert(1)</script>\nzoe@example.com\n\n"
            "SKILLS\nPython, Go\n"
        )
        assert resume.contact.email == "zoe@example.com"
        assert "Python" in resume.skill_names()

    def test_accented_name_is_read(self, parser: ResumeParser) -> None:
        resume = parser.parse_text("Zo\u00eb M\u00fcller\nzoe@example.com\n")
        assert resume.contact.name == "Zo\u00eb M\u00fcller"


class TestFailures:
    def test_empty_upload_raises(self, parser: ResumeParser) -> None:
        with pytest.raises(ExtractionError):
            parser.parse_file(b"", file_name="resume.pdf")

    def test_unsupported_type_raises(self, parser: ResumeParser) -> None:
        with pytest.raises(ExtractionError):
            parser.parse_file(b"just some notes", file_name="notes.txt")

    def test_corrupt_docx_raises(self, parser: ResumeParser) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", "<not-really-a-document")
        with pytest.raises(ExtractionError):
            parser.parse_file(buffer.getvalue(), file_name="broken.docx")

    def test_errors_carry_a_message_and_a_hint(self, parser: ResumeParser) -> None:
        with pytest.raises(ExtractionError) as info:
            parser.parse_file(b"", file_name="resume.pdf")
        assert info.value.message
        assert info.value.hint
