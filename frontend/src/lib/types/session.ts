/**
 * @file session.ts
 * @module lib/types
 *
 * Session domain types as returned by the REST API.
 */

/**
 * A chat session as returned by the `/api/sessions` endpoint.
 */
export interface Session {
  /** Unique identifier for this session. */
  session_id: string
  /** Human-readable display title. */
  title: string
  /** ISO 8601 creation timestamp. */
  created_at: string
  /** ISO 8601 last-updated timestamp. */
  updated_at: string
  /** The model used in this session. */
  model: string
  /** Total number of messages in the session history. */
  message_count: number
  /** Whether this session is pinned/starred. */
  pinned?: boolean
  /** Backend task status: "idle", "running", "completed", "failed", "cancelled". */
  task_status?: string
  /**
   * True only for an admin viewing a sentinel-owned pre-auth ("legacy")
   * session -- see synapsis/auth/scoping.py. Purely informational; absent or
   * false for a user's own sessions.
   */
  is_legacy?: boolean
}
