"""
Chat history MCP tools — search, retrieve, and index past conversations.

Provides three tools the agent can call:
- history_search:   Search across all past conversations by keyword (FTS5)
- history_retrieve: Retrieve a full conversation, clean (no tool noise)
- history_index:    Build/rebuild the search index (incremental or full)
"""

from typing import Any

from claude_agent_sdk import tool
from synapsis.database.history import (
    search_history,
    retrieve_conversation,
    index_all_sessions,
    list_indexed_sessions,
)
from synapsis.utils.responses import error_response, success_response


# ---------------------------------------------------------------------------
# history_search
# ---------------------------------------------------------------------------

@tool("history_search", "Search past conversations by keyword across all chat sessions", {
    "query": str,
    "limit": int,
    "session_id": str,
})
async def history_search(args: dict[str, Any]) -> dict[str, Any]:
    """Search across all past Synapsis conversations using FTS5 full-text search.

    Supports FTS5 query syntax: keywords, "quoted phrases", OR, AND, NOT.
    Returns matching snippets with session context.
    """
    query = args.get("query", "")
    limit = args.get("limit", 20)
    session_filter = args.get("session_id", "")

    if not query.strip():
        return error_response("Error: query is required")

    try:
        results = await search_history(
            query=query,
            limit=limit,
            session_filter=session_filter,
        )
    except Exception as e:
        error_msg = str(e)
        if "no such table" in error_msg:
            return error_response(
                "History index not built yet. Run history_index first to build the search index."
            )
        return error_response(f"Search error: {error_msg}")

    if not results:
        return success_response(f"No results found for: {query}")

    lines = [f"Found {len(results)} result(s) for \"{query}\":\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. [{r['session_id']}] {r['title']}\n"
            f"   Role: {r['role']} | {r['timestamp']}\n"
            f"   Snippet: {r['snippet']}\n"
        )

    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# history_retrieve
# ---------------------------------------------------------------------------

@tool("history_retrieve", "Retrieve a full past conversation, clean without tool usage noise", {
    "session_id": str,
    "include_tool_results": bool,
    "include_thinking": bool,
    "max_chars": int,
})
async def history_retrieve(args: dict[str, Any]) -> dict[str, Any]:
    """Retrieve a full conversation from the Synapsis database.

    By default returns only user and assistant text messages, stripping
    tool_use, tool_result, and thinking blocks to minimize token count.

    Set include_tool_results=True or include_thinking=True to include those.
    Set max_chars to limit the total output size (0 = unlimited).
    """
    session_id = args.get("session_id", "")
    include_tool_results = args.get("include_tool_results", False)
    include_thinking = args.get("include_thinking", False)
    max_chars = args.get("max_chars", 0)

    if not session_id:
        return error_response("Error: session_id is required")

    result = await retrieve_conversation(
        session_id=session_id,
        include_tool_results=include_tool_results,
        include_thinking=include_thinking,
        max_chars=max_chars,
    )

    if "error" in result:
        return error_response(result["error"])

    # Format as readable conversation
    lines = [
        f"# Conversation: {result['title']}",
        f"Session: {result['session_id']}",
        f"Created: {result['created_at']}",
        f"Messages in DB: {result['total_messages_in_db']} | "
        f"Clean messages: {result['clean_messages_returned']} | "
        f"Clean chars: {result['total_clean_chars']} (~{result['total_clean_chars'] // 4} tokens)",
        "",
        "---",
        "",
    ]

    for msg in result["messages"]:
        role_label = "**User**" if msg["role"] == "user" else "**Assistant**"
        if msg["type"] not in ("user", "text"):
            role_label = f"**{msg['type'].title()}**"

        lines.append(f"{role_label} ({msg['timestamp']}):")
        lines.append(msg["content"])
        lines.append("")

    return success_response("\n".join(lines))


# ---------------------------------------------------------------------------
# history_index
# ---------------------------------------------------------------------------

@tool("history_index", "Build or rebuild the chat history search index", {
    "force": bool,
})
async def history_index(args: dict[str, Any]) -> dict[str, Any]:
    """Build or rebuild the FTS5 search index for all Synapsis conversations.

    By default runs incrementally — only indexes new or updated sessions.
    Set force=True to rebuild the entire index from scratch.
    """
    force = args.get("force", False)

    try:
        results = await index_all_sessions(force=force)
    except Exception as e:
        return error_response(f"Indexing error: {str(e)}")

    mode = "full rebuild" if force else "incremental"
    return success_response(
        f"History index {mode} complete.\n"
        f"  Total sessions: {results['total']}\n"
        f"  Indexed: {results['indexed']}\n"
        f"  Skipped (up-to-date): {results['skipped']}\n"
        f"  Errors: {results['errors']}"
    )


# ---------------------------------------------------------------------------
# history_list
# ---------------------------------------------------------------------------

@tool("history_list", "List all past chat sessions available for retrieval", {
    "limit": int,
})
async def history_list(args: dict[str, Any]) -> dict[str, Any]:
    """List all indexed chat sessions with metadata.

    Shows session IDs, titles, message counts, and estimated token sizes
    so you can decide which conversations to retrieve.
    """
    limit = args.get("limit", 50)

    try:
        sessions = await list_indexed_sessions(limit=limit)
    except Exception as e:
        error_msg = str(e)
        if "no such table" in error_msg:
            return error_response(
                "History index not built yet. Run history_index first."
            )
        return error_response(f"Error: {error_msg}")

    if not sessions:
        return success_response(
            "No indexed sessions found. Run history_index to build the index."
        )

    lines = [f"Indexed sessions ({len(sessions)}):\n"]
    for s in sessions:
        lines.append(
            f"  [{s['session_id']}] {s['title']}\n"
            f"    Created: {s['created_at']} | Messages: {s['message_count']} | "
            f"~{s['estimated_tokens']} tokens\n"
        )

    return success_response("\n".join(lines))
