"""
Conversation export endpoints — download sessions as MD, HTML, DOCX, or PDF.

- GET /api/export/{session_id}?format=md&detail=standard  — Markdown export
- GET /api/export/{session_id}?format=html&detail=standard — HTML export
- GET /api/export/{session_id}?format=docx&detail=standard — Word Document export
- GET /api/export/{session_id}?format=pdf&detail=standard  — PDF export (falls back to HTML)

detail='standard' includes user/assistant messages and tool names.
detail='full' also includes thinking blocks, tool inputs/outputs, and system messages.
"""

import json
import re
import subprocess

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from synapsis.config import WORKSPACE, logger
from synapsis.database import get_db
from synapsis.utils.db_helpers import fetch_one_or_404
from synapsis.exporters import export_markdown, export_html, export_docx
from synapsis.exporters.common import safe_filename

router = APIRouter(prefix="/api", tags=["export"])

EXPORT_DIR = WORKSPACE / "exports"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def _get_session_data(session_id: str):
    """Fetch session info and messages from the database."""
    async with get_db() as db:
        session_row = await fetch_one_or_404(
            db,
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
            "Session",
        )

        title = session_row["title"]
        if not title:
            c2 = await db.execute(
                "SELECT data FROM messages WHERE session_id = ? AND type = 'user' ORDER BY ts LIMIT 1",
                (session_id,),
            )
            preview_row = await c2.fetchone()
            if preview_row:
                d = json.loads(preview_row["data"])
                title = d.get("content", "Untitled Session")[:80]
            else:
                title = "Untitled Session"

        cursor = await db.execute(
            "SELECT type, data, ts FROM messages WHERE session_id = ? ORDER BY ts",
            (session_id,),
        )
        rows = await cursor.fetchall()

    return title, rows


# ---------------------------------------------------------------------------
# PDF helper (tries several headless-browser / wkhtmltopdf commands)
# ---------------------------------------------------------------------------

def _html_to_pdf(html_content: str, title: str, session_id: str) -> tuple[bool, object, str]:
    """Attempt to convert an HTML string to PDF using available CLI tools.

    Returns:
        (converted, pdf_filepath, pdf_filename)
    """
    safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()

    html_filepath = EXPORT_DIR / f"{safe_title}_{session_id}_temp.html"
    html_filepath.write_text(html_content, encoding="utf-8")

    pdf_filename = f"{safe_title}_{session_id}.pdf"
    pdf_filepath = EXPORT_DIR / pdf_filename

    converted = False
    for cmd in [
        ["chromium", "--headless", "--disable-gpu", "--no-sandbox", f"--print-to-pdf={pdf_filepath}", str(html_filepath)],
        ["chromium-browser", "--headless", "--disable-gpu", "--no-sandbox", f"--print-to-pdf={pdf_filepath}", str(html_filepath)],
        ["google-chrome", "--headless", "--disable-gpu", "--no-sandbox", f"--print-to-pdf={pdf_filepath}", str(html_filepath)],
        ["wkhtmltopdf", str(html_filepath), str(pdf_filepath)],
    ]:
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
            if pdf_filepath.exists() and pdf_filepath.stat().st_size > 0:
                converted = True
                break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue

    html_filepath.unlink(missing_ok=True)
    return converted, pdf_filepath, pdf_filename


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/export/{session_id}")
async def export_conversation(session_id: str, format: str = "md", detail: str = "standard"):
    """Export a conversation session. Supported formats: md, html, docx, pdf."""
    title, rows = await _get_session_data(session_id)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    if format == "md":
        content, media_type = export_markdown(title, session_id, rows, detail)
        filename = safe_filename(title, session_id, "md")
        filepath = EXPORT_DIR / filename
        filepath.write_text(content, encoding="utf-8")
        return FileResponse(filepath, filename=filename, media_type=media_type)

    elif format == "html":
        content, media_type = export_html(title, session_id, rows, detail)
        filename = safe_filename(title, session_id, "html")
        filepath = EXPORT_DIR / filename
        filepath.write_text(content, encoding="utf-8")
        return FileResponse(filepath, filename=filename, media_type=media_type)

    elif format == "docx":
        filepath, filename = export_docx(title, session_id, rows, detail, EXPORT_DIR)
        return FileResponse(
            filepath, filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    elif format == "pdf":
        html_content, _ = export_html(title, session_id, rows, detail)
        converted, pdf_filepath, pdf_filename = _html_to_pdf(html_content, title, session_id)

        if not converted:
            safe_title = re.sub(r'[^\w\s-]', '', title)[:50].strip()
            fallback_path = EXPORT_DIR / f"{safe_title}_{session_id}.html"
            fallback_path.write_text(html_content, encoding="utf-8")
            return FileResponse(fallback_path, filename=fallback_path.name, media_type="text/html")

        return FileResponse(pdf_filepath, filename=pdf_filename, media_type="application/pdf")

    else:
        raise HTTPException(400, f"Unsupported format: {format}. Use: md, html, docx, pdf")
