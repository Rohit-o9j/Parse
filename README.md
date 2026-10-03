# Smart Resume Parser

Turn unstructured resumes into structured candidate data.

A Streamlit application that reads a PDF or DOCX resume, extracts the text,
recovers the document's section structure, parses out contact details, skills,
education, experience and projects, and exports the result as JSON or CSV.

The parser does real work on real files. Nothing is mocked, and nothing is
invented: a field it cannot determine with confidence is reported as
**Not detected** rather than guessed.

---

## Quick start

```bash
python -m pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m streamlit run app.py
```

On Windows you can also just double-click **`run.bat`**.

The app opens at <http://localhost:8501>. Two sample resumes are bundled, so
you can see a full parse without uploading anything. Press `Ctrl+C` in the
terminal to stop the server.

The spaCy model is a separate download. If it is missing the app still runs:
name, location and employer detection fall back to pattern matching, and the
sidebar says so.

### If `streamlit` is "not recognized"

Use the module form instead, which does not depend on PATH:

```bash
python -m streamlit run app.py
```

This happens with the Microsoft Store build of Python. It installs console
scripts into a sandboxed per-user folder that is never added to PATH:

```
%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.11_qbz5n2kfra8p0\
    LocalCache\local-packages\Python311\Scripts
```

`python -m <tool>` always works because it resolves the package through the
interpreter rather than through PATH. The same applies to the other tools
here: `python -m pytest`, `python -m pip`, `python -m spacy`.

To fix PATH permanently instead, add that `Scripts` folder via
*Settings &rarr; System &rarr; About &rarr; Advanced system settings &rarr;
Environment Variables &rarr; User variables &rarr; Path &rarr; New*, then open
a new terminal. Avoid `setx PATH "%PATH%;..."` for this - it merges the system
and user paths into your user path and truncates at 1024 characters.

### Regenerating the samples

`data/sample_resumes/*.txt` are the source of truth. The PDF and DOCX versions
are rendered from them:

```bash
python data/sample_resumes/generate_samples.py
```

### Running the tests

```bash
python -m pytest
```


216 tests. They parse the real generated PDF and DOCX files, not just strings,
because the bugs that matter live in the gap between text you write in a test
and text a PDF actually produces.

---

## How it works

```
Upload  ->  Extract text  ->  Analyze  ->  Structure  ->  Review  ->  Export
```

| Stage | What happens |
| --- | --- |
| **Upload** | Magic-byte format detection, size and emptiness checks. The content signature wins over the file name, so a mislabelled file is still handled and a renamed `.doc` is rejected with an explanation. |
| **Extract** | PyMuPDF for PDF, python-docx for DOCX. Both produce plain text plus provenance metadata and any embedded hyperlink targets. |
| **Analyze** | Text is normalised (bullets, ligatures, dashes, wrapped lines) and split into labelled sections using a heading-alias dictionary. spaCy runs once over the whole document. |
| **Structure** | Each field is parsed by the cheapest technique that is actually reliable for it. |
| **Export** | JSON (nested, schema-conformant) and CSV (two flattenings). |

### Why each field uses the technique it does

| Field | Technique | Reasoning |
| --- | --- | --- |
| Email | regex | Unambiguous. Validated against a TLD shape so `logo@2x.png` is not an address. |
| Phone | scored regex | Resumes are full of numbers that look like phone numbers. Candidates are scored on pattern distinctiveness and nearby keywords, and rejected on date or grade context. |
| Links | regex over text **and** embedded hyperlinks | "LinkedIn" is often a clickable label with no visible URL. |
| Name | line scoring + spaCy `PERSON` | No single signal is sufficient. Position, capitalisation, token shape, job-title keywords and NER corroboration are combined. |
| Location | place patterns + spaCy `GPE` | A bundled gazetteer gives confidence; the `City, ST` shape and NER cover what it misses. |
| Skills | dictionary + regex + spaCy | See below. |
| Education | degree and institution anchor patterns | Far more stable than layout. |
| Experience | date lifting, then fragment classification | See below. |
| Projects | section-scoped, with technology lists resolved against the skill dictionary | Projects are never inferred from job history. |

### Extraction details worth knowing

**PDF reading is column-aware.** A plain `page.get_text()` on a sidebar
resume interleaves unrelated lines and destroys section detection. Text
blocks are grouped into reading columns and each column is read in full
before moving on.

**DOCX reading covers the things Word actually does.** Tables used for
layout, headers and footers holding the candidate's name, list paragraphs
whose bullet marker is formatting rather than text, and hyperlink
relationships. A naive `"\n".join(p.text for p in doc.paragraphs)` silently
loses all four.

**Wrapped lines are rejoined.** A PDF preserves the original visual line
breaks, so one bullet arrives as two or three lines. Continuations are
detected and merged before entries are grouped, otherwise every wrapped
bullet would start a spurious new job.

**Skills use three passes.**

1. *Dictionary (regex).* `data/skills.json` maps a canonical name to its
   aliases and category. Word-boundary regexes are built per alias, which is
   the only approach that handles `C++`, `C#`, `.NET`, `Node.js` and
   `scikit-learn` correctly.
2. *Ambiguity guards.* Short names (`C`, `R`, `Go`) are marked `strict` and
   only accepted inside a skills section or an explicit technology list.
   Names that are also English words (`React`, `Rust`, `express`) are marked
   `common_word`: outside a skills list they must carry the technology's own
   capitalisation, so the verb in "I react quickly" is not a skill. URLs and
   email addresses are stripped before matching, so `github.com/jane` does
   not tag the candidate with GitHub.
3. *Discovery (spaCy).* Delimiter-separated items and short noun chunks in
   the skills section that are not in the dictionary are kept as "Other", so
   a niche tool still appears. Sub-headings such as `Databases:` supply the
   category.

**Experience classification is score-based, not sequential.** The signals
overlap: "Senior Software Engineer" contains an organisation word
(*Software*) and "Engineering Solutions Ltd" contains a role word
(*Engineering*). Legal suffixes (`Pvt Ltd`, `Inc`, `GmbH`) count anywhere;
descriptive ones (`Analytics`, `Technologies`, `Group`) only count at the end
of a fragment. The stronger signal wins rather than whichever test runs
first.

### Explainability

Every contact field records why it was chosen, visible in the UI and exported
under `meta.field_evidence`. Each skill tag carries a tooltip naming the match
source, the section it was found in and the confidence. The **Extracted text**
panel shows the exact text the parser read, so any result can be traced back
to its source. Parser diagnostics list the detected sections, the headings
that produced them, per-field presence and the spaCy model in use.

---

## Project structure

```
app.py                      Streamlit app: layout and orchestration only
requirements.txt
pytest.ini
.streamlit/config.toml      theme and upload limit

src/
  settings.py               all tunable constants
  models.py                 typed results shared across layers
  extraction/               bytes -> text
    dispatcher.py             validation and format dispatch
    pdf_extractor.py          PyMuPDF, column-aware
    docx_extractor.py         python-docx: tables, headers, hyperlinks
    errors.py                 typed failures with user-facing hints
  processing/               text -> analysable structure
    normalize.py              bullets, ligatures, dashes, wrapped words
    sections.py               heading dictionary and segmentation
    dates.py                  date and date-range parsing
    nlp.py                    spaCy facade with graceful degradation
  parser/                   structure -> fields
    contact.py  skills.py  education.py  experience.py  projects.py
    blocks.py                 shared line-shape helpers
    pipeline.py               five-stage orchestration with progress
  export/                   fields -> files
    json_export.py  csv_export.py  filenames.py
  ui/                       presentation only
    theme.py                  stylesheet, light and dark palettes
    components.py             cards, tags, timeline, callouts

data/
  skills.json               configurable skill dictionary
  sample_resumes/           txt sources + generated pdf/docx + generator

tests/                      216 tests across extraction, processing,
                            fields, pipeline and export
```

Each layer depends only on the ones above it. `src/ui` is the only package
that imports Streamlit; the parser and exporters are reusable from a script,
an API or a test.

---

## Export formats

### JSON

The top level matches the agreed candidate schema exactly, with richer keys
alongside it:

```json
{
  "name": "Rahul Sharma",
  "email": "rahul.sharma@example.com",
  "phone": "+91 98765 43210",
  "location": "Bengaluru, Karnataka, India",
  "links": { "LinkedIn": "https://linkedin.com/in/rahulsharma" },
  "summary": "Backend engineer with 4 years of experience...",
  "skills": ["Python", "Java", "Go"],
  "skills_by_category": { "Programming Languages": ["Python", "Java", "Go"] },
  "education": [
    {
      "degree": "B.Tech",
      "institution": "National Institute of Technology",
      "field_of_study": "Computer Science and Engineering",
      "start_year": "2016",
      "end_year": "2020",
      "grade": "CGPA: 8.7/10",
      "location": "Surathkal",
      "details": []
    }
  ],
  "experience": [
    {
      "job_title": "Senior Software Engineer",
      "company": "Zeta Payments Pvt Ltd",
      "location": "Bengaluru, India",
      "start_date": "Mar 2022",
      "end_date": "Present",
      "is_current": true,
      "description": ["Led the migration of the settlement service..."]
    }
  ],
  "projects": [
    {
      "name": "Smart Resume Parser",
      "description": ["Built an end-to-end resume parsing tool..."],
      "technologies": ["Python", "spaCy", "Streamlit", "PyMuPDF"],
      "link": "",
      "start_date": "",
      "end_date": ""
    }
  ],
  "meta": { "parser_version": "1.0.0", "completeness_percent": 100 }
}
```

Undetermined fields are empty strings. `"Not detected"` is a presentation
choice and never appears in exported data.

### CSV

Two flattenings, because a nested document has no single correct flat form:

- **Detailed** (default) — tidy `section, index, field, value` rows. Lossless
  and pivots cleanly in a spreadsheet.
- **Summary** — one row per candidate with repeated values joined by `;`.
  Use this when appending many resumes to one sheet.

Both are written with CRLF line endings and a UTF-8 BOM so they open
correctly in Excel on Windows without a manual import step.

---

## Error handling

| Situation | Behaviour |
| --- | --- |
| Unsupported type | Rejected by content signature with the supported list. |
| Legacy `.doc` | Rejected with advice to re-save as `.docx`. |
| Empty file | Rejected before any parsing. |
| Oversized file | Rejected with the actual and permitted sizes. |
| Corrupted PDF / DOCX | Caught and reported with a re-export suggestion. |
| Password-protected PDF | Reported as encrypted. |
| Scanned PDF with no text layer | Reported as image-only, with the image count as evidence. |
| Damaged single PDF page | Skipped; the rest of the document is parsed and a warning is raised. |
| Missing sections | Reported as warnings; the corresponding lists stay empty. |
| No headings at all | Falls back to whole-document scanning and says so. |
| Missing spaCy model | Regex-only parsing, surfaced in the sidebar and the warnings. |

Parsing problems never raise. Only an unreadable document does, and those
errors carry both a message and a remediation hint.

---

## Known limitations

- **Scanned resumes are not supported.** There is no OCR step; an image-only
  PDF is rejected with an explanation rather than silently returning nothing.
- **English only.** The heading aliases, degree patterns and spaCy model are
  English. The architecture is ready for more languages, the data is not.
- **The gazetteer is a confidence aid, not a complete place list.** An
  unlisted city is still detected via the `City, ST` shape or spaCy, but with
  lower confidence.
- **Heavily graphical templates degrade.** Text in images, or in free-floating
  frames with no reading order, cannot be recovered reliably.
- **Date-only entries sort last.** An experience entry with no parseable
  period keeps its document position at the end of the timeline.
