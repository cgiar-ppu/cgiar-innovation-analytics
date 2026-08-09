/**
 * @file websocket.ts
 * @module lib/types
 *
 * WebSocket message contracts for communication between the frontend and
 * the backend `/ws/chat` endpoint. Each message union is discriminated by
 * its `type` field.
 */

/**
 * Union of all message shapes that the backend can send over the WebSocket.
 * Each variant is discriminated by its `type` field.
 */
export type ServerMessage =
  /** A chunk of streamed assistant text. */
  | { type: 'text'; content: string }
  /** A chunk of streamed thinking/reasoning text. */
  | { type: 'thinking'; content: string }
  /** The agent is about to call a tool. */
  | { type: 'tool_use'; tool: string; input: Record<string, unknown>; tool_use_id: string }
  /** The result returned by a tool call. */
  | { type: 'tool_result'; tool_use_id: string; content: string; is_error: boolean }
  /** A server-side informational/diagnostic message. */
  | { type: 'system'; subtype?: string; data: unknown }
  /** The agent run has finished. Carries cost and timing metadata. */
  | { type: 'result'; estimated_cost: number | null; turns: number; duration_ms: number; session_id: string; is_error: boolean; auth_method: string; error_detail?: string; result_text?: string }
  /** A new or resumed session ID has been assigned. */
  | { type: 'session'; session_id: string; is_busy?: boolean }
  /** The run was cancelled at the user's request. */
  | { type: 'cancelled' }
  /** A non-recoverable error occurred on the server. */
  | { type: 'error'; message: string }
  /** AUP/policy violation detected — suggests a fallback model. */
  | { type: 'aup_error'; message: string; fallback_model: string }
  /** Confirmation that the active session's model was switched. */
  | { type: 'model_switched'; model: string; session_id: string }
  /** A sub-agent (Task tool) has started or completed. */
  | { type: 'agent_activity'; agent: string; status: 'started' | 'completed'; tool_use_id: string }
  /** Early notification that the agent is generating a tool call. */
  | { type: 'tool_generating'; tool: string; tool_use_id: string }
  /** Streaming delta of tool input JSON being constructed. */
  | { type: 'tool_input_delta'; content: string }
  /** Notification that a session's streaming task has completed (used for background session tracking). */
  | { type: 'session_complete'; session_id: string }
  /** Another device modified a session — refresh the session list. */
  | { type: 'sessions_changed' }
  /** A specific session was updated (renamed, deleted, etc.) by another device. */
  | { type: 'session_update'; action: 'renamed' | 'deleted' | 'new_message'; session_id: string; title?: string }
  /** Marks the start of a buffer replay from a managed task (ChatRunManager). */
  | { type: 'buffer_replay_start'; session_id: string; event_count: number }
  /** Marks the end of a buffer replay — live streaming continues from here. */
  | { type: 'buffer_replay_end'; session_id: string }
  /** Backend task lifecycle status update (informational). */
  | { type: 'task_status'; session_id: string; status: string }

/**
 * Union of all message shapes the frontend can send to the backend over the
 * WebSocket. Discriminated by the `type` field (or absence thereof for the
 * standard chat message).
 */
/**
 * Active data scope (year / programme filters) attached to an outgoing message.
 * The backend renders it into a preamble that constrains the agent's PRMS
 * queries and forces it to state the slice in its answer. Omitted entirely when
 * no filter is set. See synapsis/scope.py.
 */
export interface MessageScope {
  years: number[]
  programs: string[]
}

export type ClientMessage =
  /**
   * Send a chat message to the agent.
   *
   * `scope` carries the filter-bar selection; `agent` carries the specialist
   * chosen in the agent picker (a builtin agent id such as
   * "prms_data_analyst"). BOTH are omitted entirely when nothing is selected,
   * so the default frame is byte-identical to the pre-filter/pre-picker one.
   * See synapsis/scope.py and synapsis/persona.py.
   */
  | { message: string; scope?: MessageScope; agent?: string }
  /** Request the current agent run to be cancelled. */
  | { type: 'cancel' }
  /** Ask the server to create and activate a new session. */
  | { type: 'new_session' }
  /** Switch the WebSocket to an existing session. */
  | { type: 'switch_session'; session_id: string }
  /** Switch the active session's model mid-conversation. */
  | { type: 'switch_model'; model: string }
  /** Retry a message with a different model (AUP fallback). */
  | { type: 'retry_with_model'; message: string; model: string }
