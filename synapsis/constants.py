"""
Synapsis constants — centralized magic values and application-wide settings.

Keeps all hard-coded values in one place so they're easy to find and change.
"""

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

SESSION_ID_LENGTH: int = 8
"""Length of the UUID prefix used for session IDs."""

SESSION_TITLE_PREVIEW_LENGTH: int = 80
"""Max characters to use from first user message as session title."""

MAX_CONCURRENT_SESSIONS: int = 10
"""Max number of concurrent in-memory sessions (each with a CLI subprocess).

When this limit is reached, the oldest idle sessions are evicted before
creating new ones.  Override via ``SYNAPSIS_MAX_SESSIONS`` env var."""

SESSION_CREATION_RATE_WINDOW: int = 60
"""Sliding window (seconds) for the session creation rate limiter."""

SESSION_CREATION_RATE_LIMIT: int = 5
"""Max new chats ONE USER may start within ``SESSION_CREATION_RATE_WINDOW`` seconds.

Per user (was deployment-wide until 2026-09-26, so the 6th person to click
"New chat" in a minute was refused). Exceeding it returns an error frame and
keeps the WebSocket open. Override via ``IA_NEW_CHATS_PER_USER``."""

SESSION_CREATION_GLOBAL_RATE_LIMIT: int = 30
"""Deployment-wide safety net against reconnect storms (all users together).
Override via ``IA_NEW_CHATS_GLOBAL``."""

IDLE_SESSION_REAPER_INTERVAL: int = 300
"""Seconds between idle session reaper runs (5 minutes)."""

# ---------------------------------------------------------------------------
# Tool result handling
# ---------------------------------------------------------------------------

TOOL_RESULT_MAX_LENGTH: int = 8000
"""Max characters to store/send for a single tool result."""

OUTPUT_TEXT_MAX_LENGTH: int = 10000
"""Max characters to persist for a single step's output text."""

OUTPUT_PREVIEW_LENGTH: int = 200
"""Max characters for the output preview sent in step_complete events."""

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

MAX_CONTEXT_MEMORIES: int = 20
"""Max memories to inject into conversation context."""

# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

AUDIT_INPUT_MAX_LENGTH: int = 500
"""Max characters for tool input in audit log entries."""

AUDIT_OUTPUT_MAX_LENGTH: int = 300
"""Max characters for tool output in audit log entries."""

# ---------------------------------------------------------------------------
# Computer use
# ---------------------------------------------------------------------------

SCREENSHOT_PATH: str = "/tmp/synapsis_ss.png"
"""Temporary path for macOS screenshots."""

DEFAULT_SCREEN_WIDTH: int = 1920
DEFAULT_SCREEN_HEIGHT: int = 1080

SUBPROCESS_TIMEOUT_SHORT: int = 5
"""Timeout for quick subprocess calls (clicks, key presses)."""

SUBPROCESS_TIMEOUT_LONG: int = 10
"""Timeout for slower subprocess calls (screenshots, scroll)."""

SUBPROCESS_TIMEOUT_TYPE: int = 30
"""Timeout for text typing (can be slow for long strings)."""

# Computer use — JPEG quality and API constraints (for computer-use MCP server)
SCREENSHOT_JPEG_QUALITY: int = 75
"""JPEG quality for screenshots (0-100). 75 matches Claude Code's default."""

API_MAX_LONG_EDGE: int = 1568
"""Anthropic API maximum image dimension on longest edge."""

API_MAX_TOTAL_PIXELS: int = 1_150_000
"""Anthropic API maximum total pixels (approximately 1.15 megapixels)."""

POST_ACTION_DELAY: float = 0.3
"""Seconds to wait after click/type/key actions before returning."""

MOVE_SETTLE_MS: int = 50
"""Milliseconds to wait after mouse move for HID round-trip."""

# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

MAX_WS_MESSAGE_SIZE: int = 1_000_000
"""Max WebSocket message size in bytes (1 MB)."""

MAX_BUFFER_SIZE: int = 10 * 1024 * 1024
"""Max JSON buffer size for Claude SDK subprocess transport (10 MB).

The SDK default is 1 MB which is too small for responses that include
base64-encoded screenshots, large tool outputs, or PDF content.
Passed to ClaudeAgentOptions.max_buffer_size.
"""

STALL_TIMEOUT: int = 300
"""Seconds with no messages before considering a stream stalled (5 min).

Default for the stall watchdog in stream_handler.stream_response; the live
value is ``synapsis.config.STALL_TIMEOUT_SECONDS`` (env
``IA_STALL_TIMEOUT_SECONDS``)."""

TASK_CLEANUP_TIMEOUT: float = 5.0
"""Seconds to wait for cancelled tasks during cleanup."""

# ---------------------------------------------------------------------------
# Context window exhaustion message
# ---------------------------------------------------------------------------

CONTEXT_WINDOW_ERROR: str = (
    "This conversation has become too long for the model's context window. "
    "Please start a new chat to continue. Your history is preserved and can "
    "be reviewed in this session."
)

# ---------------------------------------------------------------------------
# User-facing runtime messages (English, no raw exception text -- details go
# to the server log only; see stream_core.classify_error)
# ---------------------------------------------------------------------------

CLI_RECONNECT_FAILED_ERROR: str = (
    "The assistant's session was interrupted and could not be restarted "
    "automatically. Please reload the page to continue. Your conversation "
    "history is preserved."
)

GENERIC_TURN_ERROR: str = (
    "Something went wrong while preparing this answer. Please try again. "
    "If it keeps happening, start a new chat."
)

STREAM_ENDED_EARLY_ERROR: str = (
    "The answer ended unexpectedly before it was complete. Please try again; "
    "if it keeps happening, start a new chat."
)

PROVIDER_BUSY_ERROR: str = (
    "The AI model provider is busy right now (rate limit or overload). "
    "Please wait a minute and try again."
)

PROVIDER_AUTH_ERROR: str = (
    "The assistant could not reach the AI model provider (service "
    "configuration). Please try again later or tell the administrator."
)

STALL_ERROR: str = (
    "This answer stopped making progress for {duration} and was stopped. "
    "Please try again, or ask a narrower question."
)

TURN_BUDGET_ERROR: str = (
    "This answer reached the per-question cost limit (${limit:.2f}) and was "
    "stopped. Try a narrower question or split it into smaller steps."
)

MAX_TURNS_ERROR: str = (
    "This answer reached the maximum number of steps ({limit}) and was "
    "stopped. Try a narrower question or split it into smaller steps."
)

REFUSAL_NO_FALLBACK_ERROR: str = (
    "The model declined to answer this request under its usage policy. "
    "Please rephrase the question."
)

NEW_CHAT_RATE_LIMIT_ERROR: str = (
    "You have started {limit} new chats in the last {window} seconds. "
    "Please wait a moment, or continue in one of your open chats."
)

GLOBAL_RATE_LIMIT_ERROR: str = (
    "Many new chats are being started right now. Please wait a few seconds "
    "and try again."
)

CAPACITY_ERROR: str = (
    "The assistant is at capacity ({limit} answers in progress). Please try "
    "again in a minute."
)

MODEL_NOT_ALLOWED_ERROR: str = "The model '{model}' is not available for your account."

DAILY_LIMIT_ERROR: str = (
    "You have reached today's usage limit for this test environment "
    "(${limit:.2f} per day). It resets at midnight UTC. If you need more, "
    "please contact {contact}."
)

# ---------------------------------------------------------------------------
# Memory categories
# ---------------------------------------------------------------------------

MEMORY_CATEGORIES: list[str] = [
    "user_profile",
    "project_context",
    "analysis_decision",
    "methodology_note",
    "best_practice",
    "escalation_record",
]

# ---------------------------------------------------------------------------
# Default model names (used as fallbacks in config.py)
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str = "claude-sonnet-5"
"""Default orchestrator model — Claude Sonnet 5 (fast, 1M context).

This is the default selection in the chat model-selector pill. Users can
switch the active session to Opus 5.5, Opus 5 or Fable 5.1 via the selector (see SELECTABLE_MODELS).
Override the server-wide default via the ``SYNAPSIS_MODEL`` env var."""

# ---------------------------------------------------------------------------
# Selectable models — exposed in the chat UI model-selector pill
# ---------------------------------------------------------------------------

SELECTABLE_MODELS: list[dict[str, str]] = [
    {"id": "claude-sonnet-5", "label": "Sonnet 5"},
    {"id": "claude-opus-5-5", "label": "Opus 5.5"},
    {"id": "claude-opus-5", "label": "Opus 5"},
    {"id": "claude-fable-5-1", "label": "Fable 5.1"},
    {"id": "claude-sonnet-4-6", "label": "Sonnet 4.6"},
    {"id": "claude-opus-4-8[1m]", "label": "Opus 4.8 (1M)"},
]
"""Curated models exposed in the chat UI model selector.

Each entry has an ``id`` (passed to the SDK as the model override) and a short
``label`` for the UI pill/dropdown. Sonnet 5 is the default; Opus 5.5, Opus 5 and Fable 5.1 support more demanding work.
Opus 5.5 (``claude-opus-5-5``, native 1M context, no ``[1m]`` suffix) is only served to Claude Code
CLI >= 2.1.280, i.e. claude-agent-sdk >= 0.2.159 (bundled CLI 2.1.281) — see requirements.txt.
Which curated entries a deployment actually exposes is decided by ``SYNAPSIS_AVAILABLE_MODELS``
(set per stage in .github/workflows/deploy.yml; Opus 5.5 is listed on DEV only for now).
Older entries remain available for existing sessions. Exposed via GET /api/config as
``selectable_models``."""

SELECTABLE_MODEL_IDS: set[str] = {m["id"] for m in SELECTABLE_MODELS}
"""Set of model IDs accepted by the ``switch_model`` WebSocket frame."""

# ---------------------------------------------------------------------------
# AUP / Policy error detection
# ---------------------------------------------------------------------------

AUP_ERROR_PATTERNS: list[str] = [
    "usage policy",
    "acceptable use policy",
    "appears to violate",
    "violate",
    "unable to respond to this request",
    "aup",
    "content policy",
    "safety policy",
]
"""Phrases that mark an *error string* as a policy refusal.

Only ever applied to error details (``ResultMessage.errors`` / the exception
of a failed turn), never to normal answer text -- the old code also scanned
every streamed answer, so ordinary answers mentioning e.g. "violate" raised a
bogus policy prompt (L3-13). Short tokens ("aup", "violate") match whole
words only, so "Taupe" or "inviolate" do not count."""

import re as _re

_AUP_RE = _re.compile(
    "|".join(
        (r"\b" + _re.escape(p) + r"\b") if p.isalpha() and len(p) <= 8 else _re.escape(p)
        for p in AUP_ERROR_PATTERNS
    ),
    _re.IGNORECASE,
)


def is_aup_error(error_message: str) -> bool:
    """Check if an *error* string indicates an AUP/policy refusal."""
    if not error_message:
        return False
    return _AUP_RE.search(error_message) is not None


def is_refusal_stop(stop_reason: str | None) -> bool:
    """True when the SDK reports the model refused (stop_reason ``refusal``)."""
    return (stop_reason or "").lower() == "refusal"


DEFAULT_FALLBACK_MODEL: str = "claude-opus-5"

# ---------------------------------------------------------------------------
# Available tools for custom agents
# ---------------------------------------------------------------------------

AVAILABLE_TOOLS: list[str] = [
    "Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebSearch", "WebFetch",
    # Computer use tools (computer-use MCP server)
    "mcp__computer-use__screenshot",
    "mcp__computer-use__left_click",
    "mcp__computer-use__right_click",
    "mcp__computer-use__double_click",
    "mcp__computer-use__triple_click",
    "mcp__computer-use__mouse_move",
    "mcp__computer-use__type",
    "mcp__computer-use__key",
    "mcp__computer-use__scroll",
    "mcp__computer-use__wait",
    "mcp__computer-use__left_click_drag",
]

# ---------------------------------------------------------------------------
# Agent display values
# ---------------------------------------------------------------------------

ORCHESTRATOR_COLOR: str = "hsl(270, 70%, 50%)"
"""HSL color string used for the orchestrator agent in the UI."""

DEFAULT_AGENT_COLOR: str = "#6366f1"
"""Default hex color applied to newly-created custom agents."""

# ---------------------------------------------------------------------------
# Chat Run Manager
# ---------------------------------------------------------------------------

CHAT_EVENT_BUFFER_MAX: int = 5000
"""Max events to buffer per chat session for late-joiner replay."""

CHAT_RUN_RETENTION_SECONDS: int = 600
"""Seconds to keep completed chat run handles (10 minutes)."""

CHAT_DETACHED_TASK_TIMEOUT: int = 1800
"""Seconds before auto-cancelling a detached chat task with no subscribers (30 min)."""

CHAT_SUBSCRIBER_QUEUE_SIZE: int = 1000
"""Max size of per-subscriber event queues."""

# ---------------------------------------------------------------------------
# Agent display values (continued)
# ---------------------------------------------------------------------------

ALLOWED_MODELS: set[str] = {"sonnet", "opus", *SELECTABLE_MODEL_IDS}
"""Set of model identifiers accepted by agent create/update endpoints."""


# ---------------------------------------------------------------------------
# Workflow status constants
# ---------------------------------------------------------------------------

class WorkflowStatus:
    """Status values for workflow definitions and pipeline runs."""
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Task / session status constants
# ---------------------------------------------------------------------------

class TaskStatus:
    """Status values for chat session tasks (stored in sessions.task_status)."""
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Truncation limits
# ---------------------------------------------------------------------------

OUTPUT_TEXT_MAX_LENGTH: int = 10000
"""Max characters to store for workflow step output text."""

OUTPUT_PREVIEW_LENGTH: int = 200
"""Max characters for output preview in workflow step logs."""

ERROR_TRUNCATION_LENGTH: int = 500
"""Max characters for error messages in workflow step logs."""
