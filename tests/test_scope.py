"""Tests for the active data scope — year + programme filters that constrain
the AGENT, not just a dashboard (Marc Schut's July-7 ask #6).

Covers:
- normalize_scope() validation (types, caps, unknown years, dedup, trimming);
- render_scope_preamble() — empty scope is a strict no-op, populated scope
  renders the delimited block with the counting-discipline instructions;
- the chat entry-point wiring: the message handed to the SDK carries the
  preamble when a scope is set, and is byte-identical to the user's text when
  it is not — while the PERSISTED user message is never modified;
- an invalid scope is rejected before the agent is ever touched;
- POST /api/query honours the same scope object;
- GET /api/scope/options shape + auth gating.
"""

from unittest.mock import AsyncMock, patch

import pytest

from synapsis.scope import (
    MAX_PROGRAMS,
    ScopeValidationError,
    apply_scope_to_message,
    describe_scope,
    normalize_scope,
    render_scope_preamble,
    scope_is_empty,
)


# ---------------------------------------------------------------------------
# normalize_scope
# ---------------------------------------------------------------------------

def test_normalize_scope_none_and_empty_are_empty():
    assert normalize_scope(None) == {"years": [], "programs": []}
    assert normalize_scope({}) == {"years": [], "programs": []}
    assert normalize_scope({"years": [], "programs": []}) == {"years": [], "programs": []}
    assert scope_is_empty(normalize_scope(None))


def test_normalize_scope_accepts_years_and_programs():
    out = normalize_scope({"years": [2024, 2025], "programs": ["SP09 — Scaling for Impact"]})
    assert out == {"years": [2024, 2025], "programs": ["SP09 — Scaling for Impact"]}
    assert not scope_is_empty(out)


def test_normalize_scope_sorts_dedups_and_trims():
    out = normalize_scope(
        {"years": [2025, 2024, 2024], "programs": ["  SP09  ", "SP09", "SP01"]}
    )
    assert out["years"] == [2024, 2025]
    assert out["programs"] == ["SP09", "SP01"]


def test_normalize_scope_accepts_numeric_strings_for_years():
    assert normalize_scope({"years": ["2024"]})["years"] == [2024]


def test_normalize_scope_ignores_unknown_keys():
    out = normalize_scope({"years": [2024], "regions": ["Africa"]})
    assert out == {"years": [2024], "programs": []}


@pytest.mark.parametrize(
    "bad",
    [
        "not-an-object",
        {"years": 2024},                       # not a list
        {"programs": "SP09"},                  # not a list
        {"years": [2019]},                     # outside the PRMS snapshot
        {"years": [2026]},                     # outside the PRMS snapshot
        {"years": ["twenty-twenty-four"]},     # unparseable
        {"years": [True]},                     # bool is not a year
        {"programs": [123]},                   # not a string
        {"programs": ["  "]},                  # blank
        {"programs": ["x" * 200]},             # too long
    ],
)
def test_normalize_scope_rejects_invalid_payloads(bad):
    with pytest.raises(ScopeValidationError):
        normalize_scope(bad)


def test_normalize_scope_enforces_program_cap():
    with pytest.raises(ScopeValidationError):
        normalize_scope({"programs": [f"SP{i}" for i in range(MAX_PROGRAMS + 1)]})


# ---------------------------------------------------------------------------
# Preamble rendering
# ---------------------------------------------------------------------------

def test_empty_scope_renders_no_preamble():
    assert render_scope_preamble(None) == ""
    assert render_scope_preamble({"years": [], "programs": []}) == ""


def test_empty_scope_leaves_the_message_untouched():
    assert apply_scope_to_message("how many innovations?", None) == "how many innovations?"
    assert (
        apply_scope_to_message("how many innovations?", {"years": [], "programs": []})
        == "how many innovations?"
    )


def test_populated_scope_renders_the_block():
    block = render_scope_preamble({"years": [2024], "programs": ["SP09 — Scaling for Impact"]})
    assert block.startswith("[ACTIVE DATA SCOPE")
    assert block.rstrip().endswith("[END ACTIVE DATA SCOPE]")
    assert "years = 2024" in block
    assert "SP09 — Scaling for Impact" in block
    # The counting-discipline contract: state the scope, don't silently widen it.
    assert "STATE the active scope" in block
    assert "counting method" in block


def test_apply_scope_puts_the_block_before_the_user_text():
    msg = apply_scope_to_message("how many innovations in 2024?", {"years": [2024], "programs": []})
    assert msg.index("[ACTIVE DATA SCOPE") < msg.index("how many innovations in 2024?")


def test_describe_scope_readable_forms():
    assert describe_scope(None) == "no filters (full portfolio)"
    assert describe_scope({"years": [2024, 2025], "programs": []}) == "years = 2024, 2025"
    assert (
        describe_scope({"years": [], "programs": ["SP09", "SP01"]})
        == "programs/accelerators = SP09, SP01"
    )
    both = describe_scope({"years": [2024], "programs": ["SP09"]})
    assert both == "years = 2024; programs/accelerators = SP09"


# ---------------------------------------------------------------------------
# Chat entry-point wiring (handle_user_message)
# ---------------------------------------------------------------------------

async def _run_handle_user_message(payload: dict):
    """Drive handle_user_message with every collaborator mocked out.

    Returns (sdk_message, persisted_messages, sent_frames).
    """
    from synapsis.handlers import chat_handlers

    sent: list[dict] = []
    persisted: list[tuple] = []

    async def _send_json(data, sid=None):
        sent.append(data)

    async def _save_message(session_id, msg_type, data):
        persisted.append((session_id, msg_type, data))

    launched: dict = {}

    async def _launch(session_id, client, message, send_json, lock_acquired=False):
        launched["message"] = message

    with (
        patch.object(chat_handlers, "record_activity", AsyncMock()),
        patch.object(chat_handlers, "cancel_existing_task", AsyncMock()),
        patch.object(chat_handlers, "ensure_session", AsyncMock(return_value=("sid-1", object()))),
        patch.object(chat_handlers, "save_message", _save_message),
        patch.object(chat_handlers, "consume_initial_context", AsyncMock(return_value=None)),
        patch.object(
            chat_handlers, "acquire_session_client", AsyncMock(return_value=(object(), False))
        ),
        patch.object(chat_handlers, "launch_streaming_task", _launch),
        patch.object(chat_handlers, "broadcast_to_all", AsyncMock()),
        patch.object(chat_handlers, "broadcast_to_session", AsyncMock()),
    ):
        await chat_handlers.handle_user_message(payload, "sid-1", _send_json)

    return launched.get("message"), persisted, sent


@pytest.mark.asyncio
async def test_message_to_sdk_carries_the_preamble_when_scope_is_set():
    sdk_message, persisted, _ = await _run_handle_user_message(
        {
            "message": "how many innovations?",
            "scope": {"years": [2024], "programs": ["SP09 — Scaling for Impact"]},
        }
    )
    assert "[ACTIVE DATA SCOPE" in sdk_message
    assert "years = 2024" in sdk_message
    assert sdk_message.endswith("how many innovations?")

    # The user's OWN message is persisted unmodified — the preamble is a
    # server-side wrapper, not something the user appears to have typed.
    user_rows = [d for (_, t, d) in persisted if t == "user"]
    assert user_rows == [{"content": "how many innovations?"}]


@pytest.mark.asyncio
async def test_message_to_sdk_is_unchanged_without_scope():
    sdk_message, _, _ = await _run_handle_user_message({"message": "how many innovations?"})
    assert sdk_message == "how many innovations?"

    sdk_message2, _, _ = await _run_handle_user_message(
        {"message": "how many innovations?", "scope": {"years": [], "programs": []}}
    )
    assert sdk_message2 == "how many innovations?"


@pytest.mark.asyncio
async def test_invalid_scope_is_rejected_before_reaching_the_agent():
    with pytest.raises(ValueError):
        await _run_handle_user_message({"message": "hi", "scope": {"years": [1999]}})


@pytest.mark.asyncio
async def test_invalid_scope_tells_the_user_why():
    from synapsis.handlers import chat_handlers

    sent: list[dict] = []

    async def _send_json(data, sid=None):
        sent.append(data)

    with pytest.raises(ValueError):
        await chat_handlers.handle_user_message(
            {"message": "hi", "scope": {"years": [1999]}}, "sid-1", _send_json
        )

    assert sent and sent[0]["type"] == "error"
    assert "Invalid data scope" in sent[0]["message"]


# ---------------------------------------------------------------------------
# REST surfaces
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_api_query_rejects_an_invalid_scope(test_client):
    resp = await test_client.post(
        "/api/query", json={"message": "hi", "scope": {"years": [1999]}}
    )
    assert resp.status_code == 422
    assert "Invalid data scope" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_scope_options_shape(test_client):
    resp = await test_client.get("/api/scope/options")
    assert resp.status_code == 200
    body = resp.json()
    assert body["years"] == [2022, 2023, 2024, 2025]
    assert body["source"] in ("prms", "fallback")
    assert isinstance(body["programs"], list) and body["programs"]
    first = body["programs"][0]
    assert {"code", "label", "era"} <= set(first)
    # No placeholder rows (MP-01/OFF-01/OPLAT-xx) leak into the filter list.
    codes = [p["code"] for p in body["programs"]]
    assert not any(c.startswith(("MP-", "OFF-", "OPLAT")) for c in codes)
    assert len(codes) == len(set(codes))  # deduped


@pytest.mark.asyncio
async def test_scope_options_requires_auth_when_auth_is_enforced(test_client):
    with (
        patch("synapsis.config.AUTH_DISABLED", False),
        patch("synapsis.auth.middleware.AUTH_DISABLED", False),
    ):
        resp = await test_client.get("/api/scope/options")
    assert resp.status_code == 401
