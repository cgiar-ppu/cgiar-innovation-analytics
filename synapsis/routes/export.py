"""
Conversation export endpoints — download sessions as MD, HTML, DOCX, or PDF.

- GET /api/export/{session_id}?format=md&detail=standard  — Markdown export
- GET /api/export/{session_id}?format=html&detail=standard — HTML export
- GET /api/export/{session_id}?format=docx&detail=standard — Word Document export
- GET /api/export/{session_id}?format=pdf&detail=standard  — PDF export (falls back to HTML)

detail='standard' is the conversation only: questions, answers (rendered
Markdown, charts as data tables, result codes linked) and file uploads.
detail='full' also includes thinking blocks, tool inputs/outputs, system
messages and per-turn statistics.
"""

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from synapsis.config import WORKSPACE, logger
from synapsis.database import get_db
from synapsis.utils.db_helpers import fetch_one_or_404
from synapsis.exporters import export_markdown, export_html, export_docx
from synapsis.exporters.common import safe_filename
from synapsis.auth.middleware import resolve_user_id, resolve_role
from synapsis.auth.scoping import allowed_user_ids

router = APIRouter(prefix="/api", tags=["export"])

EXPORT_DIR = WORKSPACE / "exports"

#: Rendering (Markdown → HTML/DOCX, and above all the headless-Chromium PDF
#: print) runs in worker threads, never on the event loop (review L6-03: a PDF
#: export used to freeze every chat, WebSocket and voice heartbeat for the
#: seconds Chromium took). At most this many renders run at once; further
#: export requests wait their turn without blocking anyone else.
RENDER_CONCURRENCY = max(1, int(os.getenv("IA_EXPORT_RENDER_CONCURRENCY", "2")))
_render_slots = asyncio.Semaphore(RENDER_CONCURRENCY)

#: Per-converter time limit for the PDF print.
PDF_TIMEOUT_SECONDS = 30


async def _render(fn, *args):
    """Run a blocking render function in a worker thread, bounded by the semaphore."""
    async with _render_slots:
        return await asyncio.to_thread(fn, *args)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

async def _get_session_data(session_id: str, user_id: str, role: str | None = None):
    """Fetch session info and messages, scoped to visible owners (404 otherwise).

    Admins may ALSO export sentinel-owned ("legacy" / pre-auth) sessions --
    see synapsis.auth.scoping.allowed_user_ids and docs/SECURITY-SCOPING-NOTE.md.
    """
    ids = allowed_user_ids(user_id, role)
    placeholders = ",".join("?" for _ in ids)
    async with get_db() as db:
        session_row = await fetch_one_or_404(
            db,
            f"SELECT * FROM sessions WHERE session_id = ? AND user_id IN ({placeholders})",
            (session_id, *ids),
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
# PDF helper (headless Chromium / Chrome, then wkhtmltopdf) — runs in a thread
# ---------------------------------------------------------------------------

#: Chromium flags. ``--no-pdf-header-footer`` (``--print-to-pdf-no-header`` on
#: older builds; unknown flags are ignored) removes Chromium's own print
#: header/footer, which stamped the date, title and the internal
#: ``file:///workspace/exports/…_temp.html`` path on every page (review L6-11).
#: The export's own watermark footer is unaffected (it is part of the HTML).
_CHROME_FLAGS = (
    "--headless", "--disable-gpu", "--no-sandbox", "--no-first-run",
    "--disable-extensions", "--disable-background-networking", "--disable-sync",
    "--no-pdf-header-footer", "--print-to-pdf-no-header",
)

_CHROME_BINARIES = (
    "chromium", "chromium-browser", "google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)


def _pdf_commands(html_path: Path, pdf_path: Path, profile_dir: Path) -> list[list[str]]:
    browsers = [os.environ["IA_PDF_BROWSER"]] if os.getenv("IA_PDF_BROWSER") else []
    browsers += [b for b in _CHROME_BINARIES if b not in browsers]
    cmds = [
        [b, *_CHROME_FLAGS, f"--user-data-dir={profile_dir}", f"--print-to-pdf={pdf_path}", str(html_path)]
        for b in browsers
        if shutil.which(b) or Path(b).is_file()
    ]
    if shutil.which("wkhtmltopdf"):
        cmds.append(["wkhtmltopdf", "--quiet", str(html_path), str(pdf_path)])
    return cmds


def _is_complete_pdf(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 64:
            return False
        with path.open("rb") as fh:
            head = fh.read(5)
            fh.seek(max(0, path.stat().st_size - 1024))
            tail = fh.read()
        return head == b"%PDF-" and b"%%EOF" in tail
    except OSError:
        return False


#: How often a running converter is checked for a finished PDF.
_POLL_SECONDS = 0.2


def _run_converter(cmd: list[str], out: Path) -> None:
    """Run one converter until it exits, a complete PDF is on disk, or the timeout.

    Headless Chrome/Chromium sometimes keeps running after it has written the
    PDF (seen locally with Chrome 153; review L6-11), which used to cost the
    full 30 s timeout on every export. The output file is polled instead: once
    it is a complete PDF whose size is stable, the browser is stopped.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + PDF_TIMEOUT_SECONDS
    last_size = -1
    try:
        while time.monotonic() < deadline:
            try:
                proc.wait(timeout=_POLL_SECONDS)
                return
            except subprocess.TimeoutExpired:
                pass
            if _is_complete_pdf(out):
                size = out.stat().st_size
                if size == last_size:
                    return  # finished writing; the browser just has not exited
                last_size = size
        logger.warning("PDF export: %s timed out after %ss", Path(cmd[0]).name, PDF_TIMEOUT_SECONDS)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def _html_to_pdf(html_content: str, pdf_filepath: Path) -> bool:
    """Print *html_content* to *pdf_filepath*. Blocking — call via :func:`_render`.

    Each call works in its own temporary directory (HTML input, PDF output and
    a throwaway browser profile, so two concurrent renders never share a
    Chromium profile lock) and moves the finished PDF into place atomically.
    If a converter keeps running after writing a complete PDF — Chromium
    sometimes does not exit after printing — that PDF is used as soon as it is
    complete (review L6-11); it used to be discarded in favour of the HTML
    fallback after a 30 s wait.
    """
    with tempfile.TemporaryDirectory(prefix="ia-pdf-") as tmp:
        tmp_dir = Path(tmp)
        html_path = tmp_dir / "export.html"
        html_path.write_text(html_content, encoding="utf-8")
        out = tmp_dir / "export.pdf"
        for cmd in _pdf_commands(html_path, out, tmp_dir / "profile"):
            t0 = time.monotonic()
            try:
                _run_converter(cmd, out)
            except FileNotFoundError:
                continue
            if _is_complete_pdf(out):
                os.replace(out, pdf_filepath)
                logger.info("PDF export rendered by %s in %.1fs", Path(cmd[0]).name, time.monotonic() - t0)
                return True
            out.unlink(missing_ok=True)
    return False


# ---------------------------------------------------------------------------
# Blocking export builders (run in worker threads)
# ---------------------------------------------------------------------------

def _write_text_export(fn, title: str, session_id: str, rows, detail: str, ext: str) -> tuple[Path, str, str]:
    content, media_type = fn(title, session_id, rows, detail)
    filename = safe_filename(title, session_id, ext)
    filepath = EXPORT_DIR / filename
    filepath.write_text(content, encoding="utf-8")
    return filepath, filename, media_type


def _build_pdf(title: str, session_id: str, rows, detail: str) -> tuple[Path, str, str]:
    html_content, _ = export_html(title, session_id, rows, detail)
    pdf_filename = safe_filename(title, session_id, "pdf")
    pdf_filepath = EXPORT_DIR / pdf_filename
    if _html_to_pdf(html_content, pdf_filepath):
        return pdf_filepath, pdf_filename, "application/pdf"
    logger.warning("PDF export: no converter produced a PDF; returning HTML")
    fallback_name = safe_filename(title, session_id, "html")
    fallback_path = EXPORT_DIR / fallback_name
    fallback_path.write_text(html_content, encoding="utf-8")
    return fallback_path, fallback_name, "text/html"


def _build_docx(title: str, session_id: str, rows, detail: str) -> tuple[Path, str, str]:
    filepath, filename = export_docx(title, session_id, rows, detail, EXPORT_DIR)
    return (
        Path(filepath), filename,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/export/{session_id}")
async def export_conversation(
    session_id: str,
    format: str = "md",
    detail: str = "standard",
    token: str | None = None,
):
    """Export a conversation session (owner-only). Supported formats: md, html, docx, pdf.

    Because the browser triggers this via ``window.open`` (which cannot attach an
    Authorization header), the JWT is accepted as a ``?token=`` query param and
    resolved to the owning user here. In dev-bypass mode the token is ignored.

    All rendering happens in worker threads (at most ``RENDER_CONCURRENCY`` at
    once), so an export never stalls other users' chats.
    """
    from synapsis.config import AUTH_DISABLED, LEGACY_USER_ID
    from synapsis.auth.tokens import verify_token

    if AUTH_DISABLED:
        user_id = LEGACY_USER_ID
        role = "admin"
    else:
        user = verify_token(token) if token else None
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user_id = resolve_user_id(user)
        role = resolve_role(user)

    if format not in ("md", "html", "docx", "pdf"):
        raise HTTPException(400, f"Unsupported format: {format}. Use: md, html, docx, pdf")
    if detail not in ("standard", "full"):
        detail = "standard"

    title, rows = await _get_session_data(session_id, user_id, role)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    if format == "md":
        filepath, filename, media_type = await _render(
            _write_text_export, export_markdown, title, session_id, rows, detail, "md")
    elif format == "html":
        filepath, filename, media_type = await _render(
            _write_text_export, export_html, title, session_id, rows, detail, "html")
    elif format == "docx":
        filepath, filename, media_type = await _render(_build_docx, title, session_id, rows, detail)
    else:
        filepath, filename, media_type = await _render(_build_pdf, title, session_id, rows, detail)

    return FileResponse(filepath, filename=filename, media_type=media_type)
