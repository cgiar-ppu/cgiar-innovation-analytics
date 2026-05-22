"""
computer-use MCP server -- properly structured replacement for the monolithic
``mcp__synapsis__computer`` tool.

Key design decisions
--------------------
* **Server name is ``"computer-use"``**.  The Anthropic API backend detects
  ``mcp__computer-use__*`` tool names and injects a computer-use system
  prompt hint.  The old ``mcp__synapsis__computer`` naming did not trigger
  this behaviour.

* **Separate tools** instead of one dispatcher.  Each action (screenshot,
  left_click, type, ...) is its own ``@tool``-decorated function so the
  model can call them directly.

* **Coordinate scaling** eliminates the ~22% click-miss bug.  Screenshots
  are pre-scaled to fit within API constraints (1568 px longest edge,
  1.15 MP total) so the API never silently downsamples them.  Incoming
  click coordinates are scaled back up to logical screen coordinates.

* **JPEG at quality 75** instead of PNG -- dramatically smaller payloads
  with negligible visual loss for UI screenshots.

* **All subprocess calls are async** via ``asyncio.create_subprocess_exec``
  to avoid blocking the event loop.

* **CGEvent via PyObjC** for key delivery and scroll.  This bypasses
  the reliability issues of AppleScript System Events and cliclick for
  key presses.  Uses ``kCGEventSourceStatePrivate`` for a clean modifier
  state table that prevents stuck-modifier bugs.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import tempfile
from typing import Any

from claude_agent_sdk import tool

from synapsis.tools.coordinate_scaling import DisplayConfig, _detect_display
from synapsis.tools.macos_input import (
    key_press as _cg_key_press,
    clear_modifiers as _cg_clear_modifiers,
    paste_text as _cg_paste_text,
    parse_key_spec as _cg_parse_key_spec,
    scroll as _cg_scroll,
)
from synapsis.utils.responses import error_response, success_response

# ---------------------------------------------------------------------------
# Display configuration -- computed once at import time
# ---------------------------------------------------------------------------

_logical_w, _logical_h, _scale = _detect_display()
DISPLAY = DisplayConfig.from_display(_logical_w, _logical_h, _scale)

# Brief pause (seconds) inserted after actions that mutate UI state so
# the next screenshot captures the result, not a transient state.
_POST_ACTION_DELAY = 0.3

# Subprocess timeout (seconds)
_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Key delivery is handled by synapsis.tools.macos_input (CGEvent via PyObjC).
# This replaces the previous AppleScript System Events approach which had
# reliability issues with Spotlight and other system UI.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Async subprocess helper
# ---------------------------------------------------------------------------

async def _run(*cmd: str, timeout: float = _TIMEOUT) -> tuple[int, str, str]:
    """Run a subprocess asynchronously and return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise
    return proc.returncode or 0, stdout.decode(), stderr.decode()


# ---------------------------------------------------------------------------
# Coordinate helpers
# ---------------------------------------------------------------------------

def _parse_coordinate(
    args: dict[str, Any],
    default_center: bool = False,
) -> tuple[int, int]:
    """Extract a validated (api_x, api_y) pair from the tool arguments.

    If *default_center* is True, missing coordinates default to the image
    center rather than raising an error.

    Raises ValueError if coordinates are missing (and default_center is False)
    or out of range.
    """
    coordinate = args.get("coordinate")

    # The MCP schema may deliver coordinates as a string (e.g. "715,303" or
    # "[715, 303]") or as a list/tuple.  Normalise to a list of numbers.
    if isinstance(coordinate, str):
        # Strip brackets and whitespace, then split on comma
        cleaned = coordinate.strip().strip("[]() ")
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        if len(parts) >= 2:
            coordinate = parts  # list of numeric strings
        else:
            coordinate = None  # unparseable

    if coordinate is None or not isinstance(coordinate, (list, tuple)):
        if default_center:
            return DISPLAY.target_width // 2, DISPLAY.target_height // 2
        raise ValueError(
            "Missing 'coordinate' parameter. Provide [x, y] in screenshot pixel space."
        )
    if len(coordinate) < 2:
        raise ValueError(
            f"Invalid coordinate {coordinate!r}. Expected [x, y] with two elements."
        )
    api_x, api_y = int(float(coordinate[0])), int(float(coordinate[1]))
    if api_x < 0 or api_y < 0:
        raise ValueError(
            f"Coordinates must be non-negative, got ({api_x}, {api_y})."
        )
    if api_x > DISPLAY.target_width or api_y > DISPLAY.target_height:
        raise ValueError(
            f"Coordinates ({api_x}, {api_y}) exceed screenshot dimensions "
            f"({DISPLAY.target_width}x{DISPLAY.target_height})."
        )
    return api_x, api_y


def _to_screen(api_x: int, api_y: int) -> tuple[int, int]:
    """Convert API-space coordinates to rounded logical screen coordinates."""
    sx, sy = DISPLAY.api_to_screen(api_x, api_y)
    return round(sx), round(sy)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

@tool(
    "screenshot",
    "Capture the screen. Returns a JPEG screenshot scaled to fit within API "
    "constraints. Coordinates in other tools correspond to pixels in this image.",
    {},
)
async def screenshot(args: dict[str, Any]) -> dict[str, Any]:
    """Capture screen, resize to API-compatible dimensions, return as JPEG."""
    from PIL import Image  # type: ignore[import-untyped]

    fd, tmp_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        returncode, _, stderr = await _run("screencapture", "-x", tmp_path)
        if returncode != 0:
            return error_response(f"screencapture failed: {stderr.strip()}")

        with Image.open(tmp_path) as img:
            # macOS screencapture produces RGBA; JPEG requires RGB
            rgb = img.convert("RGB") if img.mode != "RGB" else img
            resized = rgb.resize(
                (DISPLAY.target_width, DISPLAY.target_height),
                Image.LANCZOS,
            )
            buf = io.BytesIO()
            resized.save(buf, format="JPEG", quality=75)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

        # MCP image content format: flat {type, data, mimeType}.
        # The SDK wrapper converts this to the Anthropic API's nested
        # {type, source: {type, media_type, data}} shape automatically.
        return {
            "content": [
                {
                    "type": "image",
                    "data": img_b64,
                    "mimeType": "image/jpeg",
                },
            ],
        }
    except Exception as exc:
        return error_response(f"Screenshot error: {exc}")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


@tool(
    "left_click",
    "Click the left mouse button at the given [x, y] coordinate.",
    {"coordinate": list},
)
async def left_click(args: dict[str, Any]) -> dict[str, Any]:
    """Left-click at the specified coordinate."""
    try:
        api_x, api_y = _parse_coordinate(args)
        x, y = _to_screen(api_x, api_y)
        returncode, _, stderr = await _run("cliclick", f"c:{x},{y}")
        if returncode != 0:
            return error_response(f"cliclick failed: {stderr.strip()}")
        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"left_click at ({x}, {y})")
    except ValueError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"left_click error: {exc}")


@tool(
    "right_click",
    "Click the right mouse button at the given [x, y] coordinate.",
    {"coordinate": list},
)
async def right_click(args: dict[str, Any]) -> dict[str, Any]:
    """Right-click at the specified coordinate."""
    try:
        api_x, api_y = _parse_coordinate(args)
        x, y = _to_screen(api_x, api_y)
        returncode, _, stderr = await _run("cliclick", f"rc:{x},{y}")
        if returncode != 0:
            return error_response(f"cliclick failed: {stderr.strip()}")
        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"right_click at ({x}, {y})")
    except ValueError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"right_click error: {exc}")


@tool(
    "double_click",
    "Double-click the left mouse button at the given [x, y] coordinate.",
    {"coordinate": list},
)
async def double_click(args: dict[str, Any]) -> dict[str, Any]:
    """Double-click at the specified coordinate."""
    try:
        api_x, api_y = _parse_coordinate(args)
        x, y = _to_screen(api_x, api_y)
        returncode, _, stderr = await _run("cliclick", f"dc:{x},{y}")
        if returncode != 0:
            return error_response(f"cliclick failed: {stderr.strip()}")
        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"double_click at ({x}, {y})")
    except ValueError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"double_click error: {exc}")


@tool(
    "triple_click",
    "Triple-click the left mouse button at the given [x, y] coordinate. "
    "Useful for selecting an entire line of text.",
    {"coordinate": list},
)
async def triple_click(args: dict[str, Any]) -> dict[str, Any]:
    """Triple-click at the specified coordinate."""
    try:
        api_x, api_y = _parse_coordinate(args)
        x, y = _to_screen(api_x, api_y)
        returncode, _, stderr = await _run("cliclick", f"tc:{x},{y}")
        if returncode != 0:
            return error_response(f"cliclick failed: {stderr.strip()}")
        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"triple_click at ({x}, {y})")
    except ValueError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"triple_click error: {exc}")


@tool(
    "mouse_move",
    "Move the mouse cursor to the given [x, y] coordinate without clicking.",
    {"coordinate": list},
)
async def mouse_move(args: dict[str, Any]) -> dict[str, Any]:
    """Move the mouse to the specified coordinate."""
    try:
        api_x, api_y = _parse_coordinate(args)
        x, y = _to_screen(api_x, api_y)
        returncode, _, stderr = await _run("cliclick", f"m:{x},{y}")
        if returncode != 0:
            return error_response(f"cliclick failed: {stderr.strip()}")
        return success_response(f"mouse_move to ({x}, {y})")
    except ValueError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"mouse_move error: {exc}")


@tool(
    "type",
    "Type the given text into the focused application. Uses clipboard paste "
    "for reliable handling of special characters and Unicode.",
    {"text": str},
)
async def type_text(args: dict[str, Any]) -> dict[str, Any]:
    """Type text using clipboard paste (pbcopy + CGEvent Cmd+V)."""
    text = args.get("text", "")
    if not text:
        return error_response("Missing 'text' parameter. Provide the text to type.")
    try:
        await _cg_paste_text(text)
        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"Typed {len(text)} characters")
    except Exception as exc:
        return error_response(f"type error: {exc}")


@tool(
    "key",
    "Press a key or key combination. Accepts xdotool-style key specs: "
    "single keys like 'Return', 'Tab', 'Escape', 'space', 'F5', or combos "
    "like 'cmd+c', 'cmd+shift+s', 'alt+Tab'. Modifier names: cmd, ctrl, "
    "alt/option, shift, fn, super (= cmd).",
    {"key": str},
)
async def key(args: dict[str, Any]) -> dict[str, Any]:
    """Press a key or key combination via CGEvent (PyObjC/Quartz).

    Uses CGEvent with kCGEventSourceStatePrivate for reliable key delivery
    to all applications, including Spotlight and other system UI.
    """
    key_str = args.get("key", "")
    if not key_str:
        return error_response(
            "Missing 'key' parameter. Provide a key name like 'Return' or 'cmd+c'."
        )
    try:
        main_key, modifiers = _cg_parse_key_spec(key_str)
        # Use longer interval for system hotkeys (Cmd+Space, Cmd+Tab, etc.)
        interval = 0.08 if modifiers else 0.05
        await _cg_key_press(main_key, modifiers=modifiers, interval=interval)
        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"Pressed key: {key_str}")
    except Exception as exc:
        return error_response(f"key error: {exc}")


@tool(
    "scroll",
    "Scroll at the given coordinate (or screen center if omitted). "
    "Accepts 'direction' ('up', 'down', 'left', 'right') and 'amount' "
    "(number of scroll increments, default 3).",
    {"coordinate": list, "direction": str, "amount": int},
)
async def scroll(args: dict[str, Any]) -> dict[str, Any]:
    """Scroll using CGEventCreateScrollWheelEvent for universal compatibility.

    Creates genuine scroll-wheel events that Chrome and all other
    applications handle correctly, unlike AppleScript's ``scroll`` command
    which is an accessibility action that many apps do not implement.
    """
    try:
        api_x, api_y = _parse_coordinate(args, default_center=True)
        x, y = _to_screen(api_x, api_y)

        # Accept both parameter name variants for compatibility
        direction = (
            args.get("direction")
            or args.get("scroll_direction", "down")
        )
        amount = int(
            args.get("amount")
            or args.get("scroll_amount", 3)
        )

        await _cg_scroll(direction=direction, amount=amount, x=x, y=y)

        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"Scrolled {direction} {amount}x at ({x}, {y})")
    except ValueError as exc:
        return error_response(str(exc))
    except Exception as exc:
        return error_response(f"scroll error: {exc}")


@tool(
    "wait",
    "Pause for a specified duration in seconds (0.1 to 10). "
    "Useful for waiting between actions or for UI transitions to complete.",
    {"duration": float},
)
async def wait(args: dict[str, Any]) -> dict[str, Any]:
    """Pause execution for the specified duration."""
    duration = args.get("duration", 2)
    try:
        duration = min(max(0.1, float(duration)), 10)
    except (TypeError, ValueError):
        duration = 2.0
    await asyncio.sleep(duration)
    return success_response(f"Waited {duration} seconds")


@tool(
    "left_click_drag",
    "Click and drag from start_coordinate [x, y] to end_coordinate [x, y]. "
    "If only 'coordinate' is given, it is used as the start.",
    {"start_coordinate": list, "end_coordinate": list, "coordinate": list},
)
async def left_click_drag(args: dict[str, Any]) -> dict[str, Any]:
    """Click and drag from one point to another via cliclick dd:/du:."""
    try:
        # Accept either start_coordinate or coordinate for the start point
        start = args.get("start_coordinate") or args.get("coordinate")
        end = args.get("end_coordinate")

        # Normalise string coordinates (e.g. "715,303") to lists
        for coord_name in ("start", "end"):
            val = locals()[coord_name]
            if isinstance(val, str):
                cleaned = val.strip().strip("[]() ")
                parts = [p.strip() for p in cleaned.split(",") if p.strip()]
                if len(parts) >= 2:
                    if coord_name == "start":
                        start = parts
                    else:
                        end = parts

        if start is None or not isinstance(start, (list, tuple)) or len(start) < 2:
            return error_response(
                "Missing 'start_coordinate' (or 'coordinate'). "
                "Provide [x, y] for the drag start point."
            )
        if end is None or not isinstance(end, (list, tuple)) or len(end) < 2:
            return error_response(
                "Missing 'end_coordinate'. Provide [x, y] for the drag end point."
            )

        sx, sy = _to_screen(int(float(start[0])), int(float(start[1])))
        ex, ey = _to_screen(int(float(end[0])), int(float(end[1])))

        returncode, _, stderr = await _run(
            "cliclick", f"dd:{sx},{sy}", f"du:{ex},{ey}",
        )
        if returncode != 0:
            return error_response(f"cliclick drag failed: {stderr.strip()}")
        await asyncio.sleep(_POST_ACTION_DELAY)
        return success_response(f"Dragged from ({sx}, {sy}) to ({ex}, {ey})")
    except Exception as exc:
        return error_response(f"left_click_drag error: {exc}")


# ---------------------------------------------------------------------------
# Exported tool list (consumed by tools/__init__.py to build the MCP server)
# ---------------------------------------------------------------------------

computer_use_tools: list = [
    screenshot,
    left_click,
    right_click,
    double_click,
    triple_click,
    mouse_move,
    type_text,
    key,
    scroll,
    wait,
    left_click_drag,
]
