"""L2-06: scenario_analysis baselines use the canonical counting rules."""

import asyncio
import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sa = importlib.import_module("synapsis.tools.scenario_analysis")

requires_prms_db = pytest.mark.skipif(
    not os.path.isfile(sa.PRMS_DB_PATH), reason="PRMS snapshot not available"
)


def test_canon_cte_applies_the_quality_gate_and_one_row_per_code():
    cte = sa._canon_cte()
    assert "(r.source = 'Result' AND r.status_id = 2)" in cte
    assert "(r.source = 'API' AND r.status_id = 6)" in cte
    assert "PARTITION BY g.result_code" in cte


@requires_prms_db
class TestLiveBaselines:

    def test_total_innovations_equals_the_dashboard_all_years_card(self):
        from synapsis.routes.prms_dashboard import _fetch_prms_data

        conn = sa._get_connection()
        try:
            totals = sa._get_portfolio_totals(conn)
        finally:
            conn.close()
        assert totals["total_innovations"] == _fetch_prms_data(years=None)["kpis"]["total_innovations"]
        assert 0 < totals["irl_7plus"] <= totals["total_innovations"]
        assert totals["total_innovations"] <= totals["total_results"]

    def test_initiative_rows_count_distinct_codes(self):
        conn = sa._get_connection()
        try:
            rows = sa._get_initiative_baselines(conn)
        finally:
            conn.close()
        for row in rows:
            parts = row["innovations"] + row["innovation_uses"] + row["knowledge_products"] + row["policy_changes"]
            assert parts <= row["total_results"], row

    def test_output_states_snapshot_and_method(self):
        result = asyncio.run(sa.scenario_analysis.handler({
            "scenario_type": "irl_advancement",
            "description": "10% advance",
            "parameters": {"advancement_pct": 10},
            "include_chart": False,
        }))
        text = result["content"][0]["text"]
        assert "PRMS Database (snapshot" in text
        assert "counted once by PRMS result code" in text
