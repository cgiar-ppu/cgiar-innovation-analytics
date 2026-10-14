"""Release path carries the MVP test settings; the release smoke checks the MVP endpoints.

* ``release-promote.yml`` exports the GitHub environment variables,
  ``release-deploy.py`` forwards the ones that are set, and ``release-host.py``
  passes them to the container only when set (``promotion-request.json``
  ``models_config`` wins). An unset or empty value keeps the code default.
* ``release-smoke.py`` refuses a promotion whose MVP endpoints answer an
  anonymous caller with anything but 401/403 (200 = open, 404 = missing).

The scripts run on CI / the target host, so the tests execute only the marked
``mvp-env`` blocks with fake inputs. No AWS, Docker or network.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HOST = REPO / ".github/scripts/release-host.py"
DEPLOY = REPO / ".github/scripts/release-deploy.py"
PROMOTE = REPO / ".github/workflows/release-promote.yml"
SMOKE = REPO / ".github/scripts/release-smoke.py"

MVP_VARS = [
    "IA_TEST_BUDGET_USD", "IA_TEST_START", "IA_TEST_END", "IA_SESSION_BUDGET_USD",
    "IA_BUDGET_ALERT_THRESHOLDS", "IA_MAX_BUDGET_USD_RESEARCHER", "IA_DAILY_USER_BUDGET_USD",
    "IA_TELEMETRY_ENABLED", "IA_FEEDBACK_ENABLED", "IA_EXTERNAL_BLOCK_POLICY_AMOUNTS",
    "IA_EXTERNAL_W12_ONLY",
]


def _block(path: Path) -> str:
    text = path.read_text()
    m = re.search(r"^# >>> mvp-env.*?^# <<< mvp-env", text, flags=re.S | re.M)
    assert m, f"mvp-env block missing in {path.name}"
    return m.group(0)


def _host_env(cfg: dict) -> dict:
    env = {"IA_JWT_SECRET": "x"}
    exec(_block(HOST), {"cfg": cfg, "env": env})
    return env


class TestReleaseHost:

    def test_nothing_set_passes_nothing(self):
        assert _host_env({"stage": "prod"}) == {"IA_JWT_SECRET": "x"}

    def test_every_variable_is_known(self):
        names = {name for _, name in re.findall(r"\('(\w+)','(IA_\w+)'\)", _block(HOST))}
        assert names == set(MVP_VARS)

    def test_models_config_keys_are_passed(self):
        env = _host_env({"test_budget_usd": 5000, "test_start": "2026-10-15",
                         "test_end": "2026-11-15", "telemetry_enabled": False,
                         "external_w12_only": "true"})
        assert env["IA_TEST_BUDGET_USD"] == "5000"
        assert env["IA_TEST_START"] == "2026-10-15" and env["IA_TEST_END"] == "2026-11-15"
        assert env["IA_TELEMETRY_ENABLED"].lower() == "false"
        assert env["IA_EXTERNAL_W12_ONLY"] == "true"

    def test_github_variables_forwarded_by_deploy_are_passed(self):
        env = _host_env({"IA_SESSION_BUDGET_USD": "5", "IA_DAILY_USER_BUDGET_USD": "10"})
        assert env["IA_SESSION_BUDGET_USD"] == "5" and env["IA_DAILY_USER_BUDGET_USD"] == "10"

    def test_models_config_wins_over_the_github_variable(self):
        env = _host_env({"IA_TEST_BUDGET_USD": "4000", "test_budget_usd": "5000"})
        assert env["IA_TEST_BUDGET_USD"] == "5000"

    @pytest.mark.parametrize("empty", ["", "  ", None])
    def test_empty_values_are_never_passed(self, empty):
        env = _host_env({"telemetry_enabled": empty, "IA_TELEMETRY_ENABLED": empty})
        assert "IA_TELEMETRY_ENABLED" not in env

    def test_block_sits_before_the_container_start(self):
        text = HOST.read_text()
        assert text.index("# <<< mvp-env") < text.index("args.append(image)")
        assert "for key in env: args+=['-e',key]" in text  # values travel in the child environment only


class TestReleaseDeployAndWorkflow:

    def test_deploy_forwards_only_set_variables(self, monkeypatch):
        for name in MVP_VARS:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("IA_TEST_BUDGET_USD", "5000")
        monkeypatch.setenv("IA_TEST_END", "  ")
        import os
        config: dict = {}
        exec(_block(DEPLOY), {"os": os, "config": config})
        assert config == {"IA_TEST_BUDGET_USD": "5000"}

    def test_deploy_block_covers_every_variable(self):
        assert set(re.findall(r"'(IA_\w+)'", _block(DEPLOY))) == set(MVP_VARS)

    def test_deploy_reads_models_config_after_the_variables(self):
        text = DEPLOY.read_text()
        assert text.index("# <<< mvp-env") < text.index("config.update(request.get('models_config',{}))")

    def test_promote_workflow_exports_every_variable_to_the_deploy_step(self):
        text = PROMOTE.read_text()
        step = text[text.index("- name: Deploy with data preservation"):]
        for name in MVP_VARS:
            assert f"{name}: ${{{{ vars.{name} }}}}" in step, name


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
