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


def test_docx_and_md_tables_unchanged(ws, snapshot):
    path = create_document_file(user_id="alice@cgiar.org", title="Kenya list", fmt="md",
                                tables=[{"title": "List", "columns": ["Result code", "Innovation"],
                                         "rows": [[1003, "Dairy"], [42, "Yam"]]}])
    assert REPORT_URL_COLUMN not in path.read_text()
