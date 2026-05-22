"""
Slack notification MCP tool — wraps notify.sh for agent-initiated messaging.

Allows the agent to send Slack messages via the SmithClaw bot. Supports
DM to the default user, posting to a channel by name, DMing a specific
user, or posting to a channel by raw Slack ID.
"""

import asyncio
import os
from typing import Any

from claude_agent_sdk import tool

from synapsis.utils.responses import error_response, success_response

# ---------------------------------------------------------------------------
# Path to the notify.sh script
# ---------------------------------------------------------------------------

_WORKSPACE = os.path.expanduser("~/workspace")
NOTIFY_SCRIPT = os.path.join(_WORKSPACE, "scripts", "notify.sh")


# ---------------------------------------------------------------------------
# slack_notify tool
# ---------------------------------------------------------------------------

@tool(
    "slack_notify",
    "Send a Slack message via the SmithClaw bot. "
    "Can DM the default user (Jose), post to a channel by name, "
    "DM a specific user by username, or post to a channel by raw Slack ID. "
    "If no target is specified, the message is sent as a DM to Jose.",
    {
        "message": str,
        "channel": str,
        "user": str,
        "channel_id": str,
    },
)
async def slack_notify(args: dict[str, Any]) -> dict[str, Any]:
    """Send a Slack notification by shelling out to notify.sh.

    Args (via tool schema):
        message:    The message text to send (required).
        channel:    Channel name to post to, e.g. "#general" (optional).
        user:       Username to DM, e.g. "@jose" (optional).
        channel_id: Raw Slack channel ID to post to (optional).

    Returns:
        MCP-formatted success or error response.
    """
    message = args.get("message", "").strip()
    if not message:
        return error_response("Error: message is required")

    if not os.path.isfile(NOTIFY_SCRIPT):
        return error_response(
            f"Error: notify.sh not found at {NOTIFY_SCRIPT}"
        )

    # Build the command
    cmd: list[str] = [NOTIFY_SCRIPT]

    channel = args.get("channel", "").strip()
    user = args.get("user", "").strip()
    channel_id = args.get("channel_id", "").strip()

    if channel:
        cmd += ["-c", channel]
    elif user:
        cmd += ["-u", user]
    elif channel_id:
        cmd += ["-C", channel_id]

    cmd.append(message)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            return success_response(
                stdout.decode().strip() or "Message sent successfully"
            )
        else:
            err = stderr.decode().strip() or stdout.decode().strip()
            return error_response(f"notify.sh failed: {err}")

    except Exception as exc:
        return error_response(f"Error running notify.sh: {exc}")
