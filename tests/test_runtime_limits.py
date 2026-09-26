"""Runtime capacity, model policy and cost caps (IA finalisation, Lane D).

Everything here runs against fake SDK clients: no CLI subprocess is started
and no model is ever called.

Covers
- L3-03: per-user new-chat rate limit; limit errors keep the WebSocket open
- L3-04: opening old chats no longer spawns CLIs; the live-client cap is
  honoured on resume with LRU eviction
- role-aware models enforced in switch_model AND retry_with_model (L3-06:
  validation, old client disconnected, conversation resumed)
- L3-07: targeted cancel is owner-checked
- per-question cost accounting (running-total deltas), budget recycle,
  friendly limit messages, stall watchdog, error classification (L3-12/13)
- daily per-user soft cap (admins exempt), incl. REST /api/query
- /api/config role-aware contract and GET /api/admin/usage (admin only)
- agent options carry max_budget_usd / no silent fallback for researchers
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from claude_agent_sdk import ResultMessage
from fastapi import WebSocketDisconnect
from httpx import ASGITransport, AsyncClient
from starlette.websockets import WebSocketState


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

CREATED: list = []


class FakeClient:
    """Stand-in for ClaudeSDKClient. ``script`` is a list of per-query
    message lists; each query() releases the next list to receive_response."""

    def __init__(self, options=None, script=None):
        self.options = options or SimpleNamespace(model=None, resume=None)
        self.disconnected = False
        self.interrupted = False
        self.queries: list[str] = []
        self._transport = None
        self._script = list(script or [])
        self._pending: list = []
        CREATED.append(self)

    async def connect(self):
        pass

    async def disconnect(self):
        self.disconnected = True

    async def interrupt(self):
        self.interrupted = True

    async def query(self, message):
        self.queries.append(message)
        self._pending = list(self._script.pop(0)) if self._script else []

    async def receive_response(self):
        while self._pending:
            item = self._pending.pop(0)
            if item == "HANG":
                await asyncio.sleep(3600)
            yield item
            if isinstance(item, ResultMessage):
                return


class FakeWS:
    def __init__(self, frames):
        self.frames = [json.dumps(f) for f in frames]
        self.sent: list[dict] = []
        self.client_state = WebSocketState.CONNECTED
        self.closed = None

    async def accept(self):
        pass

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)
        self.client_state = WebSocketState.DISCONNECTED

    async def receive_text(self):
        if not self.frames:
            raise WebSocketDisconnect()
        return self.frames.pop(0)

    async def send_json(self, data):
        self.sent.append(dict(data))


def result(total, *, subtype="success", is_error=False, stop_reason="end_turn", **kw):
    return ResultMessage(
        subtype=subtype, duration_ms=5, duration_api_ms=5, is_error=is_error,
        num_turns=1, session_id="claude-uuid-1", total_cost_usd=total,
        stop_reason=stop_reason, **kw,
    )


def token(user_id, role):
    from synapsis.auth.tokens import create_access_token
    return create_access_token(user_id, user_id.split("@")[0], role)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def deterministic_policy():
    """Pin the deployment/model policy values: config reads the environment at
    import time, and the developer's shell may carry other SYNAPSIS_* values."""
    from synapsis.constants import SELECTABLE_MODELS
    all_ids = [m["id"] for m in SELECTABLE_MODELS]
    with (
        patch("synapsis.config.MODEL", "claude-sonnet-5"),
        patch("synapsis.config.FALLBACK_MODEL", "claude-opus-5"),
        patch("synapsis.config.AVAILABLE_MODELS", all_ids),
        patch("synapsis.config.SELECTABLE_MODELS_FILTERED", list(SELECTABLE_MODELS)),
        patch("synapsis.config.RESEARCHER_MODELS", ["claude-sonnet-5"]),
        patch("synapsis.config.ADMIN_MODELS", all_ids),
        patch("synapsis.config.MAX_BUDGET_USD_RESEARCHER", 1.0),
        patch("synapsis.config.MAX_BUDGET_USD_ADMIN", 5.0),
        patch("synapsis.config.DAILY_USER_BUDGET_USD", 5.0),
        patch("synapsis.config.MAX_TURNS", 60),
        patch("synapsis.config.NEW_CHATS_PER_USER", 5),
        patch("synapsis.config.NEW_CHATS_GLOBAL", 30),
        patch("synapsis.config.BUDGET_RECYCLE_FRACTION", 0.5),
        patch("synapsis.agent_options.MODEL", "claude-sonnet-5"),
        patch("synapsis.agent_options.MAX_TURNS", 60),
        patch("synapsis.routes.health.MODEL", "claude-sonnet-5"),
        patch("synapsis.routes.health.MAX_TURNS", 60),
    ):
        yield


@pytest.fixture
def auth_on():
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.websocket.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        yield


@pytest_asyncio.fixture
async def runtime(initialized_db):
    """Clean session registry + fake client factory (records options)."""
    from synapsis.session import session_manager, sessions
    import synapsis.session.client_registry as cr

    reg = session_manager._client_registry
    for sid in list(sessions):
        await session_manager.cleanup_session_client(sid)
    reg._creation_timestamps.clear()
    reg._global_creations.clear()
    CREATED.clear()
    scripts: list = []

    async def fake_build(resume_session_id=None, model_override=None):
        return SimpleNamespace(model=model_override, resume=resume_session_id)

    async def fake_create(options, **kwargs):
        return FakeClient(options, script=scripts.pop(0) if scripts else None)

    with (
        patch.object(cr, "build_agent_options", fake_build),
        patch.object(cr, "create_client_with_retry", fake_create),
    ):
        yield SimpleNamespace(registry=reg, sessions=sessions, scripts=scripts, db=initialized_db)

    from synapsis.chat_run_manager import chat_run_manager
    for sid in list(sessions):
        await session_manager.cleanup_session_client(sid)
    await chat_run_manager.shutdown()
    reg._creation_timestamps.clear()
    reg._global_creations.clear()


async def run_ws(frames, user="researcher@cgiar.org", role="researcher"):
    from synapsis.websocket import ws_chat
    ws = FakeWS(frames)
    await ws_chat(ws, token=token(user, role))
    return ws


def errors(ws):
    return [f for f in ws.sent if f.get("type") == "error"]


# ---------------------------------------------------------------------------
# L3-03 per-user rate limit, socket survives
# ---------------------------------------------------------------------------

async def test_sixth_new_chat_is_refused_but_socket_stays_open(runtime, auth_on):
    ws = await run_ws([{"type": "new_session"}] * 6 + [{"type": "switch_model", "model": "claude-sonnet-5"}])
    sessions = [f for f in ws.sent if f.get("type") == "session"]
    assert len(sessions) == 5
    errs = errors(ws)
    assert errs[0]["code"] == "rate_limited"
    assert "new chats" in errs[0]["message"]
    # the frame AFTER the refusal was still processed (socket alive): the
    # switch_model frame produced its own response
    assert ws.frames == []
    assert ws.closed is None
    assert any(f.get("type") == "model_switched" for f in ws.sent), ws.sent


async def test_rate_limit_is_per_user(runtime, auth_on):
    await run_ws([{"type": "new_session"}] * 5, user="a@cgiar.org")
    ws_b = await run_ws([{"type": "new_session"}], user="b@cgiar.org")
    assert [f for f in ws_b.sent if f.get("type") == "session"], ws_b.sent
    assert not errors(ws_b)


async def test_global_safety_net_still_applies(runtime, auth_on):
    with patch("synapsis.config.NEW_CHATS_GLOBAL", 3):
        await run_ws([{"type": "new_session"}] * 2, user="a@cgiar.org")
        ws = await run_ws([{"type": "new_session"}] * 2, user="b@cgiar.org")
    assert [e["code"] for e in errors(ws)] == ["rate_limited"]


async def test_new_chat_starts_no_cli_until_first_message(runtime, auth_on):
    runtime.scripts.append([[result(0.05)]])
    ws = await run_ws([{"type": "new_session"}])
    sid = next(f["session_id"] for f in ws.sent if f.get("type") == "session")
    assert CREATED == [] and sid not in runtime.sessions
    ws2 = await run_ws([{"type": "switch_session", "session_id": sid}, {"message": "hello"}])
    assert not errors(ws2), ws2.sent
    assert len(CREATED) == 1 and CREATED[0].queries


# ---------------------------------------------------------------------------
# L3-04 resume honours the cap
# ---------------------------------------------------------------------------

async def test_browsing_old_chats_spawns_no_cli(runtime, auth_on):
    from synapsis.database import create_session
    for i in range(15):
        await create_session(f"old{i:05d}", title="t", user_id="researcher@cgiar.org")
    ws = await run_ws([{"type": "switch_session", "session_id": f"old{i:05d}"} for i in range(15)])
    assert len([f for f in ws.sent if f.get("type") == "session"]) == 15
    assert CREATED == [] and len(runtime.sessions) == 0


async def test_resume_evicts_least_recently_used_idle_client(runtime, auth_on):
    from synapsis.database import create_session
    reg = runtime.registry
    with patch("synapsis.session.client_registry.MAX_SESSIONS", 3):
        for i in range(4):
            sid = f"cap{i:05d}"
            await create_session(sid, title="t", user_id="researcher@cgiar.org")
            await reg.ensure_session(sid, "q", runtime.sessions)
            reg._last_used[sid] = 100.0 + i
        reg._last_used["cap00001"] = 50.0  # least recently used
        assert len(runtime.sessions) == 3
        await create_session("cap00009", title="t", user_id="researcher@cgiar.org")
        await reg.ensure_session("cap00009", "q", runtime.sessions)
    assert len(runtime.sessions) == 3
    assert set(runtime.sessions) == {"cap00002", "cap00003", "cap00009"}


async def test_resume_refused_when_all_clients_busy(runtime, auth_on):
    from synapsis.database import create_session
    from synapsis.runtime_policy import SessionLimitError
    reg = runtime.registry
    with patch("synapsis.session.client_registry.MAX_SESSIONS", 2):
        for sid in ("busy0001", "busy0002"):
            await create_session(sid, title="t", user_id="researcher@cgiar.org")
            await reg.ensure_session(sid, "q", runtime.sessions)
            await reg.get_session_lock(sid).acquire()
        await create_session("busy0003", title="t", user_id="researcher@cgiar.org")
        with pytest.raises(SessionLimitError) as exc:
            await reg.ensure_session("busy0003", "q", runtime.sessions)
    assert exc.value.code == "capacity"
    for sid in ("busy0001", "busy0002"):
        reg.release_session_client(sid)


# ---------------------------------------------------------------------------
# Model policy: switch_model + retry_with_model (L3-06)
# ---------------------------------------------------------------------------

async def test_researcher_cannot_switch_to_opus_admin_can(runtime, auth_on):
    from synapsis.database import create_session
    await create_session("mdl00001", title="t", user_id="researcher@cgiar.org")
    ws = await run_ws([
        {"type": "switch_session", "session_id": "mdl00001"},
        {"type": "switch_model", "model": "claude-opus-5-5"},
    ])
    assert errors(ws)[-1]["code"] == "model_not_allowed"
    assert not any(f.get("type") == "model_switched" for f in ws.sent)

    await create_session("mdl00002", title="t", user_id="admin@cgiar.org")
    ws_admin = await run_ws([
        {"type": "switch_session", "session_id": "mdl00002"},
        {"type": "switch_model", "model": "claude-opus-5-5"},
    ], user="admin@cgiar.org", role="admin")
    assert any(f.get("type") == "model_switched" and f["model"] == "claude-opus-5-5" for f in ws_admin.sent)
    assert CREATED[-1].options.model == "claude-opus-5-5"


async def test_retry_with_model_validates_and_keeps_context(runtime, auth_on):
    from synapsis.database import create_session, save_claude_session_id, get_session_model
    await create_session("rty00001", title="t", user_id="researcher@cgiar.org")
    # researcher: fallback Opus is not allowed -> refused, nothing started
    ws = await run_ws([
        {"type": "switch_session", "session_id": "rty00001"},
        {"type": "retry_with_model", "message": "again", "model": "claude-opus-5"},
        {"type": "retry_with_model", "message": "again"},
        {"type": "retry_with_model", "message": "again", "model": "claude-some-unlisted-model"},
    ])
    assert [e["code"] for e in errors(ws)] == ["model_not_allowed"] * 3
    assert CREATED == []

    # admin: old client disconnected, new one resumes the conversation
    await create_session("rty00002", title="t", user_id="admin@cgiar.org")
    await save_claude_session_id("rty00002", "claude-conv-42")
    old = FakeClient()
    runtime.sessions["rty00002"] = old
    runtime.scripts.append([[result(0.3)]])
    ws_admin = await run_ws([
        {"type": "switch_session", "session_id": "rty00002"},
        {"type": "retry_with_model", "message": "again", "model": "claude-opus-5"},
    ], user="admin@cgiar.org", role="admin")
    assert not errors(ws_admin), ws_admin.sent
    new = CREATED[-1]
    assert old.disconnected is True
    assert new.options.model == "claude-opus-5"
    assert new.options.resume == "claude-conv-42"
    assert new.queries and "again" in new.queries[0]
    assert await get_session_model("rty00002") == "claude-opus-5"


async def test_resumed_chat_on_disallowed_model_uses_role_default(runtime, auth_on):
    from synapsis.database import create_session, update_session_model
    await create_session("old0opus", title="t", user_id="researcher@cgiar.org")
    await update_session_model("old0opus", "claude-opus-5")
    from synapsis.auth.context import set_current_user_id
    set_current_user_id("researcher@cgiar.org", "researcher")
    await runtime.registry.ensure_session("old0opus", "q", runtime.sessions)
    assert CREATED[-1].options.model is None  # None = server default (Sonnet 5)


# ---------------------------------------------------------------------------
# L3-07 cancel owner check
# ---------------------------------------------------------------------------

async def test_cancel_of_another_users_chat_is_refused(runtime, auth_on):
    from synapsis.database import create_session
    from synapsis.chat_run_manager import chat_run_manager
    await create_session("victim01", title="t", user_id="victim@cgiar.org")
    victim_client = FakeClient()
    runtime.sessions["victim01"] = victim_client
    lock = runtime.registry.get_session_lock("victim01")
    await lock.acquire()  # victim's answer is streaming
    try:
        with patch.object(chat_run_manager, "cancel", AsyncMock()) as cancel:
            ws = await run_ws([{"type": "cancel", "session_id": "victim01"}], user="attacker@cgiar.org")
        assert errors(ws)[0]["message"] == "Session not found."
        cancel.assert_not_called()
        assert runtime.sessions.get("victim01") is victim_client and not victim_client.disconnected
        assert lock.locked()

        # the owner can still cancel their own chat from another device
        with patch.object(chat_run_manager, "cancel", AsyncMock()) as cancel:
            await run_ws([{"type": "cancel", "session_id": "victim01"}], user="victim@cgiar.org")
        cancel.assert_awaited_once_with("victim01")
    finally:
        runtime.registry.release_session_client("victim01")


# ---------------------------------------------------------------------------
# Cost accounting, budget, limits, watchdog, error text
# ---------------------------------------------------------------------------

async def _ledger(db_path):
    import aiosqlite
    async with aiosqlite.connect(str(db_path)) as db:
        rows = await (await db.execute(
            "SELECT user_id, role, session_id, model, turn_cost_usd, cumulative_cost_usd, subtype "
            "FROM usage_events ORDER BY id")).fetchall()
    return rows


async def _wait_idle(sid):
    from synapsis.chat_run_manager import chat_run_manager
    h = chat_run_manager.get_handle(sid)
    if h and h.task:
        await asyncio.wait_for(asyncio.shield(h.task), 5)
    await asyncio.sleep(0.05)


async def test_per_question_cost_is_the_running_total_delta(runtime):
    """total_cost_usd is a running total: the ledger stores the per-question
    delta, and a resumed CLI starts from the last recorded total."""
    from synapsis.auth.context import set_current_user_id
    from synapsis.database import create_session
    from synapsis.session.client_registry import tag_client
    from synapsis.stream_handler import stream_response

    await create_session("cost0001", title="t", user_id="researcher@cgiar.org")
    sent = []

    async def send_event(event, *, sid=None):
        sent.append(event)

    with patch("synapsis.config.AUTH_DISABLED", False):
        set_current_user_id("researcher@cgiar.org", "researcher")
        c = FakeClient(SimpleNamespace(model="claude-sonnet-5", resume=None),
                       script=[[result(0.10)], [result(0.25)]])
        tag_client(c, model="claude-sonnet-5", budget_usd=1.0)
        for q in ("q1", "q2"):
            await c.query(q)
            await stream_response("cost0001", c, asyncio.Event(), send_event)
        rows = await _ledger(runtime.db)
        assert [r[4] for r in rows] == pytest.approx([0.10, 0.15])
        assert rows[0][:4] == ("researcher@cgiar.org", "researcher", "cost0001", "claude-sonnet-5")
        assert not [e for e in sent if e.get("type") == "error"]

        # Resume in a new process: baseline = last recorded running total
        await runtime.registry.ensure_session("cost0001", "q3", runtime.sessions)
        resumed = CREATED[-1]
        assert resumed.options.resume == "claude-uuid-1"
        assert resumed._ia_cost_baseline == pytest.approx(0.25)


async def test_budget_exhaustion_explains_and_recycles(runtime):
    from synapsis.database import create_session
    from synapsis.session.client_registry import tag_client
    from synapsis.stream_handler import stream_response

    await create_session("bdg00001", title="t", user_id="researcher@cgiar.org")
    sent = []

    async def send_event(event, *, sid=None):
        sent.append(event)

    first = FakeClient(script=[[result(1.02, subtype="error_max_budget_usd", is_error=True)]])
    tag_client(first, budget_usd=1.0)
    await first.query("big")
    await stream_response("bdg00001", first, asyncio.Event(), send_event)
    budget_err = [e for e in sent if e.get("code") == "turn_budget"]
    assert budget_err and "$1.00" in budget_err[0]["message"]
    assert first._ia_recycle is True

    # The next question replaces the spent CLI process (conversation resumed)
    runtime.sessions["bdg00001"] = first
    sid, client = await runtime.registry.ensure_session("bdg00001", "next", runtime.sessions)
    assert first.disconnected and client is CREATED[-1] and client is not first
    assert client._ia_recycle is False and client._ia_spent == 0.0


async def test_budget_recycle_fraction(runtime, auth_on):
    from synapsis.stream_handler import _account_result
    from synapsis.session.client_registry import tag_client
    c = FakeClient()
    tag_client(c, budget_usd=1.0)
    await _account_result(result(0.30), "x0000001", c)
    assert c._ia_recycle is False
    await _account_result(result(0.61), "x0000001", c)
    assert c._ia_spent == pytest.approx(0.61) and c._ia_recycle is True


async def test_stall_watchdog_stops_the_turn(runtime):
    from synapsis.stream_handler import stream_response
    sent = []

    async def send_event(event, *, sid=None):
        sent.append(event)

    c = FakeClient(script=[["HANG"]])
    await c.query("q")
    with patch("synapsis.config.STALL_TIMEOUT_SECONDS", 0.2):
        await asyncio.wait_for(stream_response("stall001", c, asyncio.Event(), send_event), 5)
    codes = [e.get("code") for e in sent if e.get("type") == "error"]
    assert codes == ["stalled"]
    assert c.interrupted and c._ia_recycle is True


async def test_stream_without_result_is_not_called_context_window(runtime):
    from synapsis.stream_handler import stream_response
    from synapsis.constants import CONTEXT_WINDOW_ERROR
    sent = []

    async def send_event(event, *, sid=None):
        sent.append(event)

    c = FakeClient(script=[[]])
    await c.query("q")
    await stream_response("noresult", c, asyncio.Event(), send_event)
    err = [e for e in sent if e.get("type") == "error"]
    assert err[0]["code"] == "stream_ended" and err[0]["message"] != CONTEXT_WINDOW_ERROR


async def test_answer_text_mentioning_violate_is_not_an_aup_error(runtime, auth_on):
    from synapsis.stream_handler import stream_response
    from claude_agent_sdk.types import StreamEvent
    sent = []

    async def send_event(event, *, sid=None):
        sent.append(event)

    delta = StreamEvent(uuid="u", session_id="s", event={
        "type": "content_block_delta",
        "delta": {"type": "text_delta", "text": "Projects must not violate the AUP of partners."}})
    c = FakeClient(script=[[delta, result(0.01)]])
    await c.query("q")
    await stream_response("aupfalse", c, asyncio.Event(), send_event)
    assert not [e for e in sent if e.get("type") in ("aup_error", "error")]


async def test_refusal_for_researcher_has_no_retry_admin_gets_fallback(runtime):
    from synapsis.stream_handler import stream_response
    from synapsis.auth.context import set_current_user_id
    with patch("synapsis.config.AUTH_DISABLED", False):
        for role, expect in (("researcher", "error"), ("admin", "aup_error")):
            set_current_user_id(f"{role}@cgiar.org", role)
            sent = []

            async def send_event(event, *, sid=None):
                sent.append(event)

            c = FakeClient(script=[[result(0.01, stop_reason="refusal")]])
            await c.query("q")
            await stream_response("refusal1", c, asyncio.Event(), send_event)
            kinds = [e["type"] for e in sent if e.get("type") in ("aup_error", "error")]
            assert kinds == [expect], (role, sent)


@pytest.mark.parametrize("text,code", [
    ("Error code: 429 - input tokens per minute exceeded", "provider_busy"),
    ("overloaded_error", "provider_busy"),
    ("prompt is too long: 1200000 tokens > 1000000 maximum", "context_window"),
    ("maximum recursion depth exceeded", "internal"),
    ("invalid x-api-key", "provider_auth"),
])
def test_error_classification_by_type_not_keyword(text, code):
    from synapsis.stream_core import classify_error
    assert classify_error(RuntimeError(text))[0] == code


def test_cli_error_is_english_and_classified():
    from claude_agent_sdk._errors import CLIConnectionError
    from synapsis.stream_core import classify_error
    import synapsis.websocket as ws_mod
    code, msg = classify_error(CLIConnectionError("Cannot write to terminated process"))
    assert code == "cli_disconnected" and "reload the page" in msg
    src = open(ws_mod.__file__, encoding="utf-8").read()
    assert "sesión" not in src and "recarga" not in src


# ---------------------------------------------------------------------------
# Daily soft cap
# ---------------------------------------------------------------------------

async def test_daily_cap_blocks_researcher_not_admin(runtime, auth_on):
    from synapsis.database.usage import record_turn_usage
    await record_turn_usage(user_id="spender@cgiar.org", role="researcher", session_id="s",
                            model="claude-sonnet-5", turn_cost_usd=5.01)
    await record_turn_usage(user_id="admin@cgiar.org", role="admin", session_id="s",
                            model="claude-opus-5", turn_cost_usd=50.0)
    ws = await run_ws([{"message": "one more?"}], user="spender@cgiar.org")
    err = errors(ws)
    assert err and err[0]["code"] == "daily_limit" and "midnight UTC" in err[0]["message"]
    assert CREATED == []

    runtime.scripts.append([[result(0.01)]])
    ws_admin = await run_ws([{"message": "hi"}], user="admin@cgiar.org", role="admin")
    assert not errors(ws_admin)


async def test_daily_cap_also_applies_to_rest_query(runtime, auth_on):
    from synapsis.database.usage import record_turn_usage
    from synapsis.server import app
    await record_turn_usage(user_id="spender@cgiar.org", role="researcher", session_id=None,
                            model="claude-sonnet-5", turn_cost_usd=6.0)
    with patch("synapsis.database.DB_PATH", runtime.db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
            r = await http.post("/api/query", json={"message": "hi"},
                                headers={"Authorization": f"Bearer {token('spender@cgiar.org', 'researcher')}"})
    assert r.status_code == 429 and "usage limit" in r.json()["detail"]


# ---------------------------------------------------------------------------
# /api/config contract and /api/admin/usage
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def http(initialized_db, auth_on):
    from synapsis.server import app
    with patch("synapsis.database.DB_PATH", initialized_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client


async def test_config_is_role_aware(http):
    anon = (await http.get("/api/config")).json()
    assert [m["id"] for m in anon["selectable_models"]] == ["claude-sonnet-5"]
    assert anon["available_models"] == ["claude-sonnet-5"]
    assert anon["model_policy"]["role"] == "anonymous"
    assert anon["fallback_model"] == ""

    r = (await http.get("/api/config", headers={"Authorization": f"Bearer {token('r@cgiar.org', 'researcher')}"})).json()
    assert [m["id"] for m in r["selectable_models"]] == ["claude-sonnet-5"]
    assert r["model_policy"] == {
        "role": "researcher", "default_model": "claude-sonnet-5",
        "allowed_models": ["claude-sonnet-5"], "max_budget_usd_per_turn": 1.0,
        "daily_budget_usd": 5.0, "max_turns": r["max_turns"], "show_cost": False,
    }
    assert r["max_turns"] == 60

    a = (await http.get("/api/config", headers={"Authorization": f"Bearer {token('a@cgiar.org', 'admin')}"})).json()
    ids = [m["id"] for m in a["selectable_models"]]
    assert "claude-opus-5-5" in ids and ids[0] == "claude-sonnet-5"
    assert a["model_policy"]["show_cost"] is True and a["model_policy"]["daily_budget_usd"] is None
    assert a["fallback_model"] == "claude-opus-5"
    # unchanged fields the frontend relies on
    for key in ("model", "personas", "sso_enabled", "invited_login_enabled", "self_signup"):
        assert key in a


async def test_admin_usage_requires_admin_and_has_shape(http, initialized_db):
    import aiosqlite
    from synapsis.database import create_session, save_message
    from synapsis.database.usage import record_turn_usage

    # legacy history (before the ledger): running totals 0.2 -> 0.5 => 0.2 + 0.3
    await create_session("legacy01", title="t", user_id="invited:abc")
    t0 = time.time() - 3600
    async with aiosqlite.connect(str(initialized_db)) as db:
        for i, total in enumerate((0.2, 0.5)):
            await db.execute("INSERT INTO messages (session_id, ts, type, data) VALUES (?,?,?,?)",
                             ("legacy01", t0 + i, "result", json.dumps({"estimated_cost": total})))
        await db.commit()
    await record_turn_usage(user_id="admin@cgiar.org", role="admin", session_id="new00001",
                            model="claude-opus-5-5", turn_cost_usd=0.75)

    assert (await http.get("/api/admin/usage")).status_code == 401
    r = await http.get("/api/admin/usage", headers={"Authorization": f"Bearer {token('r@cgiar.org', 'researcher')}"})
    assert r.status_code == 403
    r = await http.get("/api/admin/usage?days=3", headers={"Authorization": f"Bearer {token('a@cgiar.org', 'admin')}"})
    assert r.status_code == 200
    body = r.json()
    assert body["days"] == 3 and len(body["daily"]) == 3 and body["currency"] == "USD"
    assert body["totals"]["cost_usd"] == pytest.approx(1.25)
    assert body["totals"]["turns"] == 3 and body["totals"]["users"] == 2
    today = body["daily"][-1]
    assert today["by_role"]["admin"]["cost_usd"] == pytest.approx(0.75)
    assert today["by_role"]["researcher"]["cost_usd"] == pytest.approx(0.5)
    assert today["by_model"]["claude-opus-5-5"]["turns"] == 1
    assert set(today) >= {"date", "turns", "sessions", "users", "cost_usd", "by_role", "by_model", "voice", "source"}
    assert body["policy"]["researcher"]["allowed_models"] == ["claude-sonnet-5"]
    assert "invited:abc" not in r.text and "admin@cgiar.org" not in r.text  # no identities


# ---------------------------------------------------------------------------
# Agent options wiring
# ---------------------------------------------------------------------------

async def test_agent_options_carry_role_budget_and_fallback(initialized_db):
    from synapsis.agent_options import build_agent_options
    from synapsis.auth.context import set_current_user_id
    with patch("synapsis.config.AUTH_DISABLED", False):
        set_current_user_id("r@cgiar.org", "researcher")
        opts = await build_agent_options()
        assert opts.max_budget_usd == 1.0 and opts.fallback_model is None
        assert opts.max_turns == 60
        set_current_user_id("a@cgiar.org", "admin")
        opts = await build_agent_options(model_override="claude-opus-5-5")
        assert opts.max_budget_usd == 5.0 and opts.fallback_model == "claude-opus-5"
        opts = await build_agent_options(model_override="claude-opus-5")
        assert opts.fallback_model is None  # CLI rejects fallback == main model
