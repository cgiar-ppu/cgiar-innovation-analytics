"""
Agent options builder — assembles the ClaudeAgentOptions for the SDK.

Centralizes tool lists, hook configuration, and MCP server registration
so both the WebSocket handler and the stateless query endpoint can share
the same agent configuration.
"""

from typing import Optional

from claude_agent_sdk import ClaudeAgentOptions, HookMatcher

from synapsis.config import (
    MODEL, FALLBACK_MODEL, MAX_TURNS, WORKSPACE, PROJECT_DIR,
    SAFETY_HOOKS_ENABLED, logger,
)
from synapsis.constants import MAX_BUFFER_SIZE
from synapsis.tools import synapsis_mcp, computer_use_mcp
from synapsis.hooks import safety_validator, audit_logger, audit_logger_post
from synapsis.agents import build_system_prompt, load_all_agents


# ---------------------------------------------------------------------------
# Skills discovery — symlink .claude/ into the workspace directory
# ---------------------------------------------------------------------------
# The SDK discovers SKILL.md files under <cwd>/.claude/skills/.  We keep cwd
# as WORKSPACE (~/workspace) so all file tools work there, but symlink the
# project's .claude directory into WORKSPACE so the CLI finds skills.
# The symlink is created once at import time and is idempotent.
# ---------------------------------------------------------------------------

_project_claude_dir = PROJECT_DIR / ".claude"
_workspace_claude_dir = WORKSPACE / ".claude"

if _project_claude_dir.is_dir():
    _needs_link = False
    if _workspace_claude_dir.is_symlink():
        # Verify existing symlink points to the CURRENT project, not a stale one
        _current_target = _workspace_claude_dir.resolve()
        _expected_target = _project_claude_dir.resolve()
        if _current_target != _expected_target:
            logger.warning(
                "Stale .claude symlink: %s → %s (expected %s). Recreating.",
                _workspace_claude_dir, _current_target, _expected_target,
            )
            _workspace_claude_dir.unlink()
            _needs_link = True
    elif not _workspace_claude_dir.exists():
        _needs_link = True

    if _needs_link:
        try:
            _workspace_claude_dir.symlink_to(_project_claude_dir)
            logger.info("Symlinked %s → %s for skill discovery",
                         _workspace_claude_dir, _project_claude_dir)
        except OSError as exc:
            logger.warning("Could not symlink .claude for skills: %s", exc)


# ---------------------------------------------------------------------------
# Allowed tools for the main orchestrator
# ---------------------------------------------------------------------------

ALLOWED_TOOLS: list[str] = [
    # Built-in SDK tools
    "Read", "Write", "Edit", "Bash",
    "Glob", "Grep",
    "WebSearch", "WebFetch",
    "TodoWrite",
    "Task",
    # Skill and deferred-tool support
    "Skill",
    "ToolSearch",
    # MCP memory tools
    "mcp__synapsis__memory_store",
    "mcp__synapsis__memory_recall",
    "mcp__synapsis__memory_list",
    "mcp__synapsis__memory_forget",
    # MCP computer use tools (separate computer-use server)
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
    # MCP agent management tools
    "mcp__synapsis__agent_create",
    "mcp__synapsis__agent_list",
    "mcp__synapsis__agent_update",
    # MCP Slack notification tool
    "mcp__synapsis__slack_notify",
    # MCP fleet management tools
    "mcp__synapsis__fleet_create",
    "mcp__synapsis__fleet_spawn",
    "mcp__synapsis__fleet_resume",
    "mcp__synapsis__fleet_mediate",
    "mcp__synapsis__fleet_status",
    "mcp__synapsis__fleet_inspect",
    "mcp__synapsis__fleet_initialize",
]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_hooks() -> dict:
    """Build the hook configuration dict shared by all agent option builders.

    When SAFETY_HOOKS_ENABLED is true, a Bash-specific pre-tool hook runs
    ``safety_validator`` before the catch-all ``audit_logger`` hook.  When
    disabled, only the audit logger is attached so every tool call is still
    recorded without the safety gate.

    Returns:
        A dict suitable for passing directly as the ``hooks`` kwarg of
        ``ClaudeAgentOptions``.
    """
    pre_tool_hooks = (
        [
            HookMatcher(matcher="Bash", hooks=[safety_validator]),
            HookMatcher(hooks=[audit_logger]),
        ]
        if SAFETY_HOOKS_ENABLED
        else [HookMatcher(hooks=[audit_logger])]
    )
    return {
        "PreToolUse": pre_tool_hooks,
        "PostToolUse": [HookMatcher(hooks=[audit_logger_post])],
    }


async def build_agent_options(
    resume_session_id: str = "",
    model_override: Optional[str] = None,
) -> ClaudeAgentOptions:
    """Build a ClaudeAgentOptions instance for the main orchestrator.

    Args:
        resume_session_id: If provided, resumes an existing Claude SDK session
                          (used for session persistence across reconnects).
        model_override:    If provided, use this model instead of the configured MODEL.

    Returns:
        Fully configured ClaudeAgentOptions ready for ClaudeSDKClient or query().
    """
    # Load all agents (builtin + custom from DB)
    all_agents = await load_all_agents()

    opts = ClaudeAgentOptions(
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        system_prompt=build_system_prompt(all_agents),
        cwd=str(WORKSPACE),
        model=model_override if model_override else MODEL,
        fallback_model=FALLBACK_MODEL,
        max_turns=MAX_TURNS,
        agents=all_agents,
        include_partial_messages=True,
        mcp_servers={"synapsis": synapsis_mcp, "computer-use": computer_use_mcp},
        hooks=_build_hooks(),
        setting_sources=["project"],
        max_buffer_size=MAX_BUFFER_SIZE,
    )

    if resume_session_id:
        opts.resume = resume_session_id
        logger.info("Building agent options with resume=%s", resume_session_id)

    return opts


def _build_generic_system_prompt(agents_dict: dict) -> str:
    """Build the system prompt for the generic orchestrator.

    Lists every available specialist agent dynamically so the prompt stays
    accurate as agents are added or removed.

    Args:
        agents_dict: Mapping of agent_id -> AgentDefinition for all loaded agents.

    Returns:
        The full system prompt string for the generic orchestrator.
    """
    agent_lines = ""
    for agent_id, agent_def in agents_dict.items():
        desc = agent_def.description
        if len(desc) > 120:
            desc = desc[:117] + "..."
        agent_lines += f"- **{agent_id}**: {desc}\n"

    return f"""You are a general-purpose AI orchestrator that delegates tasks to specialist sub-agents.

Your role is to:
1. Understand the user's request
2. Break it into sub-tasks if needed
3. Delegate to the appropriate specialist agent
4. Synthesize results and present a coherent response

You have access to the following specialist agents via the Task tool. Choose the best agent for each sub-task.

Available agents:
{agent_lines}
## Guidelines
- Always explain your reasoning for which agent you chose
- If a task needs multiple agents, run them in sequence
- Synthesize outputs from different agents into a coherent response
- You can also handle simple tasks directly without delegation
"""


async def build_generic_agent_options(
    resume_session_id: str = "",
    model_override: Optional[str] = None,
) -> ClaudeAgentOptions:
    """Build a ClaudeAgentOptions instance for the generic (non-Synapsis) orchestrator.

    Uses a minimal, domain-agnostic system prompt that simply lists available
    agents and describes the delegation workflow — no analytics-specific context.

    Args:
        resume_session_id: If provided, resumes an existing Claude SDK session.
        model_override:    If provided, use this model instead of the configured MODEL.

    Returns:
        Fully configured ClaudeAgentOptions ready for ClaudeSDKClient or query().
    """
    all_agents = await load_all_agents()

    opts = ClaudeAgentOptions(
        allowed_tools=ALLOWED_TOOLS,
        permission_mode="bypassPermissions",
        system_prompt=_build_generic_system_prompt(all_agents),
        cwd=str(WORKSPACE),
        model=model_override if model_override else MODEL,
        fallback_model=FALLBACK_MODEL,
        max_turns=MAX_TURNS,
        agents=all_agents,
        include_partial_messages=True,
        mcp_servers={"synapsis": synapsis_mcp, "computer-use": computer_use_mcp},
        hooks=_build_hooks(),
        setting_sources=["project"],
        max_buffer_size=MAX_BUFFER_SIZE,
    )

    if resume_session_id:
        opts.resume = resume_session_id
        logger.info("Building generic agent options with resume=%s", resume_session_id)

    return opts
