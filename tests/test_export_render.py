"""Export round-trips (review L6-01/02/03/11/12, wave 3b Lane C).

A typical answer — a heading, **bold**, a pipe table, a result-code citation,
a web link, an internal file path and a <chart> block — must come out of every
export as real structure: HTML/PDF with <table> and clickable <a href>, DOCX
with a Word table and a real hyperlink, and never raw `**`, `| --- |`, chart
JSON or a `file://` / server path.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import sys
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from synapsis.exporters import export_docx, export_html, export_markdown
from synapsis.exporters import render
from synapsis.exporters import watermark as wm

REPORT_URL = "https://reporting.cgiar.org/reports/result-details/1003?phase=6"
OWNER_PATH = "/workspace/outputs/u/0123456789abcdef01234567/0123456789abcdef0123456789abcdef/Kenya-report.docx"

ANSWER = f"""## Summary

**Total:** 1,185 innovation developments in 2025, e.g. [R1003]({REPORT_URL}).
Background: https://www.cgiar.org/research/ and the file `{OWNER_PATH}`.

| Year | Count |
|---|---|
| 2024 | 1,016 |
| 2025 | **1,185** |

- first *point*
- second point

<chart>
{{"chartType": "bar", "title": "Innovations per year", "xAxisKey": "year",
  "data": [{{"year": "2024", "count": 1016}}, {{"year": "2025", "count": null}}],
  "series": [{{"key": "count", "label": "Count"}}]}}
</chart>

<script>alert(1)</script> [click](javascript:alert(1)) ![img](https://evil.example/x.png)
"""


def _rows(answer: str = ANSWER, extra: list | None = None):
    base = [
        {"type": "user", "data": json.dumps({"content": "How many innovations in 2025?"}), "ts": 1_790_000_000.0},
        {"type": "tool_use", "data": json.dumps({"tool": "mcp__synapsis__prms_query", "input": {"sql": "SELECT 1"}}), "ts": 1_790_000_001.0},
        {"type": "tool_result", "data": json.dumps({"content": "rows: 1"}), "ts": 1_790_000_002.0},
        {"type": "thinking", "data": json.dumps({"content": "internal reasoning"}), "ts": 1_790_000_003.0},
        {"type": "text", "data": json.dumps({"content": answer}), "ts": 1_790_000_004.0},
        {"type": "result", "data": json.dumps({"turns": 3, "duration_ms": 4200}), "ts": 1_790_000_005.0},
    ]
    return base + (extra or [])


# ---------------------------------------------------------------------------
# HTML (and therefore PDF, which prints this HTML)
# ---------------------------------------------------------------------------

def test_html_export_renders_markdown_tables_links_and_charts():
    html, media = export_html("Portfolio", "sid-1", _rows(), "standard")
    assert media == "text/html"
    body = html.split('<div class="message user">', 1)[1]
    assert "<table>" in body and "<th>Year</th>" in body and "<td>1,016</td>" in body
    assert "<strong>Total:</strong>" in body and "<strong>1,185</strong>" in body
    assert "<h4>Summary</h4>" in body or "<h2>Summary</h2>" in body
    assert f'<a href="{REPORT_URL}"' in body.replace("&amp;", "&")
    assert '<a href="https://www.cgiar.org/research/"' in body  # bare URL auto-linked
    assert "<li>first <em>point</em></li>" in body
    # The chart is a captioned data table; a missing value is n/a, never 0.
    assert 'class="chart-table"' in body and "Innovations per year (bar chart" in body
    assert "<td>n/a</td>" in body and "chartType" not in body and "<chart>" not in body
    # No raw Markdown and no internal paths.
    assert "**" not in body and "|---|" not in body and "| Year |" not in body
    assert "file://" not in html and "/workspace/" not in html and "Kenya-report.docx" in body


def test_html_export_never_passes_model_markup_or_unsafe_links():
    html, _ = export_html("Portfolio", "sid-1", _rows(), "standard")
    body = html.split('<div class="message user">', 1)[1]
    assert "<script>" not in body and "&lt;script&gt;" in body
    assert 'href="javascript' not in body
    assert "<img" not in html  # images are never fetched by the PDF renderer
    assert "default-src 'none'" in html  # CSP: the export loads nothing external


def test_standard_export_hides_tool_thinking_and_turn_rows_full_shows_them():
    std, _ = export_html("T", "sid", _rows(), "standard")
    full, _ = export_html("T", "sid", _rows(), "full")
    for internal in ("mcp__synapsis__prms_query", "internal reasoning", "3 turns"):
        assert internal not in std
        assert internal in full
    md_std, _ = export_markdown("T", "sid", _rows(), "standard")
    assert "Tool:" not in md_std and "Thinking" not in md_std and "turns ·" not in md_std


def test_timestamps_carry_date_and_utc():
    md, _ = export_markdown("T", "sid", _rows(), "standard")
    assert "## 🧑 You (2026-09-21 " in md and " UTC)" in md


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def test_markdown_export_turns_charts_into_tables_and_scrubs_paths():
    md, _ = export_markdown("Portfolio", "sid-1", _rows(), "standard")
    assert "<chart>" not in md and "chartType" not in md
    assert "*Innovations per year (bar chart; shown as a data table in this export)*" in md
    assert "| Year | Count |" in md and "| 2025 | n/a |" in md
    assert f"[R1003]({REPORT_URL})" in md
    assert "file://" not in md and "/workspace/" not in md and "`Kenya-report.docx`" in md


def test_bare_citation_tokens_are_linked_at_export_time():
    """Chats saved before Lane G's linkifier still export with links."""
    md, _ = export_markdown("T", "sid", _rows("Key result: [R1003]."), "standard")
    m = re.search(r"\[R1003\]\((https://[^)]+)\)", md)
    assert m, md
    html, _ = export_html("T", "sid", _rows("Key result: [R1003]."), "standard")
    assert '<a href="https://' in html and ">R1003</a>" in html


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _docx_parts(path) -> dict[str, str]:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith((".xml", ".rels"))}


def test_docx_export_has_real_tables_and_hyperlinks(tmp_path):
    docx = pytest.importorskip("docx")
    path, _ = export_docx("Portfolio", "sid-1", _rows(), "standard", tmp_path)
    doc = docx.Document(path)
    # Two tables: the answer's pipe table and the chart's data table.
    assert len(doc.tables) == 2
    t = doc.tables[0]
    assert [c.text for c in t.rows[0].cells] == ["Year", "Count"]
    assert [c.text for c in t.rows[2].cells] == ["2025", "1,185"]
    assert any(r.bold for r in t.rows[2].cells[1].paragraphs[0].runs)
    chart = doc.tables[1]
    assert [c.text for c in chart.rows[2].cells] == ["2025", "n/a"]
    parts = _docx_parts(path)
    rels = parts["word/_rels/document.xml.rels"]
    assert 'TargetMode="External"' in rels and "reporting.cgiar.org/reports/result-details/1003" in rels
    assert "www.cgiar.org/research/" in rels
    body = parts["word/document.xml"]
    assert "<w:hyperlink" in body
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "**" not in text and "|---|" not in text and "chartType" not in text
    assert "Total:" in text and any(r.bold and r.text == "Total:" for p in doc.paragraphs for r in p.runs)
    assert "Summary" in [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert any(p.style.name.startswith("List Bullet") and "first" in p.text for p in doc.paragraphs)
    for name, xml in parts.items():
        assert "file://" not in xml, name
        assert "/workspace/" not in xml, name


def test_docx_footer_names_the_snapshot_and_data_date(tmp_path):
    docx = pytest.importorskip("docx")
    path, _ = export_docx("Portfolio", "sid-1", _rows(), "standard", tmp_path)
    footer = " ".join(p.text for p in docx.Document(path).sections[0].footer.paragraphs)
    assert wm.snapshot_line() in footer
    assert f"Data as of {wm.data_as_of_date()}." in footer


def test_docx_survives_control_characters(tmp_path):
    """Review L6-12: \\x0b / ANSI / NUL used to raise ValueError → HTTP 500."""
    docx = pytest.importorskip("docx")
    nasty = "Line\x0bbreak \x1b[32mgreen\x1b[0m and NUL\x00 here"
    rows = _rows(nasty) + [{"type": "tool_result", "data": json.dumps({"content": nasty}), "ts": 1_790_000_009.0}]
    for detail in ("standard", "full"):
        path, _ = export_docx("T\x07itle", "sid", rows, detail, tmp_path)
        text = "\n".join(p.text for p in docx.Document(path).paragraphs)
        assert "green" in text and "\x1b" not in text


def test_watermark_wording_is_unchanged_in_every_format(tmp_path):
    md, _ = export_markdown("T", "sid", _rows(), "standard")
    html, _ = export_html("T", "sid", _rows(), "standard")
    for out in (md, html):
        assert wm.WATERMARK_BANNER in out and wm.SOP_DISCLOSURE in out and wm.snapshot_line() in out
    assert html.split("<body>", 1)[1].lstrip().startswith('<div class="ai-watermark-overlay"')
    docx = pytest.importorskip("docx")
    path, _ = export_docx("T", "sid", _rows(), "standard", tmp_path)
    doc = docx.Document(path)
    assert doc.paragraphs[0].text == wm.WATERMARK_BANNER
    assert "PowerPlusWaterMarkObject1" in doc.sections[0].header._element.xml


# ---------------------------------------------------------------------------
# Renderer units
# ---------------------------------------------------------------------------

def test_scrub_internal_paths_keeps_public_urls():
    s = render.scrub_internal_paths(
        f"see {OWNER_PATH} and file:///workspace/exports/x_temp.html and "
        "https://example.org/app/report.pdf and /workspace/outputs/exports/20260926_dashboard.html"
    )
    assert "Kenya-report.docx" in s and "x_temp.html" in s and "20260926_dashboard.html" in s
    assert "https://example.org/app/report.pdf" in s
    assert "file://" not in s and "/workspace/" not in s


def test_chart_table_formats_numbers_and_gaps():
    caption, cols, rows = render.chart_to_table({
        "chartType": "pie", "title": "Share", "xAxisKey": "region",
        "data": [{"region": "East Africa", "share": 56.0}, {"region": "South Asia", "share": None},
                 {"region": "West Africa", "share": 1234567}],
        "series": [{"key": "share", "label": "Share (%)"}],
    })
    assert caption.startswith("Share (pie chart")
    assert cols == ["Region", "Share (%)"]
    assert rows == [["East Africa", "56"], ["South Asia", "n/a"], ["West Africa", "1,234,567"]]
    assert render.chart_to_table(None)[1] == []
    assert "could not be read" in render.render_message_html("<chart>{not json</chart>")


# ---------------------------------------------------------------------------
# Route: rendering off the event loop, PDF flags, timeout handling (L6-03/L6-11)
# ---------------------------------------------------------------------------

def test_pdf_flags_drop_the_browser_header_footer(tmp_path, monkeypatch):
    from synapsis.routes import export as ex

    monkeypatch.setenv("IA_PDF_BROWSER", sys.executable)
    cmds = ex._pdf_commands(tmp_path / "a.html", tmp_path / "a.pdf", tmp_path / "profile")
    assert cmds and cmds[0][0] == sys.executable
    assert "--no-pdf-header-footer" in cmds[0]
    assert any(a.startswith("--user-data-dir=") for a in cmds[0])


_FAKE_PDF = b"%PDF-1.4\n" + b"0" * 200 + b"\n%%EOF\n"


def _fake_browser(tmp_path, *, sleep: float) -> str:
    script = tmp_path / "fake_browser.py"
    script.write_text(
        "import sys, time\n"
        "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--print-to-pdf=')][0]\n"
        f"open(out, 'wb').write({_FAKE_PDF!r})\n"
        f"time.sleep({sleep})\n"
    )
    return str(script)


def test_pdf_written_before_a_timeout_is_used(tmp_path, monkeypatch):
    """Chromium sometimes hangs after printing; the finished PDF must be kept."""
    from synapsis.routes import export as ex

    script = _fake_browser(tmp_path, sleep=5)
    monkeypatch.setattr(ex, "PDF_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(ex, "_pdf_commands", lambda h, p, prof: [[sys.executable, script, f"--print-to-pdf={p}", str(h)]])
    target = tmp_path / "out.pdf"
    t0 = time.monotonic()
    assert ex._html_to_pdf("<html><body>x</body></html>", target) is True
    assert time.monotonic() - t0 < 4
    assert target.read_bytes() == _FAKE_PDF


def test_incomplete_pdf_is_rejected(tmp_path, monkeypatch):
    from synapsis.routes import export as ex

    script = tmp_path / "broken.py"
    script.write_text(
        "import sys\n"
        "out = [a.split('=', 1)[1] for a in sys.argv if a.startswith('--print-to-pdf=')][0]\n"
        "open(out, 'wb').write(b'%PDF-1.4 truncated')\n"
    )
    monkeypatch.setattr(ex, "_pdf_commands", lambda h, p, prof: [[sys.executable, str(script), f"--print-to-pdf={p}"]])
    assert ex._html_to_pdf("<html></html>", tmp_path / "o.pdf") is False
    assert not (tmp_path / "o.pdf").exists()


@pytest.mark.asyncio
async def test_export_rendering_does_not_block_the_event_loop(initialized_db, tmp_path, monkeypatch):
    """While a slow PDF render runs, other coroutines keep being served."""
    from synapsis.config import LEGACY_USER_ID
    from synapsis.database import get_db
    from synapsis.routes import export as ex

    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions(session_id,title,created_at,updated_at,model,user_id) VALUES(?,?,?,?,?,?)",
            ("sid-slow", "Slow", time.time(), time.time(), "m", LEGACY_USER_ID))
        await db.execute("INSERT INTO messages(session_id,type,data,ts) VALUES(?,?,?,?)",
                         ("sid-slow", "text", json.dumps({"content": "**hi**"}), time.time()))
        await db.commit()

    def slow_pdf(html_content, pdf_filepath):
        time.sleep(0.6)  # a blocking Chromium run
        Path(pdf_filepath).write_bytes(_FAKE_PDF)
        return True

    monkeypatch.setattr(ex, "_html_to_pdf", slow_pdf)
    monkeypatch.setattr(ex, "EXPORT_DIR", tmp_path / "exports")
    ticks = 0

    async def ticker():
        nonlocal ticks
        for _ in range(10):
            await asyncio.sleep(0.03)
            ticks += 1

    with patch("synapsis.config.AUTH_DISABLED", True):
        resp, _ = await asyncio.gather(
            ex.export_conversation("sid-slow", format="pdf", detail="standard"), ticker())
    assert ticks == 10  # the loop kept running during the 0.6 s render
    assert resp.media_type == "application/pdf"


@pytest.mark.asyncio
async def test_route_exports_every_format(initialized_db, tmp_path, monkeypatch):
    from synapsis.config import LEGACY_USER_ID
    from synapsis.database import get_db
    from synapsis.routes import export as ex

    async with get_db() as db:
        await db.execute(
            "INSERT INTO sessions(session_id,title,created_at,updated_at,model,user_id) VALUES(?,?,?,?,?,?)",
            ("sid-all", "All formats", time.time(), time.time(), "m", LEGACY_USER_ID))
        for r in _rows():
            await db.execute("INSERT INTO messages(session_id,type,data,ts) VALUES(?,?,?,?)",
                             ("sid-all", r["type"], r["data"], r["ts"]))
        await db.commit()
    monkeypatch.setattr(ex, "EXPORT_DIR", tmp_path / "exports")
    monkeypatch.setattr(ex, "_html_to_pdf", lambda html, target: False)  # no converter → HTML fallback
    with patch("synapsis.config.AUTH_DISABLED", True):
        for fmt, media in (("md", "text/markdown"), ("html", "text/html"),
                           ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
                           ("pdf", "text/html")):
            resp = await ex.export_conversation("sid-all", format=fmt, detail="standard")
            assert resp.media_type == media, fmt
            data = Path(resp.path).read_bytes()
            assert b"file://" not in data
            assert b"<chart>" not in data
            if fmt in ("html", "pdf"):
                assert b"**Total" not in data and b"<table>" in data
        with pytest.raises(Exception) as err:
            await ex.export_conversation("sid-all", format="exe")
        assert getattr(err.value, "status_code", None) == 400


def _find_browser():
    import shutil
    for b in ("chromium", "chromium-browser", "google-chrome",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if shutil.which(b) or Path(b).is_file():
            return b
    return None


@pytest.mark.skipif(_find_browser() is None, reason="no Chromium/Chrome available")
def test_real_pdf_has_links_and_no_file_url_footer(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from synapsis.routes import export as ex

    html, _ = export_html("Portfolio", "sid-1", _rows(), "standard")
    target = tmp_path / "real.pdf"
    assert ex._html_to_pdf(html, target) is True
    reader = pypdf.PdfReader(str(target))
    text = "".join(p.extract_text() or "" for p in reader.pages)
    assert "file://" not in text and "_temp.html" not in text
    assert "REQUIRES HUMAN VALIDATION" in text
    assert "**" not in text
    uris = [a.get_object().get("/A", {}).get("/URI") for p in reader.pages for a in (p.get("/Annots") or [])]
    assert any(u and "reporting.cgiar.org/reports/result-details/1003" in u for u in uris)


# ---------------------------------------------------------------------------
# Agent-created documents (Lane A's create_document) use the same renderer
# ---------------------------------------------------------------------------

def test_create_document_docx_and_md_use_the_export_renderer(tmp_path):
    docx = pytest.importorskip("docx")
    from synapsis.tools.create_document import create_document_file

    with patch("synapsis.config.WORKSPACE", tmp_path):
        path = create_document_file(user_id="alice@cgiar.org", title="Kenya brief", fmt="docx",
                                    content=ANSWER)
        md_path = create_document_file(user_id="alice@cgiar.org", title="Kenya brief", fmt="md",
                                       content=ANSWER)
    doc = docx.Document(str(path))
    assert len(doc.tables) == 2  # the pipe table + the chart's data table
    parts = _docx_parts(path)
    assert "reporting.cgiar.org/reports/result-details/1003" in parts["word/_rels/document.xml.rels"]
    assert "<w:hyperlink" in parts["word/document.xml"]
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "**" not in text and "chartType" not in text and "/workspace/" not in text
    md = md_path.read_text()
    assert "<chart>" not in md and "| 2025 | n/a |" in md and f"[R1003]({REPORT_URL})" in md
