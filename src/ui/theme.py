"""Visual theme.

One stylesheet, driven by CSS custom properties so the light and dark palettes
differ only in a token block. The look is a restrained SaaS dashboard: white
or near-black surfaces, 1px borders, 12px radii, a single indigo accent, and
generous whitespace. No gradients, no glass, no decorative motion - the only
transitions are 120ms hover states on interactive elements.
"""

from __future__ import annotations

from typing import Literal

Appearance = Literal["light", "dark"]

_LIGHT_TOKENS = """
  --bg: #f6f7f9;
  --surface: #ffffff;
  --surface-muted: #f9fafb;
  --surface-hover: #f3f4f6;
  --border: #e5e7eb;
  --border-strong: #d1d5db;
  --text: #111827;
  --text-muted: #6b7280;
  --text-subtle: #9ca3af;
  --accent: #4f46e5;
  --accent-hover: #4338ca;
  --accent-soft: #eef2ff;
  --accent-border: #c7d2fe;
  --success: #047857;
  --success-soft: #ecfdf5;
  --warning: #b45309;
  --warning-soft: #fffbeb;
  --danger: #b91c1c;
  --danger-soft: #fef2f2;
  --shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06);
  --shadow-lift: 0 4px 12px rgba(16, 24, 40, 0.08);
"""

_DARK_TOKENS = """
  --bg: #0b0d12;
  --surface: #14171f;
  --surface-muted: #1a1e28;
  --surface-hover: #1f2430;
  --border: #272c38;
  --border-strong: #363d4d;
  --text: #e8eaf0;
  --text-muted: #9ba3b4;
  --text-subtle: #6b7280;
  --accent: #818cf8;
  --accent-hover: #a5b4fc;
  --accent-soft: #1e2338;
  --accent-border: #3b4374;
  --success: #34d399;
  --success-soft: #11241d;
  --warning: #fbbf24;
  --warning-soft: #2a2110;
  --danger: #f87171;
  --danger-soft: #2a1414;
  --shadow: 0 1px 2px rgba(0, 0, 0, 0.3);
  --shadow-lift: 0 4px 14px rgba(0, 0, 0, 0.45);
"""

#: ``__TOKENS__`` is substituted with the palette. Plain string replacement is
#: used rather than ``str.format`` so none of the CSS braces need escaping.
_STYLESHEET = """
<style>
:root {
__TOKENS__
  --radius: 12px;
  --radius-sm: 8px;
  --radius-pill: 999px;
}

/* ---------- app shell ---------- */

.stApp, [data-testid="stAppViewContainer"] {
  background: var(--bg);
}
[data-testid="stHeader"] {
  background: transparent;
}
.block-container {
  padding-top: 2.2rem;
  padding-bottom: 4rem;
  max-width: 1180px;
}
.stApp, .stApp p, .stApp li, .stApp span, .stApp label,
.stApp h1, .stApp h2, .stApp h3, .stApp h4 {
  color: var(--text);
}
.stApp a {
  color: var(--accent);
  text-decoration: none;
}
.stApp a:hover {
  text-decoration: underline;
}
hr {
  border-color: var(--border);
}

/* ---------- hero ---------- */

.srp-hero {
  margin-bottom: 1.6rem;
}
.srp-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.72rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-pill);
  padding: 0.28rem 0.7rem;
  margin-bottom: 0.9rem;
}
.srp-title {
  font-size: 2.3rem;
  font-weight: 700;
  letter-spacing: -0.025em;
  line-height: 1.15;
  margin: 0 0 0.4rem 0;
  color: var(--text);
}
.srp-subtitle {
  font-size: 1.04rem;
  color: var(--text-muted);
  margin: 0;
  max-width: 46rem;
  line-height: 1.55;
}

/* ---------- section headers ---------- */

.srp-section {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 1rem;
  margin: 2.4rem 0 0.9rem 0;
  padding-bottom: 0.6rem;
  border-bottom: 1px solid var(--border);
}
.srp-section-title {
  font-size: 1.12rem;
  font-weight: 650;
  letter-spacing: -0.012em;
  color: var(--text);
}
.srp-section-meta {
  font-size: 0.82rem;
  color: var(--text-subtle);
  white-space: nowrap;
}

/* ---------- cards ---------- */

.srp-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.05rem 1.15rem;
  box-shadow: var(--shadow);
  height: 100%;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}
.srp-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-lift);
}
.srp-card-label {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--text-subtle);
  margin-bottom: 0.4rem;
  display: flex;
  align-items: center;
  gap: 0.35rem;
}
.srp-card-value {
  font-size: 1rem;
  font-weight: 560;
  color: var(--text);
  word-break: break-word;
  line-height: 1.4;
}
.srp-card-value.is-large {
  font-size: 1.28rem;
  font-weight: 650;
  letter-spacing: -0.015em;
}
.srp-card-value.is-missing {
  color: var(--text-subtle);
  font-weight: 450;
  font-style: italic;
}
.srp-card-note {
  margin-top: 0.45rem;
  font-size: 0.74rem;
  color: var(--text-subtle);
  line-height: 1.45;
}

/* ---------- metrics ---------- */

.srp-metric {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 0.85rem 1rem;
  box-shadow: var(--shadow);
}
.srp-metric-value {
  font-size: 1.5rem;
  font-weight: 680;
  letter-spacing: -0.02em;
  line-height: 1.1;
  color: var(--text);
}
.srp-metric-label {
  font-size: 0.74rem;
  color: var(--text-muted);
  margin-top: 0.2rem;
}
.srp-meter {
  height: 5px;
  border-radius: var(--radius-pill);
  background: var(--surface-hover);
  margin-top: 0.6rem;
  overflow: hidden;
}
.srp-meter > span {
  display: block;
  height: 100%;
  border-radius: var(--radius-pill);
  background: var(--accent);
}

/* ---------- tags ---------- */

.srp-tag-group {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin: 0.15rem 0 0.2rem 0;
}
.srp-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--text);
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 0.24rem 0.68rem;
  transition: border-color 120ms ease, background 120ms ease;
}
.srp-tag:hover {
  border-color: var(--accent-border);
  background: var(--accent-soft);
}
.srp-tag.is-accent {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}
.srp-tag-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.65;
}
.srp-category {
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-subtle);
  margin: 0.9rem 0 0.45rem 0;
}

/* ---------- timeline ---------- */

.srp-timeline {
  position: relative;
  padding-left: 1.4rem;
}
.srp-timeline::before {
  content: "";
  position: absolute;
  left: 4px;
  top: 6px;
  bottom: 6px;
  width: 1px;
  background: var(--border);
}
.srp-timeline-item {
  position: relative;
  margin-bottom: 0.9rem;
}
.srp-timeline-item::before {
  content: "";
  position: absolute;
  left: -1.4rem;
  top: 1.15rem;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--surface);
  border: 2px solid var(--border-strong);
}
.srp-timeline-item.is-current::before {
  background: var(--accent);
  border-color: var(--accent);
}

/* ---------- entry cards ---------- */

.srp-entry {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.05rem 1.2rem;
  box-shadow: var(--shadow);
  margin-bottom: 0.85rem;
  transition: border-color 120ms ease, box-shadow 120ms ease;
}
.srp-entry:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-lift);
}
.srp-entry-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem 1rem;
}
.srp-entry-title {
  font-size: 1.02rem;
  font-weight: 640;
  letter-spacing: -0.01em;
  color: var(--text);
}
.srp-entry-sub {
  font-size: 0.92rem;
  color: var(--text-muted);
  margin-top: 0.18rem;
}
.srp-entry-dates {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-muted);
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 0.18rem 0.6rem;
  white-space: nowrap;
}
.srp-entry-dates.is-current {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: var(--accent-border);
}
.srp-entry-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 1.1rem;
  margin-top: 0.7rem;
  padding-top: 0.7rem;
  border-top: 1px dashed var(--border);
}
.srp-field {
  font-size: 0.84rem;
  color: var(--text-muted);
}
.srp-field b {
  font-weight: 600;
  color: var(--text);
}
.srp-field.is-missing b {
  color: var(--text-subtle);
  font-weight: 450;
  font-style: italic;
}
.srp-bullets {
  margin: 0.7rem 0 0 1.05rem;
  padding: 0;
  color: var(--text-muted);
  font-size: 0.9rem;
  line-height: 1.6;
}
.srp-bullets li {
  margin-bottom: 0.28rem;
  color: var(--text-muted);
}
.srp-bullets li::marker {
  color: var(--text-subtle);
}

/* ---------- processing stages ---------- */

.srp-stages {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.1rem 1.25rem;
  box-shadow: var(--shadow);
}
.srp-stage {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  font-size: 0.93rem;
  padding: 0.26rem 0;
  color: var(--text-subtle);
}
.srp-stage-icon {
  width: 1.1rem;
  text-align: center;
  font-weight: 700;
}
.srp-stage.is-done {
  color: var(--text);
}
.srp-stage.is-done .srp-stage-icon {
  color: var(--success);
}
.srp-stage.is-active {
  color: var(--accent);
  font-weight: 560;
}
.srp-stage.is-active .srp-stage-icon {
  color: var(--accent);
}

/* ---------- callouts ---------- */

.srp-note {
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  background: var(--surface);
  border-radius: var(--radius-sm);
  padding: 0.7rem 0.9rem;
  font-size: 0.87rem;
  color: var(--text-muted);
  line-height: 1.55;
}
.srp-note.is-warning {
  border-left-color: var(--warning);
  background: var(--warning-soft);
}
.srp-note.is-danger {
  border-left-color: var(--danger);
  background: var(--danger-soft);
}
.srp-note.is-success {
  border-left-color: var(--success);
  background: var(--success-soft);
}
.srp-note b {
  color: var(--text);
}
.srp-empty {
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  padding: 1.5rem 1.2rem;
  text-align: center;
  color: var(--text-subtle);
  font-size: 0.9rem;
  background: var(--surface-muted);
}

/* ---------- streamlit widget overrides ---------- */

[data-testid="stFileUploaderDropzone"] {
  background: var(--surface) !important;
  border: 1.5px dashed var(--border-strong) !important;
  border-radius: var(--radius) !important;
  padding: 2rem 1.5rem !important;
  transition: border-color 120ms ease, background 120ms ease;
}
[data-testid="stFileUploaderDropzone"]:hover {
  border-color: var(--accent) !important;
  background: var(--accent-soft) !important;
}
[data-testid="stFileUploaderDropzone"] * {
  color: var(--text-muted) !important;
}
[data-testid="stFileUploaderDropzone"] button {
  background: var(--surface-muted) !important;
  color: var(--text) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: var(--radius-sm) !important;
}
[data-testid="stFileUploaderFile"] {
  background: var(--surface-muted);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 0.5rem 0.7rem;
}
[data-testid="stFileUploaderFile"] * {
  color: var(--text) !important;
}

.stButton > button, .stDownloadButton > button {
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-strong);
  background: var(--surface);
  color: var(--text);
  font-weight: 550;
  padding: 0.5rem 1.05rem;
  transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--accent);
  color: var(--accent);
  background: var(--accent-soft);
}
.stButton > button[kind="primary"],
.stDownloadButton > button[kind="primary"] {
  background: var(--accent);
  border-color: var(--accent);
  color: #ffffff;
}
.stButton > button[kind="primary"]:hover,
.stDownloadButton > button[kind="primary"]:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
  color: #ffffff;
}
.stButton > button:disabled, .stButton > button:disabled:hover {
  background: var(--surface-muted);
  border-color: var(--border);
  color: var(--text-subtle);
  cursor: not-allowed;
}

[data-testid="stExpander"] {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius) !important;
  box-shadow: var(--shadow);
}
[data-testid="stExpander"] details {
  border: none !important;
  background: transparent !important;
}
[data-testid="stExpander"] summary {
  color: var(--text) !important;
  font-weight: 550;
}
[data-testid="stExpander"] summary:hover {
  color: var(--accent) !important;
}

[data-testid="stSidebar"] {
  background: var(--surface);
  border-right: 1px solid var(--border);
}
[data-testid="stSidebar"] * {
  color: var(--text);
}
[data-testid="stSidebar"] .srp-sidebar-brand {
  font-size: 1.02rem;
  font-weight: 680;
  letter-spacing: -0.015em;
  margin-bottom: 0.15rem;
}
[data-testid="stSidebar"] .srp-sidebar-note {
  font-size: 0.8rem;
  color: var(--text-muted);
  line-height: 1.5;
}

[data-testid="stProgress"] > div > div > div {
  background: var(--accent);
}
[data-testid="stProgress"] > div > div {
  background: var(--surface-hover);
}

.stTextArea textarea, .stTextInput input, .stSelectbox div[data-baseweb="select"] > div {
  background: var(--surface) !important;
  color: var(--text) !important;
  border-color: var(--border) !important;
  border-radius: var(--radius-sm) !important;
}
.stTextArea textarea {
  font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  font-size: 0.8rem !important;
  line-height: 1.55;
}
[data-testid="stDataFrame"] {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.stRadio [role="radiogroup"] label, .stCheckbox label {
  color: var(--text) !important;
}
code {
  background: var(--surface-muted) !important;
  color: var(--accent) !important;
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 0.08rem 0.3rem;
  font-size: 0.84em;
}

/* ---------- responsive ---------- */

@media (max-width: 820px) {
  .srp-title { font-size: 1.85rem; }
  .block-container { padding-top: 1.4rem; }
  .srp-entry-head { flex-direction: column; align-items: flex-start; }
}
</style>
"""


def stylesheet(appearance: Appearance = "light") -> str:
    """Return the full ``<style>`` block for the chosen appearance."""
    tokens = _DARK_TOKENS if appearance == "dark" else _LIGHT_TOKENS
    return _STYLESHEET.replace("__TOKENS__", tokens.strip("\n"))
