"""CI / DEV QA gate (review L7-02 / L7-06 / L5-02, 2026-09-26).

Structural tests for the scripts and workflows that gate DEV deploys and future
promotions. No network, no model, no AWS: the hosted checks themselves run in the
deploy (DEV) and release (TST/PRD) lanes; ``dev-qa-smoke.py`` was proven locally
against a prod-auth server (see the Lane F report).
"""
import asyncio
import importlib.util
import logging
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".github" / "scripts"
WORKFLOWS = ROOT / ".github" / "workflows"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_").removesuffix(".py"), SCRIPTS / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # __name__ != '__main__': nothing runs
    return module


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


# ---------------------------------------------------------------------------
# dev-qa-smoke.py
# ---------------------------------------------------------------------------

def test_qa_smoke_never_lets_a_token_or_invite_link_through():
    qa = load("dev-qa-smoke.py")
    import base64
    b64 = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")  # noqa: E731
    jwt = ".".join((b64(b'{"alg":"HS256"}'), b64(b'{"sub":"x"}'), b64(b"not-a-signature")))  # synthetic
    text = (f"GET http://x/api/export/s?format=md&token={jwt} Authorization: Bearer {jwt} "
            f"https://ia.example/#invite=abcdefabcdef ws://x/ws/chat?token={jwt}")
    out = qa.scrub(text)
    assert "eyJ" not in out and "abcdefabcdef" not in out
    assert out.count("[REDACTED]") >= 3


def test_qa_smoke_log_filter_scrubs_http_client_lines():
    qa = load("dev-qa-smoke.py")
    handler = logging.StreamHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        qa.quiet_logs()
        assert logging.getLogger("httpx").level >= logging.WARNING
        record = logging.LogRecord("x", logging.INFO, __file__, 1,
                                   "HTTP Request: GET %s", ("http://h/api/export/s?token=eyJa.b.c",), None)
        for f in handler.filters:
            f.filter(record)
        assert "eyJ" not in record.getMessage()
    finally:
        root.removeHandler(handler)


def test_qa_smoke_route_walker_sees_exactly_the_chat_socket():
    """The walker must descend into included routers (FastAPI 0.141), and the
    only WebSocket is /ws/chat."""
    from synapsis.server import app

    qa = load("dev-qa-smoke.py")
    assert qa.websocket_paths(app) == ["/ws/chat"]
    assert "/api/personas" in {p for p, _ in qa.iter_routes(app.routes)}


def test_qa_smoke_skips_become_failures_for_required_lanes(monkeypatch):
    qa = load("dev-qa-smoke.py")

    async def lane_c_missing():
        raise qa.Skip("renderer not deployed", "C")

    async def plain_skip():
        raise qa.Skip("nothing to reuse")

    async def broken():
        raise AssertionError("boom")

    runner = qa.QA("http://localhost:1")
    asyncio.run(runner.run("tolerant", lane_c_missing))
    monkeypatch.setattr(qa, "REQUIRE", {"C"})
    asyncio.run(runner.run("strict", lane_c_missing))
    asyncio.run(runner.run("no-lane", plain_skip))
    asyncio.run(runner.run("fails", broken))
    status = {r["check"]: r["status"] for r in runner.results}
    assert status == {"tolerant": "skip", "strict": "fail", "no-lane": "skip", "fails": "fail"}


def test_qa_smoke_is_zero_spend_and_cleans_up():
    text = (SCRIPTS / "dev-qa-smoke.py").read_text()
    # No chat message is ever sent: only control frames on /ws/chat.
    assert "'message':" not in text and '"message":' not in text
    assert "'[QA] '" in text and "api/sessions/" in text and "revoke-cohort" in text
    assert "if __name__ == '__main__':" in text


def test_ws_refusal_helper_accepts_403_and_1008_only(monkeypatch):
    qa = load("dev-qa-smoke.py")
    from websockets.exceptions import InvalidStatus

    class Resp:
        status_code = 403

    class Refusing:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            raise InvalidStatus(Resp())

        async def __aexit__(self, *a):
            return False

    class Accepting(Refusing):
        async def __aenter__(self):
            return self

        async def recv(self):
            await asyncio.sleep(10)

    monkeypatch.setattr(qa.websockets, "connect", Refusing)
    assert asyncio.run(qa.ws_refused("ws://x/ws/chat")) == "refused 403"
    monkeypatch.setattr(qa.websockets, "connect", Accepting)
    with pytest.raises(AssertionError, match="accepted"):
        asyncio.run(qa.ws_refused("ws://x/ws/agent/x"))


# ---------------------------------------------------------------------------
# release-smoke.py (WebSocket probe) and release-model-smoke.py (no Bash)
# ---------------------------------------------------------------------------

def test_release_smoke_probes_every_websocket_route():
    from synapsis.server import app

    smoke = load("release-smoke.py")
    assert smoke.websocket_routes(app) == ["/ws/chat"]
    text = (SCRIPTS / "release-smoke.py").read_text()
    assert "results.append(await websocket_probe())" in text
    assert "quiet_http_logs()" in text


def test_release_model_smoke_uses_an_ia_tool_not_bash(tmp_path):
    smoke = load("release-model-smoke.py")
    direct = smoke.options("claude-sonnet-5", str(tmp_path))
    delegated = smoke.options("claude-sonnet-5", str(tmp_path), delegate=True)
    for opts in (direct, delegated):
        assert "Bash" not in (opts.allowed_tools or []) and "Bash" not in (opts.tools or [])
        assert "synapsis" in opts.mcp_servers and opts.strict_mcp_config
    assert direct.allowed_tools == ["mcp__synapsis__prms_query"] and direct.tools == []
    specialist = delegated.agents[smoke.SPECIALIST]
    assert "mcp__synapsis__prms_query" in specialist.tools
    assert "Bash" not in smoke.prompt() and "Bash" not in smoke.prompt(True)


def test_release_chat_smoke_switches_models_as_an_admin():
    """Researchers are offered Sonnet 5 only since 2026-09-26 (role-aware models)."""
    text = (SCRIPTS / "release-chat-smoke.py").read_text()
    assert "'Synthetic release chat QA','admin'" in text


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

def test_deploy_workflow_targets_dev_only():
    wf = workflow("deploy.yml")
    on = wf[True]  # YAML 1.1 reads the key `on` as True
    assert on["push"]["branches"] == ["feature/innovation-platform-foundation"]
    assert on["workflow_dispatch"]["inputs"]["environment"]["options"] == ["dev"]
    steps = wf["jobs"]["deploy"]["steps"]
    guard = next(s for s in steps if s.get("name") == "Refuse any target other than DEV")
    assert steps.index(guard) == 1 and "exit 1" in guard["run"]


def test_deploy_runs_the_dev_qa_smoke_after_the_opus_check():
    steps = workflow("deploy.yml")["jobs"]["deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    qa = steps[names.index("DEV QA smoke (authenticated, no model spend)")]
    assert names.index("Live Opus 5.5 check (DEV)") < names.index(qa["name"])
    assert "env.STAGE == 'dev'" in qa["if"] and "!cancelled()" in qa["if"]
    assert ".github/scripts/dev-qa-smoke.py" in qa["run"] and "zlib.compress" in qa["run"]
    assert "scrub(r['StandardErrorContent'])" in qa["run"]
    assert qa["env"]["QA_REQUIRE_LANES"] == ""


def test_ci_workflow_is_safe_for_a_public_repo():
    wf = workflow("ci.yml")
    on = wf[True]
    assert "pull_request_target" not in on and "pull_request" in on
    assert wf["permissions"] == {"contents": "read"}
    jobs = wf["jobs"]
    with_oidc = [n for n, j in jobs.items() if (j.get("permissions") or {}).get("id-token") == "write"]
    assert with_oidc == ["backend-prms-data"]
    assert "github.event_name == 'push'" in jobs["backend-prms-data"]["if"]
    for name in ("backend", "backend-prms-data"):
        assert jobs[name]["env"]["SYNAPSIS_PLATFORM"] == "linux"
        text = yaml.safe_dump(jobs[name])
        assert "pytest" in text and "secrets." not in text and "upload-artifact" not in text
    front = yaml.safe_dump(jobs["frontend"])
    for cmd in ("npm ci", "npx vitest run", "npx tsc -b --noEmit", "npm run build"):
        assert cmd in front
