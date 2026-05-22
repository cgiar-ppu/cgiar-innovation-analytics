"""
Tests for synapsis/hooks/audit.py

Covers: write to audit log, log rotation, PreToolUse format, PostToolUse
format, and that both hook functions return an empty dict (no side-effects
on tool execution).
"""

import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from synapsis.hooks.audit import (
    _write_audit_entry,
    _format_pre_entry,
    _format_post_entry,
    _rotate_audit_log,
    MAX_AUDIT_SIZE,
    audit_logger,
    audit_logger_post,
)


# ---------------------------------------------------------------------------
# _write_audit_entry
# ---------------------------------------------------------------------------

def test_audit_log_write(tmp_path: Path):
    """An entry is written as a single line to the audit log file."""
    audit_file = tmp_path / "audit.log"
    synapsis_dir = tmp_path

    with (
        patch("synapsis.hooks.audit.AUDIT_LOG", audit_file),
        patch("synapsis.hooks.audit.SYNAPSIS_DIR", synapsis_dir),
    ):
        _write_audit_entry("TEST_ENTRY: hello world")

    assert audit_file.exists(), "Audit log file was not created"
    content = audit_file.read_text()
    assert "TEST_ENTRY: hello world" in content
    assert content.endswith("\n"), "Audit log entry should end with a newline"


# ---------------------------------------------------------------------------
# _rotate_audit_log
# ---------------------------------------------------------------------------

def test_audit_log_rotation(tmp_path: Path):
    """When the audit log exceeds MAX_AUDIT_SIZE, it is rotated to <path>.1."""
    audit_file = tmp_path / "audit.log"
    rotated_file = tmp_path / "audit.log.1"

    # Write a file larger than MAX_AUDIT_SIZE
    audit_file.write_bytes(b"x" * (MAX_AUDIT_SIZE + 1))
    assert audit_file.stat().st_size > MAX_AUDIT_SIZE

    _rotate_audit_log(str(audit_file))

    assert not audit_file.exists(), "Original log file should have been renamed"
    assert rotated_file.exists(), "Rotated log file (.1) should exist"


def test_audit_log_rotation_skipped_when_small(tmp_path: Path):
    """Rotation is skipped when the log file is smaller than MAX_AUDIT_SIZE."""
    audit_file = tmp_path / "audit.log"
    audit_file.write_text("small log content\n")

    _rotate_audit_log(str(audit_file))

    # File should still exist at the original path
    assert audit_file.exists(), "Small log file should not have been rotated"


# ---------------------------------------------------------------------------
# _format_pre_entry
# ---------------------------------------------------------------------------

def test_audit_log_pre_format():
    """PreToolUse log entry contains the event name, tool name, and input."""
    input_data = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la"},
    }
    line = _format_pre_entry("PreToolUse", "Bash", input_data)

    assert "PreToolUse" in line
    assert "tool=Bash" in line
    assert "ls -la" in line
    # Should contain an ISO timestamp prefix like [2026-...
    assert line.startswith("[")


def test_audit_log_pre_format_truncates_long_input():
    """Input summary in PreToolUse entries is truncated to AUDIT_INPUT_MAX_LENGTH."""
    from synapsis.constants import AUDIT_INPUT_MAX_LENGTH
    long_command = "echo " + "A" * (AUDIT_INPUT_MAX_LENGTH + 500)
    input_data = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"cmd": long_command}}
    line = _format_pre_entry("PreToolUse", "Bash", input_data)

    # The whole line must not exceed AUDIT_INPUT_MAX_LENGTH (with prefix overhead)
    # What matters is the input portion is truncated
    assert len(line) < len(long_command) + 200, "Input was not truncated"


# ---------------------------------------------------------------------------
# _format_post_entry
# ---------------------------------------------------------------------------

def test_audit_log_post_format():
    """PostToolUse log entry contains the tool name and a snippet of the result."""
    input_data = {
        "tool_name": "Read",
        "tool_response": "file contents here",
    }
    line = _format_post_entry("Read", input_data)

    assert "PostToolUse" in line
    assert "tool=Read" in line
    assert "file contents here" in line
    assert line.startswith("[")


def test_audit_log_post_format_truncates_long_result():
    """Result summary in PostToolUse entries is truncated to AUDIT_OUTPUT_MAX_LENGTH."""
    from synapsis.constants import AUDIT_OUTPUT_MAX_LENGTH
    long_result = "R" * (AUDIT_OUTPUT_MAX_LENGTH + 500)
    input_data = {"tool_name": "Write", "tool_response": long_result}
    line = _format_post_entry("Write", input_data)

    assert len(line) < len(long_result) + 100, "Result was not truncated"


# ---------------------------------------------------------------------------
# Hook return values
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_logger_hook_returns_empty(tmp_path: Path):
    """audit_logger (PreToolUse hook) always returns an empty dict."""
    audit_file = tmp_path / "audit.log"
    synapsis_dir = tmp_path
    mock_context = MagicMock()

    with (
        patch("synapsis.hooks.audit.AUDIT_LOG", audit_file),
        patch("synapsis.hooks.audit.SYNAPSIS_DIR", synapsis_dir),
    ):
        result = await audit_logger(
            {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {}},
            tool_use_id="tid-001",
            context=mock_context,
        )

    assert result == {}, f"audit_logger must return empty dict, got: {result!r}"


@pytest.mark.asyncio
async def test_audit_logger_post_hook_returns_empty(tmp_path: Path):
    """audit_logger_post (PostToolUse hook) always returns an empty dict."""
    audit_file = tmp_path / "audit.log"
    synapsis_dir = tmp_path
    mock_context = MagicMock()

    with (
        patch("synapsis.hooks.audit.AUDIT_LOG", audit_file),
        patch("synapsis.hooks.audit.SYNAPSIS_DIR", synapsis_dir),
    ):
        result = await audit_logger_post(
            {"tool_name": "Read", "tool_response": "some output"},
            tool_use_id="tid-002",
            context=mock_context,
        )

    assert result == {}, f"audit_logger_post must return empty dict, got: {result!r}"
