"""Tests for the SELECTED SPECIALIST — the agent picker seam (feedback F3:
"can I use a specific agent if I want/need? now I cannot find this option").

Covers:
- the selectable list (nine base builtins, no model variants, matching the
  validator exactly, so the picker can never offer a rejected id);
- normalize_persona() validation (None/"" are "no selection", types, length,
  unknown ids, variant ids);
- render_persona_preamble() — no selection is a STRICT no-op (the acceptance
  criterion: default behaviour unchanged), a selection renders the delimited
  routing block naming the Task subagent_type;
- the chat entry-point wiring: the message handed to the SDK carries the block
  when a specialist is picked and is byte-identical to the user's text when it
  is not, while the PERSISTED user message is never modified;
- co-existence with the active data scope (both blocks present, order stable);
- an invalid id is rejected before the agent is ever touched;
- POST /api/query honours the same field; GET /api/personas shape.
"""

from unittest.mock import AsyncMock, patch

import pytest

from synapsis.agents import SUBAGENTS
from synapsis.persona import (
    AUDIENCE_TYPE,
    PersonaValidationError,
    audience_persona_ids,
    is_audience_persona,
    specialist_persona_ids,
    apply_persona_to_message,
    describe_persona,
    normalize_persona,
    persona_display_name,
    persona_is_empty,
    render_persona_preamble,
    selectable_persona_ids,
    selectable_personas,
)


# ---------------------------------------------------------------------------
# The selectable list
# ---------------------------------------------------------------------------

def test_selectable_ids_are_audience_personas_plus_base_builtins():
    ids = selectable_persona_ids()
    assert ids, "the picker must offer at least one specialist"
    assert ids == audience_persona_ids() + specialist_persona_ids()
    assert all(i in SUBAGENTS for i in specialist_persona_ids())
    assert not any(i in SUBAGENTS for i in audience_persona_ids())
    assert not any(
        i.endswith(("_opus_powerful", "_sonnet_efficient")) for i in ids
    ), "model variants are a legacy routing detail, not a user-facing choice"
    # The CGIAR domain specialists are the point of the feature.
    assert "prms_data_analyst" in ids
    assert "innovation_strategy_advisor" in ids


def test_selectable_ids_are_unique_and_stable_order():
    ids = selectable_persona_ids()
    assert len(ids) == len(set(ids))
    assert ids == selectable_persona_ids()


def test_selectable_personas_payload_shape():
    payload = selectable_personas()
    assert [p["id"] for p in payload] == selectable_persona_ids()
    for p in payload:
        assert {"id", "name", "description", "type", "color", "tags"} <= set(p)
        assert p["name"] and p["description"]
        assert isinstance(p["tags"], list)


def test_every_offered_id_is_accepted_by_the_validator():
    """The picker and the chat path cannot disagree — the whole bug class."""
    for p in selectable_personas():
        assert normalize_persona(p["id"]) == p["id"]


# ---------------------------------------------------------------------------
# normalize_persona
# ---------------------------------------------------------------------------

def test_none_and_empty_mean_no_selection():
    assert normalize_persona(None) == ""
    assert normalize_persona("") == ""
    assert normalize_persona("   ") == ""
    assert persona_is_empty(normalize_persona(None))


def test_known_id_is_accepted_and_trimmed():
    assert normalize_persona("  prms_data_analyst  ") == "prms_data_analyst"
    assert not persona_is_empty("prms_data_analyst")


def test_unknown_id_is_rejected():
    with pytest.raises(PersonaValidationError):
        normalize_persona("definitely_not_an_agent")


def test_variant_ids_are_not_selectable():
    # They exist in SUBAGENTS but are not offered, so they must not be accepted
    # from a client either — otherwise the picker and validator drift.
    assert "prms_data_analyst_opus_powerful" in SUBAGENTS
    with pytest.raises(PersonaValidationError):
        normalize_persona("prms_data_analyst_opus_powerful")


def test_non_string_and_overlong_are_rejected():
    with pytest.raises(PersonaValidationError):
        normalize_persona(123)
    with pytest.raises(PersonaValidationError):
        normalize_persona(["prms_data_analyst"])
    with pytest.raises(PersonaValidationError):
        normalize_persona("a" * 200)


# ---------------------------------------------------------------------------
# render_persona_preamble / apply_persona_to_message
# ---------------------------------------------------------------------------

def test_no_selection_is_a_strict_no_op():
    """THE acceptance criterion for F3: default behaviour unchanged."""
    assert render_persona_preamble("") == ""
    assert render_persona_preamble(None) == ""
    assert apply_persona_to_message("how many innovations in 2024?", "") == (
        "how many innovations in 2024?"
    )
    assert apply_persona_to_message("hi", None) == "hi"


def test_selection_renders_the_routing_block():
    block = render_persona_preamble("prms_data_analyst")
    assert block.startswith("[SELECTED SPECIALIST")
    assert block.rstrip().endswith("[END SELECTED SPECIALIST]")
    # The mechanical instruction W3 must be able to observe end to end.
    assert 'subagent_type="prms_data_analyst"' in block
    assert "Task tool" in block
    # Honesty clauses: name the specialist used; never silently reroute.
    assert "Name the specialist you used" in block
    assert "never silently reroute" in block
    # Standing data discipline survives the routing choice.
    assert "counting method" in block


def test_block_precedes_the_user_text():
    msg = apply_persona_to_message("list 2025 innovations", "prms_data_analyst")
    assert msg.index("[SELECTED SPECIALIST") < msg.index("list 2025 innovations")
    assert msg.endswith("list 2025 innovations")


def test_display_name_and_description():
    assert persona_display_name("prms_data_analyst") == "PRMS Data Analyst"
    assert describe_persona("") == "no specialist selected (orchestrator routes)"
    assert describe_persona("prms_data_analyst") == "PRMS Data Analyst (prms_data_analyst)"


def test_every_selectable_persona_renders_a_wellformed_block():
    for agent_id in specialist_persona_ids():
        block = render_persona_preamble(agent_id)
        assert f'subagent_type="{agent_id}"' in block
        assert block.rstrip().endswith("[END SELECTED SPECIALIST]")
    for persona_id in audience_persona_ids():
        block = render_persona_preamble(persona_id)
        assert block.startswith("[AUDIENCE PERSONA")
        assert block.rstrip().endswith("[END AUDIENCE PERSONA]")
        assert "subagent_type" not in block  # audience personas never route


# ---------------------------------------------------------------------------
# Audience personas — Marc's funder/investor and scientist skills (R-05/R-30),
# WB W2 "language … not relevant to non-CGIAR users" (R-26), Nikki "Trust" (R-28)
# ---------------------------------------------------------------------------

def test_the_two_audience_personas_are_offered_first():
    assert audience_persona_ids() == ["funder_investor", "scientist_researcher"]
    payload = selectable_personas()
    assert [p["id"] for p in payload[:2]] == ["funder_investor", "scientist_researcher"]
    names = {p["id"]: p["name"] for p in payload}
    assert names["funder_investor"] == "Funder / investor"
    assert names["scientist_researcher"] == "Scientist / researcher"
    for p in payload[:2]:
        assert p["type"] == AUDIENCE_TYPE
        assert "audience" in p["tags"]
        assert p["description"] and p["color"]


def test_audience_ids_are_accepted_and_named():
    for pid in ("funder_investor", "scientist_researcher"):
        assert normalize_persona(pid) == pid
        assert is_audience_persona(pid)
    assert not is_audience_persona("prms_data_analyst")
    assert persona_display_name("funder_investor") == "Funder / investor"
    assert describe_persona("scientist_researcher") == "Scientist / researcher (scientist_researcher)"


def _words(block: str) -> int:
    body = block.split("\n", 1)[1].rsplit("[END AUDIENCE PERSONA]", 1)[0]
    return len(body.split())


def test_funder_block_carries_marcs_concrete_behaviours():
    block = render_persona_preamble("funder_investor")
    low = block.lower()
    # entry branch: public funder vs private investor, asked once
    assert "public/institutional funder or a private investor" in block
    # vocabulary + figures + visuals change together
    for needle in ("vocabulary", "figures", "visual"):
        assert needle in low
    # silent translation of CGIAR jargon
    assert "translate silently" in low
    for jargon in ("IRL", "Scaling Readiness", "W1/W2"):
        assert jargon in block
    # readiness is not use
    assert "readiness is not deployment" in low
    # gaps shown, not dropped
    assert '"not yet reported"' in block and "never drop rows" in low
    # codes out of prose, links always kept via the Sources list
    assert "Sources" in block and "(R<code>)" in block and "public link" in block
    # USAID is not a current funder
    assert "USAID" in block and "not present USAID as a current" in block
    assert _words(block) <= 700


def test_scientist_block_carries_marcs_concrete_behaviours():
    block = render_persona_preamble("scientist_researcher")
    low = block.lower()
    assert "reviewing your own innovation" in low and "portfolio/bundle" in low
    assert "identical across all personas" in low
    assert "evidence tier" in low
    assert "field-definitions" in low and "structured export" in low
    for nudge in ("Bundling", "Enablers", "Demand", "Exit strategy"):
        assert f"**{nudge}**" in block
    assert "substitute, relocate, reorient, stop" in low
    assert "no hallucination" in low and "never construct a citation" in low
    assert _words(block) <= 700


def test_audience_block_keeps_standing_rules():
    for pid in audience_persona_ids():
        block = render_persona_preamble(pid)
        assert "counting method" in block
        assert "result-code citations" in block and "public links" in block
        assert "Sources list" in block


def test_audience_persona_reaches_the_sdk_message_but_not_the_history():
    msg = apply_persona_to_message("what is ready to scale in Kenya?", "funder_investor")
    assert msg.startswith("[AUDIENCE PERSONA — Funder / investor")
    assert msg.endswith("what is ready to scale in Kenya?")


def test_system_prompt_has_trust_citation_and_persona_rules():
    from synapsis.system_prompt import build_system_prompt

    prompt = build_system_prompt()
    # R-04: every result carries its public URL + a Sources list
    assert "reports/result-details/<code>?phase=<phase>" in prompt
    assert "**Sources**" in prompt
    assert "Only cite codes you actually retrieved" in prompt
    # R-28: data vs interpretation, light
    assert "From the PRMS data (snapshot" in prompt
    assert "**Interpretation:**" in prompt
    assert "From the web" in prompt
    # personas are opt-in; default voice unchanged
    assert "[AUDIENCE PERSONA" in prompt
    assert "Without such a block, keep the default voice" in prompt
    # the old "never link reporting.cgiar.org / dashboard only" rule is gone
    assert "Citations resolve ONLY to the public CGIAR Results Dashboard" not in prompt


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
async def test_sdk_message_carries_the_block_when_an_agent_is_picked():
    sdk_message, persisted, _ = await _run_handle_user_message(
        {"message": "how many innovations in 2024?", "agent": "prms_data_analyst"}
    )
    assert "[SELECTED SPECIALIST" in sdk_message
    assert 'subagent_type="prms_data_analyst"' in sdk_message
    assert sdk_message.endswith("how many innovations in 2024?")

    # The user's OWN message is persisted unmodified.
    user_rows = [d for (_, t, d) in persisted if t == "user"]
    assert user_rows == [{"content": "how many innovations in 2024?"}]


@pytest.mark.asyncio
async def test_sdk_message_is_byte_identical_without_a_pick():
    """Default routing must be exactly what shipped before the picker."""
    sdk_message, _, _ = await _run_handle_user_message({"message": "hello"})
    assert sdk_message == "hello"

    for empty in (None, "", "   "):
        msg, _, _ = await _run_handle_user_message({"message": "hello", "agent": empty})
        assert msg == "hello"


@pytest.mark.asyncio
async def test_persona_and_scope_compose():
    sdk_message, _, _ = await _run_handle_user_message(
        {
            "message": "how many innovations?",
            "agent": "prms_data_analyst",
            "scope": {"years": [2024], "programs": ["SP09 — Scaling for Impact"]},
        }
    )
    # Both blocks present, persona outermost, user text last.
    assert sdk_message.index("[SELECTED SPECIALIST") < sdk_message.index("[ACTIVE DATA SCOPE")
    assert sdk_message.index("[ACTIVE DATA SCOPE") < sdk_message.index("how many innovations?")
    assert sdk_message.endswith("how many innovations?")


@pytest.mark.asyncio
async def test_invalid_agent_is_rejected_before_reaching_the_agent():
    with pytest.raises(ValueError):
        await _run_handle_user_message({"message": "hi", "agent": "not_an_agent"})


@pytest.mark.asyncio
async def test_invalid_agent_tells_the_user_why():
    from synapsis.handlers import chat_handlers

    sent: list[dict] = []

    async def _send_json(data, sid=None):
        sent.append(data)

    with pytest.raises(ValueError):
        await chat_handlers.handle_user_message(
            {"message": "hi", "agent": "not_an_agent"}, "sid-1", _send_json
        )

    assert sent and sent[0]["type"] == "error"
    assert "Invalid agent selection" in sent[0]["message"]


# ---------------------------------------------------------------------------
# REST surfaces
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_personas_endpoint_shape(researcher_client):
    # Any signed-in user (the persona picker); auth is enforced in the suite.
    resp = await researcher_client.get("/api/personas")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default"] is None, "no selection is the default"
    ids = [p["id"] for p in body["personas"]]
    assert ids == selectable_persona_ids()
    assert ids[:2] == ["funder_investor", "scientist_researcher"]
    for p in body["personas"]:
        assert {"id", "name", "description", "type", "color", "tags"} <= set(p)


@pytest.mark.asyncio
async def test_personas_endpoint_requires_sign_in(test_client):
    assert (await test_client.get("/api/personas")).status_code == 401


@pytest.mark.asyncio
async def test_api_query_rejects_an_unknown_agent(researcher_client):
    resp = await researcher_client.post(
        "/api/query", json={"message": "hi", "agent": "not_an_agent"}
    )
    assert resp.status_code == 422
    assert "Invalid agent selection" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_audience_persona_wiring_keeps_the_persisted_message_clean():
    sdk_message, persisted, _ = await _run_handle_user_message(
        {"message": "which innovations are ready to scale?", "agent": "funder_investor"}
    )
    assert sdk_message.startswith("[AUDIENCE PERSONA — Funder / investor")
    assert "subagent_type" not in sdk_message
    assert sdk_message.endswith("which innovations are ready to scale?")
    user_rows = [d for (_, t, d) in persisted if t == "user"]
    assert user_rows == [{"content": "which innovations are ready to scale?"}]
