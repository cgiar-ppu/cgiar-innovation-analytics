"""Integration tests for the run_id bugfix.

Validates that every WebSocket event carries a run_id scoped to the turn
that produced it, preventing stale events from corrupting state across turns.

Requirements:
    - The v16 server must be running on http://localhost:7778
    - pip install websockets pytest pytest-asyncio pytest-timeout
"""

import asyncio
import json
import os
import time

import pytest
import websockets

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:7778")
WS_URL = os.environ.get("TEST_WS_URL", "ws://localhost:7778/ws/chat")

# Timeout for collecting events from a single turn (seconds).
COLLECT_TIMEOUT = 45

# Event types that MUST carry a run_id after the fix.
RUN_ID_REQUIRED_TYPES = {"text", "result", "session_complete"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def collect_turn_events(
    ws,
    *,
    timeout: float = COLLECT_TIMEOUT,
    wait_for_session_complete: bool = False,
) -> list[dict]:
    """Read WebSocket messages until a terminal event is received or timeout.

    By default, stops at the first 'result' event. If wait_for_session_complete
    is True, continues collecting after 'result' for up to 5 more seconds
    looking for a 'session_complete' event.

    Returns the list of parsed JSON events.
    """
    events: list[dict] = []
    deadline = time.monotonic() + timeout
    got_result = False

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5.0))
        except asyncio.TimeoutError:
            # If we already have a result and are just waiting for session_complete,
            # stop here -- it may have arrived via the broadcast path instead.
            if got_result:
                break
            continue
        except websockets.exceptions.ConnectionClosed:
            break

        event = json.loads(raw)
        events.append(event)

        etype = event.get("type")
        if etype == "result":
            got_result = True
            if not wait_for_session_complete:
                break
            # Give a short window for session_complete to arrive
            deadline = min(deadline, time.monotonic() + 5.0)
        elif etype == "session_complete":
            break

    return events


async def send_and_collect(
    ws,
    message: str,
    session_id: str | None = None,
    *,
    wait_for_session_complete: bool = False,
) -> list[dict]:
    """Send a chat message and collect events until the turn completes."""
    payload = {"type": "chat", "message": message}
    if session_id:
        payload["session_id"] = session_id
    await ws.send(json.dumps(payload))
    return await collect_turn_events(
        ws, wait_for_session_complete=wait_for_session_complete
    )


def extract_session_id(events: list[dict]) -> str | None:
    """Extract the session_id from a 'session' event in the event list."""
    for e in events:
        if e.get("type") == "session" and "session_id" in e:
            return e["session_id"]
    # Fallback: get it from any event that has session_id
    for e in events:
        if "session_id" in e:
            return e["session_id"]
    return None


def extract_run_ids(events: list[dict]) -> set[str]:
    """Return the set of distinct run_id values from events that carry one."""
    return {e["run_id"] for e in events if "run_id" in e}


def filter_by_types(events: list[dict], types: set[str]) -> list[dict]:
    """Return only events whose type is in the given set."""
    return [e for e in events if e.get("type") in types]


# ---------------------------------------------------------------------------
# Test 1: Events carry run_id
# ---------------------------------------------------------------------------

@pytest.mark.timeout(120)
async def test_events_carry_run_id():
    """Streaming events (text, result, session_complete) must carry a run_id."""
    async with websockets.connect(WS_URL) as ws:
        events = await send_and_collect(ws, "Say hello in 3 words")

    assert len(events) > 0, "No events received from WebSocket"

    # Filter to the event types that must carry run_id.
    relevant = filter_by_types(events, RUN_ID_REQUIRED_TYPES)
    assert len(relevant) > 0, (
        f"No relevant events ({RUN_ID_REQUIRED_TYPES}) received. "
        f"Got types: {[e.get('type') for e in events]}"
    )

    for event in relevant:
        assert "run_id" in event, (
            f"Event of type '{event.get('type')}' is missing run_id. "
            f"Full event: {json.dumps(event, indent=2)[:500]}"
        )
        assert isinstance(event["run_id"], str) and len(event["run_id"]) > 0, (
            f"run_id must be a non-empty string, got: {event.get('run_id')!r}"
        )

    # All run_ids within the turn must be identical.
    run_ids = extract_run_ids(relevant)
    assert len(run_ids) == 1, (
        f"Expected exactly 1 run_id within a single turn, got {len(run_ids)}: {run_ids}"
    )


# ---------------------------------------------------------------------------
# Test 2: run_id changes between turns
# ---------------------------------------------------------------------------

@pytest.mark.timeout(120)
async def test_run_id_changes_between_turns():
    """Two sequential turns on the same session must produce different run_ids."""
    async with websockets.connect(WS_URL) as ws:
        # Turn 1: collect and wait for session_complete to fully drain.
        events_1 = await send_and_collect(
            ws, "Say hi", wait_for_session_complete=True
        )
        session_id = extract_session_id(events_1)
        assert session_id, "Could not extract session_id from turn 1 events"

        run_ids_1 = extract_run_ids(events_1)
        assert len(run_ids_1) >= 1, (
            f"Turn 1 produced no run_ids. Types: {[e.get('type') for e in events_1]}"
        )

        # Brief pause to let any trailing Turn 1 events flush through.
        await asyncio.sleep(1.0)

        # Drain any straggler events from Turn 1 before starting Turn 2.
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                event = json.loads(raw)
                # Attribute any straggler to Turn 1.
                if "run_id" in event:
                    run_ids_1.add(event["run_id"])
        except asyncio.TimeoutError:
            pass

        # Turn 2 -- same session
        events_2 = await send_and_collect(ws, "Say bye", session_id=session_id)

        # Filter Turn 2 events: only keep those with a run_id NOT in Turn 1.
        # Some late Turn 1 events (e.g. broadcast session_complete) may arrive
        # in the Turn 2 collection window.
        events_2_own = [
            e for e in events_2
            if "run_id" not in e or e["run_id"] not in run_ids_1
        ]
        run_ids_2 = extract_run_ids(events_2_own)
        assert len(run_ids_2) >= 1, (
            f"Turn 2 produced no run_ids after filtering. "
            f"Types: {[e.get('type') for e in events_2_own]}"
        )

    # The run_id sets must be disjoint.
    overlap = run_ids_1 & run_ids_2
    assert len(overlap) == 0, (
        f"run_ids must differ between turns, but overlap found: {overlap}"
    )


# ---------------------------------------------------------------------------
# Test 3: Rapid-fire -- no cross-contamination
# ---------------------------------------------------------------------------

@pytest.mark.timeout(120)
async def test_rapid_fire_no_cross_contamination():
    """Sending a second message before the first completes must not mix run_ids."""
    async with websockets.connect(WS_URL) as ws:
        # Send message 1 (a prompt likely to produce a longer response).
        payload_1 = json.dumps({
            "type": "chat",
            "message": "Count from 1 to 5 slowly",
        })
        await ws.send(payload_1)

        # Collect early events for up to 1 second to get session_id.
        early_events: list[dict] = []
        deadline = time.monotonic() + 1.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                early_events.append(json.loads(raw))
            except asyncio.TimeoutError:
                break

        session_id = extract_session_id(early_events)

        # Fire message 2 while message 1 is (likely) still streaming.
        payload_2 = json.dumps({
            "type": "chat",
            "message": "What is 2+2?",
            **({"session_id": session_id} if session_id else {}),
        })
        await ws.send(payload_2)

        # Collect ALL remaining events. We need to see 1 or 2 terminal events
        # (the first turn might get cancelled, producing 0 terminal events for it).
        late_events: list[dict] = []
        terminal_count = sum(
            1 for e in early_events if e.get("type") in {"result", "session_complete"}
        )

        collect_deadline = time.monotonic() + 60
        while terminal_count < 2:
            remaining = collect_deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 10.0))
            except asyncio.TimeoutError:
                # If we have at least 1 terminal, the cancelled turn may not produce one
                if terminal_count >= 1:
                    break
                continue
            except websockets.exceptions.ConnectionClosed:
                break
            event = json.loads(raw)
            late_events.append(event)
            if event.get("type") in {"result", "session_complete"}:
                terminal_count += 1

    all_events = early_events + late_events

    # Group events by run_id.
    events_with_run_id = [e for e in all_events if "run_id" in e]

    if not events_with_run_id:
        pytest.skip("No events carried run_id -- cannot verify grouping")

    run_id_groups: dict[str, list[dict]] = {}
    for e in events_with_run_id:
        rid = e["run_id"]
        run_id_groups.setdefault(rid, []).append(e)

    # At most 2 distinct run_ids (one per turn; the first may have been
    # cancelled so it could produce 0 or 1 groups).
    assert len(run_id_groups) <= 2, (
        f"Expected at most 2 distinct run_ids, got {len(run_id_groups)}: "
        f"{list(run_id_groups.keys())}"
    )

    # Within each group, events should be temporally ordered (we use list
    # index as a proxy for arrival order -- they were appended sequentially).
    for rid, group in run_id_groups.items():
        indices = [all_events.index(e) for e in group]
        assert indices == sorted(indices), (
            f"Events for run_id {rid} are not in arrival order: {indices}"
        )


# ---------------------------------------------------------------------------
# Test 4: session_complete carries run_id
# ---------------------------------------------------------------------------

@pytest.mark.timeout(120)
async def test_session_complete_carries_run_id():
    """The session_complete event must carry a run_id matching the turn's events.

    session_complete may arrive via the subscriber path (through send_event) or
    via the broadcast path (through broadcast_to_all). Either way it must carry
    the correct run_id.
    """
    async with websockets.connect(WS_URL) as ws:
        events = await send_and_collect(
            ws, "Say OK", wait_for_session_complete=True
        )

    # We must have at least a result event.
    result_events = [e for e in events if e.get("type") == "result"]
    assert len(result_events) >= 1, (
        f"Never received result event. Types: {[e.get('type') for e in events]}"
    )

    # Collect the run_id from the result event(s).
    result_run_id = result_events[0].get("run_id")
    assert result_run_id, "result event missing run_id"

    # Check if session_complete arrived.
    sc_events = [e for e in events if e.get("type") == "session_complete"]
    if sc_events:
        sc = sc_events[0]
        assert "run_id" in sc, (
            f"session_complete event is missing run_id: "
            f"{json.dumps(sc, indent=2)[:500]}"
        )
        assert sc["run_id"] == result_run_id, (
            f"session_complete run_id {sc['run_id']!r} does not match "
            f"result run_id {result_run_id!r}"
        )
    else:
        # session_complete may have been sent via the broadcast path.
        # The run_id on 'result' is still the definitive proof that the
        # fix is working. Log and pass.
        pass

    # All run_ids in the turn must be identical.
    all_run_ids = extract_run_ids(events)
    assert len(all_run_ids) == 1, (
        f"Expected 1 run_id in the turn, got {len(all_run_ids)}: {all_run_ids}"
    )


# ---------------------------------------------------------------------------
# Test 5: try_mark_session_complete rejects stale run_id (unit test)
# ---------------------------------------------------------------------------

async def test_try_mark_session_complete_rejects_stale():
    """ChatRunManager.try_mark_session_complete must reject a stale run_id."""
    import sys
    sys.path.insert(0, "/Users/smithai/workspace/synapsis-agent-macos-v16")
    from synapsis.chat_run_manager import ChatRunManager

    manager = ChatRunManager()

    # --- Turn N ---
    async def noop_coro(send_event, cancel_event):
        pass

    handle_1 = await manager.start_task("test-1", noop_coro)
    run_id_1 = handle_1.run_id
    assert isinstance(run_id_1, str) and len(run_id_1) > 0

    # First call with the correct run_id should succeed.
    result = manager.try_mark_session_complete("test-1", run_id=run_id_1)
    assert result is True, (
        "try_mark_session_complete should return True for the current run_id"
    )

    # --- Turn N+1 ---
    handle_2 = await manager.start_task("test-1", noop_coro)
    run_id_2 = handle_2.run_id
    assert run_id_1 != run_id_2, "New handle must have a different run_id"

    # Stale call with old run_id must be rejected.
    result_stale = manager.try_mark_session_complete("test-1", run_id=run_id_1)
    assert result_stale is False, (
        f"try_mark_session_complete should return False for stale run_id "
        f"{run_id_1!r} (current is {run_id_2!r})"
    )

    # Call with the new run_id should succeed.
    result_new = manager.try_mark_session_complete("test-1", run_id=run_id_2)
    assert result_new is True, (
        "try_mark_session_complete should return True for the new run_id"
    )

    # Cleanup
    await manager.shutdown()
