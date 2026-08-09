"""
Stateless single-query endpoint — fire-and-forget agent interaction.

- POST /api/query — Send a message, get the full response (non-streaming).

Unlike the WebSocket endpoint, this creates a fresh agent for each request
and does not maintain session state.
"""

from fastapi import APIRouter, HTTPException

from claude_agent_sdk import (
    query,
    AssistantMessage,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
)
from synapsis.agent_options import build_agent_options
from synapsis.models import QueryRequest
from synapsis.persona import (
    PersonaValidationError,
    apply_persona_to_message,
    describe_persona,
    normalize_persona,
)
from synapsis.scope import (
    ScopeValidationError,
    apply_scope_to_message,
    describe_scope,
    normalize_scope,
)

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query")
async def api_query(payload: QueryRequest):
    """Process a single query and return the complete response.

    Honours the optional ``scope`` object (year / programme filters) and the
    optional ``agent`` selection the same way the chat WebSocket does: each is
    rendered into a preamble prepended to the message handed to the agent, so
    the answer is constrained to — and states — the active slice, and is routed
    to the specialist the caller asked for.

    Returns:
        response: Combined text output
        tool_uses: List of tools the agent invoked
        result: Cost, turns, and duration metadata
        scope: The normalized active scope echoed back (empty when unscoped)
        agent: The normalized specialist id echoed back ("" when unselected)
    """
    try:
        scope = normalize_scope(payload.scope)
    except ScopeValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid data scope: {exc}") from None

    try:
        persona = normalize_persona(payload.agent)
    except PersonaValidationError as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid agent selection: {exc}"
        ) from None

    user_msg = apply_persona_to_message(
        apply_scope_to_message(payload.message.strip(), scope), persona
    )

    options = await build_agent_options()

    texts: list[str] = []
    tool_uses: list[dict] = []
    result_info: dict = {}

    async for message in query(prompt=user_msg, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
                elif isinstance(block, ToolUseBlock):
                    tool_uses.append({"tool": block.name, "input": block.input})
        elif isinstance(message, ResultMessage):
            result_info = {
                "estimated_cost": message.total_cost_usd,
                "turns": message.num_turns,
                "duration_ms": message.duration_ms,
            }

    return {
        "response": "\n".join(texts),
        "tool_uses": tool_uses,
        "result": result_info,
        "scope": scope,
        "scope_description": describe_scope(scope),
        "agent": persona,
        "agent_description": describe_persona(persona),
    }
