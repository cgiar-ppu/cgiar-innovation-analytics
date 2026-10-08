"""
Centre + Program/Accelerator filters on the PRMS dashboard (Marc Schut, 2026-10-08).

Semantics under test:

- a result-phase row is in scope when THAT row has an active link to a selected
  centre (`results_center`, any role) or program (`results_by_inititiative`,
  role 1 'Primary submitter' = lead OR 2 'Contributor') — "lead AND contribute";
- several values in one dropdown = union, deduped by result code;
- Years AND Centres AND Programs = intersection;
- no centre/program selected = the signed-off numbers, unchanged;
- unknown codes are rejected with a 400, like an invalid year.

The DB-backed tests compare the dashboard with independent direct SQL and skip
cleanly when the PRMS snapshot is not present.
"""

import asyncio
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import synapsis.routes.prms_dashboard as mod  # noqa: E402
from synapsis.prms_snapshot import get_snapshot_info  # noqa: E402
from synapsis.routes.prms_dashboard import (  # noqa: E402
    _PRMS_DB_PATH,
    _bind_scope,
    _fetch_prms_data,
    filters_label,
    normalize_codes,
)

requires_prms_db = pytest.mark.skipif(
    not os.path.isfile(_PRMS_DB_PATH),
    reason=f"PRMS snapshot not available at {_PRMS_DB_PATH}",
)

CIMMYT = "CENTER-05"
IITA = "CENTER-11"

_GATE = "((r.source='Result' AND r.status_id=2) OR (r.source='API' AND r.status_id=6))"


def _independent(years, centers=(), programs=()):
    """(total_results, innovations W1/W2 + bilateral, uses) by direct SQL."""
    open_ids = ",".join(str(i) for i in get_snapshot_info(_PRMS_DB_PATH).open_phase_ids) or "-1"
    conds = []
    params: list = []
    if centers:
        conds.append(
            "EXISTS (SELECT 1 FROM results_center rc WHERE rc.result_id = r.id "
            f"AND rc.is_active = 1 AND rc.center_id IN ({','.join('?' * len(centers))}))"
        )
        params += list(centers)
    if programs:
        conds.append(
            "EXISTS (SELECT 1 FROM results_by_inititiative b JOIN clarisa_initiatives i "
            "ON i.id = b.inititiative_id WHERE b.result_id = r.id AND b.is_active = 1 "
            f"AND b.initiative_role_id IN (1, 2) AND i.official_code IN ({','.join('?' * len(programs))}))"
        )
        params += list(programs)
    base = (
        f"FROM main.result r WHERE r.is_active = 1 AND r.version_id NOT IN ({open_ids}) "
        f"AND r.reported_year_id IN ({','.join(str(int(y)) for y in years)}) AND " + " AND ".join(conds)
    )
    db = sqlite3.connect(f"file:{_PRMS_DB_PATH}?mode=ro", uri=True)
    try:
        q = lambda extra: db.execute(f"SELECT COUNT(DISTINCT r.result_code) {base} AND {extra}", params).fetchone()[0]  # noqa: E731
        total = q(f"{_GATE} AND r.result_type_id IN (2, 7, 10)")
        w12 = q("r.source = 'Result' AND r.status_id = 2 AND r.result_type_id = 7")
        bil = q("r.source = 'API' AND r.status_id = 6 AND r.result_type_id = 7")
        uses = q(f"{_GATE} AND r.result_type_id = 2")
    finally:
        db.close()
    return total, w12 + bil, uses


def _kpis(data):
    k = data["kpis"]
    return k["total_results"], k["total_innovations"], k["innovation_uses"]


# ---------------------------------------------------------------------------
# (f) parsing / validation — no DB needed
# ---------------------------------------------------------------------------
class TestNormalizeCodes:

    def test_empty_means_no_filter(self):
        assert normalize_codes(None) == ([], [])
        assert normalize_codes([]) == ([], [])
        assert normalize_codes([" ", ","]) == ([], [])

    def test_repeated_comma_case_and_dedupe(self):
        assert normalize_codes(["sp01", "SP02,SP01", " init-11 "]) == (["INIT-11", "SP01", "SP02"], [])

    def test_unknown_codes_are_reported_invalid(self):
        codes, invalid = normalize_codes(["SP01", "SP99"], {"SP01", "SP02"})
        assert codes == ["SP01"]
        assert invalid == ["SP99"]

    def test_sql_shaped_garbage_is_invalid_even_without_a_catalog(self):
        codes, invalid = normalize_codes(["SP01'; DROP TABLE result; --"])
        assert codes == [] and invalid

    def test_too_many_values_are_rejected(self):
        codes, invalid = normalize_codes([",".join(f"X{i}" for i in range(60))])
        assert invalid


class TestScopeBinding:

    SQL = "FROM __CAND_SRC__ r WHERE x __CANON_SCOPE__"

    def test_unfiltered_binds_to_the_original_text(self):
        assert _bind_scope(self.SQL, False) == "FROM result r WHERE x "

    def test_filtered_reads_the_unscoped_canon_then_keeps_in_scope_codes(self):
        out = _bind_scope(self.SQL, True)
        assert "result_unscoped" in out and "temp.dash_scope_ids" in out


class TestEndpointValidation:

    def _call(self, **kw):
        kw.setdefault("years", ["2025"])
        kw.setdefault("year", None)
        return asyncio.run(mod.prms_dashboard_stats(**kw))

    @requires_prms_db
    def test_unknown_centre_is_a_400_like_an_invalid_year(self, monkeypatch):
        monkeypatch.setattr(mod, "_cache", {})
        resp = self._call(centers=["CENTER-99"], programs=None)
        assert resp.status_code == 400
        assert b"CENTER-99" in resp.body

    @requires_prms_db
    def test_unknown_program_is_a_400(self, monkeypatch):
        monkeypatch.setattr(mod, "_cache", {})
        resp = self._call(centers=None, programs=["SP99"])
        assert resp.status_code == 400

    @requires_prms_db
    def test_cache_key_separates_filtered_from_unfiltered(self, monkeypatch):
        calls = []

        def fake(years=None, centers=None, programs=None):
            calls.append((tuple(years or ()), tuple(centers or ()), tuple(programs or ())))
            return {"kpis": {}, "charts": {}, "n": len(calls)}

        monkeypatch.setattr(mod, "_fetch_prms_data", fake)
        monkeypatch.setattr(mod, "_cache", {})
        monkeypatch.setattr(mod, "_cache_ts", {})
        a = self._call(centers=None, programs=None)
        b = self._call(centers=[CIMMYT], programs=None)
        c = self._call(centers=None, programs=["SP01"])
        d = self._call(centers=[CIMMYT], programs=None)  # cached
        assert [x["n"] for x in (a, b, c, d)] == [1, 2, 3, 2]
        assert calls[1] == ((2025,), (CIMMYT,), ())


# ---------------------------------------------------------------------------
# Live regression against the PRMS snapshot
# ---------------------------------------------------------------------------
@requires_prms_db
class TestNoFilterIsUnchanged:
    """(a) With no centre/program selected the signed-off numbers stand."""

    def test_2025_benchmarks(self):
        d = _fetch_prms_data([2025])
        k = d["kpis"]
        assert (k["total_results"], k["total_innovations"], k["total_innovations_w1w2"],
                k["total_innovations_bilateral"], k["innovation_uses"]) == (1641, 1185, 963, 222, 403)
        assert d["scope_label"] == "2025"
        assert d["filters"]["label"] == ""

    def test_empty_filter_lists_are_byte_identical_to_no_filters(self):
        for years in ([], [2025], [2023], [2024, 2025]):
            a = _fetch_prms_data(years)
            b = _fetch_prms_data(years, [], [])
            a.pop("last_updated"), b.pop("last_updated")
            assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_all_years_headline(self):
        assert _fetch_prms_data([])["kpis"]["total_innovations"] == 1852


@requires_prms_db
class TestFilteredCountsMatchDirectSQL:

    def test_program_sp01_2025_equals_lead_plus_contributor_union(self):
        """(b)"""
        got = _kpis(_fetch_prms_data([2025], [], ["SP01"]))
        assert got == _independent([2025], programs=["SP01"])
        assert got[0] > 0

    def test_program_filter_includes_contributed_results_not_only_led(self):
        db = sqlite3.connect(f"file:{_PRMS_DB_PATH}?mode=ro", uri=True)
        try:
            led_only = db.execute(
                "SELECT COUNT(DISTINCT r.result_code) FROM result r "
                "JOIN results_by_inititiative b ON b.result_id = r.id AND b.is_active = 1 "
                "AND b.initiative_role_id = 1 JOIN clarisa_initiatives i ON i.id = b.inititiative_id "
                "WHERE i.official_code = 'SP09' AND r.reported_year_id = 2025 AND r.is_active = 1 "
                f"AND {_GATE} AND r.result_type_id IN (2, 7, 10)"
            ).fetchone()[0]
        finally:
            db.close()
        total = _fetch_prms_data([2025], [], ["SP09"])["kpis"]["total_results"]
        assert total > led_only  # contributions are included

    def test_centre_cimmyt_2025(self):
        """(c)"""
        assert _kpis(_fetch_prms_data([2025], [CIMMYT], [])) == _independent([2025], centers=[CIMMYT])

    def test_initiative_in_its_own_era(self):
        assert _kpis(_fetch_prms_data([2023], [], ["INIT-01"])) == _independent([2023], programs=["INIT-01"])

    def test_and_across_filters(self):
        """(d) Years AND Centres AND Programs."""
        both = _fetch_prms_data([2025], [CIMMYT], ["SP01"])
        assert _kpis(both) == _independent([2025], centers=[CIMMYT], programs=["SP01"])
        centre = _fetch_prms_data([2025], [CIMMYT], [])["kpis"]["total_results"]
        prog = _fetch_prms_data([2025], [], ["SP01"])["kpis"]["total_results"]
        assert both["kpis"]["total_results"] <= min(centre, prog)
        assert both["scope_label"] == "2025 · Centre: CIMMYT · Program: SP01"

    def test_multiselect_is_a_deduped_union(self):
        """(e)"""
        a = _fetch_prms_data([2025], [CIMMYT], [])["kpis"]["total_results"]
        b = _fetch_prms_data([2025], [IITA], [])["kpis"]["total_results"]
        u = _fetch_prms_data([2025], [CIMMYT, IITA], [])
        assert _kpis(u) == _independent([2025], centers=[CIMMYT, IITA])
        assert max(a, b) <= u["kpis"]["total_results"] < a + b  # shared results counted once
        p = _fetch_prms_data([2025], [], ["SP01", "SP02"])
        assert _kpis(p) == _independent([2025], programs=["SP01", "SP02"])


@requires_prms_db
class TestEveryFigureIsScoped:

    @pytest.mark.parametrize("years", [[2025], [], [2024, 2025]])
    def test_filtered_figures_never_exceed_the_unfiltered_ones(self, years):
        full = _fetch_prms_data(years)
        sub = _fetch_prms_data(years, [CIMMYT], [])
        for key, value in sub["kpis"].items():
            assert value <= full["kpis"][key], key
        pie = {r["type"]: r["count"] for r in sub["charts"]["results_by_type"]["data"]}
        assert pie["Innovation Development"] == sub["kpis"]["total_innovations"]
        irl = sum(r["count"] for r in sub["charts"]["irl_distribution"]["data"])
        assert irl <= sub["kpis"]["total_innovations"]
        assert sub["charts"]["top_countries"]["data"][0]["total"] <= full["charts"]["top_countries"]["data"][0]["total"]

    def test_all_years_canon_is_restricted_not_recomputed(self):
        """The latest-phase canon is picked on the full population, then filtered."""
        full = _fetch_prms_data([])["kpis"]
        for centers, programs in (([CIMMYT], []), ([], ["SP01"]), ([], ["INIT-01"])):
            k = _fetch_prms_data([], centers, programs)["kpis"]
            assert k["total_innovations"] <= full["total_innovations"]
            assert k["total_innovations"] <= k["total_results"]

    def test_chart_titles_state_the_filter(self):
        d = _fetch_prms_data([2025], [CIMMYT], [])
        for chart in d["charts"].values():
            assert chart["title"].endswith("(2025 · Centre: CIMMYT)"), chart["title"]
        top = d["charts"]["top_initiatives"]
        assert "LEAD program" in top["description"]

    def test_unfiltered_chart_titles_keep_the_old_suffix(self):
        d = _fetch_prms_data([2025])
        assert d["charts"]["results_by_type"]["title"] == "Innovations by Type (2025)"


@requires_prms_db
class TestEraHintAndOptions:

    def test_sp_program_with_old_years_explains_the_empty_view(self):
        d = _fetch_prms_data([2023], [], ["SP01"])
        assert d["kpis"]["total_results"] == 0
        assert "2025" in d["filters"]["era_hint"]

    def test_initiative_with_2025_explains(self):
        assert _fetch_prms_data([2025], [], ["INIT-01"])["filters"]["era_hint"]

    def test_matching_era_has_no_hint(self):
        assert _fetch_prms_data([2025], [], ["SP01"])["filters"]["era_hint"] == ""

    def test_options_list_only_entities_with_results_grouped_by_era(self):
        opts = mod._load_filter_options()
        codes = [c["code"] for c in opts["centers"]]
        assert CIMMYT in codes and "OFF-01" not in codes
        assert all(c["results"] > 0 for c in opts["centers"])
        cimmyt = next(c for c in opts["centers"] if c["code"] == CIMMYT)
        assert cimmyt["acronym"] == "CIMMYT" and "Maize" in cimmyt["name"]
        eras = [p["era"] for p in opts["programs"]]
        assert eras[0] == "Programs & Accelerators (2025+)"
        assert "Initiatives (2022–2024)" in eras
        # 2025+ group first, then 2022–2024 — never interleaved
        first_old = eras.index("Initiatives (2022–2024)")
        assert all(e == "Initiatives (2022–2024)" for e in eras[first_old:])
        assert all(p["results"] > 0 for p in opts["programs"])

    def test_filters_label_wording(self):
        assert filters_label([], []) == ""
        assert filters_label([CIMMYT, IITA], []) == "Centres: CIMMYT + IITA"
        assert filters_label([], ["SP01", "SP02", "SP03", "SP04"]) == "Programs: 4 programs"
