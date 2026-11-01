"""Env-power busy/activity signal (AWS cost sprint, Nov 2026) -- synapsis/power.py."""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.testclient import TestClient

from synapsis import power


@pytest.fixture(autouse=True)
def _reset():
    power.take_activity()
    yield
    power.take_activity()


def test_env_name(monkeypatch):
    monkeypatch.delenv("ENV_POWER_ENV", raising=False)
    monkeypatch.setenv("IA_ENVIRONMENT", "staging")
    assert power.env_name() == "cgiar-ia-staging"
    monkeypatch.setenv("IA_ENVIRONMENT", "")
    assert power.env_name() == ""
    assert power.enabled() is False  # local runs: no env -> off
    monkeypatch.setenv("IA_ENVIRONMENT", "dev")
    assert power.enabled() is True
    monkeypatch.setenv("ENV_POWER_SIGNAL", "off")
    assert power.enabled() is False


def test_busy_counts_running_chats_and_detached_pipelines(monkeypatch):
    from synapsis.chat_run_manager import chat_run_manager
    from synapsis.workflow_run_manager import run_manager

    monkeypatch.setattr(chat_run_manager, "_handles", {
        "a": SimpleNamespace(status="running"), "b": SimpleNamespace(status="completed")})
    monkeypatch.setattr(run_manager, "_active_runs", {
        "r1": SimpleNamespace(status="running"), "r2": SimpleNamespace(status="cancelled")})
    assert power.chat_busy() == 1
    assert power.pipelines_busy() == 1


def test_finished_chat_with_open_socket_is_not_busy(monkeypatch):
    from synapsis.chat_run_manager import chat_run_manager

    monkeypatch.setattr(chat_run_manager, "_handles", {"a": SimpleNamespace(status="completed")})
    assert power.chat_busy() == 0


async def test_voice_busy_counts_live_sessions(initialized_db):
    import time

    from synapsis.database import get_db
    from synapsis.voice import sessions as vs

    await vs.init()
    now = time.time()
    async with get_db() as db:
        for rid, status, exp, hb in (("1", "active", now + 300, now + 30), ("2", "closed", now + 300, now + 30),
                                     ("3", "active", now - 1, now + 30), ("4", "creating", now + 300, now + 30)):
            await db.execute("INSERT INTO voice_sessions(owner,request_id,status,created,expires,heartbeat) "
                             "VALUES (?,?,?,?,?,?)", ("o" + rid, rid, status, now, exp, hb))
        await db.commit()
    assert await power.voice_busy() == 2


def test_signal_line_is_filterable_json():
    d = json.loads(power.signal_line(2, 5, env="cgiar-ia-dev"))
    assert d["env_power"] == 1 and d["env"] == "cgiar-ia-dev" and d["busy"] == 2 and d["activity"] == 5


async def test_publisher_emits_interval_peak_and_resets_activity():
    lines = []
    values = iter([0, 3, 1])

    async def sample():
        return next(values, 0)

    power.record_activity(2)
    await power.run_publisher(emit=lines.append, sample=sample, publish_seconds=0.05,
                              sample_seconds=0.01, max_publishes=1)
    d = json.loads(lines[0])
    assert d["busy"] == 3 and d["activity"] == 2
    assert power.take_activity() == 0


async def test_publisher_never_raises():
    async def sample():
        raise RuntimeError("boom")

    def emit(_line):
        raise OSError("closed stdout")

    await power.run_publisher(emit=emit, sample=sample, publish_seconds=0.01, sample_seconds=0.005,
                              max_publishes=2)


def _app():
    app = FastAPI()
    app.add_middleware(power.ActivityMiddleware)

    @app.get("/api/health")
    async def health():
        return {}

    @app.post("/api/auth/sso/session")
    async def sso():
        return {}

    @app.get("/api/voice/status")
    async def voice_status():
        return {}

    @app.get("/api/sessions")
    async def sessions():
        return []

    @app.get("/api/private")
    async def private():
        raise HTTPException(401)

    @app.get("/{path:path}")
    async def spa(path: str):
        return {"spa": path}

    @app.websocket("/ws/chat")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.receive_text()
        await websocket.close()

    return app


def test_activity_ignores_background_scanners_and_refresh():
    c = TestClient(_app())
    c.get("/api/health")
    c.post("/api/auth/sso/session")       # AuthGate refresh from a tab
    c.get("/api/voice/status")            # VoiceGuide re-check
    c.get("/")                            # SPA / scanner
    c.get("/NmapUpperCheck123")           # SPA fallback answers 200 to scanners
    c.get("/api/private")                 # 401 probe
    c.options("/api/sessions")
    assert power.take_activity() == 0


def test_activity_counts_user_actions_and_deploy_hold():
    c = TestClient(_app())
    c.get("/api/sessions")
    c.get("/api/health", headers={"X-Env-Power-Hold": "1"})
    with c.websocket_connect("/ws/chat") as w:
        w.send_text('{"type":"message"}')
    assert power.take_activity() == 3
