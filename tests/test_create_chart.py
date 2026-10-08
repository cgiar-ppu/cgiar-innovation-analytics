"""create_chart numeric parsing (review L6-04).

"56%" used to be plotted as 0 (the series was inferred because the detector
stripped "%", but the converter only stripped ","), and "n/a" was plotted as a
real zero. One parser now serves both paths; missing values become gaps
(``None``) and the agent is told about them.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from synapsis.tools.create_chart import create_chart, parse_number


@pytest.mark.parametrize("raw,expected", [
    (1185, 1185), (56.2, 56.2), ("56%", 56), ("56.5 %", 56.5), ("1,234", 1234),
    ("1 234", 1234), ("1 234", 1234), ("$2.5", 2.5), ("USD 1,000", 1000),
    ("€ 12", 12), ("(12)", -12), ("−12", -12), ("-3.5", -3.5), (" 7 ", 7),
])
def test_parse_number_reads_formatted_numbers(raw, expected):
    number, ok = parse_number(raw)
    assert ok and number == expected


@pytest.mark.parametrize("raw", [None, "", "n/a", "N/A", "—", "-", "null", "not yet reported", float("nan")])
def test_missing_markers_are_gaps_not_zero(raw):
    assert parse_number(raw) == (None, True)


@pytest.mark.parametrize("raw", ["1.2k", "about 40", "abc", True, [1], "inf"])
def test_unreadable_values_are_gaps_and_flagged(raw):
    assert parse_number(raw) == (None, False)


def _run(args):
    out = asyncio.run(create_chart.handler(args))
    text = out["content"][0]["text"]
    m = re.search(r"<chart>\n(.*)\n</chart>", text, re.S)
    return text, (json.loads(m.group(1)) if m else None), out


def test_percentages_and_missing_values_are_plotted_correctly():
    text, spec, _ = _run({
        "chart_type": "bar", "title": "Innovation share by region",
        "data": [{"region": "East Africa", "share": "56%", "count": "1,234"},
                 {"region": "South Asia", "share": "44%", "count": "n/a"}],
    })
    assert spec["xAxisKey"] == "region"
    assert [s["key"] for s in spec["series"]] == ["share", "count"]
    assert [d["share"] for d in spec["data"]] == [56, 44]  # was [0, 0]
    assert [d["count"] for d in spec["data"]] == [1234, None]  # "n/a" was 0
    assert "1 value(s) are missing and are shown as gaps, not zeros" in text


def test_unreadable_value_is_reported_to_the_agent():
    text, spec, _ = _run({
        "chart_type": "line", "title": "Trend", "x_axis_key": "year",
        "data": [{"year": "2024", "n": "1.2k"}, {"year": "2025", "n": 1185}],
        "series": [{"key": "n"}],
    })
    assert [d["n"] for d in spec["data"]] == [None, 1185]
    assert "could not be read as numbers: n='1.2k'" in text


def test_series_inferred_even_when_first_row_is_missing():
    _, spec, _ = _run({
        "chart_type": "bar", "title": "Counts",
        "data": [{"region": "A", "count": "n/a"}, {"region": "B", "count": 12}],
    })
    assert [s["key"] for s in spec["series"]] == ["count"]
    assert [d["count"] for d in spec["data"]] == [None, 12]


def test_x_axis_prefers_a_real_label_over_a_numeric_string():
    _, spec, _ = _run({
        "chart_type": "pie", "title": "Share",
        "data": [{"share": "56%", "region": "East Africa"}, {"share": "44%", "region": "South Asia"}],
    })
    assert spec["xAxisKey"] == "region"
    assert [d["share"] for d in spec["data"]] == [56, 44]


def test_year_strings_still_serve_as_the_x_axis():
    _, spec, _ = _run({
        "chart_type": "bar", "title": "Per year",
        "data": [{"year": "2024", "count": 1016}, {"year": "2025", "count": 1185}],
    })
    assert spec["xAxisKey"] == "year" and [s["key"] for s in spec["series"]] == ["count"]


def test_all_values_unreadable_is_an_error_not_a_zero_chart():
    text, spec, out = _run({
        "chart_type": "bar", "title": "Nothing", "x_axis_key": "k",
        "data": [{"k": "a", "v": "n/a"}, {"k": "b", "v": "?"}], "series": [{"key": "v"}],
    })
    assert spec is None and out.get("is_error") is True
    assert "could be read as numbers" in text


def test_clean_numeric_data_produces_no_warning():
    text, spec, _ = _run({
        "chart_type": "bar", "title": "Clean",
        "data": [{"year": "2024", "count": 1016}, {"year": "2025", "count": 1185}],
    })
    assert "missing" not in text and [d["count"] for d in spec["data"]] == [1016, 1185]
