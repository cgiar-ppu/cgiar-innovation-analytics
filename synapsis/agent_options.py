"""
Agent options builder — assembles the ClaudeAgentOptions for the SDK.

Centralizes tool lists, hook configuration, and MCP server registration
so both the WebSocket handler and the stateless query endpoint can share
the same agent configuration.
"""

import hashlib
import os
import re
from pathlib import Path
from typing import Optional

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from synapsis.config import (
    MODEL, FALLBACK_MODEL, MAX_TURNS, WORKSPACE, logger,
)
from synapsis.constants import MAX_BUFFER_SIZE
from synapsis.tools import synapsis_mcp
from synapsis.hooks import audit_logger, audit_logger_post
from synapsis.hooks.sandbox import build_sandbox_hooks
from synapsis.agents import build_system_prompt, load_all_agents
from synapsis.runtime_policy import sdk_fallback_model, turn_budget_usd  # Lane D: role-aware cost policy


# ---------------------------------------------------------------------------
# System-prompt file (per build, content-addressed)
# ---------------------------------------------------------------------------
# On Linux the system prompt (~131 KB) exceeds ARG_MAX when passed as a CLI
# argument, so it is written to a file and passed via --system-prompt-file.
# Review L3-14: a single shared /tmp/cgiar-ia-system-prompt.txt was truncated
# and rewritten by every client build, so a CLI starting at the same moment
# could read a half-written or different prompt. Each distinct prompt now gets
# its own content-hashed file, written atomically (temp file + os.replace):
# a reader always sees a complete file whose content matches its name.
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT_DIR = Path(os.getenv("IA_SYSTEM_PROMPT_DIR", "/tmp"))
_SYSTEM_PROMPT_PREFIX = "cgiar-ia-system-prompt-"


def _write_system_prompt_file(prompt_text: str) -> dict:
    """Write the prompt to a content-hashed file and return a SystemPromptFile dict.

    Falls back to the inline string if the file cannot be written.
    """
    digest = hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:20]
    target = _SYSTEM_PROMPT_DIR / f"{_SYSTEM_PROMPT_PREFIX}{digest}.txt"
    try:
        if not target.is_file():
            tmp = target.with_name(f".{target.name}.{os.getpid()}.{os.urandom(4).hex()}")
            tmp.write_text(prompt_text, encoding="utf-8")
            os.replace(tmp, target)
        logger.debug("System prompt file %s (%d chars)", target, len(prompt_text))
    except OSError as exc:
        logger.warning(
            "Could not write system prompt file %s: %s — falling back to inline",
            target,
            exc,
        )
        return prompt_text  # type: ignore[return-value]
    return {"type": "file", "path": str(target)}


# ---------------------------------------------------------------------------
# End-user sandbox: IA-only tools (review 2026-09-23 P0-2 / L3-09)
# ---------------------------------------------------------------------------
# The orchestrator and every specialist run for CGIAR staff and invited
# externals. They get exactly the capabilities the product needs: PRMS data
# tools, charts, dashboards, documents, the user's own chat history, web
# search, and read-only access to references / the user's own files. There is
# NO shell (Bash), NO file writing (Write/Edit/NotebookEdit), no memory,
# custom-agent, fleet, Slack, image-generation, TTS-settings or computer-use
# tools. Files reach the user only through create_document / html_dashboard,
# which write into the caller's own area (synapsis/user_files.py).
# ---------------------------------------------------------------------------

#: Built-in CLI tools the agent may see at all (passed as ``tools=``: the base
#: set; anything else — Bash, Write, Edit, ... — does not exist for the model).
IA_BUILTIN_TOOLS: list[str] = [
    "Read", "Glob", "Grep",          # path-confined by hooks/sandbox.py
    "WebSearch",                     # server-side web search
    "WebFetch",                      # SSRF-guarded by hooks/sandbox.py
    "TodoWrite",
    "Task",                          # delegate to the IA specialists
]

#: MCP tools served in-process by the ``synapsis`` server (tools/__init__.py).
IA_MCP_TOOLS: list[str] = [
    "mcp__synapsis__prms_query",
    "mcp__synapsis__prms_search",
    "mcp__synapsis__create_chart",
    "mcp__synapsis__scenario_analysis",
    "mcp__synapsis__partner_identification",
    "mcp__synapsis__html_dashboard",
    "mcp__synapsis__create_document",
    "mcp__synapsis__history_search",
    "mcp__synapsis__history_retrieve",
    "mcp__synapsis__history_index",
    "mcp__synapsis__history_list",
]

#: Auto-approved tools (orchestrator). Sub-agents' ``tools=`` lists are subsets.
ALLOWED_TOOLS: list[str] = IA_BUILTIN_TOOLS + IA_MCP_TOOLS

#: Names the tool gate hook accepts ("Agent" is the CLI's current name for Task).
_GATE_ALLOWED: list[str] = ALLOWED_TOOLS + ["Agent"]

#: Explicitly removed from the model's context (belt and braces with ``tools=``
#: and the tool-gate hook). Unknown names are ignored by the CLI.
DISALLOWED_TOOLS: list[str] = [
    "Bash", "BashOutput", "KillShell", "KillBash", "Monitor", "PowerShell",
    "Write", "Edit", "MultiEdit", "NotebookEdit",
    "Skill", "SlashCommand", "AskUserQuestion", "ExitPlanMode", "EnterWorktree",
    "CronCreate", "CronDelete", "CronList", "RemoteTrigger", "TeamCreate",
    "SendMessage", "Workflow", "Sleep",
    "ListMcpResourcesTool", "ReadMcpResourceTool",
    "mcp__synapsis__memory_store", "mcp__synapsis__memory_recall",
    "mcp__synapsis__memory_list", "mcp__synapsis__memory_forget",
    "mcp__synapsis__agent_create", "mcp__synapsis__agent_list",
    "mcp__synapsis__agent_update", "mcp__synapsis__slack_notify",
    "mcp__synapsis__image_generate", "mcp__synapsis__image_edit",
    "mcp__synapsis__tts_set_voice", "mcp__synapsis__tts_get_voices",
    "mcp__synapsis__fleet_create", "mcp__synapsis__fleet_spawn",
    "mcp__synapsis__fleet_resume", "mcp__synapsis__fleet_mediate",
    "mcp__synapsis__fleet_status", "mcp__synapsis__fleet_inspect",
    "mcp__synapsis__fleet_initialize",
]

#: With the tool set above, the tool-gate hook and the path/SSRF hooks,
#: every capability the agent has is enumerated and guarded, so skipping the
#: interactive permission prompt (there is no human at a terminal) is safe.
#: See the Lane A report for why this stays ``bypassPermissions``.
AGENT_PERMISSION_MODE = "bypassPermissions"


# ---------------------------------------------------------------------------
# Agent subprocess environment — secrets stripped (review L1-03 / L3-02)
# ---------------------------------------------------------------------------
# The SDK starts the CLI with {**os.environ, **options.env}. Every secret the
# server holds (JWT signing key, OpenAI key, SSO secrets, AWS credentials,
# Litestream credentials, ...) is overridden with an empty value. Only what the
# CLI needs to call the model is kept.
# ---------------------------------------------------------------------------

#: Credentials the Claude CLI itself needs to reach the model API.
_CLI_CREDENTIAL_KEYS = frozenset({
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
})

#: Always blanked, even when not currently set (defence against late export).
_ALWAYS_BLANK = ("IA_JWT_SECRET", "OPENAI_API_KEY", "AWS_ACCESS_KEY_ID",
                 "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")

_SECRET_NAME = re.compile(
    r"(SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|PRIVATE|APIKEY|API_KEY|_KEY$|_KEY_|"
    r"^AWS_|^LITESTREAM_|DATABASE_URL|_DSN$|SESSION_KEY|COOKIE)",
    re.IGNORECASE,
)


def agent_env(environ: Optional[dict] = None) -> dict[str, str]:
    """Environment overrides for the agent CLI: every secret blanked."""
    src = os.environ if environ is None else environ
    env = {k: "" for k in _ALWAYS_BLANK}
    for key in src:
        if key in _CLI_CREDENTIAL_KEYS:
            continue
        if _SECRET_NAME.search(key):
            env[key] = ""
    # Keep MCP tools loaded up front (never deferred behind ToolSearch): the
    # model must see create_document / prms_query on the first turn.
    env["ENABLE_TOOL_SEARCH"] = "false"
    return env


# ---------------------------------------------------------------------------
# Hooks
# ---------------------------------------------------------------------------

def _build_hooks(owner_id: Optional[str]) -> dict:
    """Hook configuration for one client, bound to its owner.

    PreToolUse: the sandbox (tool gate, Read/Glob/Grep confinement, WebFetch
    SSRF guard) plus the audit trail. PostToolUse: audit trail. The old
    Bash-pattern ``safety_validator`` is not registered: Bash is not available.
    """
    return {
        "PreToolUse": build_sandbox_hooks(owner_id, _GATE_ALLOWED)
        + [HookMatcher(hooks=[audit_logger])],
        "PostToolUse": [HookMatcher(hooks=[audit_logger_post])],
    }


def _current_owner() -> str:
    """The verified identity of the connection/request building the client."""
    from synapsis.auth.context import get_current_user_id

    return get_current_user_id()


async def build_agent_options(
    resume_session_id: str = "",
    model_override: Optional[str] = None,
) -> ClaudeAgentOptions:
    """Build a sandboxed ClaudeAgentOptions instance for the IA orchestrator.

    The caller's identity is read from the connection/request context
    (``synapsis.auth.context``) and bound into the sandbox hooks, so the
    agent can only read that user's files.

    Args:
        resume_session_id: If provided, resumes an existing Claude SDK session
                          (used for session persistence across reconnects).
        model_override:    If provided, use this model instead of the configured MODEL.

    Returns:
        Fully configured ClaudeAgentOptions ready for ClaudeSDKClient or query().
    """
    # Builtin IA specialists only (custom DB agents are never injected).
    all_agents = await load_all_agents()
    owner_id = _current_owner()

    sp = _write_system_prompt_file(build_system_prompt(all_agents))
    opts = ClaudeAgentOptions(
        tools=list(IA_BUILTIN_TOOLS),
        allowed_tools=list(ALLOWED_TOOLS),
        disallowed_tools=list(DISALLOWED_TOOLS),
        permission_mode=AGENT_PERMISSION_MODE,
        system_prompt=sp,
        cwd=str(WORKSPACE),
        model=model_override if model_override else MODEL,
        # Lane D: no silent escalation to a model the caller's role may not use.
        fallback_model=sdk_fallback_model(model_override),
        max_turns=MAX_TURNS,
        # Lane D: per-question spend ceiling for the caller's role (SDK stops
        # the turn with subtype error_max_budget_usd).
        max_budget_usd=turn_budget_usd(),
        agents=all_agents,
        include_partial_messages=True,
        mcp_servers={"synapsis": synapsis_mcp},
        strict_mcp_config=True,
        hooks=_build_hooks(owner_id),
        # No user/project settings: nothing on the host (e.g. a permissive
        # .claude/settings.json allow-list or hooks) can widen the sandbox.
        setting_sources=[],
        # Deliver prompts verbatim: no ``@/path`` file-mention expansion (which
        # would read files without a tool call, bypassing the hooks) and no
        # slash-command dispatch.
        verbatim_prompts=True,
        env=agent_env(),
        max_buffer_size=MAX_BUFFER_SIZE,
    )

    if resume_session_id:
        opts.resume = resume_session_id
        logger.info("Building agent options with resume=%s", resume_session_id)

    return opts


async def build_generic_agent_options(
    resume_session_id: str = "",
    model_override: Optional[str] = None,
) -> ClaudeAgentOptions:
    """Former "generic orchestrator" (Synapsis workflows / /ws/agent).

    The generic, non-CGIAR prompt is gone (review L3-14/L7-05): its only
    callers were the removed workflow/agent sockets and routes. Kept as an
    alias so any remaining import gets the same sandboxed IA options.
    """
    return await build_agent_options(resume_session_id, model_override)
