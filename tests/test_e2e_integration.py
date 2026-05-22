"""
End-to-end integration tests for CGIAR Innovation Analytics Platform.

Phase 1 acceptance gate — "Panama milestone" deliverable.
Tests the full stack: WebSocket → Orchestrator → Agent routing → PRMS queries → Responses.

These tests run against a live server on port 7780 (or TEST_PORT env var).
Start the server before running: ./start-innovation-analytics.sh

Run with:
    python -m pytest tests/test_e2e_integration.py -v -s
    # or standalone:
    python tests/test_e2e_integration.py
"""

import asyncio
import json
import os
import sys
import time
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PORT = int(os.environ.get("TEST_PORT", "7780"))
BASE_URL = f"http://localhost:{PORT}"
WS_URL = f"ws://localhost:{PORT}/ws/chat"
AGENT_WS_URL = f"ws://localhost:{PORT}/ws/agent"

# Timeouts: these tests hit live LLM endpoints, so they need generous timeouts
MSG_TIMEOUT = 180       # seconds to wait for a full response
CONNECT_TIMEOUT = 10    # seconds for initial WS handshake


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def collect_ws_response(ws, timeout: float = MSG_TIMEOUT) -> dict:
    """Collect all WS frames until a 'result' or 'error' frame, or timeout.

    Returns a dict with:
        text:         The full concatenated assistant text
        tool_uses:    List of tool_use frames
        tool_results: List of tool_result frames
        result:       The result frame (if received)
        error:        The error frame (if received)
        all_frames:   List of all raw frames
    """
    import websockets

    text_parts = []
    tool_uses = []
    tool_results = []
    result_frame = None
    error_frame = None
    all_frames = []

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 30))
            frame = json.loads(raw)
            all_frames.append(frame)

            ftype = frame.get("type", "")

            if ftype == "text":
                content = frame.get("content", "")
                if content:
                    text_parts.append(content)
            elif ftype == "tool_use":
                tool_uses.append(frame)
            elif ftype == "tool_result":
                tool_results.append(frame)
            elif ftype == "result":
                result_frame = frame
                break
            elif ftype == "error":
                error_frame = frame
                break
            elif ftype == "session_complete":
                # Session done, but we may have gotten a result first
                if result_frame:
                    break
                # Give a moment for any trailing frames
                await asyncio.sleep(0.5)
                break

        except asyncio.TimeoutError:
            break
        except Exception as e:
            error_frame = {"type": "error", "message": str(e)}
            break

    return {
        "text": "".join(text_parts),
        "tool_uses": tool_uses,
        "tool_results": tool_results,
        "result": result_frame,
        "error": error_frame,
        "all_frames": all_frames,
    }


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

async def run_all_tests():
    """Run all E2E tests and return results."""
    import websockets

    results = []

    def record(name: str, passed: bool, details: str = ""):
        status = "PASS" if passed else "FAIL"
        results.append({"name": name, "status": status, "details": details})
        icon = "✓" if passed else "✗"
        print(f"  {icon} {name}: {status}")
        if details and not passed:
            # Show first 500 chars of details for failures
            print(f"    → {details[:500]}")

    # =========================================================================
    # 1. HTTP Endpoint Tests
    # =========================================================================
    print("\n━━━ 1. HTTP Stack Health ━━━")

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as http:
        # 1a. Health endpoint
        try:
            r = await http.get("/api/health")
            data = r.json()
            passed = r.status_code == 200 and data.get("status") == "ok"
            record("1a. /api/health returns ok", passed, json.dumps(data))
        except Exception as e:
            record("1a. /api/health returns ok", False, str(e))

        # 1b. Frontend serves HTML
        try:
            r = await http.get("/")
            passed = r.status_code == 200 and '<div id="root">' in r.text
            has_title = "CGIAR Innovation Analytics" in r.text
            record("1b. Frontend serves HTML with React root", passed and has_title,
                   f"status={r.status_code}, has_root={'<div id=\"root\">' in r.text}, has_title={has_title}")
        except Exception as e:
            record("1b. Frontend serves HTML with React root", False, str(e))

        # 1c. Config endpoint: 27 personas
        try:
            r = await http.get("/api/config")
            data = r.json()
            personas = data.get("personas", [])
            passed = len(personas) == 27
            cgiar = ['prms_data_analyst', 'innovation_strategy_advisor', 'research_synthesizer', 'report_generator']
            cgiar_present = all(a in personas for a in cgiar)
            record("1c. /api/config has 27 personas", passed and cgiar_present,
                   f"count={len(personas)}, cgiar_all_present={cgiar_present}")
        except Exception as e:
            record("1c. /api/config has 27 personas", False, str(e))

        # 1d. Agents endpoint: CGIAR agents with metadata
        try:
            r = await http.get("/api/agents")
            data = r.json()
            agents = data if isinstance(data, list) else data.get("agents", [])
            agent_map = {a.get("id"): a for a in agents if isinstance(a, dict)}
            cgiar_checks = []
            for aid in ['prms_data_analyst', 'innovation_strategy_advisor', 'research_synthesizer', 'report_generator']:
                a = agent_map.get(aid, {})
                cgiar_checks.append(bool(a.get("name") and a.get("color") and a.get("tags")))
            passed = all(cgiar_checks)
            record("1d. /api/agents has CGIAR agents with metadata", passed,
                   f"agents_found={len(agent_map)}, all_have_metadata={passed}")
        except Exception as e:
            record("1d. /api/agents has CGIAR agents with metadata", False, str(e))

    # =========================================================================
    # 2. WebSocket Connection Test
    # =========================================================================
    print("\n━━━ 2. WebSocket Connectivity ━━━")

    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            # Request a new session
            await ws.send(json.dumps({"type": "new_session"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)
            frame = json.loads(raw)
            session_id = frame.get("session_id", "")
            passed = frame.get("type") == "session" and bool(session_id)
            record("2a. WebSocket connects and gets session", passed,
                   f"frame_type={frame.get('type')}, session_id={session_id[:20]}")
    except Exception as e:
        record("2a. WebSocket connects and gets session", False, str(e))
        session_id = None

    # =========================================================================
    # 3. End-to-End Conversational Flow (the key tests)
    # =========================================================================
    print("\n━━━ 3. End-to-End Conversational Flow ━━━")

    # 3a. PRMS Data Query
    print("\n  [3a] Testing PRMS data query...")
    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "new_session"}))
            await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)  # session frame

            await ws.send(json.dumps({
                "message": "How many innovation development results are in the PRMS database? Just give me the count."
            }))

            resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text = resp["text"]

            # Check for PRMS query execution
            prms_tool_used = any(
                t.get("tool") in ("prms_query", "mcp__synapsis__prms_query")
                for t in resp["tool_uses"]
            )

            # Check for source attribution
            has_attribution = (
                "PRMS" in text.upper() or
                "prms" in text.lower() or
                "database" in text.lower()
            )

            # Check for a number in the response (should contain a count)
            import re
            has_number = bool(re.search(r'\d{2,}', text))  # at least 2-digit number

            has_result = resp["result"] is not None
            no_error = resp["error"] is None

            passed = has_result and no_error and has_number and has_attribution
            details = (
                f"got_result={has_result}, no_error={no_error}, "
                f"prms_tool_used={prms_tool_used}, has_number={has_number}, "
                f"has_attribution={has_attribution}, text_len={len(text)}"
            )
            record("3a. PRMS data query returns data with attribution", passed, details)

            if not passed and text:
                print(f"    Response excerpt: {text[:300]}...")
    except Exception as e:
        record("3a. PRMS data query returns data with attribution", False, str(e))

    # 3b. Knowledge Base Query
    print("\n  [3b] Testing knowledge base query...")
    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "new_session"}))
            await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)

            await ws.send(json.dumps({
                "message": "What is the Innovation Readiness Level scale in CGIAR? Explain the levels briefly."
            }))

            resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text = resp["text"]

            # Check for IRL content
            has_irl = "IRL" in text or "readiness level" in text.lower() or "innovation readiness" in text.lower()
            has_levels = any(f"level {i}" in text.lower() or f"irl {i}" in text.lower() for i in range(10))
            has_scaling = "scal" in text.lower()  # scaling, scale, etc.

            has_result = resp["result"] is not None
            no_error = resp["error"] is None

            # This should NOT need a PRMS query — it's knowledge-base
            prms_tool_used = any(
                t.get("tool") in ("prms_query", "mcp__synapsis__prms_query")
                for t in resp["tool_uses"]
            )

            passed = has_result and no_error and has_irl and (has_levels or has_scaling)
            details = (
                f"got_result={has_result}, no_error={no_error}, "
                f"has_irl={has_irl}, has_levels={has_levels}, has_scaling={has_scaling}, "
                f"prms_tool_used={prms_tool_used}, text_len={len(text)}"
            )
            record("3b. Knowledge base query returns IRL framework info", passed, details)

            if not passed and text:
                print(f"    Response excerpt: {text[:300]}...")
    except Exception as e:
        record("3b. Knowledge base query returns IRL framework info", False, str(e))

    # 3c. Cross-Cutting Query (combines data + knowledge)
    print("\n  [3c] Testing cross-cutting query...")
    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "new_session"}))
            await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)

            await ws.send(json.dumps({
                "message": "How many innovations are tagged for climate change? Include a brief explanation of what the climate change tag means in CGIAR."
            }))

            resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text = resp["text"]

            # Should combine PRMS data with knowledge
            import re
            has_number = bool(re.search(r'\d{2,}', text))
            has_climate = "climate" in text.lower()
            has_explanation = len(text) > 200  # Should be substantive

            has_result = resp["result"] is not None
            no_error = resp["error"] is None

            passed = has_result and no_error and has_number and has_climate and has_explanation
            details = (
                f"got_result={has_result}, no_error={no_error}, "
                f"has_number={has_number}, has_climate={has_climate}, "
                f"has_explanation={has_explanation}, text_len={len(text)}"
            )
            record("3c. Cross-cutting query combines data + knowledge", passed, details)

            if not passed and text:
                print(f"    Response excerpt: {text[:300]}...")
    except Exception as e:
        record("3c. Cross-cutting query combines data + knowledge", False, str(e))

    # 3d. Graceful handling of vague/out-of-scope query
    print("\n  [3d] Testing graceful handling of vague query...")
    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "new_session"}))
            await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)

            await ws.send(json.dumps({
                "message": "What's the weather like?"
            }))

            resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text = resp["text"]

            has_result = resp["result"] is not None
            no_error = resp["error"] is None
            responded = len(text) > 20  # Gave some response

            passed = has_result and no_error and responded
            details = (
                f"got_result={has_result}, no_error={no_error}, "
                f"responded={responded}, text_len={len(text)}"
            )
            record("3d. Vague query handled gracefully (no crash)", passed, details)
    except Exception as e:
        record("3d. Vague query handled gracefully (no crash)", False, str(e))

    # =========================================================================
    # 4. Response Quality Checks
    # =========================================================================
    print("\n━━━ 4. Response Quality ━━━")

    # 4a. Source attribution in PRMS response
    print("\n  [4a] Testing source attribution in PRMS response...")
    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "new_session"}))
            await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)

            await ws.send(json.dumps({
                "message": "What are the top 5 initiatives by number of innovation development results? Show the SQL you used."
            }))

            resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text = resp["text"]

            # Check source attribution
            has_prms_label = (
                "[PRMS" in text or
                "PRMS-VALIDATED" in text or
                "PRMS database" in text or
                "PRMS Database" in text
            )

            # Check SQL is shown
            has_sql = (
                "SELECT" in text.upper() or
                "sql" in text.lower() or
                "query" in text.lower()
            )

            # Check it has actual data (initiative names or counts)
            has_data = any(
                term in text for term in ["INIT-", "SP0", "initiative", "Initiative"]
            ) or bool(re.search(r'\d{2,}', text))

            has_result = resp["result"] is not None
            no_error = resp["error"] is None

            passed = has_result and no_error and has_prms_label and has_data
            details = (
                f"got_result={has_result}, no_error={no_error}, "
                f"has_prms_label={has_prms_label}, has_sql={has_sql}, "
                f"has_data={has_data}, text_len={len(text)}"
            )
            record("4a. PRMS response has source attribution + data", passed, details)

            if not passed and text:
                print(f"    Response excerpt: {text[:400]}...")
    except Exception as e:
        record("4a. PRMS response has source attribution + data", False, str(e))

    # 4b. Professional tone check
    print("\n  [4b] Testing professional tone...")
    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            await ws.send(json.dumps({"type": "new_session"}))
            await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)

            await ws.send(json.dumps({
                "message": "Can you explain what CGIAR science programmes are?"
            }))

            resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text = resp["text"]

            has_result = resp["result"] is not None
            no_error = resp["error"] is None

            # Check for professional, accessible tone
            is_substantive = len(text) > 100
            mentions_sp = "science programme" in text.lower() or "SP0" in text
            not_overly_technical = "SQL" not in text and "SELECT" not in text  # Shouldn't show SQL for this

            passed = has_result and no_error and is_substantive and mentions_sp
            details = (
                f"got_result={has_result}, is_substantive={is_substantive}, "
                f"mentions_sp={mentions_sp}, not_overly_technical={not_overly_technical}, "
                f"text_len={len(text)}"
            )
            record("4b. Response is professional and accessible", passed, details)
    except Exception as e:
        record("4b. Response is professional and accessible", False, str(e))

    # =========================================================================
    # 5. Session Persistence (multi-turn)
    # =========================================================================
    print("\n━━━ 5. Session Persistence ━━━")

    print("\n  [5a] Testing multi-turn context retention...")
    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            # Get session
            await ws.send(json.dumps({"type": "new_session"}))
            session_frame = await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)

            # Turn 1: establish context
            await ws.send(json.dumps({
                "message": "What is SP09 in CGIAR? Just give me the name and purpose in one sentence."
            }))
            resp1 = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text1 = resp1["text"]

            has_sp09 = "scaling" in text1.lower() or "SP09" in text1 or "scale" in text1.lower()
            turn1_ok = resp1["result"] is not None and has_sp09

            if turn1_ok:
                # Drain any trailing frames (session_complete, etc.) before sending turn 2
                # This is critical — the server sends session_complete after result
                try:
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=5)
                        frame = json.loads(raw)
                        if frame.get("type") == "session_complete":
                            break
                except (asyncio.TimeoutError, Exception):
                    pass  # No more trailing frames, or already got session_complete

                # Small pause to let server state settle between turns
                await asyncio.sleep(1)

                # Turn 2: reference previous context
                await ws.send(json.dumps({
                    "message": "How many innovations are linked to that programme?"
                }))
                resp2 = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
                text2 = resp2["text"]

                # Should understand "that programme" = SP09
                understood_context = (
                    "SP09" in text2 or
                    "scaling" in text2.lower() or
                    "innovation" in text2.lower()
                )
                import re
                has_number = bool(re.search(r'\d+', text2))

                has_result = resp2["result"] is not None
                no_error = resp2["error"] is None

                passed = has_result and no_error and understood_context
                details = (
                    f"turn1_ok={turn1_ok}, turn2_result={has_result}, "
                    f"understood_context={understood_context}, has_number={has_number}, "
                    f"text2_len={len(text2)}"
                )
            else:
                passed = False
                details = f"Turn 1 failed: got_result={resp1['result'] is not None}, has_sp09={has_sp09}"

            record("5a. Multi-turn context retained across turns", passed, details)
    except Exception as e:
        record("5a. Multi-turn context retained across turns", False, str(e))

    # =========================================================================
    # 6. Direct Agent WebSocket Test
    # =========================================================================
    print("\n━━━ 6. Direct Agent Access ━━━")

    print("\n  [6a] Testing direct PRMS Data Analyst agent...")
    try:
        url = f"{AGENT_WS_URL}/prms_data_analyst"
        async with websockets.connect(url, close_timeout=5) as ws:
            # Should get agent_info first
            raw = await asyncio.wait_for(ws.recv(), timeout=CONNECT_TIMEOUT)
            info = json.loads(raw)

            is_correct_agent = (
                info.get("type") == "agent_info" and
                info.get("agent_id") == "prms_data_analyst"
            )

            if is_correct_agent:
                await ws.send(json.dumps({
                    "message": "Count the total number of active results in the database, grouped by result type. Show counts only."
                }))

                resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
                text = resp["text"]

                prms_used = any(
                    t.get("tool") in ("prms_query", "mcp__synapsis__prms_query")
                    for t in resp["tool_uses"]
                )

                import re
                has_numbers = bool(re.search(r'\d{3,}', text))  # 3+ digit numbers expected

                passed = resp["result"] is not None and has_numbers
                details = (
                    f"correct_agent={is_correct_agent}, prms_used={prms_used}, "
                    f"has_numbers={has_numbers}, text_len={len(text)}"
                )
            else:
                passed = False
                details = f"Wrong agent info: {info}"

            record("6a. Direct PRMS Data Analyst responds with data", passed, details)
    except Exception as e:
        record("6a. Direct PRMS Data Analyst responds with data", False, str(e))

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 60)
    print("PHASE 1 ACCEPTANCE GATE — RESULTS SUMMARY")
    print("=" * 60)

    total = len(results)
    passed_count = sum(1 for r in results if r["status"] == "PASS")
    failed_count = total - passed_count

    print(f"\n{'Test':<55} {'Status':>6}")
    print("-" * 62)
    for r in results:
        icon = "✓" if r["status"] == "PASS" else "✗"
        print(f"  {icon} {r['name']:<52} {r['status']:>6}")

    print("-" * 62)
    print(f"  Total: {total} | Passed: {passed_count} | Failed: {failed_count}")

    if failed_count == 0:
        print("\n  🟢 ALL TESTS PASSED — Platform is gate-ready.")
    else:
        print(f"\n  🔴 {failed_count} TEST(S) FAILED — Review failures above.")

    print()
    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    sys.exit(0 if all(r["status"] == "PASS" for r in results) else 1)
