"""
Tests for synapsis/hooks/safety.py

Verifies that the pre-compiled DANGEROUS_PATTERNS list and safety_validator()
hook correctly block known-dangerous commands and allow safe ones.

The tests call the pattern-matching logic directly (no SDK required) so they
run without any external dependencies.
"""

import re
import pytest
from unittest.mock import MagicMock

from synapsis.hooks.safety import (
    _COMPILED_PATTERNS,
    DANGEROUS_PATTERNS,
    safety_validator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _matches_any_pattern(command: str) -> bool:
    """Return True if *command* is blocked by at least one compiled pattern."""
    return any(pattern.search(command) for pattern, _ in _COMPILED_PATTERNS)


# ---------------------------------------------------------------------------
# Dangerous commands must be blocked
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "rm -rf / ",                          # trailing space variant
    "rm -rf /",                           # end-of-string variant
    "mkfs.ext4 /dev/sda1",               # filesystem format
    "mkfs.vfat /dev/sdb",                # another mkfs variant
    "dd if=/dev/zero of=/dev/sda",        # dd to block device
    "dd if=/dev/urandom of=/dev/nvme0n1", # dd NVMe device
    ":(){:|:&};:",                         # classic fork bomb
    "chmod -R 777 / ",                    # recursive world-writable on root
    "DROP DATABASE production;",          # SQL DROP DATABASE
    "DROP TABLE users;",                  # SQL DROP TABLE
    "drop database mydb",                 # lowercase SQL DROP DATABASE
    "drop table orders",                  # lowercase SQL DROP TABLE
])
def test_dangerous_commands_blocked(command: str):
    """Each known-dangerous command must match at least one compiled pattern."""
    assert _matches_any_pattern(command), (
        f"Expected command to be blocked but it passed through: {command!r}"
    )


# ---------------------------------------------------------------------------
# Safe commands must be allowed
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "ls -la /home/user",
    "python script.py",
    "cat file.txt",
    "pip install pandas",
    "echo 'hello world'",
    "git status",
    "mkdir -p /workspace/outputs",
    "cp data.csv /tmp/backup.csv",
    "grep -r 'pattern' /workspace/",
    "find /workspace -name '*.py'",
    "rm file.txt",                        # plain rm (not -rf /)
    "rm -rf /tmp/mytemp",                 # rm -rf on a non-root path
    "rm -rf ./build",                     # rm -rf on a relative path
    "SELECT * FROM users;",               # safe SQL SELECT
    "CREATE TABLE foo (id INT);",         # safe SQL CREATE
    "chmod 755 script.sh",                # safe chmod (not -R 777 /)
    "chmod -R 755 /home/user/project",    # chmod -R but not on /
])
def test_safe_commands_allowed(command: str):
    """Safe commands must not match any dangerous pattern."""
    assert not _matches_any_pattern(command), (
        f"Expected command to be allowed but it was blocked: {command!r}"
    )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_rm_rf_slash_requires_slash_at_end():
    """'rm -rf /tmp' must be allowed; only 'rm -rf /' (root) is blocked."""
    assert not _matches_any_pattern("rm -rf /tmp/something")
    assert _matches_any_pattern("rm -rf / ")   # trailing space = blocked
    assert _matches_any_pattern("rm -rf /")    # EOL = blocked


def test_mkfs_prefix_blocking():
    """Any mkfs.* variant (ext4, vfat, ntfs, etc.) is blocked."""
    for variant in ("mkfs.ext4", "mkfs.vfat", "mkfs.ntfs", "mkfs.btrfs"):
        assert _matches_any_pattern(f"{variant} /dev/sda"), (
            f"{variant} should be blocked"
        )


def test_dd_only_blocked_when_writing_to_device():
    """dd if=... is only blocked when writing to /dev/; reading from it is not."""
    # Writing to a device — must be blocked
    assert _matches_any_pattern("dd if=/dev/zero of=/dev/sda")
    # Writing to a file — must be allowed
    assert not _matches_any_pattern("dd if=/dev/zero of=/tmp/testfile bs=1M count=10")


def test_patterns_are_case_insensitive():
    """All patterns are compiled with re.IGNORECASE."""
    assert _matches_any_pattern("DROP DATABASE mydb")
    assert _matches_any_pattern("drop database mydb")
    assert _matches_any_pattern("Drop Database MyDb")


def test_patterns_list_nonempty():
    """Sanity check: the DANGEROUS_PATTERNS list must not be empty."""
    assert len(DANGEROUS_PATTERNS) > 0
    assert len(_COMPILED_PATTERNS) == len(DANGEROUS_PATTERNS)


# ---------------------------------------------------------------------------
# safety_validator hook function
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safety_validator_blocks_dangerous_command():
    """safety_validator returns a deny decision for a dangerous command."""
    mock_context = MagicMock()
    input_data = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},
    }

    result = await safety_validator(input_data, tool_use_id="tid-001", context=mock_context)

    assert "hookSpecificOutput" in result
    decision = result["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "Blocked" in decision["permissionDecisionReason"]


@pytest.mark.asyncio
async def test_safety_validator_allows_safe_command():
    """safety_validator returns an empty dict (allow) for a safe command."""
    mock_context = MagicMock()
    input_data = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "ls -la /workspace"},
    }

    result = await safety_validator(input_data, tool_use_id="tid-002", context=mock_context)

    assert result == {}, f"Expected empty dict (allow), got: {result!r}"


@pytest.mark.asyncio
async def test_safety_validator_ignores_non_pretooluse_events():
    """safety_validator returns empty dict for events other than PreToolUse."""
    mock_context = MagicMock()
    input_data = {
        "hook_event_name": "PostToolUse",    # not a PreToolUse event
        "tool_name": "Bash",
        "tool_input": {"command": "rm -rf /"},   # dangerous, but wrong event
    }

    result = await safety_validator(input_data, tool_use_id="tid-003", context=mock_context)

    assert result == {}, (
        "safety_validator should ignore PostToolUse events entirely"
    )


@pytest.mark.asyncio
async def test_safety_validator_allows_non_bash_tools():
    """safety_validator only examines Bash commands; other tools pass through."""
    mock_context = MagicMock()
    # A non-Bash tool with a dangerous-looking name — still not a bash command
    input_data = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"path": "/etc/passwd"},
    }

    # No "command" key in tool_input, so no pattern match should occur
    result = await safety_validator(input_data, tool_use_id="tid-004", context=mock_context)

    assert result == {}


@pytest.mark.asyncio
async def test_safety_validator_sql_drop_database_blocked():
    """DROP DATABASE in a tool input is blocked."""
    mock_context = MagicMock()
    input_data = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "psql -c 'DROP DATABASE production'"},
    }

    result = await safety_validator(input_data, tool_use_id="tid-005", context=mock_context)

    assert result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
