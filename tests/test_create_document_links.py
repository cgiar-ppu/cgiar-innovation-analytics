"""QA-4 D8: agent-made Excel/CSV carry a "PRMS report" URL column (and real
hyperlinks in xlsx) whenever a table has a result-code column."""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import zipfile
from unittest.mock import patch

import pytest

from synapsis.tools.create_document import (
    REPORT_URL_COLUMN,
    add_report_link_columns,
    create_document_file,
    normalize_tables,
    result_code_column,
)
from synapsis.tools.result_code_citation import use_citation_db_path

R = "https://reporting.cgiar.org/reports/result-details/{}?phase={}"


@pytest.fixture()
def snapshot(tmp_path):
    db = tmp_path / "prms.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE version (id INTEGER PRIMARY KEY, phase_name TEXT, phase_year INT, "
                     "status INT, app_module_id INT)")
        conn.execute("CREATE TABLE result (id INTEGER PRIMARY KEY, result_code INT, version_id INT, "
                     "result_type_id INT, source TEXT, status_id INT, is_active INT, title TEXT)")
        conn.executemany("INSERT INTO version VALUES (?,?,?,?,?)",
                         [(1, "Reporting 2022", 2022, 0, 1), (6, "Reporting 2025", 2025, 0, 1)])
        conn.executemany("INSERT INTO result VALUES (?,?,?,?,?,?,?, 'x')",
                         [(22506, 1003, 6, 7, "Result", 2, 1), (42, 42, 1, 7, "Result", 2, 1)])
    use_citation_db_path(str(db))
    yield db
    use_citation_db_path(None)


@pytest.fixture()
def ws(tmp_path):
    w = tmp_path / "workspace"
    w.mkdir()
    with patch("synapsis.config.WORKSPACE", w):
        yield w


def _t(columns, rows, title="Kenya IRL 7+"):
    return normalize_tables([{"title": title, "columns": columns, "rows": rows}])[0]


@pytest.mark.parametrize("columns,rows,expected", [
    (["Result code", "Innovation", "IRL"], [[1003, "Dairy", 9], [42, "Yam", 7]], 0),
    (["Innovation", "Code"], [["Dairy", "R1003"], ["Yam", "[R42]"]], 1),
    (["Innovation", "Result"], [["Dairy", "[R1003](https://x.org)"], ["Yam", "R42"]], 1),
    (["Country", "Innovations"], [["Kenya", 91], ["Ghana", 7]], None),   # counts are not codes
    (["Year", "Count"], [[2024, 445], [2025, 1185]], None),
])
def test_result_code_column_detection(columns, rows, expected):
    assert result_code_column(_t(columns, rows)) == expected


def test_url_column_added_after_the_code_column(snapshot):
    t = add_report_link_columns([_t(["Result code", "Innovation"], [[1003, "Dairy"], [99999, "Unknown"]])])[0]
    assert t["columns"] == ["Result code", REPORT_URL_COLUMN, "Innovation"]
    assert t["rows"][0] == [1003, R.format(1003, 6), "Dairy"]
    assert t["rows"][1] == [99999, "", "Unknown"]          # unknown code: never a guessed link


def test_existing_url_column_is_left_alone(snapshot):
    t = _t(["Code", "Link"], [["R1003", "https://example.org"], ["R42", ""]])
    assert add_report_link_columns([t])[0]["columns"] == ["Code", "Link"]


def test_csv_carries_the_url_column(ws, snapshot):
    path = create_document_file(user_id="alice@cgiar.org", title="Kenya list", fmt="csv",
                                tables=[{"title": "List", "columns": ["Result code", "Innovation"],
                                         "rows": [[1003, "Dairy"], [42, "Yam"]]}])
    rows = list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig"))))
    assert ["Result code", REPORT_URL_COLUMN, "Innovation"] in rows
    assert ["1003", R.format(1003, 6), "Dairy"] in rows
    assert ["42", R.format(42, 1), "Yam"] in rows


def test_xlsx_has_real_hyperlinks(ws, snapshot):
    path = create_document_file(user_id="alice@cgiar.org", title="Kenya list", fmt="xlsx",
                                tables=[{"title": "List", "columns": ["Innovation", "Code"],
                                         "rows": [["Dairy", "[R1003](https://reporting.cgiar.org/x)"],
                                                  ["Yam", "R42"]]}])
    with zipfile.ZipFile(path) as z:
        sheet = z.read("xl/worksheets/sheet2.xml").decode()
        rels = z.read("xl/worksheets/_rels/sheet2.xml.rels").decode()
        assert "xl/worksheets/_rels/sheet1.xml.rels" not in z.namelist()
    # Code cell text is the plain code, not the markdown link.
    assert ">R1003<" in sheet and "](" not in sheet
    refs = re.findall(r'<hyperlink ref="([A-Z]+\d+)" r:id="(rId\d+)"/>', sheet)
    assert refs == [("B5", "rId1"), ("C5", "rId2"), ("B6", "rId3"), ("C6", "rId4")]
    assert rels.count('TargetMode="External"') == 4
    assert f'Target="{R.format(1003, 6)}"' in rels
    # Opens in openpyxl with the hyperlinks intact.
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.load_workbook(path)
    ws_ = wb.worksheets[1]
    assert ws_["A4"].value == "Innovation" and ws_["C4"].value == REPORT_URL_COLUMN
    assert ws_["B5"].hyperlink.target == R.format(1003, 6)
    assert ws_["C6"].value == R.format(42, 1) and ws_["C6"].hyperlink.target == R.format(42, 1)


def test_md_tables_link_codes_to_the_prms_report(ws, snapshot):
    path = create_document_file(user_id="alice@cgiar.org", title="Kenya list", fmt="md",
                                tables=[{"title": "List", "columns": ["Result code", "Innovation"],
                                         "rows": [[1003, "Dairy"], [42, "Yam"]]}])
    text = path.read_text()
    assert REPORT_URL_COLUMN not in text
    assert f"[R1003]({R.format(1003, 6)})" in text and f"[R42]({R.format(42, 1)})" in text
    assert "results-dashboard" not in text


def test_docx_tables_carry_clickable_prms_report_links(ws, snapshot):
    docx = pytest.importorskip("docx")
    path = create_document_file(user_id="alice@cgiar.org", title="Kenya list", fmt="docx",
                                tables=[{"title": "List", "columns": ["Result code", "Innovation"],
                                         "rows": [[1003, "Dairy"], [99999, "Unknown"]]}])
    d = docx.Document(str(path))
    t = d.tables[-1]
    assert [c.text for c in t.rows[0].cells] == ["Result code", REPORT_URL_COLUMN, "Innovation"]
    assert [c.text for c in t.rows[1].cells] == ["1003", R.format(1003, 6), "Dairy"]
    assert [c.text for c in t.rows[2].cells] == ["99999", "", "Unknown"]
    targets = [r.target_ref for r in d.part.rels.values() if r.reltype.endswith("/hyperlink")]
    assert R.format(1003, 6) in targets and not any("results-dashboard" in x for x in targets)
    assert len(t._tbl.xpath(".//w:hyperlink")) == 2          # code cell + report cell


DASH = "https://www.cgiar.org/food-security-impact/results-dashboard"
I = "https://reporting.cgiar.org/reports/ipsr-details/{}?phase={}"


@pytest.fixture()
def ipsr_snapshot(snapshot):
    with sqlite3.connect(snapshot) as conn:
        conn.executemany("INSERT INTO version VALUES (?,?,?,?,?)",
                         [(2, "IPSR 2023", 2023, 0, 2), (5, "IPSR 2024", 2024, 0, 2), (7, "IPSR 2025", 2025, 0, 2)])
        conn.executemany("INSERT INTO result VALUES (?,?,?,?,?,?,?, 'x')", [
            (11809, 11180, 2, 10, "Result", 2, 1), (19913, 11180, 5, 10, "Result", 2, 1),
            (29633, 11180, 7, 10, "Result", 2, 1), (17803, 16106, 5, 11, "Result", 2, 1)])
    use_citation_db_path(str(snapshot))
    return snapshot


def test_report_column_for_ipsr_and_unavailable_codes(ipsr_snapshot):
    from synapsis.tools.result_code_citation import REPORT_UNAVAILABLE_NOTE

    t = add_report_link_columns([_t(["Result code", "Innovation"], [[11180, "Package"], [16106, "Seed"]])])[0]
    assert t["rows"][0] == [11180, I.format(11180, 7), "Package"]       # Marc's example
    assert t["rows"][1] == [16106, REPORT_UNAVAILABLE_NOTE, "Seed"]      # no dashboard, no error page
    assert (1, 0) not in t["_links"] and (1, 1) not in t["_links"]


def test_model_written_url_column_is_corrected(ipsr_snapshot):
    from synapsis.tools.result_code_citation import GATED_LINK_NOTE, REPORT_UNAVAILABLE_NOTE

    t = _t(["Code", "Link"], [
        ["R1003", f"{DASH}/?result_code=1003"],                  # dashboard deep link
        ["R11180", f"{DASH}/"],                                   # dashboard home, code from the row
        ["R11180", I.format(11180, 5)],                           # broken IPSR 2024 report
        ["R16106", f"{DASH}/?result_code=16106"],                 # no working PRMS report
        ["R42", "https://example.org/evidence.pdf"],              # evidence link: kept
        ["R1003", "https://reporting.cgiar.org/result/result-detail/1003/general-information"],
        ["R99", f"{DASH}/?result_code=99"],                       # unknown: link dropped
    ])
    out = add_report_link_columns([t])[0]
    assert out["columns"] == ["Code", "Link"]
    links = [r[1] for r in out["rows"]]
    assert links[0] == R.format(1003, 6)
    assert links[1] == I.format(11180, 7)
    assert links[2] == I.format(11180, 7)
    assert links[3] == REPORT_UNAVAILABLE_NOTE
    assert links[4] == "https://example.org/evidence.pdf"
    assert links[5] == R.format(1003, 6)
    assert links[6] == ""
    assert not any("results-dashboard" in str(v) for v in out["_links"].values())
    assert GATED_LINK_NOTE not in str(links)
