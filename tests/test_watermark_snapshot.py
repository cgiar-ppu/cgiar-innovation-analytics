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
