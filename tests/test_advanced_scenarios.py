"""
Advanced integration tests for the chat desync fix.

Tests the hard edge cases:
1. Session switching mid-stream (unsubscribe/resubscribe)
2. Multiple concurrent sessions streaming simultaneously
3. Two "devices" (WebSocket connections) on the same session
4. Reproducing the original bug: stale session_complete from Turn N during Turn N+1
5. Rapid session switch while streaming (detach mid-stream, reattach)
6. Cancel mid-stream and immediate new message
7. Broadcast session_complete carries run_id
8. Cross-turn guard with real server handles

All tests run against the live v16 server on port 7778.
"""

import asyncio
import json
import os
import time

import httpx
import pytest
import websockets

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:7778")
WS_URL = os.environ.get("TEST_WS_URL", "ws://localhost:7778/ws/chat")
TIMEOUT = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def ws_new_session(ws) -> str:
    """Send new_session on a WebSocket, return the session_id."""
    await ws.send(json.dumps({"type": "new_session"}))
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            event = json.loads(raw)
            if event.get("type") == "session" and event.get("session_id"):
                return event["session_id"]
        except asyncio.TimeoutError:
            continue
    raise RuntimeError("Failed to create session: no session event received")


async def ws_switch_session(ws, session_id: str) -> list:
    """Send switch_session, drain events until session ack, return events."""
    await ws.send(json.dumps({"type": "switch_session", "session_id": session_id}))
    events = []
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
            ev = json.loads(raw)
            events.append(ev)
            if ev.get("type") == "session" and ev.get("session_id") == session_id:
                break
            if ev.get("type") == "buffer_replay_end":
                break
    except asyncio.TimeoutError:
        pass
    return events


async def send_chat(ws, session_id: str, message: str):
    """Send a chat message over WebSocket."""
    await ws.send(json.dumps({
        "type": "message",
        "message": message,
        "session_id": session_id,
    }))


async def collect_events(ws, *, until_types=None, timeout=TIMEOUT, max_events=500):
    """Collect events until we see one of the specified types or timeout."""
    if until_types is None:
        until_types = {"result", "session_complete"}
    events = []
    deadline = time.time() + timeout
    while time.time() < deadline and len(events) < max_events:
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 5.0))
            event = json.loads(raw)
            events.append(event)
            if event.get("type") in until_types:
                # Drain trailing events briefly
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                        events.append(json.loads(raw))
                except asyncio.TimeoutError:
                    pass
                break
        except asyncio.TimeoutError:
            continue
    return events


async def drain_events(ws, timeout=3.0):
    """Drain pending events from a WebSocket."""
    events = []
    try:
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            events.append(json.loads(raw))
    except asyncio.TimeoutError:
        pass
    return events


def extract_run_ids(events, session_id=None):
    """Extract unique run_ids from events."""
    run_ids = set()
    for e in events:
        if session_id and e.get("session_id") != session_id:
            continue
        rid = e.get("run_id")
        if rid:
            run_ids.add(rid)
    return run_ids


def events_by_type(events, event_type, session_id=None):
    """Filter events by type and optionally session_id."""
    return [
        e for e in events
        if e.get("type") == event_type
        and (session_id is None or e.get("session_id") == session_id)
    ]


# ---------------------------------------------------------------------------
# Test 1: Session switching mid-stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_session_switch_mid_stream():
    """
    Start streaming on Session A, switch_session to B mid-stream,
    send on B, then switch back to A.

    Uses switch_session (like the real frontend) which properly detaches
    from the old session's ChatRunManager task, allowing it to continue
    independently in the background.

    Verifies:
    - Session B gets its own events with distinct run_id
    - No cross-session text leakage
    - Session A's task completes in the background
    """
    # Pre-create both sessions on temporary connections
    async with websockets.connect(WS_URL) as ws_setup:
        session_a = await ws_new_session(ws_setup)
    async with websockets.connect(WS_URL) as ws_setup:
        session_b = await ws_new_session(ws_setup)

    async with websockets.connect(WS_URL) as ws:
        # Switch to Session A
        await ws_switch_session(ws, session_a)

        # Start a message on Session A
        await send_chat(ws, session_a, "Count from 1 to 10, one number per line")

        # Collect a few events (wait for at least one text event)
        partial_a = []
        try:
            for _ in range(15):
                raw = await asyncio.wait_for(ws.recv(), timeout=8.0)
                ev = json.loads(raw)
                partial_a.append(ev)
                if ev.get("type") == "text":
                    break
        except asyncio.TimeoutError:
            pass

        assert any(e.get("type") == "text" for e in partial_a), \
            f"Expected text from A, got: {[e.get('type') for e in partial_a]}"

        # Switch to Session B (detaches from A's ChatRunManager task)
        await ws_switch_session(ws, session_b)

        # Send a message on Session B
        await send_chat(ws, session_b, "Say 'BANANA' exactly once")
        events_b = await collect_events(ws, until_types={"result", "session_complete"})

        # Verify B events have their own run_id
        run_ids_b = extract_run_ids(events_b, session_b)
        assert len(run_ids_b) >= 1, "Session B should have at least one run_id"

        # Verify no Session A text events leaked into B's collection
        for e in events_b:
            if e.get("type") == "text" and e.get("session_id"):
                assert e["session_id"] != session_a, \
                    f"Session A text leaked into B: {e}"

        # Poll for Session A completion in background
        async with httpx.AsyncClient() as client:
            for _ in range(25):  # Up to 50 seconds
                await asyncio.sleep(2)
                resp = await client.get(f"{BASE_URL}/api/sessions")
                sessions_list = resp.json().get("sessions", [])
                sess_a = next((s for s in sessions_list if s["session_id"] == session_a), None)
                if sess_a and sess_a.get("task_status") != "running":
                    break

            resp = await client.get(f"{BASE_URL}/api/history", params={"session_id": session_a})
            history = resp.json().get("messages", [])

        assistant_msgs = [m for m in history if m.get("type") in ("text", "assistant")]
        assert len(assistant_msgs) > 0, \
            f"Session A should have completed in background. History roles: {[m.get('type') for m in history]}"

    print(f"✅ Session switch mid-stream: A={session_a}, B={session_b}")
    print(f"   B run_ids: {run_ids_b}, A history msgs: {len(assistant_msgs)}")


# ---------------------------------------------------------------------------
# Test 2: Multiple concurrent sessions (two WebSocket connections)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multiple_concurrent_sessions():
    """
    Two WebSocket connections each streaming on different sessions.

    Verifies:
    - Both get responses
    - Events are tagged with correct session_id
    - run_ids are distinct between sessions
    """
    async with websockets.connect(WS_URL) as ws1, \
               websockets.connect(WS_URL) as ws2:

        session_a = await ws_new_session(ws1)
        session_b = await ws_new_session(ws2)

        # Start both sessions concurrently
        await send_chat(ws1, session_a, "Say 'ALPHA' exactly once")
        await send_chat(ws2, session_b, "Say 'BETA' exactly once")

        # Collect events from both
        events_a, events_b = await asyncio.gather(
            collect_events(ws1, until_types={"result", "session_complete"}),
            collect_events(ws2, until_types={"result", "session_complete"}),
        )

        assert len(events_a) > 0, "Session A should have events"
        assert len(events_b) > 0, "Session B should have events"

        # Events should be tagged correctly
        for e in events_a:
            if e.get("session_id") and e.get("type") in ("text", "result"):
                assert e["session_id"] == session_a, \
                    f"WS1 got wrong session: {e['session_id']}"

        for e in events_b:
            if e.get("session_id") and e.get("type") in ("text", "result"):
                assert e["session_id"] == session_b, \
                    f"WS2 got wrong session: {e['session_id']}"

        # run_ids should be distinct
        run_ids_a = extract_run_ids(events_a, session_a)
        run_ids_b = extract_run_ids(events_b, session_b)
        if run_ids_a and run_ids_b:
            assert run_ids_a.isdisjoint(run_ids_b), \
                f"Run IDs should be distinct: A={run_ids_a}, B={run_ids_b}"

    print(f"✅ Multiple concurrent sessions: A={session_a}, B={session_b}")
    print(f"   A run_ids: {run_ids_a}, B run_ids: {run_ids_b}")


# ---------------------------------------------------------------------------
# Test 3: Two devices on the same session
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_two_devices_same_session():
    """
    Two WebSocket connections viewing the same session.
    One sends a message, both should see events.

    Verifies:
    - Sender gets full streaming events
    - Viewer gets at least broadcast notifications
    - session_complete broadcasts carry run_id
    """
    async with websockets.connect(WS_URL) as ws_sender, \
               websockets.connect(WS_URL) as ws_viewer:

        # Sender creates a session
        session_id = await ws_new_session(ws_sender)

        # Viewer switches to the same session
        await ws_switch_session(ws_viewer, session_id)

        # Sender sends a message
        await send_chat(ws_sender, session_id, "Say 'SHARED' exactly once")

        # Collect from both
        sender_task = asyncio.create_task(
            collect_events(ws_sender, until_types={"result", "session_complete"})
        )
        viewer_task = asyncio.create_task(
            collect_events(ws_viewer, until_types={"result", "session_complete", "sessions_changed"})
        )

        sender_events, viewer_events = await asyncio.gather(sender_task, viewer_task)

        # Sender should have streaming events
        sender_text = events_by_type(sender_events, "text")
        assert len(sender_text) > 0, "Sender should receive text events"

        sender_results = events_by_type(sender_events, "result")
        assert len(sender_results) > 0, "Sender should receive result"
        for r in sender_results:
            assert r.get("run_id"), f"Result should have run_id: {r}"

        # Viewer should receive something
        viewer_types = {e.get("type") for e in viewer_events}
        print(f"   Viewer event types: {viewer_types}")

        has_notification = bool(
            viewer_types & {"sessions_changed", "session_complete", "text", "result"}
        )
        assert has_notification, f"Viewer should get notifications, got: {viewer_types}"

        # Any session_complete from viewer should carry run_id
        for sc in events_by_type(viewer_events, "session_complete"):
            assert sc.get("run_id"), f"Viewer's session_complete should have run_id: {sc}"

    print(f"✅ Two devices same session: {session_id}")
    print(f"   Sender events: {len(sender_events)}, Viewer events: {len(viewer_events)}")


# ---------------------------------------------------------------------------
# Test 4: Reproduce the original bug — stale session_complete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stale_session_complete_rejected():
    """
    The core desync scenario:
    1. Turn N → complete → capture run_id_N
    2. Turn N+1 → complete → capture run_id_N+1
    3. Verify run_id_N ≠ run_id_N+1
    4. Verify ALL Turn N+1 events carry run_id_N+1 (no stale leakage)
    5. Verify session_complete is properly scoped
    """
    async with websockets.connect(WS_URL) as ws:
        session_id = await ws_new_session(ws)

        # --- Turn N ---
        await send_chat(ws, session_id, "Say 'TURN_N' exactly once")
        events_n = await collect_events(ws, until_types={"result", "session_complete"})

        run_ids_n = extract_run_ids(events_n, session_id)
        assert len(run_ids_n) >= 1, f"Turn N needs run_id. Events: {[e.get('type') for e in events_n]}"
        run_id_n = next(iter(run_ids_n))

        # Verify session_complete from Turn N has correct run_id
        for sc in events_by_type(events_n, "session_complete", session_id):
            assert sc.get("run_id") == run_id_n, \
                f"Turn N session_complete run_id mismatch: {sc.get('run_id')} != {run_id_n}"

        # Drain stragglers
        stragglers = await drain_events(ws, timeout=4)

        # --- Turn N+1 ---
        await send_chat(ws, session_id, "Say 'TURN_N_PLUS_1' exactly once")
        events_n1 = await collect_events(ws, until_types={"result", "session_complete"})

        run_ids_n1 = extract_run_ids(events_n1, session_id)
        assert len(run_ids_n1) >= 1, "Turn N+1 needs run_id"
        run_id_n1 = next(iter(run_ids_n1))

        # CRITICAL: different run_ids
        assert run_id_n != run_id_n1, \
            f"Turns must have different run_ids: {run_id_n} vs {run_id_n1}"

        # ALL Turn N+1 events should carry the new run_id
        for e in events_n1:
            if e.get("run_id") and e.get("session_id") == session_id:
                assert e["run_id"] == run_id_n1, \
                    f"Stale event in Turn N+1: type={e.get('type')}, run_id={e['run_id']}"

    print(f"✅ Stale session_complete rejected: session={session_id}")
    print(f"   Turn N: {run_id_n}, Turn N+1: {run_id_n1}")
    print(f"   Stragglers: {len(stragglers)}")


# ---------------------------------------------------------------------------
# Test 5: Rapid-fire with session switch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rapid_fire_with_session_switch():
    """
    1. Start message on A
    2. Before completion, switch_session to B
    3. Send on B
    4. Verify no cross-session contamination
    5. Verify A completes in background

    Uses switch_session (like the real frontend) for proper detach semantics.
    """
    # Pre-create both sessions
    async with websockets.connect(WS_URL) as ws_setup:
        session_a = await ws_new_session(ws_setup)
    async with websockets.connect(WS_URL) as ws_setup:
        session_b = await ws_new_session(ws_setup)

    async with websockets.connect(WS_URL) as ws:
        # Start on Session A
        await ws_switch_session(ws, session_a)

        # Send a message on A (don't wait for completion)
        await send_chat(ws, session_a, "Write a haiku about the ocean")

        # Wait for streaming to start
        got_text = False
        try:
            for _ in range(15):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                ev = json.loads(raw)
                if ev.get("type") == "text":
                    got_text = True
                    break
        except asyncio.TimeoutError:
            pass

        # Switch to Session B while A is still streaming
        await ws_switch_session(ws, session_b)

        # Send on Session B
        await send_chat(ws, session_b, "Say 'BRAVO' exactly once")
        events_b = await collect_events(ws, until_types={"result", "session_complete"})

        # Verify B events are clean (no A leakage)
        for e in events_b:
            if e.get("type") in ("text", "tool_use", "result") and e.get("session_id"):
                assert e["session_id"] == session_b, \
                    f"Session A leaked into B: type={e.get('type')}, sid={e.get('session_id')}"

        run_ids_b = extract_run_ids(events_b, session_b)

        # Poll for Session A to complete in background
        async with httpx.AsyncClient() as client:
            for _ in range(25):
                await asyncio.sleep(2)
                resp = await client.get(f"{BASE_URL}/api/sessions")
                sessions_list = resp.json().get("sessions", [])
                sess_a = next((s for s in sessions_list if s["session_id"] == session_a), None)
                if sess_a and sess_a.get("task_status") != "running":
                    break

            resp = await client.get(f"{BASE_URL}/api/history", params={"session_id": session_a})
            history_a = resp.json().get("messages", [])

        assistant_msgs_a = [m for m in history_a if m.get("type") in ("text", "assistant")]
        assert len(assistant_msgs_a) > 0, \
            f"Session A should have completed in background. History roles: {[m.get('type') for m in history_a]}"

    print(f"✅ Rapid-fire with session switch: A={session_a}, B={session_b}")
    print(f"   Got text from A: {got_text}, B run_ids: {run_ids_b}")
    print(f"   A background msgs: {len(assistant_msgs_a)}")


# ---------------------------------------------------------------------------
# Test 6: Cross-turn guard with real server
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_turn_guard_realistic():
    """
    Two turns on the same session, verify run_ids differ and no cross-contamination.
    """
    async with websockets.connect(WS_URL) as ws:
        session_id = await ws_new_session(ws)

        # Turn 1
        await send_chat(ws, session_id, "Say 'ONE'")
        events_1 = await collect_events(ws, until_types={"result", "session_complete"})
        run_ids_1 = extract_run_ids(events_1, session_id)
        assert len(run_ids_1) >= 1
        rid_1 = next(iter(run_ids_1))

        await drain_events(ws, timeout=4)

        # Turn 2
        await send_chat(ws, session_id, "Say 'TWO'")
        events_2 = await collect_events(ws, until_types={"result", "session_complete"})
        run_ids_2 = extract_run_ids(events_2, session_id)
        assert len(run_ids_2) >= 1
        rid_2 = next(iter(run_ids_2))

        # Different run_ids
        assert rid_1 != rid_2, f"Expected different run_ids: {rid_1} vs {rid_2}"

        # No Turn 1 events in Turn 2
        for e in events_2:
            if e.get("run_id") and e.get("session_id") == session_id:
                assert e["run_id"] == rid_2, \
                    f"Stale Turn 1 event: type={e.get('type')}, run_id={e['run_id']}"

    print(f"✅ Cross-turn guard: Turn1={rid_1}, Turn2={rid_2}")


# ---------------------------------------------------------------------------
# Test 7: Broadcast session_complete carries run_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broadcast_session_complete_has_run_id():
    """
    Verify the broadcast path (not subscriber path) includes run_id.
    Observer WS doesn't switch to the session — it gets broadcast_to_all.
    """
    async with websockets.connect(WS_URL) as ws_active, \
               websockets.connect(WS_URL) as ws_observer:

        session_id = await ws_new_session(ws_active)

        # Observer just listens globally (no switch_session)
        await drain_events(ws_observer, timeout=2)

        # Active sends a message
        await send_chat(ws_active, session_id, "Say 'BROADCAST_TEST'")

        # Collect from active
        active_events = await collect_events(
            ws_active, until_types={"result", "session_complete"}
        )

        # Collect from observer
        observer_events = await drain_events(ws_observer, timeout=8)

        # Active should have result with run_id
        active_results = events_by_type(active_events, "result")
        assert len(active_results) > 0
        active_run_id = active_results[0].get("run_id")
        assert active_run_id, "Active result should have run_id"

        # Check observer's session_complete (if any)
        observer_completes = events_by_type(observer_events, "session_complete")
        if observer_completes:
            for sc in observer_completes:
                assert sc.get("run_id"), f"Broadcast session_complete needs run_id: {sc}"
                if sc.get("session_id") == session_id:
                    assert sc["run_id"] == active_run_id, \
                        f"Broadcast run_id mismatch: {sc['run_id']} != {active_run_id}"
            print(f"   Observer got {len(observer_completes)} session_complete with run_id ✓")
        else:
            # Subscriber path won the race → broadcast was skipped (correct behavior)
            print("   Observer got 0 session_complete (subscriber won race — correct)")

        observer_types = [e.get("type") for e in observer_events]
        print(f"   Observer types: {observer_types}")

    print(f"✅ Broadcast run_id: session={session_id}, run_id={active_run_id}")


# ---------------------------------------------------------------------------
# Test 8: Cancel mid-stream and immediate new message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_and_immediate_new_message():
    """
    1. Start a long task
    2. Cancel mid-stream
    3. Immediately send a new message
    4. Verify no leaked events from cancelled run
    """
    async with websockets.connect(WS_URL) as ws:
        session_id = await ws_new_session(ws)

        # Start a long task
        await send_chat(ws, session_id, "Write a very detailed essay about climate change, at least 500 words")

        # Wait for streaming to start
        pre_cancel = []
        try:
            for _ in range(20):
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                ev = json.loads(raw)
                pre_cancel.append(ev)
                if ev.get("type") == "text":
                    break
        except asyncio.TimeoutError:
            pass

        cancelled_run_ids = extract_run_ids(pre_cancel, session_id)

        # Cancel
        await ws.send(json.dumps({"type": "cancel", "session_id": session_id}))
        cancel_events = await drain_events(ws, timeout=5)

        # Immediately send new message
        await send_chat(ws, session_id, "Say 'AFTER_CANCEL' exactly once")
        new_events = await collect_events(ws, until_types={"result", "session_complete"})

        new_run_ids = extract_run_ids(new_events, session_id)
        assert len(new_run_ids) >= 1, "New message should have a run_id"

        # Different run_ids
        if cancelled_run_ids:
            assert new_run_ids.isdisjoint(cancelled_run_ids), \
                f"New run should differ from cancelled: new={new_run_ids}, cancelled={cancelled_run_ids}"

        # No cancelled events in new run
        for e in new_events:
            if e.get("run_id") and e.get("session_id") == session_id:
                assert e["run_id"] not in cancelled_run_ids, \
                    f"Cancelled event leaked: type={e.get('type')}, run_id={e['run_id']}"

    print(f"✅ Cancel + new message: session={session_id}")
    print(f"   Cancelled run_ids: {cancelled_run_ids}, New: {new_run_ids}")
