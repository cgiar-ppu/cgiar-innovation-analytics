"""L2-11: prms_search structured filters are honoured or rejected, never ignored."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from synapsis.tools.prms_search import (  # noqa: E402
    PRMS_DB_PATH,
    FilterError,
    _compile_filters_sql,
    _resolve_eligible,
)

requires_prms_db = pytest.mark.skipif(
    not os.path.isfile(PRMS_DB_PATH), reason="PRMS snapshot not available"
)


class TestCompile:

    def test_country_only_filter_is_no_longer_ignored(self):
        sql = _compile_filters_sql({"country_iso3": ["KEN"]})
        assert sql is not None
        assert "UPPER(cc.iso_alpha_3) IN ('KEN')" in sql

    def test_irl_min_only_filter_is_no_longer_ignored(self):
        sql = _compile_filters_sql({"irl_min": 7})
        assert sql is not None and "cirl.level >= 7" in sql

    def test_quality_gate_is_always_applied(self):
        sql = _compile_filters_sql({"year": 2025})
        assert "(r.source = 'Result' AND r.status_id = 2)" in sql
        assert "(r.source = 'API' AND r.status_id = 6)" in sql

    def test_unknown_key_is_rejected(self):
        with pytest.raises(FilterError):
            _compile_filters_sql({"country": "Kenya"})

    def test_bad_iso_is_rejected_not_interpolated(self):
        with pytest.raises(FilterError):
            _compile_filters_sql({"country_iso3": ["KEN'); DROP TABLE x;--"]})

    def test_irl_out_of_range_is_rejected(self):
        with pytest.raises(FilterError):
            _compile_filters_sql({"irl_min": 12})

    def test_resolve_reports_filter_errors(self):
        eligible, err = _resolve_eligible(None, {"irl": 7})
        assert eligible is None and "Unsupported filter key" in err


@requires_prms_db
class TestLive:

    def test_country_filter_narrows_the_eligible_set(self):
        kenya, err = _resolve_eligible(None, {"country_iso3": "KEN", "year": 2025})
        assert err is None and kenya
        everything, err = _resolve_eligible(None, {"year": 2025})
        assert err is None
        assert 0 < len(kenya) < len(everything)
