"""
Tests for the PRMS dashboard route (`/api/dashboard/prms-stats`).

Covers the multi-year selection introduced by colleague-feedback item F7:

- `years` query-parameter parsing (repeated params, comma lists, dedup,
  ordering, rejection of out-of-range/garbage tokens)
- the human-readable selection label
- `__YEARS__` token binding (no user input is ever interpolated into SQL)
- live regression against the real PRMS snapshot: a single-year selection must
  return exactly the numbers the old `?year=` branch returned, and a multi-year
  selection must be the UNION of its single-year sets (never their sum).

The DB-backed tests skip cleanly when the PRMS snapshot is not present.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.routes.prms_dashboard import (  # noqa: E402
    _PRMS_DB_PATH,
    _bind_years,
    _entity_chart_wording,
    _entity_label,
    _fetch_prms_data,
    _year_params,
    normalize_years,
    years_label,
)

requires_prms_db = pytest.mark.skipif(
    not os.path.isfile(_PRMS_DB_PATH),
    reason=f"PRMS snapshot not available at {_PRMS_DB_PATH}",
)


# ---------------------------------------------------------------------------
# years-param parsing
# ---------------------------------------------------------------------------
class TestNormalizeYears:

    def test_none_and_empty_mean_all_years(self):
        assert normalize_years(None) == ([], [])
        assert normalize_years([]) == ([], [])
        assert normalize_years([""]) == ([], [])

    def test_repeated_params(self):
        assert normalize_years(["2024", "2025"]) == ([2024, 2025], [])

    def test_comma_list(self):
        assert normalize_years(["2024,2025"]) == ([2024, 2025], [])

    def test_mixed_repeated_and_comma_list_with_whitespace(self):
        assert normalize_years(["2025", " 2022 , 2023 "]) == ([2022, 2023, 2025], [])

    def test_duplicates_collapse_and_order_is_ascending(self):
        assert normalize_years(["2025", "2024", "2025"]) == ([2024, 2025], [])

    def test_accepts_ints_as_well_as_strings(self):
        assert normalize_years([2025, 2024]) == ([2024, 2025], [])

    def test_out_of_range_year_is_reported_invalid(self):
        years, invalid = normalize_years(["2021", "2025"])
        assert years == [2025]
        assert invalid == ["2021"]

    def test_garbage_token_is_reported_invalid(self):
        years, invalid = normalize_years(["abc"])
        assert years == []
        assert invalid == ["abc"]


class TestYearsLabel:

    def test_empty_selection_is_all_years(self):
        assert years_label([]) == "All years"

    def test_single_year(self):
        assert years_label([2025]) == "2025"

    def test_contiguous_run_collapses_to_a_range(self):
        assert years_label([2024, 2025]) == "2024–2025"
        assert years_label([2022, 2023, 2024, 2025]) == "2022–2025"

    def test_non_contiguous_selection_is_listed_explicitly(self):
        assert years_label([2022, 2025]) == "2022, 2025"

    def test_label_is_order_insensitive(self):
        assert years_label([2025, 2024]) == "2024–2025"


class TestYearBinding:
    """The __YEARS__ token must become bound parameters, never literals."""

    def test_single_year_binds_one_placeholder(self):
        sql = _bind_years("WHERE reported_year_id IN (__YEARS__)", [2025])
        assert sql == "WHERE reported_year_id IN (:y0)"
        assert _year_params([2025]) == {"y0": 2025}

    def test_multiple_years_bind_positional_placeholders(self):
        sql = _bind_years("WHERE reported_year_id IN (__YEARS__)", [2024, 2025])
        assert sql == "WHERE reported_year_id IN (:y0, :y1)"
        assert _year_params([2024, 2025]) == {"y0": 2024, "y1": 2025}

    def test_no_year_value_is_interpolated_into_the_sql_text(self):
        sql = _bind_years("WHERE reported_year_id IN (__YEARS__)", [2024, 2025])
        assert "2024" not in sql and "2025" not in sql


# ---------------------------------------------------------------------------
# Live regression against the PRMS snapshot
# ---------------------------------------------------------------------------
@requires_prms_db
class TestPRMSDashboardData:

    # Docstring benchmark: 2025 alive-in-year W1/W2 = 963 (+222 bilateral).
    def test_2025_single_year_kpis_are_unchanged(self):
        kpis = _fetch_prms_data(years=[2025])["kpis"]
        assert kpis["total_innovations_w1w2"] == 963
        assert kpis["total_innovations_bilateral"] == 222
        assert kpis["total_innovations"] == 1185

    def test_single_year_alive_in_year_benchmarks(self):
        expected = {2022: 477, 2023: 872, 2024: 1016, 2025: 963}
        for year, w1w2 in expected.items():
            kpis = _fetch_prms_data(years=[year])["kpis"]
            assert kpis["total_innovations_w1w2"] == w1w2, year

    def test_all_years_view_headline_is_the_canonical_1852(self):
        kpis = _fetch_prms_data(years=None)["kpis"]
        assert kpis["total_innovations"] == 1852

    def test_multi_year_is_a_union_not_a_sum(self):
        one = _fetch_prms_data(years=[2024])["kpis"]["total_innovations_w1w2"]
        two = _fetch_prms_data(years=[2025])["kpis"]["total_innovations_w1w2"]
        both = _fetch_prms_data(years=[2024, 2025])["kpis"]["total_innovations_w1w2"]
        # Union: at least as big as either year, strictly smaller than the sum
        # (codes alive in both years are counted once — the F4 discipline).
        assert max(one, two) <= both < one + two

    def test_selection_metadata_is_echoed_back(self):
        data = _fetch_prms_data(years=[2024, 2025])
        assert data["years"] == [2024, 2025]
        assert data["years_label"] == "2024–2025"
        # `year` stays null for multi-year selections (backward-compat field).
        assert data["year"] is None

        single = _fetch_prms_data(years=[2025])
        assert single["year"] == 2025 and single["years"] == [2025]

        all_years = _fetch_prms_data(years=None)
        assert all_years["year"] is None and all_years["years"] == []
        assert all_years["years_label"] == "All years"

    def test_year_labels_appear_in_chart_titles(self):
        charts = _fetch_prms_data(years=[2024, 2025])["charts"]
        for chart in charts.values():
            assert "(2024–2025)" in chart["title"], chart["title"]


# ---------------------------------------------------------------------------
# F1 + F14 — Science-Program / Initiative chart
# ---------------------------------------------------------------------------
class TestEntityLabelling:

    def test_entity_label_joins_code_and_name(self):
        assert _entity_label("SP09", "Scaling for Impact") == "SP09 — Scaling for Impact"

    def test_entity_label_strips_non_breaking_spaces(self):
        # Several SP short names carry a trailing \xa0 in clarisa_initiatives.
        assert _entity_label("SP02", "Sustainable Farming\xa0") == "SP02 — Sustainable Farming"

    def test_entity_label_falls_back_to_the_bare_code(self):
        assert _entity_label("SP99", None) == "SP99"
        assert _entity_label("SP99", "  ") == "SP99"

    def test_wording_is_science_programs_for_the_2025_era(self):
        noun, era = _entity_chart_wording([3, 3, 3])
        assert noun == "Science Programs"
        assert era == "Programs & Accelerators (2025+)"

    def test_wording_is_initiatives_for_the_2022_2024_era(self):
        noun, era = _entity_chart_wording([2, 2])
        assert noun == "Initiatives"
        assert era == "Initiatives (2022–2024)"

    def test_mixed_eras_are_named_explicitly_never_silently_merged(self):
        noun, era = _entity_chart_wording([2, 3])
        assert noun == "Science Programs / Initiatives"
        assert "Initiatives (2022–2024)" in era
        assert "Programs & Accelerators (2025+)" in era


@requires_prms_db
class TestTopEntitiesChart:

    def test_2025_ranks_science_programs_with_the_top_one_first(self):
        chart = _fetch_prms_data(years=[2025])["charts"]["top_initiatives"]
        assert chart["chartType"] == "horizontalBar"
        assert chart["title"] == "Top 10 Science Programs by Innovations (2025)"
        assert chart["xAxisKey"] == "entity"
        assert chart["data"][0]["entity"] == "SP09 — Scaling for Impact"
        assert chart["data"][0]["count"] == 224
        counts = [row["count"] for row in chart["data"]]
        assert counts == sorted(counts, reverse=True)

    def test_2022_is_labelled_as_the_initiative_era(self):
        chart = _fetch_prms_data(years=[2022])["charts"]["top_initiatives"]
        assert chart["title"] == "Top 10 Initiatives by Innovations (2022)"
        assert chart["data"][0]["entity"] == "INIT-01 — Accelerated Breeding"

    def test_a_cross_era_selection_names_both_eras(self):
        chart = _fetch_prms_data(years=[2024, 2025])["charts"]["top_initiatives"]
        assert chart["title"] == "Top 10 Science Programs / Initiatives by Innovations (2024–2025)"

    def test_every_bar_carries_a_readable_label_and_an_era(self):
        chart = _fetch_prms_data(years=None)["charts"]["top_initiatives"]
        assert len(chart["data"]) == 10
        for row in chart["data"]:
            assert row["entity"].startswith(row["code"])
            assert " — " in row["entity"]        # code + readable short name
            assert "\xa0" not in row["entity"]   # non-breaking space cleaned
            assert row["era"] in (
                "Initiatives (2022–2024)",
                "Programs & Accelerators (2025+)",
            )
