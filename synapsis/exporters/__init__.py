"""
Synapsis export formatters.

Each public function converts a list of raw DB message rows plus session
metadata into the rendered artefact for its format.
"""

from .markdown import export_markdown
from .html import export_html
from .docx import export_docx
from .workflow_run import export_workflow_run_markdown, export_workflow_run_html
from .html_dashboard import generate_html_dashboard, render_dashboard_html
from .watermark import (
    apply_ai_watermark,
    watermark_markdown,
    watermark_html,
    watermark_html_style,
    watermark_plain,
    provenance_notice,
    WATERMARK_BANNER,
    WATERMARK_HTML_CSS,
)

__all__ = [
    "export_markdown",
    "export_html",
    "export_docx",
    "export_workflow_run_markdown",
    "export_workflow_run_html",
    "generate_html_dashboard",
    "render_dashboard_html",
    # AI-content watermark utility (applied to every export format)
    "apply_ai_watermark",
    "watermark_markdown",
    "watermark_html",
    "watermark_html_style",
    "watermark_plain",
    "provenance_notice",
    "WATERMARK_BANNER",
    "WATERMARK_HTML_CSS",
]
