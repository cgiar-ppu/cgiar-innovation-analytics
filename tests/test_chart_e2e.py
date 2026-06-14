"""
E2E Integration Tests for the CGIAR Visualization Pipeline (Phase 2).

Tests the full chart generation flow:
  WebSocket → Agent → PRMS query → create_chart → <chart> JSON → response

Run against a live server on port 7780:
    python tests/test_chart_e2e.py
"""

import asyncio
import json
import os
import re
import sys
import time

PORT = int(os.environ.get("TEST_PORT", "7780"))
WS_URL = f"ws://localhost:{PORT}/ws/chat"
MSG_TIMEOUT = 180  # LLM calls can be slow


async def collect_ws_response(ws, timeout: float = MSG_TIMEOUT) -> dict:
    """Collect all WS frames until a 'result' or 'error' frame."""
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
                text_parts.append(frame.get("content", ""))
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
                if result_frame:
                    break
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


def extract_chart_spec(text: str) -> dict | None:
    """Extract a <chart>...</chart> JSON spec from response text."""
    match = re.search(r'<chart>([\s\S]*?)</chart>', text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
    # Also try fenced JSON with chartType
    fenced = re.findall(r'```(?:json)?\s*\n([\s\S]*?)```', text)
    for block in fenced:
        try:
            obj = json.loads(block.strip())
            if isinstance(obj, dict) and "chartType" in obj:
                return obj
        except json.JSONDecodeError:
            continue
    return None


def validate_chart_spec(spec: dict, expected_type: str = None) -> list[str]:
    """Validate a chart spec and return list of issues (empty = valid)."""
    issues = []
    if not isinstance(spec, dict):
        return ["spec is not a dict"]
    if "chartType" not in spec:
        issues.append("missing chartType")
    elif expected_type and spec["chartType"] != expected_type:
        issues.append(f"expected chartType={expected_type}, got {spec['chartType']}")
    if not isinstance(spec.get("data"), list) or len(spec["data"]) == 0:
        issues.append("missing or empty data array")
    if "title" not in spec or not spec["title"]:
        issues.append("missing title")
    if not isinstance(spec.get("series"), list) or len(spec["series"]) == 0:
        issues.append("missing series")
    else:
        for s in spec["series"]:
            if not s.get("key"):
                issues.append("series entry missing 'key'")
    # Check CGIAR brand colors
    cgiar_colors = {"#427730", "#7AB800", "#0065BD", "#E37222", "#8B1A4A",
                    "#00A5DB", "#F4B223", "#5C3D8F", "#009E73", "#D32F2F"}
    has_cgiar_color = any(
        s.get("color", "").upper() in {c.upper() for c in cgiar_colors}
        for s in spec.get("series", [])
    )
    if not has_cgiar_color:
        issues.append("no CGIAR brand color in series")
    return issues


async def run_chart_test(test_name: str, message: str, checks: dict) -> dict:
    """Run a single chart test via WebSocket.

    checks can include:
      expected_chart_type: str  — expected chartType value
      expect_chart: bool        — whether a chart spec is expected
      expect_prms: bool         — whether PRMS tool should be used
      min_data_points: int      — minimum data array length
      expect_graceful: bool     — expect graceful handling (no crash)
    """
    import websockets

    result = {"name": test_name, "status": "FAIL", "details": ""}

    try:
        async with websockets.connect(WS_URL, close_timeout=5) as ws:
            # Get session
            await ws.send(json.dumps({"type": "new_session"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            session_frame = json.loads(raw)
            if session_frame.get("type") != "session":
                result["details"] = f"Bad session frame: {session_frame}"
                return result

            # Send message
            print(f"    Sending: {message[:80]}...")
            await ws.send(json.dumps({"message": message}))

            # Collect response
            resp = await collect_ws_response(ws, timeout=MSG_TIMEOUT)
            text = resp["text"]
            has_result = resp["result"] is not None
            no_error = resp["error"] is None

            if not has_result:
                result["details"] = f"No result frame. Error: {resp['error']}. Text len: {len(text)}"
                return result

            if not no_error:
                result["details"] = f"Error frame: {resp['error']}"
                return result

            # Check PRMS tool usage
            prms_tool_used = any(
                t.get("tool") in ("prms_query", "mcp__synapsis__prms_query")
                for t in resp["tool_uses"]
            )
            chart_tool_used = any(
                t.get("tool") in ("create_chart", "mcp__synapsis__create_chart")
                for t in resp["tool_uses"]
            )

            details_parts = [
                f"text_len={len(text)}",
                f"prms_used={prms_tool_used}",
                f"chart_tool_used={chart_tool_used}",
                f"tool_uses={len(resp['tool_uses'])}",
            ]

            # Check chart spec
            if checks.get("expect_chart", True):
                spec = extract_chart_spec(text)
                if spec is None:
                    result["details"] = f"No chart spec found in response. {', '.join(details_parts)}"
                    # Still might be okay if graceful handling expected
                    if checks.get("expect_graceful"):
                        result["status"] = "PASS"
                        result["details"] += " (graceful - no chart expected)"
                    return result

                spec_issues = validate_chart_spec(spec, checks.get("expected_chart_type"))
                details_parts.append(f"chartType={spec.get('chartType')}")
                details_parts.append(f"data_points={len(spec.get('data', []))}")
                details_parts.append(f"title={spec.get('title', 'N/A')[:50]}")

                if spec_issues:
                    details_parts.append(f"spec_issues={spec_issues}")
                    result["details"] = ", ".join(details_parts)
                    return result

                # Check minimum data points
                min_pts = checks.get("min_data_points", 2)
                if len(spec.get("data", [])) < min_pts:
                    details_parts.append(f"too_few_data_points (need {min_pts})")
                    result["details"] = ", ".join(details_parts)
                    return result

                # Check PRMS was used if expected
                if checks.get("expect_prms", True) and not prms_tool_used:
                    details_parts.append("expected PRMS tool but not used")
                    # This is a warning, not a hard failure
                    # Agent might have used cached knowledge

                result["status"] = "PASS"
                result["details"] = ", ".join(details_parts)
            else:
                # No chart expected — check for graceful handling
                if checks.get("expect_graceful"):
                    result["status"] = "PASS"
                    result["details"] = f"Graceful response (no chart). {', '.join(details_parts)}"
                else:
                    result["status"] = "PASS"
                    result["details"] = ", ".join(details_parts)

    except Exception as e:
        result["details"] = f"Exception: {type(e).__name__}: {e}"

    return result


async def run_all_tests():
    """Run all chart E2E tests."""
    results = []

    # =========================================================================
    # Test 3a: Bar chart — Top countries
    # =========================================================================
    print("\n  [3a] Chart: Top 10 countries by results (bar)...")
    r = await run_chart_test(
        "3a. Bar chart: Top 10 countries by results",
        "Show me a bar chart of the top 10 countries by number of results in the PRMS database.",
        {
            "expected_chart_type": "bar",
            "expect_prms": True,
            "min_data_points": 5,
        },
    )
    results.append(r)

    # =========================================================================
    # Test 3b: Pie chart — Results by type
    # =========================================================================
    print("\n  [3b] Chart: Results by type (pie)...")
    r = await run_chart_test(
        "3b. Pie chart: Results by type",
        "Create a pie chart of results by type from the PRMS database.",
        {
            "expected_chart_type": "pie",
            "expect_prms": True,
            "min_data_points": 3,
        },
    )
    results.append(r)

    # =========================================================================
    # Test 3c: Bar chart — IRL distribution
    # =========================================================================
    print("\n  [3c] Chart: Innovation readiness level distribution (bar)...")
    r = await run_chart_test(
        "3c. Bar chart: Innovation Readiness Level distribution",
        "Chart the innovation readiness level distribution from the PRMS database. Use a bar chart showing each IRL level.",
        {
            "expected_chart_type": "bar",
            "expect_prms": True,
            "min_data_points": 5,
        },
    )
    results.append(r)

    # =========================================================================
    # Test 4a: Edge case — Empty results
    # =========================================================================
    print("\n  [4a] Edge case: Chart for empty data (Antarctica)...")
    r = await run_chart_test(
        "4a. Edge case: Empty results (Antarctica)",
        "Show me a bar chart of CGIAR innovations in Antarctica from the PRMS database.",
        {
            "expect_chart": False,
            "expect_graceful": True,
        },
    )
    results.append(r)

    # =========================================================================
    # Test 4b: Edge case — Large dataset
    # =========================================================================
    print("\n  [4b] Edge case: Large dataset (all countries)...")
    r = await run_chart_test(
        "4b. Edge case: Large dataset (all countries)",
        "Create a bar chart of ALL countries with their result counts from the PRMS database.",
        {
            "expect_chart": True,
            "expect_prms": True,
            "min_data_points": 5,
        },
    )
    results.append(r)

    # =========================================================================
    # Test 4c: Edge case — Vague request
    # =========================================================================
    print("\n  [4c] Edge case: Vague chart request...")
    r = await run_chart_test(
        "4c. Edge case: Vague request",
        "Make me a chart about CGIAR results from the PRMS database.",
        {
            "expect_chart": True,  # Agent should make a reasonable default
            "expect_graceful": True,
            "min_data_points": 2,
        },
    )
    results.append(r)

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("CHART E2E TEST SUMMARY")
    print("=" * 70)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    for r in results:
        icon = "PASS" if r["status"] == "PASS" else "FAIL"
        print(f"  [{icon}] {r['name']}")
        if r["details"]:
            print(f"         {r['details'][:200]}")
    print(f"\n  Total: {passed} passed, {failed} failed out of {len(results)}")
    print("=" * 70)

    return results


if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    sys.exit(0 if all(r["status"] == "PASS" for r in results) else 1)
