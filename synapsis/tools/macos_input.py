"""
macos_input.py -- Reliable macOS input via CGEvent (PyObjC/Quartz)

This module provides async-compatible keyboard and scroll input for macOS
using the CGEvent API directly through PyObjC. It avoids the reliability
issues of AppleScript System Events, cliclick key press, and PyAutoGUI
by using kCGEventSourceStatePrivate (clean modifier state) and proper
inter-event timing.

Requirements:
    pip install pyobjc-framework-Quartz

Permissions required:
    - Accessibility (System Settings > Privacy & Security > Accessibility)
    - The Python process (or Terminal/IDE running it) must be listed

Usage:
    from synapsis.tools.macos_input import key_press, key_combo, scroll, paste_text

    await key_press("return")
    await key_press("v", modifiers=["command"])
    await scroll("down", amount=5)
    await paste_text("hello world")
"""

import asyncio
import subprocess
from typing import Optional

import Quartz
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventCreateScrollWheelEvent,
    CGEventPost,
    CGEventSetFlags,
    CGEventSourceCreate,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGEventSourceStatePrivate,
    kCGHIDEventTap,
    kCGScrollEventUnitLine,
    kCGScrollEventUnitPixel,
    kCGSessionEventTap,
)

# ---------------------------------------------------------------------------
# Key code mapping (macOS virtual key codes)
# ---------------------------------------------------------------------------
KEY_CODES: dict[str, int] = {
    # Letters
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04,
    "g": 0x05, "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09,
    "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F,
    "y": 0x10, "t": 0x11, "i": 0x22, "p": 0x23, "l": 0x25,
    "j": 0x26, "k": 0x28, "n": 0x2D, "m": 0x2E, "o": 0x1F,
    "u": 0x20,
    # Numbers
    "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15,
    "5": 0x17, "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
    # Special keys
    "return": 0x24, "enter": 0x24, "tab": 0x30, "space": 0x31,
    "delete": 0x33, "backspace": 0x33, "escape": 0x35, "esc": 0x35,
    "forwarddelete": 0x75,
    # Modifiers
    "command": 0x37, "cmd": 0x37,
    "shift": 0x38, "capslock": 0x39,
    "option": 0x3A, "alt": 0x3A,
    "control": 0x3B, "ctrl": 0x3B,
    "rightcommand": 0x36, "rightshift": 0x3C,
    "rightoption": 0x3D, "rightcontrol": 0x3E,
    "fn": 0x3F,
    # Arrow keys
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    # Function keys
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76,
    "f5": 0x60, "f6": 0x61, "f7": 0x62, "f8": 0x64,
    "f9": 0x65, "f10": 0x6D, "f11": 0x67, "f12": 0x6F,
    # Navigation
    "home": 0x73, "end": 0x77, "pageup": 0x74, "pagedown": 0x79,
    # Punctuation
    "-": 0x1B, "=": 0x18, "[": 0x21, "]": 0x1E,
    "\\": 0x2A, ";": 0x29, "'": 0x27, ",": 0x2B,
    ".": 0x2F, "/": 0x2C, "`": 0x32,
}

# Aliases for xdotool-style names used by the MCP key tool
_KEY_ALIASES: dict[str, str] = {
    "Return": "return",
    "Tab": "tab",
    "Escape": "escape",
    "BackSpace": "backspace",
    "Delete": "forwarddelete",
    "fwd-delete": "forwarddelete",
    "Up": "up", "arrow-up": "up",
    "Down": "down", "arrow-down": "down",
    "Left": "left", "arrow-left": "left",
    "Right": "right", "arrow-right": "right",
    "Home": "home", "End": "end",
    "Page_Up": "pageup", "page-up": "pageup",
    "Page_Down": "pagedown", "page-down": "pagedown",
    "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
    "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8",
    "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
    "super": "command",
}

MODIFIER_FLAGS: dict[str, int] = {
    "command": kCGEventFlagMaskCommand,
    "cmd": kCGEventFlagMaskCommand,
    "super": kCGEventFlagMaskCommand,
    "shift": kCGEventFlagMaskShift,
    "option": kCGEventFlagMaskAlternate,
    "alt": kCGEventFlagMaskAlternate,
    "control": kCGEventFlagMaskControl,
    "ctrl": kCGEventFlagMaskControl,
}

# Names recognized as modifiers (for splitting combo strings like "cmd+c")
_MODIFIER_NAMES: set[str] = {
    "command", "cmd", "super", "shift", "option", "alt",
    "control", "ctrl", "fn",
}


def _make_source():
    """Create a PRIVATE event source with an independent state table.

    kCGEventSourceStatePrivate prevents modifier state pollution from
    prior key operations -- the single most important fix for reliability.
    """
    return CGEventSourceCreate(kCGEventSourceStatePrivate)


def _build_flags(modifiers: list[str]) -> int:
    """Combine modifier names into a CGEvent flags bitmask."""
    flags = 0
    for mod in modifiers:
        flag = MODIFIER_FLAGS.get(mod.lower())
        if flag:
            flags |= flag
    return flags


def _resolve_key(name: str) -> str:
    """Resolve a key name (possibly an alias) to a KEY_CODES key."""
    # Direct match
    if name in KEY_CODES:
        return name
    # Check alias table
    alias = _KEY_ALIASES.get(name)
    if alias and alias in KEY_CODES:
        return alias
    # Case-insensitive fallback
    lower = name.lower()
    if lower in KEY_CODES:
        return lower
    alias = _KEY_ALIASES.get(lower)
    if alias and alias in KEY_CODES:
        return alias
    return name  # will raise in key_press if not found


# ---------------------------------------------------------------------------
# Core key delivery
# ---------------------------------------------------------------------------

async def key_press(
    key: str,
    modifiers: Optional[list[str]] = None,
    interval: float = 0.05,
    tap: int = kCGHIDEventTap,
) -> None:
    """Press a key with optional modifiers via CGEvent.

    The sequence is:
        modifier-down(s) -> key-down (with flags) -> key-up -> modifier-up(s)

    Args:
        key:       Key name from KEY_CODES or _KEY_ALIASES.
        modifiers: Optional list like ["command"], ["command", "shift"].
        interval:  Seconds between events. 50ms default; use 80ms+ for
                   system hotkeys like Cmd+Space.
        tap:       CGEvent tap location. Use kCGHIDEventTap (default) for
                   normal apps; try kCGSessionEventTap for system UI.
    """
    modifiers = modifiers or []
    resolved = _resolve_key(key)

    if resolved not in KEY_CODES:
        raise ValueError(
            f"Unknown key: {key!r}. "
            f"Known keys: {sorted(set(list(KEY_CODES.keys()) + list(_KEY_ALIASES.keys())))}"
        )

    key_code = KEY_CODES[resolved]
    source = _make_source()
    flags = _build_flags(modifiers)

    # 1. Press each modifier key down
    for mod in modifiers:
        mod_resolved = _resolve_key(mod)
        mod_code = KEY_CODES.get(mod_resolved)
        if mod_code is not None:
            ev = CGEventCreateKeyboardEvent(source, mod_code, True)
            CGEventPost(tap, ev)
            await asyncio.sleep(interval)

    # 2. Main key down with modifier flags
    ev_down = CGEventCreateKeyboardEvent(source, key_code, True)
    if flags:
        CGEventSetFlags(ev_down, flags)
    CGEventPost(tap, ev_down)
    await asyncio.sleep(interval)

    # 3. Main key up (still with flags so the release is recognized)
    ev_up = CGEventCreateKeyboardEvent(source, key_code, False)
    if flags:
        CGEventSetFlags(ev_up, flags)
    CGEventPost(tap, ev_up)
    await asyncio.sleep(interval)

    # 4. Release modifiers in reverse order
    for mod in reversed(modifiers):
        mod_resolved = _resolve_key(mod)
        mod_code = KEY_CODES.get(mod_resolved)
        if mod_code is not None:
            ev = CGEventCreateKeyboardEvent(source, mod_code, False)
            CGEventPost(tap, ev)
            await asyncio.sleep(interval)


async def key_combo(keys: list[str], interval: float = 0.05) -> None:
    """Press a key combination. Last element is the main key; all others
    are modifiers.

    Examples:
        await key_combo(["command", "space"])       # Spotlight
        await key_combo(["command", "shift", "s"])   # Save As
        await key_combo(["return"])                   # just Return
    """
    if len(keys) == 1:
        await key_press(keys[0], interval=interval)
    else:
        await key_press(keys[-1], modifiers=keys[:-1], interval=interval)


async def paste_text(text: str) -> None:
    """Type text via the clipboard (pbcopy + CGEvent Cmd+V). Handles any Unicode."""
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
    await asyncio.sleep(0.05)
    await key_press("v", modifiers=["command"])


async def clear_modifiers(tap: int = kCGHIDEventTap) -> None:
    """Release all modifier keys to clear any stuck state."""
    source = _make_source()
    for code in [0x37, 0x38, 0x3A, 0x3B, 0x36, 0x3C, 0x3D, 0x3E, 0x3F]:
        ev = CGEventCreateKeyboardEvent(source, code, False)
        CGEventPost(tap, ev)
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# Scroll
# ---------------------------------------------------------------------------

async def scroll(
    direction: str = "down",
    amount: int = 5,
    x: Optional[int] = None,
    y: Optional[int] = None,
    unit: str = "line",
) -> None:
    """Scroll via CGEventCreateScrollWheelEvent.

    Creates real mouse-wheel events that all apps (including Chrome) handle
    correctly, unlike AppleScript's accessibility-based ``scroll``.

    Args:
        direction: "up", "down", "left", or "right"
        amount:    Positive number of units to scroll
        x, y:      Move cursor here before scrolling (scroll targets cursor)
        unit:      "line" (discrete, like notched wheel) or "pixel" (smooth)
    """
    scroll_unit = (
        kCGScrollEventUnitPixel if unit == "pixel" else kCGScrollEventUnitLine
    )

    if direction == "down":
        v, h = -amount, 0
    elif direction == "up":
        v, h = amount, 0
    elif direction == "left":
        v, h = 0, amount
    elif direction == "right":
        v, h = 0, -amount
    else:
        raise ValueError(f"Unknown scroll direction: {direction!r}")

    # Optionally move cursor to target
    if x is not None and y is not None:
        move = Quartz.CGEventCreateMouseEvent(
            None,
            Quartz.kCGEventMouseMoved,
            Quartz.CGPointMake(float(x), float(y)),
            Quartz.kCGMouseButtonLeft,
        )
        CGEventPost(kCGHIDEventTap, move)
        await asyncio.sleep(0.05)

    # Post in batches of 10 (Apple-recommended range)
    remaining_v, remaining_h = v, h
    while remaining_v != 0 or remaining_h != 0:
        bv = max(-10, min(10, remaining_v))
        bh = max(-10, min(10, remaining_h))

        if h != 0:
            ev = CGEventCreateScrollWheelEvent(None, scroll_unit, 2, bv, bh)
        else:
            ev = CGEventCreateScrollWheelEvent(None, scroll_unit, 1, bv)

        CGEventPost(kCGHIDEventTap, ev)
        remaining_v -= bv
        remaining_h -= bh

        if remaining_v != 0 or remaining_h != 0:
            await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# Parsing xdotool-style key specs ("cmd+c", "Return", "ctrl+shift+s")
# ---------------------------------------------------------------------------

def parse_key_spec(key_str: str) -> tuple[str, list[str]]:
    """Parse an xdotool-style key spec into (main_key, modifiers).

    Examples:
        "Return"       -> ("return", [])
        "cmd+c"        -> ("c", ["command"])
        "cmd+shift+s"  -> ("s", ["command", "shift"])
        "Escape"       -> ("escape", [])
        "super+space"  -> ("space", ["command"])
    """
    parts = key_str.split("+")
    if len(parts) == 1:
        return (_resolve_key(parts[0]), [])

    modifiers = []
    for p in parts[:-1]:
        lower = p.lower()
        # Normalize modifier names
        if lower in ("super", "cmd", "command"):
            modifiers.append("command")
        elif lower in ("alt", "option"):
            modifiers.append("option")
        elif lower in ("ctrl", "control"):
            modifiers.append("control")
        elif lower == "shift":
            modifiers.append("shift")
        elif lower == "fn":
            modifiers.append("fn")
        else:
            modifiers.append(lower)

    main_key = _resolve_key(parts[-1])
    return (main_key, modifiers)
