"""
DOCX exporter — produces a Word document (.docx) from session rows.

Message bodies are written as real Word structure (headings, bold/italic runs,
bullet/numbered lists, tables, clickable hyperlinks; ``<chart>`` blocks as a
captioned data table) by :func:`synapsis.exporters.render.markdown_into_docx`.

Requires python-docx:  pip install python-docx
"""

import json
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException

from .common import is_visible, parse_row, safe_filename
from .render import clean_text, markdown_into_docx, prepare_assistant_text, prepare_user_text
from .watermark import apply_ai_watermark


def build_docx(title: str, session_id: str, rows, detail: str):
    """Build the watermarked ``Document`` for a session (not saved)."""
    try:
        from docx import Document as DocxDocument
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
    except ImportError:
        raise HTTPException(500, "python-docx not installed. Install with: pip install python-docx")

    title = clean_text(title)
    doc = DocxDocument()

    # Title
    title_para = doc.add_heading(title, level=0)
    for run in title_para.runs:
        run.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)

    # Metadata line
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.LEFT
    meta_run = meta.add_run(
        f"Session: {session_id} · Exported: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    meta_run.font.size = Pt(9)
    meta_run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    doc.add_paragraph()

    def small(text: str, rgb: tuple, *, italic=False, bold=False, size=9):
        p = doc.add_paragraph()
        run = p.add_run(clean_text(text))
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor(*rgb)
        run.italic = italic or None
        run.bold = bold or None
        return p

    for row in rows:
        msg_type, data, ts = parse_row(row)
        if not is_visible(msg_type, data, detail):
            continue

        if msg_type == "user":
            heading = doc.add_heading(f"You ({ts})", level=2)
            for run in heading.runs:
                run.font.color.rgb = RGBColor(0x2E, 0x7D, 0x32)
            markdown_into_docx(doc, prepare_user_text(data.get("content", "")), heading_offset=2)

        elif msg_type == "text":
            heading = doc.add_heading(f"Assistant ({ts})", level=2)
            for run in heading.runs:
                run.font.color.rgb = RGBColor(0x15, 0x65, 0xC0)
            markdown_into_docx(doc, prepare_assistant_text(data.get("content", "")), heading_offset=2)

        elif msg_type == "system":
            subtype = data.get("subtype", "")
            content = prepare_user_text(data.get("content", ""))
            if subtype == "file_upload":
                small(f"📎 {content}", (0x2E, 0x7D, 0x32), italic=True)
            else:
                small(f"📋 System [{subtype}]: {content}", (0x66, 0x66, 0x66), italic=True)

        elif msg_type == "thinking":
            small(f"💭 Thinking: {data.get('content', '')}", (0x7B, 0x1F, 0xA2), italic=True)

        elif msg_type == "tool_use":
            small(f"🔧 Tool: {data.get('tool', 'unknown')}", (0xE6, 0x51, 0x00), bold=True)
            small(json.dumps(data.get("input", {}), indent=2), (0x66, 0x33, 0x00), size=8)

        elif msg_type == "tool_result":
            small(f"📤 Result: {str(data.get('content', ''))[:2000]}", (0x28, 0x35, 0x93))

        elif msg_type == "result":
            turns = data.get("turns", 0)
            duration = data.get("duration_ms", 0)
            p = small(f"— {turns} turns · {duration/1000:.1f}s —", (0x99, 0x99, 0x99))
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # AI-content watermark / disclaimer — required on every export. Applied
    # last so the notice box lands at the very top of the document body and
    # the per-page header/footer marks (running banner, diagonal draft
    # watermark, page numbers) are attached to the section.
    apply_ai_watermark(doc, title=title)
    return doc


def export_docx(title: str, session_id: str, rows, detail: str, export_dir: Path) -> tuple[str, str]:
    """Convert messages to a Word document and save it to export_dir.

    Args:
        title:      Human-readable session title.
        session_id: Session UUID embedded in the document metadata.
        rows:       Iterable of raw DB message rows (type, data JSON, ts).
        detail:     'standard' or 'full'. 'standard' is the conversation only
                    (questions, answers, file uploads); 'full' also includes
                    thinking blocks, tool inputs/outputs, system messages and
                    the per-turn statistics.
        export_dir: Directory in which the .docx file will be written.

    Returns:
        (filepath, filename) — absolute path string and the bare filename.

    Raises:
        HTTPException(500) if python-docx is not installed.
    """
    doc = build_docx(title, session_id, rows, detail)
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(title, session_id, "docx")
    filepath = export_dir / filename
    doc.save(str(filepath))
    return str(filepath), filename
