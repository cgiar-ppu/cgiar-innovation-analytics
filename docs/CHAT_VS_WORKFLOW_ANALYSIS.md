# Chat vs. Single-Orchestrator Workflow: Behavioral Equivalence Analysis

> **Produced**: 2026-03-29
> **Repo Commit**: `90379e6` — *Fix background task notifications contaminating active streaming session*
> **Full SHA**: `90379e6e9893c63fd626042aea5cf21918a3a9bb`
> **Analysis Method**: Deep code-level inspection of both execution paths by multiple specialist agents

---

## Purpose

This document answers the question: **Does a Workflow containing a single "Synapsis Orchestrator" step behave the same way — and yield the same result — as sending a single message in the Chat tab?**

The short answer is: **the LLM receives identical inputs and would produce the same output, but the surrounding infrastructure differs in ~20 meaningful ways.**

---

## What IS the Same

| Aspect | Detail |
|--------|--------|
| **System prompt** | Both call `build_agent_options()` -> `build_system_prompt(all_agents)` — the exact same orchestrator prompt |
| **Model** | Both use the configured `MODEL` (default: `claude-opus-4-6`) |
| **Subagents available** | Both load all agents via `load_all_agents()` (15 built-in + custom from DB) |
| **Tool set** | Both get the full `ALLOWED_TOOLS` list including `Task`, MCP tools, Bash, Read, etc. |
| **MCP servers** | Both register the same `synapsis` MCP server (memory, computer, agent management) |
| **Hooks** | Both apply the same safety validator + audit logger hooks |
| **Permission mode** | Both use `bypassPermissions` |
| **Prompt content (step 0)** | For step 0 with no per-step overrides, the raw user prompt is passed identically to `client.query()` |

**Conclusion on LLM behavior**: Claude receives the same system prompt, tools, subagents, and user prompt — so for a given input, it would reason and respond in the same way.

---

## What is DIFFERENT (22 Differences Found)

### 1. Session & Client Lifecycle

| # | Aspect | Chat | Workflow |
|---|--------|------|----------|
| 1 | **Client lifetime** | Long-lived, persists in `sessions` dict across messages | Short-lived, created fresh per step, never explicitly disconnected, orphaned after use |
| 2 | **Session resume** | Supports resuming via Claude SDK session UUID (`opts.resume`) | Never resumes — always a fresh session |
| 3 | **Connect retry** | On failure, retries without resume as fallback | Immediate fatal — step marked as `"failed"` |
| 4 | **Per-session locking** | `acquire_session_client` / `release_session_client` prevents concurrent queries | No locking at all |

### 2. Prompt & Configuration Modifications

| # | Aspect | Chat | Workflow |
|---|--------|------|----------|
| 5 | **Extra instructions** | Never modifies the system prompt per-message | `stepConfigs.extra_instructions` can be appended to system prompt |
| 6 | **Subagent filtering** | Always has all subagents | `stepConfigs.sub_agents` can restrict available subagents |
| 7 | **Per-step prompt additions** | N/A | `step_prompts[0]` can append `## Additional Instructions` to the user prompt |

### 3. Streaming Protocol

| # | Aspect | Chat | Workflow |
|---|--------|------|----------|
| 8 | **Event shape** | Events carry `sid=session_id` | Events carry `"step": step_idx` instead |
| 9 | **SystemMessage handling** | Fully processed — persists Claude session UUID, sends init summary to frontend | **Silently dropped** — SystemMessages are not handled at all |
| 10 | **Agent activity events** | Emits `{"type": "agent_activity"}` when orchestrator uses `Task` tool | **Not emitted** — no special handling for Task tool calls |
| 11 | **Completion event** | Sends `session_complete` | Sends `step_complete` + `pipeline_complete` (different protocol) |

### 4. Persistence

| # | Aspect | Chat | Workflow |
|---|--------|------|----------|
| 12 | **Message DB persistence** | Every block (text, thinking, tool_use, tool_result, result) saved to SQLite via `save_message()` | **Nothing saved to DB** — messages only recorded in in-memory `step_log` |
| 13 | **Claude session UUID** | Persisted to DB for future resumption | **Not persisted** — recorded only in the run log JSON |
| 14 | **Run log file** | Not created | Comprehensive JSON run log saved to `~/workspace/workflow_logs/` |

### 5. Safety & Error Handling

| # | Aspect | Chat | Workflow |
|---|--------|------|----------|
| 15 | **AUP violation checking** | Checks accumulated text + exceptions for Acceptable Use Policy violations, sends `aup_error` events | **No AUP checking at all** |
| 16 | **Context window exhaustion** | Detects when stream ends without `ResultMessage`, sends informative error | **No detection** |
| 17 | **Enhanced error messages** | Enriches context/token errors with actionable user guidance | Raw error messages only |

### 6. Pre/Post Processing

| # | Aspect | Chat | Workflow |
|---|--------|------|----------|
| 18 | **Pre-drain** | 0.3s drain of stale SDK messages before `client.query()` | No pre-drain (safe since client is always fresh, but architecturally different) |
| 19 | **Post-drain** | 1.0s drain of background task notifications after stream ends | No post-drain |
| 20 | **Activity recording** | Calls `record_activity(time.time())` for dashboard stats | No activity recording |
| 21 | **Sessions broadcast** | Broadcasts `sessions_changed` to other connected devices | No broadcast |
| 22 | **Result event fields** | Includes `auth_method`, `result_text`, `error_detail` | Only `estimated_cost`, `turns`, `duration_ms`, `is_error` |

---

## Practical Impact Assessment

| Impact Level | Differences |
|:---:|---|
| **No impact on LLM output** | #1, #4, #8, #11, #18, #19, #20, #21 — Infrastructure/protocol differences that don't affect what Claude sees or produces |
| **No impact IF defaults used** | #5, #6, #7 — Only differ when `stepConfigs` or `step_prompts` are non-empty; with defaults, these are identical |
| **Functional gap in workflow** | #9, #10, #12, #13 — Workflow drops SystemMessages, doesn't track agent activity, and doesn't persist individual messages to the DB |
| **Safety gap in workflow** | #15, #16, #17 — Workflow has no AUP checking, no context window detection, and less informative errors |
| **Resumability gap** | #2, #3 — Workflow can never resume a session; a failure is always final |

---

## Key Files Involved

### Chat Path

| File | Role |
|------|------|
| `synapsis/websocket.py` | WebSocket `/ws/chat` endpoint — thin frame router |
| `synapsis/handlers/chat_handlers.py` | `handle_user_message()` — session setup, query, streaming task launch |
| `synapsis/session_manager.py` | Client lifecycle, per-session locking, resume support |
| `synapsis/stream_handler.py` | `stream_response()` — async consumption of SDK response stream |
| `synapsis/message_handlers.py` | Per-block processing (text, thinking, tool_use, tool_result, system, result) |
| `synapsis/agent_options.py` | `build_agent_options()` — assembles `ClaudeAgentOptions` |
| `synapsis/system_prompt.py` | `build_system_prompt()` — dynamic orchestrator prompt |
| `synapsis/agents.py` | Subagent definitions and `load_all_agents()` |

### Workflow Path

| File | Role |
|------|------|
| `synapsis/workflow_ws.py` | WebSocket `/ws/workflow/{id}` — thin transport adapter |
| `synapsis/services/workflow_executor.py` | `WorkflowExecutor` — pipeline engine, `execute_step()`, `_stream_step()` |
| `synapsis/agent_options.py` | Same `build_agent_options()` (shared with chat) |
| `synapsis/system_prompt.py` | Same `build_system_prompt()` (shared with chat) |
| `synapsis/agents.py` | Same subagent definitions (shared with chat) |

### Frontend

| File | Role |
|------|------|
| `frontend/src/hooks/useWebSocket.ts` | Chat WebSocket connection + message routing |
| `frontend/src/hooks/usePipelineExecution.ts` | Workflow WebSocket connection + state management |
| `frontend/src/stores/chat.ts` | Chat Zustand store — `handleServerMessage()` dispatcher |
| `frontend/src/components/workflows/PipelineRunner.tsx` | Workflow execution overlay UI |

---

## Final Verdict

For a single orchestrator step with default configuration (no `extra_instructions`, no `sub_agents` filtering, no `step_prompts`):

- **Same brain, same tools, same prompt** -> Claude would produce the same reasoning and output.
- **Different plumbing** -> Different observability (no agent activity banner in workflow), different persistence (no DB messages, JSON run log instead), different safety nets (no AUP checks, no context window detection), and different error recovery (no resume, no connect retry).

### Potential Action Items

1. **Parity gap**: Consider adding AUP checking, context window detection, and enhanced error messages to the workflow executor.
2. **Agent activity**: Consider emitting `agent_activity` events from `_stream_step()` to give the workflow UI visibility into subagent delegation.
3. **SystemMessage handling**: Consider processing SystemMessages in the workflow path (at minimum, for logging the Claude session UUID).
4. **Client cleanup**: The workflow path never calls `client.disconnect()` — the client is orphaned. Consider explicit cleanup.
5. **Activity recording**: Workflow runs are not reflected in dashboard activity stats.

---

*This analysis was produced via deep automated code inspection. It should be re-verified if the files listed above are significantly modified after commit `90379e6`.*
