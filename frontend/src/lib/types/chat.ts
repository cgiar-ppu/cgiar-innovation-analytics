/**
 * @file chat.ts
 * @module lib/types
 *
 * Chat message types for the UI layer. All server message types are normalised
 * to the {@link ChatMessage} shape before being stored in the chat Zustand store.
 */

/**
 * All possible roles a {@link ChatMessage} can have in the UI chat log.
 *
 * | Role          | Description                                       |
 * |---------------|---------------------------------------------------|
 * | `user`        | Message typed by the human user.                  |
 * | `assistant`   | Finalised assistant text response.                |
 * | `system`      | Server-sent informational / diagnostic message.   |
 * | `tool_use`    | The agent invoking a tool.                        |
 * | `tool_result` | The output returned by a tool invocation.         |
 * | `thinking`    | Extended thinking / reasoning block.              |
 * | `result`      | Run-complete summary (cost, turns, duration).     |
 */
export type MessageRole = 'user' | 'assistant' | 'system' | 'tool_use' | 'tool_result' | 'thinking' | 'result'

/**
 * The canonical UI-layer representation of a single entry in the chat log.
 * All server message types are normalised to this shape before being stored
 * in the chat Zustand store.
 */
export interface ChatMessage {
  /** Unique identifier for this message (used as a React key). */
  id: string
  /** Determines how the message is rendered. */
  role: MessageRole
  /** Main text content of the message. */
  content: string
  /** Unix millisecond timestamp of when the message was received/created. */
  timestamp: number

  // -- tool_use specific --
  /** Name of the tool being called (only present when `role === "tool_use"`). */
  tool?: string
  /** Input arguments passed to the tool. */
  toolInput?: Record<string, unknown>
  /** Correlation ID linking a `tool_use` message to its `tool_result`. */
  toolUseId?: string

  // -- tool_result / result specific --
  /** `true` when the tool call or agent run resulted in an error. */
  isError?: boolean

  // -- result specific --
  /** Estimated cost of the run in USD. */
  estimatedCost?: number | null
  /** Number of agentic turns taken. */
  turns?: number
  /** Total wall-clock duration of the run in milliseconds. */
  durationMs?: number
  /** Billing method used for this run. */
  authMethod?: string
  /** Text output from slash commands (e.g. /config, /usage) that return results without streaming. */
  resultText?: string

  // -- system specific --
  /** Sub-type of system message (e.g. `"init"`). */
  subtype?: string

  // -- thinking specific --
  /**
   * `true` while the thinking block is still being streamed (the timer
   * in {@link ThinkingBlock} is active). `false` once finalised.
   */
  isActive?: boolean
}

/**
 * Metadata for a file that has been uploaded but not yet sent with a message.
 * Tracked in the chat store so attachment state persists across re-renders
 * and session switches.
 */
export interface PendingAttachment {
  /** Original filename as selected by the user. */
  fileName: string
  /** Server-side path where the uploaded file was stored. */
  filePath: string
  /** File size in bytes. */
  fileSize: number
}

/**
 * A single search result from the /api/search endpoint.
 */
export interface SearchResult {
  session_id: string
  session_title: string
  message_type: string
  snippet: string
  timestamp: string
}
