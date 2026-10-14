/**
 * @file runScope.ts
 * @module stores/chat
 *
 * Turn-level run_id scoping shared by the chat store and the WebSocket router.
 *
 * Every chat turn on the server is a "run" with its own `run_id`. The client
 * adopts the run id of the first event of a new turn (`currentRunId`) and
 * drops events of any other run as stale.
 *
 * Quick follow-up bug (verification round, Oct 2026): when a follow-up was
 * sent 1-3 s after an answer, the server was still finishing the previous run
 * (post-processing after `result`) and cancelled it, which emits that run's
 * terminal events (`task_status`, `session_complete`, ...) AFTER the user's new
 * message had reset `currentRunId`. The first such stale event was adopted as
 * the new turn's run id, so every event of the real new run was then dropped:
 * an empty bubble and a spinning stop button although the server answered.
 *
 * Fix: when the user sends a message, the run that was current is "retired";
 * events of a retired run are always stale, and terminal / bookkeeping events
 * never bootstrap the run id of a new turn.
 */

const RETIRED_LIMIT = 50
const retired: string[] = []

/** Event types that close or annotate a run; they never start a new turn. */
export const NON_BOOTSTRAP_TYPES: ReadonlySet<string> = new Set([
  'session_complete', 'result', 'task_status', 'cancelled', 'error', 'text_links',
])

/** Mark *runId* as finished from the client's point of view (a new turn started). */
export function retireRun(runId: string | null | undefined): void {
  if (!runId || retired.includes(runId)) return
  retired.push(runId)
  if (retired.length > RETIRED_LIMIT) retired.shift()
}

/** True when an event of *msgRunId* must be ignored for the current turn. */
export function isStaleRunEvent(msgRunId: string | null | undefined, currentRunId: string | null): boolean {
  if (!msgRunId) return false
  if (currentRunId) return msgRunId !== currentRunId
  return retired.includes(msgRunId)
}

/** True when an event may set the run id of a new turn. */
export function mayBootstrapRun(msgType: string, msgRunId: string | null | undefined, currentRunId: string | null): boolean {
  return !!msgRunId && !currentRunId && !NON_BOOTSTRAP_TYPES.has(msgType) && !retired.includes(msgRunId)
}

/** Test helper. */
export function _resetRetiredRuns(): void {
  retired.length = 0
}
