"""
Pre-tool safety validation hooks for dangerous command detection.

This module provides a PreToolUse hook that inspects every Bash invocation
and denies execution when the command matches a set of known-dangerous
patterns (destructive filesystem operations, fork bombs, etc.).

The hook is only wired into the agent when SYNAPSIS_SAFETY_HOOKS is enabled
(see agent_options.py).  Even when disabled, the patterns and compiled
regexes are kept here for reference and potential reuse.
"""

import re
from typing import Any

from claude_agent_sdk import HookContext
from synapsis.config import logger


# ---------------------------------------------------------------------------
# Dangerous command patterns (regex strings)
# ---------------------------------------------------------------------------

# Each entry is a raw regex pattern.  We keep the human-readable strings
# around so we can include the offending pattern in the denial reason.
DANGEROUS_PATTERNS: list[str] = [
    r"rm\s+-rf\s+/\s",           # rm -rf / (with trailing space)
    r"rm\s+-rf\s+/\s*$",         # rm -rf / (end of string)
    r"mkfs\.",                    # any mkfs.* (formats a filesystem)
    r"dd\s+if=.*of=/dev/",        # dd writing directly to a block device
    r":\(\)\s*\{\s*:\|:\s*&\s*\}",  # classic fork bomb :(){:|:&};:
    r"chmod\s+-R\s+777\s+/\s",   # recursive world-writable on root
    r"DROP\s+DATABASE",           # SQL: drop entire database
    r"DROP\s+TABLE",              # SQL: drop a table
]

# Pre-compiled versions of DANGEROUS_PATTERNS for faster repeated matching.
# Stored as (compiled_pattern, original_string) so we can report which
# pattern triggered the block.
_COMPILED_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(p, re.IGNORECASE), p) for p in DANGEROUS_PATTERNS
]


# ---------------------------------------------------------------------------
# PreToolUse hook: safety_validator
# ---------------------------------------------------------------------------

async def safety_validator(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Block bash commands that match dangerous patterns.

    Called by the Claude Agent SDK for every PreToolUse event.  Only examines
    Bash tool invocations (other tools pass through immediately).

    Args:
        input_data:   SDK-provided dict with keys ``hook_event_name``,
                      ``tool_name``, and ``tool_input``.
        tool_use_id:  Opaque identifier for this tool call (may be None).
        context:      SDK HookContext for the current agent run.

    Returns:
        A dict with a ``hookSpecificOutput`` deny decision if the command is
        dangerous, or an empty dict to allow the tool call to proceed.
    """
    # This hook only applies to PreToolUse events
    if input_data.get("hook_event_name") != "PreToolUse":
        return {}

    command = input_data.get("tool_input", {}).get("command", "")

    for compiled, raw_pattern in _COMPILED_PATTERNS:
        if compiled.search(command):
            logger.warning("BLOCKED dangerous command: %s", command[:200])
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        f"Blocked: dangerous command pattern detected ({raw_pattern})"
                    ),
                }
            }

    # No dangerous pattern found — allow the command
    return {}
