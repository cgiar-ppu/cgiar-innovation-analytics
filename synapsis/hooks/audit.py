"""
Audit logging hooks for tool invocation tracking.

This module provides two hooks that together create a complete audit trail of
every tool the agent calls:

- ``audit_logger``      — PreToolUse hook: records tool name + input summary
- ``audit_logger_post`` — PostToolUse hook: records tool name + result summary

Both hooks write append-only lines to the AUDIT_LOG file configured in
``synapsis.config``.  Failures are caught and logged via the standard logger
so that an audit-write error never interrupts the agent's tool pipeline.
"""

import os
from datetime import datetime
from typing import Any

from claude_agent_sdk import HookContext
from synapsis.config import AUDIT_LOG, SYNAPSIS_DIR, logger
from synapsis.constants import AUDIT_INPUT_MAX_LENGTH, AUDIT_OUTPUT_MAX_LENGTH

# ---------------------------------------------------------------------------
# Audit log rotation
# ---------------------------------------------------------------------------

MAX_AUDIT_SIZE = 10 * 1024 * 1024  # 10 MB


def _rotate_audit_log(path: str) -> None:
    """Rotate the audit log file when it exceeds MAX_AUDIT_SIZE.

    Keeps a single previous generation at ``<path>.1``.  Any OSError
    (permissions, missing parent, etc.) is silently swallowed so that a
    rotation failure never interrupts the hook pipeline.

    Args:
        path: Absolute filesystem path to the current audit log file.
    """
    try:
        if os.path.exists(path) and os.path.getsize(path) > MAX_AUDIT_SIZE:
            rotated = path + ".1"
            if os.path.exists(rotated):
                os.remove(rotated)
            os.rename(path, rotated)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _write_audit_entry(line: str) -> None:
    """Append a single line to the audit log file.

    Creates the .synapsis directory if it does not yet exist.  Handles I/O
    errors with a warning and all other unexpected errors with an error log
    so that audit failures never crash the hook pipeline.

    Args:
        line: The pre-formatted log line to append (without trailing newline).
    """
    try:
        SYNAPSIS_DIR.mkdir(parents=True, exist_ok=True)
        _rotate_audit_log(str(AUDIT_LOG))
        with open(AUDIT_LOG, "a") as f:
            f.write(line + "\n")
    except OSError as e:
        logger.warning("Audit log write failed (OSError): %s", e)
    except Exception as e:
        # Catch-all: audit writes must never crash the hook pipeline regardless
        # of what unexpected error the filesystem or runtime produces.
        logger.error("Audit log write failed (unexpected): %s", e)


def _format_pre_entry(event: str, tool_name: str, input_data: dict) -> str:
    """Format a PreToolUse audit log line.

    Args:
        event:      The hook event name string (e.g. "PreToolUse").
        tool_name:  The name of the tool being invoked.
        input_data: The full hook input dict (used to extract tool_input).

    Returns:
        A single-line string ready for appending to the audit log.
    """
    ts = datetime.now().isoformat()
    input_summary = str(input_data.get("tool_input", {}))[:AUDIT_INPUT_MAX_LENGTH]
    return f"[{ts}] {event} tool={tool_name} input={input_summary}"


def _format_post_entry(tool_name: str, input_data: dict) -> str:
    """Format a PostToolUse audit log line.

    Args:
        tool_name:  The name of the tool that was invoked.
        input_data: The full hook input dict (used to extract tool_response).

    Returns:
        A single-line string ready for appending to the audit log.
    """
    ts = datetime.now().isoformat()
    response = str(input_data.get("tool_response", ""))[:AUDIT_OUTPUT_MAX_LENGTH]
    return f"[{ts}] PostToolUse tool={tool_name} result={response}"


# ---------------------------------------------------------------------------
# PreToolUse hook: audit_logger
# ---------------------------------------------------------------------------

async def audit_logger(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Log all tool invocations to the audit log file.

    Captures the event name, tool name, and a truncated snapshot of the tool
    input before the tool executes.

    Args:
        input_data:   SDK-provided dict with ``hook_event_name``, ``tool_name``,
                      and ``tool_input``.
        tool_use_id:  Opaque identifier for this tool call (may be None).
        context:      SDK HookContext for the current agent run.

    Returns:
        Always an empty dict (this hook never modifies tool behaviour).
    """
    event = input_data.get("hook_event_name", "unknown")
    tool_name = input_data.get("tool_name", "unknown")
    _write_audit_entry(_format_pre_entry(event, tool_name, input_data))
    return {}


# ---------------------------------------------------------------------------
# PostToolUse hook: audit_logger_post
# ---------------------------------------------------------------------------

async def audit_logger_post(
    input_data: dict[str, Any], tool_use_id: str | None, context: HookContext
) -> dict[str, Any]:
    """Log tool results to the audit log file.

    Captures the tool name and a truncated snapshot of its response after
    execution completes.

    Args:
        input_data:   SDK-provided dict with ``tool_name`` and ``tool_response``.
        tool_use_id:  Opaque identifier for this tool call (may be None).
        context:      SDK HookContext for the current agent run.

    Returns:
        Always an empty dict (this hook never modifies tool behaviour).
    """
    tool_name = input_data.get("tool_name", "unknown")
    _write_audit_entry(_format_post_entry(tool_name, input_data))
    return {}
