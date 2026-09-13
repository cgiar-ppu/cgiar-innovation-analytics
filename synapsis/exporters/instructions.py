"""Shared instructions for agent-authored files, in addition to route exporters."""
from synapsis.exporters.watermark import WATERMARK_BANNER

EXPORT_INSTRUCTIONS = f"""## Mandatory AI zero-draft marks on deliverables
Every downloadable output is an AI-assisted draft and must visibly carry:
**{WATERMARK_BANNER}**. This includes files you create with Write/Bash or delegate,
not only the built-in chat export buttons. Preserve this requirement when briefing
another agent. Do not describe any output as approved or human-validated.

Reuse `synapsis.exporters.watermark` from the installed application (Python imports
can add `/app` to sys.path on the hosted runtime): `apply_ai_watermark(document)`
for DOCX; `watermark_markdown()` and `watermark_markdown_footer()` for Markdown;
`watermark_html()`, `watermark_html_overlay()` and `WATERMARK_HTML_CSS` for HTML
and its PDF rendering. Keep the visible banner, per-page mark where supported,
provenance notice and UTC export timestamp. Do not add personal contacts to exports.
For spreadsheets, put the notice in a visible first worksheet and printed headers
or footers; for slides and standalone charts, add a readable draft notice in the
slide/chart footer. Verify the saved file contains the notice before sharing it.
State the actual source snapshot separately from the export generation date.
"""
