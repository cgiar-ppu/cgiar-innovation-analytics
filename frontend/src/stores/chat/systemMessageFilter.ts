/**
 * @file systemMessageFilter.ts
 * @module stores/chat
 *
 * Single source of truth for deciding whether a `role: 'system'` chat message
 * is SDK-forwarded per-turn telemetry that should NOT be shown as a pill in the
 * chat UI.
 *
 * Why this exists
 * ---------------
 * The Claude Agent SDK emits `SystemMessage` events that the backend forwards
 * verbatim (`message_handlers.py` / `agent_ws.py`). The extended-thinking models
 * produce per-turn task/usage telemetry — one or more events per turn — which
 * the frontend renders as small rounded "pills" (Expanded view) and counts in
 * the collapsed "N system messages" row (Compact view). The user asked to remove
 * this clutter ("the thinking_tokens pill") while keeping the actual thinking
 * content block.
 *
 * The thinking *content* block is a separate role (`role: 'thinking'`, rendered
 * by `ThinkingBlock.tsx`) and is completely unaffected by this filter — this
 * predicate only ever inspects `role: 'system'` messages.
 *
 * Precision over breadth
 * ----------------------
 * The suppressed set is an explicit allowlist of the SDK's known telemetry
 * subtypes, confirmed against claude-agent-sdk 0.1.72
 * (`_internal/message_parser.py` -> `case "system"`), where the SDK parses the
 * following SystemMessage subclasses, each carrying per-turn token/usage
 * counters in their payload:
 *   - "task_started"      (TaskStartedMessage)
 *   - "task_progress"     (TaskProgressMessage — carries `usage.total_tokens`)
 *   - "task_notification" (TaskNotificationMessage — carries `usage`)
 *
 * We deliberately do NOT suppress any of the genuinely-useful system subtypes:
 *   - "init"             — the session-started summary
 *   - "aup_error"        — usage-policy notice
 *   - "workflow_context" — persisted workflow context banner
 *   - "mirror_error"     — a real (non-fatal) error notice
 *   - file_upload / attachment notices, slash-command feedback, generic errors
 *   - any system message with no subtype (legacy/local UX notices)
 */

/**
 * SDK telemetry subtypes whose pills should be hidden from the chat.
 *
 * Confirmed from claude-agent-sdk 0.1.72 system-message parsing. Keep this list
 * tight: add a subtype here ONLY if it is pure per-turn token/usage telemetry,
 * never a message a user would want to read.
 */
const SUPPRESSED_SYSTEM_SUBTYPES = new Set<string>([
  'task_started',
  'task_progress',
  'task_notification',
])

/**
 * Returns true when a `role: 'system'` message is SDK-forwarded telemetry that
 * should be hidden from the chat (the "thinking_tokens" pills). Returns false
 * for every genuinely-useful system message so those still render.
 *
 * @param subtype - The message `subtype` (may be undefined for local UX notices).
 * @param _content - The serialized message content. Currently unused: matching
 *   is done purely on the known telemetry `subtype`, which is the precise and
 *   robust signal. Kept in the signature so callers at both ingestion points
 *   (live stream + history) share one call shape, and so a content-based
 *   fallback can be added here in one place if the SDK contract ever changes.
 */
export function isSuppressedSystemMessage(
  subtype: string | undefined,
  _content: string,
): boolean {
  if (subtype && SUPPRESSED_SYSTEM_SUBTYPES.has(subtype)) return true
  return false
}
