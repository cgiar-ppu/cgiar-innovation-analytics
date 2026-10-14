"""The release smoke checks the MVP endpoints (Marc items 1-5).

``release-smoke.py`` (identical on the DEV branch and the release line, so a
DEV -> release merge carries it) refuses a promotion whose MVP endpoints answer
an anonymous caller with anything but 401/403 (200 = open, 404 = missing).

The MVP settings themselves reach TST/PRD through ``promotion-request.json``
``models_config`` on the release line; that change is prepared as a patch
against the release-line ``release-host.py`` (it differs from the DEV copy) and
is not made here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / ".github/scripts/release-smoke.py"


def _smoke():
    spec = importlib.util.spec_from_file_location("release_smoke_mvp", SMOKE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestReleaseSmokeMvpEndpoints:

    def _statuses(self, code=401, **override):
        smoke = _smoke()
        st = {(m, p): code for m, p, _ in smoke.MVP_ANON_PROBES}
        st.update({tuple(k.split(" ", 1)): v for k, v in override.items()})
        return smoke, st

    def test_lists_the_five_endpoints(self):
        paths = {p for _, p, _ in _smoke().MVP_ANON_PROBES}
        assert paths == {"/api/telemetry", "/api/feedback/general", "/api/admin/usage",
                         "/api/admin/engagement", "/api/auth/invitations/role"}

    def test_all_denied_passes(self):
        smoke, st = self._statuses(401)
        assert smoke.check_mvp_anonymous(st).startswith("anonymous MVP endpoints:")

    @pytest.mark.parametrize("code", [200, 204, 404, 405, 422, 500])
    def test_open_or_missing_endpoint_fails(self, code):
        smoke, st = self._statuses(403)
        st[("GET", "/api/admin/usage")] = code
        with pytest.raises(AssertionError, match="not denied"):
            smoke.check_mvp_anonymous(st)

    def test_a_switched_off_feature_may_answer_404(self):
        smoke, st = self._statuses(401)
        st[("POST", "/api/telemetry")] = 404
        assert "disabled (404)" in smoke.check_mvp_anonymous(st, disabled=("telemetry",))
        with pytest.raises(AssertionError):
            smoke.check_mvp_anonymous(st)

    def test_main_runs_the_probe(self):
        text = SMOKE.read_text()
        assert "results.append(check_mvp_anonymous(statuses,mvp_disabled_features()))" in text


async def test_the_app_denies_the_mvp_endpoints_to_anonymous_callers(test_client):
    """The exact requests the release smoke sends, against this build."""
    smoke = _smoke()
    statuses = {}
    for method, path, _ in smoke.MVP_ANON_PROBES:
        r = await test_client.request(method, path, json={} if method == "POST" else None)
        statuses[(method, path)] = r.status_code
    assert smoke.check_mvp_anonymous(statuses)
