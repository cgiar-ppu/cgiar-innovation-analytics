"""Answer/voice feedback for restricted test rounds (Lane H, 2026-09-26).

Owner-only writes (one editable row per user per answer), server-side answer
identification, opt-in sharing of chat text, admin list/filters/CSV, voice
feedback via the guide's submit_feedback tool, and cohort attribution.
"""
import csv
import io
import json
import time
from unittest.mock import patch
from uuid import uuid4

import aiosqlite
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from synapsis.auth.tokens import create_access_token


def sso(user_id, role="researcher"):
    return {"Authorization": "Bearer " + create_access_token(user_id, user_id.split(":")[-1], role, auth_source="sso")}


ALICE, BOB, ADMIN = sso("sso:alice"), sso("sso:bob"), sso("sso:admin", "admin")


@pytest_asyncio.fixture
async def http(initialized_db, monkeypatch):
    import synapsis.config as config
    from synapsis.server import app  # import before SSO is switched on (import-time settings check)
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("IA_ENVIRONMENT", "dev")
    monkeypatch.setattr(config, "ENVIRONMENT_LABEL", "dev")
    monkeypatch.setattr(config, "SSO_ENABLED", True)
    monkeypatch.setattr(config, "INVITED_LOGIN_ENABLED", True)
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
        patch("synapsis.database.DB_PATH", initialized_db),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client


async def seed_chat(db_path, session_id="chat-a", owner="sso:alice", answers=2, model="claude-sonnet-5"):
    """A chat with `answers` finished answers; the first question carries specialist + scope."""
    t = time.time() - 600
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute(
            "INSERT INTO sessions (session_id, title, created_at, updated_at, model, user_id) VALUES (?,?,?,?,?,?)",
            (session_id, "t", t, t, model, owner))
        for i in range(1, answers + 1):
            meta = {"agent": "prms_data_analyst", "scope": {"years": [2025], "programs": []}} if i == 1 else {}
            rows = [
                ("user", {"content": f"Question {i}?", **meta}),
                ("tool_use", {"tool": "mcp__synapsis__prms_query", "input": {}}),
                ("text", {"content": f"Answer {i} part A."}),
                ("text", {"content": f"Answer {i} part B."}),
                ("result", {"estimated_cost": 0.1 * i, "turns": 3, "is_error": False}),
            ]
            for kind, data in rows:
                t += 1
                await db.execute("INSERT INTO messages (session_id, ts, type, data) VALUES (?,?,?,?)",
                                 (session_id, t, kind, json.dumps(data)))
        await db.commit()


async def rows(db_path):
    async with aiosqlite.connect(str(db_path)) as db:
        db.row_factory = aiosqlite.Row
        return [dict(r) for r in await (await db.execute("SELECT * FROM answer_feedback ORDER BY id")).fetchall()]


# ---------------------------------------------------------------------------
# Chat answers
# ---------------------------------------------------------------------------

async def test_owner_rates_an_answer_once_and_can_edit_it(http, initialized_db):
    await seed_chat(initialized_db)
    from synapsis.database.usage import record_turn_usage
    async with aiosqlite.connect(str(initialized_db)) as db:
        (first_result_ts,) = await (await db.execute(
            "SELECT ts FROM messages WHERE type='result' ORDER BY ts LIMIT 1")).fetchone()
    await record_turn_usage(user_id="sso:alice", role="researcher", session_id="chat-a",
                            model="claude-sonnet-5", turn_cost_usd=0.1, ts=first_result_ts + 1)

    r = await http.post("/api/feedback", headers=ALICE, json={
        "session_id": "chat-a", "message_id": "r1", "rating": 1, "comment": "  Clear and sourced.  "})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["rating"] == 1 and body["comment"] == "Clear and sourced." and body["share_answer"] is False

    r = await http.post("/api/feedback", headers=ALICE, json={
        "session_id": "chat-a", "message_id": "r1", "rating": -1, "comment": "Wrong year",
        "expected": "The 2025 count, 1,185."})
    assert r.status_code == 200

    stored = await rows(initialized_db)
    assert len(stored) == 1, "one feedback per user per answer"
    row = stored[0]
    assert (row["rating"], row["comment"], row["expected"]) == (-1, "Wrong year", "The 2025 count, 1,185.")
    assert row["user_id"] == "sso:alice" and row["channel"] == "chat" and row["message_id"] == "r1"
    assert row["model"] == "claude-sonnet-5" and row["role"] == "researcher"
    assert row["persona"] == "prms_data_analyst"
    assert json.loads(row["scope"])["years"] == [2025]
    assert row["app_version"] == "abc1234" and row["environment"] == "dev"
    assert row["shared_question"] is None and row["shared_answer"] is None, "no chat text without opt-in"
    assert row["updated_at"] >= row["created_at"]

    mine = (await http.get("/api/feedback?session_id=chat-a", headers=ALICE)).json()["feedback"]
    assert [(f["message_id"], f["rating"]) for f in mine] == [("r1", -1)]


async def test_answers_without_recorded_specialist_or_scope_store_none(http, initialized_db):
    await seed_chat(initialized_db)
    r = await http.post("/api/feedback", headers=ALICE, json={"session_id": "chat-a", "message_id": "r2", "rating": 1})
    assert r.status_code == 200
    row = (await rows(initialized_db))[0]
    assert row["persona"] == "" and row["scope"] == ""
    assert row["model"] == "claude-sonnet-5", "falls back to the chat's model without a ledger row"
    # The browser cannot supply them.
    r = await http.post("/api/feedback", headers=ALICE, json={
        "session_id": "chat-a", "message_id": "r2", "rating": 1, "persona": "prms_data_analyst"})
    assert r.status_code == 422


async def test_sharing_the_answer_is_opt_in_and_uses_server_side_text(http, initialized_db):
    await seed_chat(initialized_db)
    r = await http.post("/api/feedback", headers=ALICE, json={
        "session_id": "chat-a", "message_id": "r2", "rating": -1, "share_answer": True})
    assert r.status_code == 200 and r.json()["share_answer"] is True
    row = (await rows(initialized_db))[0]
    assert row["shared_question"] == "Question 2?"
    assert row["shared_answer"] == "Answer 2 part A.\n\nAnswer 2 part B."
    # Withdrawing consent removes the copy.
    await http.post("/api/feedback", headers=ALICE, json={
        "session_id": "chat-a", "message_id": "r2", "rating": -1, "share_answer": False})
    row = (await rows(initialized_db))[0]
    assert row["shared_question"] is None and row["shared_answer"] is None


@pytest.mark.parametrize("body,status", [
    ({"message_id": "r3", "rating": 1}, 404),            # no third answer
    ({"message_id": "r0", "rating": 1}, 422),
    ({"message_id": "hist-4", "rating": 1}, 422),        # browser ids are not accepted
    ({"message_id": "r1", "rating": 2}, 422),            # chat is thumbs up/down
    ({"message_id": "r1", "rating": 1, "role": "admin"}, 422),  # no extra fields
    ({"message_id": "r1", "rating": 1, "comment": "x" * 2001}, 422),
])
async def test_invalid_chat_feedback_is_rejected(http, initialized_db, body, status):
    await seed_chat(initialized_db)
    r = await http.post("/api/feedback", headers=ALICE, json={"session_id": "chat-a", **body})
    assert r.status_code == status
    assert await rows(initialized_db) == []


async def test_only_the_owner_can_rate_read_or_withdraw(http, initialized_db):
    await seed_chat(initialized_db)
    await seed_chat(initialized_db, session_id="legacy-chat", owner="legacy@innovation-analytics", answers=1)
    body = {"session_id": "chat-a", "message_id": "r1", "rating": 1}
    assert (await http.post("/api/feedback", json=body)).status_code == 401
    assert (await http.post("/api/feedback", headers=BOB, json=body)).status_code == 404
    # Admin role grants no access to other users' chats (Jose, 14 Sep).
    assert (await http.post("/api/feedback", headers=ADMIN, json=body)).status_code == 404
    assert (await http.post("/api/feedback", headers=ADMIN, json={**body, "session_id": "legacy-chat"})).status_code == 404
    assert (await http.post("/api/feedback", headers=ALICE, json={**body, "session_id": "missing"})).status_code == 404

    saved = (await http.post("/api/feedback", headers=ALICE, json=body)).json()
    assert (await http.get("/api/feedback?session_id=chat-a", headers=BOB)).json()["feedback"] == []
    assert (await http.delete(f"/api/feedback/{saved['id']}", headers=BOB)).status_code == 404
    assert (await http.delete(f"/api/feedback/{saved['id']}", headers=ADMIN)).status_code == 404
    assert (await http.delete(f"/api/feedback/{saved['id']}", headers=ALICE)).status_code == 200
    assert await rows(initialized_db) == []


async def test_feedback_can_be_switched_off(http, initialized_db, monkeypatch):
    await seed_chat(initialized_db)
    monkeypatch.setenv("IA_FEEDBACK_ENABLED", "false")
    assert (await http.post("/api/feedback", headers=ALICE, json={
        "session_id": "chat-a", "message_id": "r1", "rating": 1})).status_code == 404
    assert (await http.get("/api/feedback?session_id=chat-a", headers=ALICE)).status_code == 404
    assert (await http.get("/api/admin/feedback", headers=ADMIN)).status_code == 404


# ---------------------------------------------------------------------------
# Voice sessions
# ---------------------------------------------------------------------------

async def seed_voice(owner, request_id, sdp_hash="abc"):
    from synapsis.voice import sessions as s
    await s.init()
    from synapsis.database import get_db
    async with get_db() as db:
        now = time.time()
        await db.execute("INSERT INTO voice_sessions(owner,request_id,sdp_hash,status,created,expires,heartbeat) "
                         "VALUES (?,?,?,?,?,?,?)", (owner, request_id, sdp_hash, "closed", now, now, now))
        await db.commit()


async def test_voice_session_feedback_rating_and_one_improvement(http, initialized_db, monkeypatch):
    monkeypatch.setenv("IA_VOICE_MODEL", "gpt-live-1")
    rid, tombstone = str(uuid4()), str(uuid4())
    await seed_voice("sso:alice", rid)
    await seed_voice("sso:alice", tombstone, sdp_hash="")   # End pressed before any start: not rateable
    voice = {"channel": "voice", "session_id": rid, "rating": 4, "comment": "Let me see the sources sooner."}
    r = await http.post("/api/feedback", headers=ALICE, json=voice)
    assert r.status_code == 200, r.text
    r = await http.post("/api/feedback", headers=ALICE, json={**voice, "rating": 5})
    stored = await rows(initialized_db)
    assert len(stored) == 1
    row = stored[0]
    assert (row["channel"], row["rating"], row["message_id"], row["model"]) == ("voice", 5, "", "gpt-live-1")
    assert row["comment"] == "Let me see the sources sooner."

    assert (await http.post("/api/feedback", headers=BOB, json=voice)).status_code == 404
    assert (await http.post("/api/feedback", headers=ALICE, json={**voice, "session_id": tombstone})).status_code == 404
    assert (await http.post("/api/feedback", headers=ALICE, json={**voice, "session_id": "nope"})).status_code == 422
    for bad in ({"rating": 0}, {"rating": 6}, {"expected": "x"}, {"message_id": "r1"}, {"share_answer": True}):
        assert (await http.post("/api/feedback", headers=ALICE, json={**voice, **bad})).status_code == 422


def test_voice_guide_offers_submit_feedback_tool_and_asks_once():
    from synapsis.voice.config import TOOLS, session_config
    tool = next(t for t in TOOLS if t["name"] == "submit_feedback")
    props = tool["parameters"]["properties"]
    assert props["rating"] == {"type": "integer", "minimum": 1, "maximum": 5}
    assert props["improvement"]["type"] == "string"
    assert tool["parameters"]["required"] == ["rating", "improvement"]
    assert tool["parameters"]["additionalProperties"] is False and tool["strict"] is True
    config = session_config()
    for text in (config["instructions"], config["delegation"]["responses"]["instructions"]):
        assert "submit_feedback" in text and "do not ask again" in text
    assert "submit_feedback" in [t["name"] for t in config["delegation"]["responses"]["tools"]]


async def test_voice_status_reports_the_feedback_prompt_flag(http, monkeypatch):
    monkeypatch.setenv("IA_VOICE_ORIGINS", "http://t")
    body = (await http.get("/api/voice/status", headers=ALICE)).json()
    assert body["feedback_prompt"] is True
    monkeypatch.setenv("IA_VOICE_FEEDBACK_PROMPT", "false")
    assert (await http.get("/api/voice/status", headers=ALICE)).json()["feedback_prompt"] is False
    monkeypatch.setenv("IA_VOICE_FEEDBACK_PROMPT", "true")
    monkeypatch.setenv("IA_FEEDBACK_ENABLED", "false")
    assert (await http.get("/api/voice/status", headers=ALICE)).json()["feedback_prompt"] is False


# ---------------------------------------------------------------------------
# Admin view
# ---------------------------------------------------------------------------

async def test_admin_list_filters_cohorts_and_csv(http, initialized_db):
    from synapsis.auth import invited_storage as invited
    await seed_chat(initialized_db)
    await seed_chat(initialized_db, session_id="chat-b", owner="sso:bob", answers=1)
    # An invited tester in a named cohort.
    token = await invited.create_invitation("ttl@worldbank.example", "Test TTL", "sso:admin", cohort="WB TTLs Oct-2026")
    tester = await invited.accept_invitation(token, "long-test-password")
    tester_headers = {"Authorization": "Bearer " + create_access_token(
        tester["user_id"], tester["name"], "researcher", email=tester["email"],
        auth_source="invited", credential_version=tester["credential_version"])}
    await seed_chat(initialized_db, session_id="chat-t", owner=tester["user_id"], answers=1)

    assert (await http.post("/api/feedback", headers=ALICE, json={
        "session_id": "chat-a", "message_id": "r1", "rating": 1, "comment": "=HYPERLINK(\"http://x\")"})).status_code == 200
    assert (await http.post("/api/feedback", headers=BOB, json={
        "session_id": "chat-b", "message_id": "r1", "rating": -1, "expected": "Cite the source"})).status_code == 200
    r = await http.post("/api/feedback", headers=tester_headers, json={
        "session_id": "chat-t", "message_id": "r1", "rating": -1, "share_answer": True})
    assert r.status_code == 200, r.text

    assert (await http.get("/api/admin/feedback")).status_code == 401
    assert (await http.get("/api/admin/feedback", headers=ALICE)).status_code == 403

    body = (await http.get("/api/admin/feedback", headers=ADMIN)).json()
    assert body["total"] == 3 and body["counts"] == {"positive": 1, "negative": 2, "neutral": 0}
    assert body["cohorts"] == ["WB TTLs Oct-2026"] and body["environment"] == "dev"
    tester_row = next(i for i in body["items"] if i["cohort"])
    assert tester_row["user_email"] == "ttl@worldbank.example" and tester_row["shared_answer"].startswith("Answer 1")
    assert {"model", "persona", "scope", "app_version", "environment", "session_id", "message_id"} <= set(tester_row)

    neg = (await http.get("/api/admin/feedback?rating=negative", headers=ADMIN)).json()
    assert neg["total"] == 2
    cohort = (await http.get("/api/admin/feedback", params={"cohort": "WB TTLs Oct-2026"}, headers=ADMIN)).json()
    assert [i["user_email"] for i in cohort["items"]] == ["ttl@worldbank.example"]
    no_cohort = (await http.get("/api/admin/feedback?cohort=__none__", headers=ADMIN)).json()
    assert no_cohort["total"] == 2
    assert (await http.get("/api/admin/feedback?channel=voice", headers=ADMIN)).json()["total"] == 0
    assert (await http.get("/api/admin/feedback?from=2999-01-01", headers=ADMIN)).json()["total"] == 0
    assert (await http.get("/api/admin/feedback?days=1", headers=ADMIN)).json()["total"] == 3
    assert (await http.get("/api/admin/feedback?rating=bad", headers=ADMIN)).status_code == 422

    r = await http.get("/api/admin/feedback?format=csv", headers=ADMIN)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"].startswith('attachment; filename="ia-feedback-dev-')
    table = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert len(table) == 3 and table[0].keys() >= {"created_at", "rating", "comment", "cohort", "model", "app_version"}
    alice_row = next(t for t in table if t["user_name"] == "alice" or t["comment"].startswith("'"))
    assert alice_row["comment"].startswith("'="), "spreadsheet formulas are neutralised"
    assert (await http.get("/api/admin/feedback?format=csv", headers=ALICE)).status_code == 403


async def test_usage_summary_reports_cost_by_cohort(http, initialized_db):
    from synapsis.auth import invited_storage as invited
    from synapsis.database.usage import record_turn_usage
    token = await invited.create_invitation("ttl@worldbank.example", "Test TTL", "sso:admin", cohort="WB TTLs Oct-2026")
    tester = await invited.accept_invitation(token, "long-test-password")
    await record_turn_usage(user_id=tester["user_id"], role="researcher", session_id="s1",
                            model="claude-sonnet-5", turn_cost_usd=0.4)
    await record_turn_usage(user_id="sso:alice", role="researcher", session_id="s2",
                            model="claude-sonnet-5", turn_cost_usd=0.2)
    body = (await http.get("/api/admin/usage?days=1", headers=ADMIN)).json()
    today = body["daily"][-1]
    assert today["by_cohort"] == {"WB TTLs Oct-2026": {"turns": 1, "cost_usd": 0.4, "users": 1}}
    assert tester["user_id"] not in json.dumps(body) and "worldbank" not in json.dumps(body)


# ---------------------------------------------------------------------------
# Turn metadata on the saved question
# ---------------------------------------------------------------------------

def test_turn_meta_records_only_real_selections():
    from synapsis.handlers.chat_handlers import _turn_meta
    assert _turn_meta({"years": [], "programs": []}, "") == {}
    assert _turn_meta({"years": [2025], "programs": []}, "prms_data_analyst") == {
        "agent": "prms_data_analyst", "scope": {"years": [2025], "programs": []}}


async def test_feedback_table_is_created_by_init_db(initialized_db):
    async with aiosqlite.connect(str(initialized_db)) as db:
        cols = {r[1] for r in await (await db.execute("PRAGMA table_info(answer_feedback)")).fetchall()}
    assert {"user_id", "channel", "session_id", "message_id", "rating", "comment", "expected",
            "model", "persona", "scope", "cohort", "app_version", "environment"} <= cols
