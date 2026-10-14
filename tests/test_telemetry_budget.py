"""MVP test budget (SYN-2306) and first-party usage events (SYN-2305).

Budget: window anchoring, spend sums (incl. voice minutes), threshold log
lines once per threshold, graceful stops (global cap, window closed,
per-session cap) for non-admins only, the ``test_budget`` block of
``/api/admin/usage`` and the REST query refusal.

Telemetry: ``POST /api/telemetry`` auth (header or beacon body token),
validation/dropping, dedupe, rate cap, kill-switch, size limit; the admin-only
engagement summary and CSV (no raw identities).
"""

import json
import logging
import time
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest import make_auth_headers


def token_of(headers: dict) -> str:
    return headers["Authorization"].split(" ", 1)[1]


@pytest_asyncio.fixture
async def http(initialized_db):
    from synapsis.server import app
    with patch("synapsis.database.DB_PATH", initialized_db):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            yield client


@pytest.fixture
def budget10():
    """A $10 test budget, open window starting an hour ago, $3 per chat."""
    start = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 3600))
    with (
        patch("synapsis.config.TEST_BUDGET_USD", 10.0),
        patch("synapsis.config.TEST_START", start),
        patch("synapsis.config.TEST_END", ""),
        patch("synapsis.config.TEST_DAYS", 30),
        patch("synapsis.config.SESSION_BUDGET_USD", 3.0),
        patch("synapsis.config.BUDGET_ALERT_THRESHOLDS", (0.5, 0.75, 0.9)),
        patch("synapsis.config.VOICE_USD_PER_MINUTE", 0.10),
    ):
        yield


async def spend(usd, *, user="r@cgiar.org", role="researcher", session="sess0001"):
    from synapsis.database.usage import record_turn_usage
    await record_turn_usage(user_id=user, role=role, session_id=session,
                            model="claude-sonnet-5", turn_cost_usd=usd)


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

def test_threshold_parsing_accepts_fractions_and_percentages():
    from synapsis.config import _parse_thresholds
    assert _parse_thresholds("0.5,0.75,0.9") == (0.5, 0.75, 0.9)
    assert _parse_thresholds("90, 50,75") == (0.5, 0.75, 0.9)
    assert _parse_thresholds("nonsense,,2.5e9") == (0.5, 0.75, 0.9)


def test_defaults_match_the_agreed_test_plan():
    import synapsis.config as c
    # conftest scrubs IA_* so these are the code defaults
    assert c.TEST_BUDGET_USD == 5000.0
    assert c.SESSION_BUDGET_USD == 3.0
    assert c.TEST_DAYS == 30
    assert c.BUDGET_ALERT_THRESHOLDS == (0.5, 0.75, 0.9)
    assert c.TELEMETRY_ENABLED is True


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

async def test_window_without_config_is_anchored_at_first_run(initialized_db):
    from synapsis.database.budget import test_window
    with patch("synapsis.config.TEST_START", ""), patch("synapsis.config.TEST_END", ""):
        first = await test_window(now=1_800_000_000.0)
        later = await test_window(now=1_800_100_000.0)
    assert first["start"] == later["start"] == 1_800_000_000.0
    assert first["start_source"] == "first_run"
    assert first["end"] == first["start"] + 30 * 86400


async def test_configured_window_bare_end_date_is_inclusive(initialized_db):
    from synapsis.database.budget import parse_utc, test_window
    with patch("synapsis.config.TEST_START", "2026-10-15"), patch("synapsis.config.TEST_END", "2026-11-14"):
        w = await test_window()
    assert w["start"] == parse_utc("2026-10-15")
    assert w["end"] == parse_utc("2026-11-15")  # end of the 14th
    assert w["start_source"] == "config" and w["end_source"] == "config"
    assert parse_utc("not a date") is None


# ---------------------------------------------------------------------------
# Status, thresholds, voice
# ---------------------------------------------------------------------------

async def test_status_and_threshold_lines_logged_once(initialized_db, budget10, caplog):
    from synapsis.runtime_policy import test_budget_status
    caplog.set_level(logging.WARNING, logger="synapsis_agent")

    await spend(5.5)
    s = await test_budget_status()
    assert s["state"] == "open" and s["pct"] == 55.0 and s["budget_usd"] == 10.0
    assert s["remaining_usd"] == pytest.approx(4.5)
    assert [a["pct"] for a in s["alerts"]] == [50]
    lines = [r.getMessage() for r in caplog.records if "IA_TEST_BUDGET_THRESHOLD" in r.getMessage()]
    assert len(lines) == 1 and lines[0].startswith("IA_TEST_BUDGET_THRESHOLD pct=50 spent=5.50 budget=10.00")

    await spend(2.0, session="sess0002")  # 75 % crossed by the ledger write itself
    await test_budget_status()
    await test_budget_status()
    lines = [r.getMessage() for r in caplog.records if "IA_TEST_BUDGET_THRESHOLD" in r.getMessage()]
    assert [ln.split()[1] for ln in lines] == ["pct=50", "pct=75"]
    s = await test_budget_status()
    assert s["thresholds"] == [50, 75, 90] and s["window"]["days_left"] > 29


async def test_spend_outside_window_does_not_count(initialized_db, budget10):
    from synapsis.database.usage import record_turn_usage
    from synapsis.runtime_policy import test_budget_status
    await record_turn_usage(user_id="r@cgiar.org", role="researcher", session_id="old00001",
                            model="m", turn_cost_usd=9.0, ts=time.time() - 3 * 86400)
    s = await test_budget_status()
    assert s["spent_usd"] == 0 and s["state"] == "open"


async def test_voice_minutes_count_toward_the_budget(initialized_db, budget10):
    import aiosqlite
    from synapsis.runtime_policy import test_budget_status
    from synapsis.voice import sessions as voice_sessions
    await voice_sessions.init()
    now = time.time()
    async with aiosqlite.connect(str(initialized_db)) as db:
        await db.execute(
            "INSERT INTO voice_sessions (owner, request_id, sdp_hash, status, created, expires, heartbeat, "
            "provider_seconds) VALUES ('u','r1','h','closed',?,?,?,600)", (now, now + 60, now))
        await db.commit()
    s = await test_budget_status()
    assert s["voice"]["minutes"] == 10.0 and s["voice"]["usd"] == pytest.approx(1.0)
    assert s["spent_usd"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Graceful stops
# ---------------------------------------------------------------------------

async def test_global_cap_stops_non_admins_only_and_logs_exhausted(initialized_db, budget10, caplog):
    from synapsis.runtime_policy import MvpBudgetExhausted, enforce_test_budget
    caplog.set_level(logging.WARNING, logger="synapsis_agent")
    await spend(10.5, user="a@cgiar.org", role="admin")  # admin spend counts
    with pytest.raises(MvpBudgetExhausted) as exc:
        await enforce_test_budget(role="researcher")
    assert exc.value.code == "test_budget"
    assert "budget for this test period has been used up" in exc.value.user_message
    await enforce_test_budget(role="admin")  # admins are not stopped
    exhausted = [r for r in caplog.records if "IA_TEST_BUDGET_EXHAUSTED" in r.getMessage()]
    assert len(exhausted) == 1


async def test_closed_window_stops_with_end_date(initialized_db):
    from synapsis.runtime_policy import MvpPeriodClosed, enforce_test_budget
    with (
        patch("synapsis.config.TEST_BUDGET_USD", 5000.0),
        patch("synapsis.config.TEST_START", "2026-01-01"),
        patch("synapsis.config.TEST_END", "2026-01-31"),
    ):
        with pytest.raises(MvpPeriodClosed) as exc:
            await enforce_test_budget(role="researcher")
        await enforce_test_budget(role="admin")
    # IA_TEST_END is inclusive: the message names the last open day, not the day after.
    assert exc.value.code == "test_ended" and "ended on 2026-01-31" in exc.value.user_message


async def test_not_started_window_refuses_with_start_date(initialized_db):
    from synapsis.runtime_policy import MvpPeriodClosed, enforce_test_budget
    with (
        patch("synapsis.config.TEST_BUDGET_USD", 5000.0),
        patch("synapsis.config.TEST_START", "2099-01-01"),
        patch("synapsis.config.TEST_END", ""),
    ):
        with pytest.raises(MvpPeriodClosed) as exc:
            await enforce_test_budget(role="researcher")
    assert "starts on 2099-01-01" in exc.value.user_message


async def test_disabled_budget_never_stops(initialized_db):
    from synapsis.runtime_policy import enforce_test_budget, test_budget_status
    with patch("synapsis.config.TEST_BUDGET_USD", 0.0), patch("synapsis.config.TEST_END", "2026-01-31"):
        await spend(99.0)
        await enforce_test_budget(role="researcher")
        s = await test_budget_status()
    assert s["state"] == "disabled" and s["enabled"] is False and s["pct"] is None


async def test_session_cap_per_chat_non_admin(initialized_db, budget10):
    from synapsis.runtime_policy import SessionBudgetExceeded, enforce_session_budget
    await spend(1.6, session="chat0001")
    await enforce_session_budget("chat0001", role="researcher")
    await spend(1.5, session="chat0001")
    with pytest.raises(SessionBudgetExceeded) as exc:
        await enforce_session_budget("chat0001", role="researcher")
    assert exc.value.code == "session_limit" and "$3.00 per chat" in exc.value.user_message
    await enforce_session_budget("chat0002", role="researcher")  # other chat fine
    await enforce_session_budget(None, role="researcher")  # brand-new chat fine
    await enforce_session_budget("chat0001", role="admin")  # admins exempt


async def test_check_failure_fails_open(initialized_db, budget10):
    from synapsis.runtime_policy import enforce_session_budget, enforce_test_budget
    with patch("synapsis.database.budget.spent_between", side_effect=RuntimeError("db down")):
        await enforce_test_budget(role="researcher")
    with patch("synapsis.database.budget.spent_in_session", side_effect=RuntimeError("db down")):
        await enforce_session_budget("chat0001", role="researcher")


# ---------------------------------------------------------------------------
# HTTP surfaces
# ---------------------------------------------------------------------------

async def test_admin_usage_exposes_test_budget(http, budget10):
    await spend(7.6)
    r = await http.get("/api/admin/usage?days=2", headers=make_auth_headers("admin"))
    assert r.status_code == 200
    tb = r.json()["test_budget"]
    assert tb["pct"] == 76.0 and tb["state"] == "open" and tb["budget_usd"] == 10.0
    assert set(tb["window"]) >= {"start", "end", "start_source", "end_source", "days_left"}
    assert [a["pct"] for a in tb["alerts"]] == [50, 75]
    assert tb["session_budget_usd"] == 3.0
    r = await http.get("/api/admin/usage", headers=make_auth_headers("researcher"))
    assert r.status_code == 403


async def test_rest_query_refused_when_budget_used_up(http, budget10):
    await spend(10.0)
    r = await http.post("/api/query", json={"message": "hi"}, headers=make_auth_headers("researcher"))
    assert r.status_code == 429 and "used up" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Telemetry ingestion
# ---------------------------------------------------------------------------

def ev(i, etype="click", **kw):
    base = {"id": f"evt-{i:06d}", "type": etype, "ts": time.time() * 1000, "visit_id": "visit-aaaa01",
            "path": "/chat?q=secret#frag", "name": "send-button"}
    base.update(kw)
    return base


async def _rows(db_path):
    import aiosqlite
    async with aiosqlite.connect(str(db_path)) as db:
        cur = await db.execute("SELECT user_id, role, env, event_type, url_path, event_name, value, cohort "
                               "FROM ui_events ORDER BY id")
        return await cur.fetchall()


async def test_telemetry_requires_identity(http):
    r = await http.post("/api/telemetry", json={"events": [ev(1)]})
    assert r.status_code == 401
    r = await http.post("/api/telemetry", json={"events": [ev(1)], "token": "not-a-jwt"})
    assert r.status_code == 401


async def test_telemetry_header_and_beacon_body_token(http, initialized_db):
    h = make_auth_headers("researcher", "tester@example.org")
    r = await http.post("/api/telemetry", json={"events": [ev(1), ev(2, "page_view", name="ignored")]}, headers=h)
    assert r.status_code == 204
    # sendBeacon: no headers, token in the body, text/plain content type
    body = json.dumps({"events": [ev(3, "heartbeat", value=30)], "token": token_of(h)})
    r = await http.post("/api/telemetry", content=body, headers={"Content-Type": "text/plain;charset=UTF-8"})
    assert r.status_code == 204
    rows = await _rows(initialized_db)
    assert [r[3] for r in rows] == ["click", "page_view", "heartbeat"]
    assert rows[0][:3] == ("tester@example.org", "researcher", "local")
    assert rows[0][4] == "/chat" and rows[0][5] == "send-button"
    assert rows[1][5] == ""  # names only kept for clicks
    assert rows[2][6] == 30.0


async def test_telemetry_drops_bad_events_dedupes_and_caps(http, initialized_db):
    h = make_auth_headers("researcher")
    events = [
        ev(1), ev(1),  # duplicate id
        {"type": "keystroke", "visit_id": "visit-aaaa01"},  # unknown type
        ev(2, visit_id="x"),  # bad visit id
        ev(3, name="<script>alert(1)</script>", path="javascript:alert(1)"),
        ev(4, "heartbeat", value=10_000),
        "not-a-dict",
    ]
    r = await http.post("/api/telemetry", json={"events": events}, headers=h)
    assert r.status_code == 204
    rows = await _rows(initialized_db)
    assert len(rows) == 3
    assert rows[1][4] == "" and rows[1][5] == "scriptalert1/script"
    assert rows[2][6] == 120.0  # one heartbeat never claims more than 2 min

    many = [ev(100 + i) for i in range(80)]
    await http.post("/api/telemetry", json={"events": many}, headers=h)
    assert len(await _rows(initialized_db)) == 3 + 50  # batch cap

    with patch("synapsis.config.TELEMETRY_MAX_EVENTS_PER_MINUTE", 0):
        await http.post("/api/telemetry", json={"events": [ev(999)]}, headers=h)
    assert len(await _rows(initialized_db)) == 53


async def test_telemetry_kill_switch_and_size_limit(http):
    h = make_auth_headers("researcher")
    with patch("synapsis.config.TELEMETRY_ENABLED", False):
        assert (await http.post("/api/telemetry", json={"events": []}, headers=h)).status_code == 404
    big = json.dumps({"events": [], "pad": "x" * 70_000})
    r = await http.post("/api/telemetry", content=big, headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 413
    r = await http.post("/api/telemetry", content="[1,2]", headers={**h, "Content-Type": "application/json"})
    assert r.status_code == 422


async def test_telemetry_records_invited_cohort(http, initialized_db):
    import aiosqlite
    from synapsis.auth import invited_storage
    await invited_storage.init_invited_tables()
    async with aiosqlite.connect(str(initialized_db)) as db:
        await db.execute("INSERT INTO invited_accounts (email, user_id, name, created_at, cohort) "
                         "VALUES ('x@example.org', 'invited:abc', 'X', 0, 'Pilot Oct-2026')")
        await db.commit()
    # The cohort is looked up by account id (token source does not matter here).
    h = make_auth_headers("researcher", "invited:abc")
    assert (await http.post("/api/telemetry", json={"events": [ev(1)]}, headers=h)).status_code == 204
    assert (await _rows(initialized_db))[0][7] == "Pilot Oct-2026"


# ---------------------------------------------------------------------------
# Engagement read-outs
# ---------------------------------------------------------------------------

async def test_engagement_summary_and_csv(http, initialized_db):
    t0 = time.time() - 600
    h = make_auth_headers("researcher", "tester@example.org")
    events = [
        ev(1, "page_view", ts=t0 * 1000, visit_id="visit-one111"),
        ev(2, "click", ts=(t0 + 10) * 1000, visit_id="visit-one111", name="send-button"),
        ev(3, "click", ts=(t0 + 20) * 1000, visit_id="visit-one111", name="send-button"),
        ev(4, "heartbeat", ts=(t0 + 30) * 1000, visit_id="visit-one111", value=30),
        ev(5, "heartbeat", ts=(t0 + 240) * 1000, visit_id="visit-one111", value=30),
        ev(6, "click", ts=(t0 + 300) * 1000, visit_id="visit-two222", name="new-chat"),
    ]
    assert (await http.post("/api/telemetry", json={"events": events}, headers=h)).status_code == 204
    await spend(0.4, user="tester@example.org")
    await spend(0.6, user="tester@example.org", session="sess0002")

    assert (await http.get("/api/admin/engagement")).status_code == 401
    assert (await http.get("/api/admin/engagement", headers=h)).status_code == 403
    r = await http.get("/api/admin/engagement?days=2", headers=make_auth_headers("admin"))
    assert r.status_code == 200
    body = r.json()
    assert "Umami" in body["tracking"] and "cookieless" in body["tracking"]
    t = body["totals"]
    assert (t["users"], t["visits"], t["page_views"], t["clicks"], t["questions"]) == (1, 2, 1, 3, 2)
    # visit one: 240 s wall time = 4.0 min; visit two: single event = 0 min
    assert t["session_minutes_avg"] == 2.0
    u = body["by_user"][0]
    assert u["user_key"].startswith("u-") and u["questions"] == 2 and u["cost_usd"] == pytest.approx(1.0)
    assert body["top_targets"][0] == {"name": "send-button", "clicks": 2}
    assert body["by_cohort"][0]["cohort"] == "(no cohort)"
    assert "tester@example.org" not in r.text

    r = await http.get("/api/admin/engagement.csv?days=2", headers=make_auth_headers("admin"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().split("\n")
    assert lines[0].startswith("environment,date,user_key,role,cohort,questions,cost_usd,visits")
    assert len(lines) == 2 and "tester@example.org" not in r.text
    assert (await http.get("/api/admin/engagement.csv", headers=h)).status_code == 403


async def test_idle_gap_in_a_visit_is_not_session_time(initialized_db):
    """A tab left open for 4 h and then closed is a short session, not 240 minutes."""
    from synapsis.database.telemetry import engagement_summary, record_events
    now = time.time()
    t0 = now - 5 * 3600
    base = {"chat_session_id": None, "url_path": "/", "event_name": "", "value": None, "visit_id": "visit-idle01"}
    await record_events([
        {**base, "event_id": "idle-0001", "ts": t0, "event_type": "page_view"},
        {**base, "event_id": "idle-0002", "ts": t0 + 4 * 3600, "event_type": "visit_end"},
    ], user_id="u@example.org", role="researcher", env="t")
    s = await engagement_summary(2, now=now)
    assert s["totals"]["session_minutes_avg"] == 5.0  # one capped 5-minute gap


def test_user_key_is_stable_and_keyed():
    from synapsis.database.telemetry import user_key
    assert user_key("a@x.org") == user_key("a@x.org") != user_key("b@x.org")
    import hashlib
    assert user_key("a@x.org")[2:] != hashlib.sha256(b"a@x.org").hexdigest()[:10]


async def test_threshold_fires_again_after_the_budget_is_raised(initialized_db, budget10, caplog):
    """Raising IA_TEST_BUDGET_USD mid-test re-arms the alerts for the new budget (once)."""
    from synapsis.runtime_policy import test_budget_status
    caplog.set_level(logging.WARNING, logger="synapsis_agent")

    def lines():
        return [r.getMessage().split()[1:4:2] for r in caplog.records
                if "IA_TEST_BUDGET_THRESHOLD" in r.getMessage()]

    await spend(5.5)
    await test_budget_status()
    assert lines() == [["pct=50", "budget=10.00"]]
    with patch("synapsis.config.TEST_BUDGET_USD", 20.0):
        await test_budget_status()          # 27 %: nothing new
        assert lines() == [["pct=50", "budget=10.00"]]
        await spend(5.0, session="sess0002")  # 52.5 % of the new budget
        await test_budget_status()
        await test_budget_status()
    assert lines() == [["pct=50", "budget=10.00"], ["pct=50", "budget=20.00"]]
