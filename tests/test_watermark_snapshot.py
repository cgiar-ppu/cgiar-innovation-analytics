"""Every export surface must name the PRMS snapshot it was built from (2026-09-07 re-point)."""

from __future__ import annotations

from datetime import datetime

import pytest

from synapsis.exporters import watermark as wm
from synapsis import prms_snapshot as ps

PINNED = datetime(2026, 7, 20, 14, 30)


@pytest.fixture(autouse=True)
def _fresh_cache():
    ps._cache.clear()
    yield
    ps._cache.clear()


def test_snapshot_line_is_data_not_prose():
    line = wm.snapshot_line()
    assert line.startswith("PRMS snapshot")
    assert line.endswith(".")
    # never a hard-coded vintage
    assert "June" not in line and "March" not in line


def test_markdown_carries_snapshot_line():
    md = wm.watermark_markdown(PINNED)
    assert wm.snapshot_line() in md
    assert md.index(wm.provenance_notice(PINNED)) < md.index(wm.snapshot_line()) < md.index(wm.export_timestamp_line(PINNED))
    assert wm.snapshot_line() in wm.watermark_markdown_footer(PINNED)


def test_html_and_plain_carry_snapshot_line():
    html = wm.watermark_html(PINNED)
    assert 'class="ai-watermark-snapshot"' in html
    assert wm.snapshot_line() in html
    assert "ai-watermark-snapshot" in wm.WATERMARK_HTML_CSS
    assert wm.snapshot_line() in wm.watermark_html_overlay(PINNED)
    assert wm.snapshot_line() in wm.watermark_plain(PINNED)


def test_docx_notice_box_carries_snapshot_line():
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("body")
    wm.apply_ai_watermark(doc, date=PINNED, title="t")
    texts = [p.text for p in doc.paragraphs]
    assert any(wm.snapshot_line() in t for t in texts[:3])


def test_unavailable_snapshot_degrades_gracefully(monkeypatch, tmp_path):
    monkeypatch.setenv("PRMS_DB_PATH", str(tmp_path / "missing.sqlite"))
    ps._cache.clear()
    assert wm.snapshot_line() == "PRMS snapshot unavailable."
    # "Data as of" never falls back to the export date (review L6-01).
    assert wm.data_as_of_date() == wm.DATA_DATE_UNKNOWN
    assert wm.provenance_notice(PINNED).endswith(f"Data as of {wm.DATA_DATE_UNKNOWN}.")
    assert "2026-07-20" not in wm.provenance_notice(PINNED)


# ---------------------------------------------------------------------------
# Review L6-01: "Data as of" = the snapshot's data date, on every surface
# ---------------------------------------------------------------------------

def _fake_snapshot(tmp_path, max_updated="2026-09-12 08:00:00", name="prdb_20260913.sqlite"):
    import sqlite3

    db = tmp_path / name
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE result (id INTEGER, last_updated_date TEXT)")
    con.execute("INSERT INTO result VALUES (1, ?)", (max_updated,))
    con.execute("CREATE TABLE version (id INTEGER, phase_name TEXT, is_active INTEGER, status INTEGER, end_date TEXT)")
    con.commit()
    con.close()
    return db


def test_data_as_of_is_the_snapshot_data_date_not_the_export_date(monkeypatch, tmp_path):
    db = _fake_snapshot(tmp_path)
    monkeypatch.setenv("PRMS_DB_PATH", str(db))
    monkeypatch.setenv("PRMS_DB_ROOT", str(tmp_path / "no-root"))
    ps._cache.clear()
    assert wm.data_as_of_date() == "2026-09-12"
    notice = wm.provenance_notice(datetime(2026, 9, 26, 10, 0))
    assert notice.endswith("Data as of 2026-09-12.")
    assert "2026-09-26" not in notice
    # The snapshot line agrees with it, and the export moment has its own line.
    assert wm.snapshot_line() == "PRMS snapshot 2026-09-13 (data as of 2026-09-12)."
    md = wm.watermark_markdown(datetime(2026, 9, 26, 10, 0))
    assert "Data as of 2026-09-12." in md and "Export generated on 26 September 2026 at 10:00 UTC." in md
    for surface in (wm.watermark_html(PINNED), wm.watermark_html_overlay(PINNED),
                    wm.watermark_plain(PINNED), wm.watermark_markdown_footer(PINNED)):
        assert "Data as of 2026-09-12." in surface
        assert "Data as of 2026-07-20" not in surface


def test_docx_footer_carries_data_date_and_snapshot_line(monkeypatch, tmp_path):
    docx = pytest.importorskip("docx")
    db = _fake_snapshot(tmp_path)
    monkeypatch.setenv("PRMS_DB_PATH", str(db))
    monkeypatch.setenv("PRMS_DB_ROOT", str(tmp_path / "no-root"))
    ps._cache.clear()
    doc = docx.Document()
    doc.add_paragraph("body")
    wm.apply_ai_watermark(doc, date=PINNED, title="t")
    footer = " ".join(p.text for p in doc.sections[0].footer.paragraphs)
    assert "Data as of 2026-09-12." in footer
    assert "PRMS snapshot 2026-09-13 (data as of 2026-09-12)." in footer
    assert "2026-07-20" not in footer
