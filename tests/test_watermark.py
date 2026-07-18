"""Tests for the shared AI-content watermark utility and its application to
every export format (Step 1 of the July-7 guardrails sprint).

The mandate (Jules's standing AI-disclaimer requirement + CGIAR SO SOP) is that
EVERY export the tool produces carries the standardized AI-content notice. These
tests assert the notice is present in each supported format's output.
"""

from datetime import datetime

import pytest

from synapsis.exporters import watermark as wm


# ---------------------------------------------------------------------------
# Core wording
# ---------------------------------------------------------------------------

def test_banner_and_notice_wording():
    assert "AI V0 DRAFT" in wm.WATERMARK_BANNER
    notice = wm.provenance_notice(datetime(2026, 7, 20))
    assert "CGIAR innovation data (PRMS)" in notice
    assert "AI-added interpretation" in notice
    assert "human quality assurance" in notice
    assert "Data as of 2026-07-20." in notice


def test_sop_disclosure_present():
    # The verbatim CGIAR SO SOP disclosure sentence must be reused.
    assert "reviewed, validated, and approved by responsible human authors" in wm.SOP_DISCLOSURE


def test_markdown_watermark_block():
    md = wm.watermark_markdown(datetime(2026, 7, 20))
    assert md.startswith("> ")
    assert wm.WATERMARK_BANNER in md
    assert "human quality assurance" in md


def test_html_watermark_block_and_css():
    html = wm.watermark_html(datetime(2026, 7, 20))
    assert 'class="ai-watermark"' in html
    assert wm.WATERMARK_BANNER in html
    assert "ai-watermark" in wm.WATERMARK_HTML_CSS


def test_docx_watermark_applied_at_top_and_footer():
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Some body content.")
    wm.apply_ai_watermark(doc, date=datetime(2026, 7, 20))

    texts = [p.text for p in doc.paragraphs]
    # Banner is the very first paragraph.
    assert texts[0] == wm.WATERMARK_BANNER
    # Provenance + SOP follow.
    assert any("CGIAR innovation data (PRMS)" in t for t in texts[:3])
    assert any("responsible human authors" in t for t in texts[:3])
    # Footer carries the banner on every page.
    footer_text = " ".join(p.text for p in doc.sections[0].footer.paragraphs)
    assert wm.WATERMARK_BANNER in footer_text


# ---------------------------------------------------------------------------
# End-to-end: each exporter emits the watermark
# ---------------------------------------------------------------------------

def _fake_rows():
    """Minimal DB-row stand-ins understood by the exporters (dict-like access)."""
    import json

    return [
        {"type": "user", "data": json.dumps({"content": "How many innovations?"}), "ts": 1_700_000_000.0},
        {"type": "text", "data": json.dumps({"content": "There are 2,755."}), "ts": 1_700_000_001.0},
    ]


def test_markdown_export_is_watermarked():
    from synapsis.exporters import export_markdown

    content, _ = export_markdown("Test", "abc123", _fake_rows(), "standard")
    assert wm.WATERMARK_BANNER in content
    assert "human quality assurance" in content


def test_html_export_is_watermarked():
    from synapsis.exporters import export_html

    content, _ = export_html("Test", "abc123", _fake_rows(), "standard")
    assert 'class="ai-watermark"' in content
    assert wm.WATERMARK_BANNER in content


def test_docx_export_is_watermarked(tmp_path):
    docx = pytest.importorskip("docx")
    from synapsis.exporters import export_docx

    filepath, _ = export_docx("Test", "abc123", _fake_rows(), "standard", tmp_path)
    doc = docx.Document(filepath)
    assert doc.paragraphs[0].text == wm.WATERMARK_BANNER


def test_html_dashboard_is_watermarked():
    from synapsis.exporters import render_dashboard_html

    html = render_dashboard_html(
        "Portfolio", [{"type": "kpi", "cards": [{"label": "Total", "value": "2,755"}]}]
    )
    assert 'class="ai-watermark"' in html
    assert wm.WATERMARK_BANNER in html
