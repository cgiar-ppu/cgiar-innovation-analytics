/**
 * @file telemetry.ts
 * @module lib
 *
 * First-party, cookieless usage events (SYN-2305, 2026-10-14).
 *
 * Collects three kinds of in-app engagement signal and posts them, batched,
 * to this deployment's own `POST /api/telemetry`:
 *
 * - `page_view` - each route the user opens (path only, never the query);
 * - `click` - clicks on elements tagged `data-track` (preferred) or
 *   `data-testid`; other buttons/links count as `untagged:<tag>`. The element's
 *   text, position or content is never read;
 * - `heartbeat` - every 30 s while the tab is visible AND the user interacted
 *   in the last 5 min, carrying the engaged seconds. Session length is derived
 *   from these server-side.
 *
 * No cookies and no browser storage: the visit id lives in memory for one page
 * load. No third-party script and no new CSP origin (same-origin requests
 * only). The event shape follows Umami's open-source event model, see
 * `synapsis/database/telemetry.py`.
 *
 * Transport: timer flushes use `fetch(..., { keepalive: true })` with the
 * normal bearer header; when the page is hidden/closed the queue goes out with
 * `navigator.sendBeacon` (which cannot carry headers, so the app token rides
 * in the JSON body and is verified server-side like the header).
 * Failures never surface to the user. A `404` (feature switched off on the
 * server) stops the module for the rest of the page load.
 */

export type TelemetryEventType = 'page_view' | 'click' | 'heartbeat' | 'visit_end'

export interface TelemetryEvent {
  id: string
  type: TelemetryEventType
  ts: number
  visit_id: string
  path: string
  name?: string
  chat_session_id?: string
  value?: number
}

export interface TelemetryOptions {
  /** Current bearer token (null when signed out / dev bypass). */
  getToken: () => string | null
  /** Active chat id, so events can be joined to the question ledger. */
  getChatSessionId?: () => string | null
  /** Override timings (tests). */
  flushMs?: number
  heartbeatMs?: number
  idleMs?: number
  /** Start even under vitest (module tests only). */
  force?: boolean
}

export const TELEMETRY_ENDPOINT = '/api/telemetry'
export const MAX_BATCH = 50
const MAX_QUEUE = 200

interface State {
  opts: TelemetryOptions
  visitId: string
  queue: TelemetryEvent[]
  disabled: boolean
  lastInteraction: number
  lastBeat: number
  timers: ReturnType<typeof setInterval>[]
  cleanup: (() => void)[]
  inFlight: boolean
}

let state: State | null = null

function randomId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, '')
  return Math.random().toString(36).slice(2) + Date.now().toString(36)
}

function currentPath(): string {
  return (typeof window !== 'undefined' ? window.location.pathname : '/') || '/'
}

/** The label recorded for a click on `target`, or null to ignore the click. */
export function trackLabelFor(target: EventTarget | null): string | null {
  if (!(target instanceof Element)) return null
  const tagged = target.closest('[data-track],[data-testid]')
  if (tagged) return tagged.getAttribute('data-track') || tagged.getAttribute('data-testid')
  const interactive = target.closest('button,a,[role="button"],input,select,textarea,summary')
  return interactive ? `untagged:${interactive.tagName.toLowerCase()}` : null
}

function push(type: TelemetryEventType, extra: Partial<TelemetryEvent> = {}): void {
  if (!state || state.disabled) return
  const chat = state.opts.getChatSessionId?.() || undefined
  state.queue.push({
    id: randomId(),
    type,
    ts: Date.now(),
    visit_id: state.visitId,
    path: currentPath(),
    ...(chat ? { chat_session_id: chat } : {}),
    ...extra,
  })
  if (state.queue.length > MAX_QUEUE) state.queue.splice(0, state.queue.length - MAX_QUEUE)
}

export function trackPageView(): void {
  push('page_view')
}

export function trackClick(name: string): void {
  push('click', { name })
}

/** Send what is queued. `beacon` = the page is going away. */
export async function flushTelemetry(beacon = false): Promise<void> {
  const s = state
  if (!s || s.disabled || s.queue.length === 0) return
  if (s.inFlight && !beacon) return
  const batch = s.queue.splice(0, MAX_BATCH)
  const token = s.opts.getToken()

  if (beacon && typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
    const body = JSON.stringify({ events: batch, ...(token ? { token } : {}) })
    // text/plain keeps the beacon a "simple" request (no preflight).
    const ok = navigator.sendBeacon(TELEMETRY_ENDPOINT, new Blob([body], { type: 'text/plain;charset=UTF-8' }))
    if (!ok) s.queue.unshift(...batch)
    return
  }

  s.inFlight = true
  try {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers.Authorization = `Bearer ${token}`
    const res = await fetch(TELEMETRY_ENDPOINT, {
      method: 'POST',
      headers,
      body: JSON.stringify({ events: batch }),
      keepalive: true,
    })
    if (res.status === 404) {
      s.disabled = true // switched off on this deployment
      s.queue.length = 0
    }
    // 401 (signed out) / 4xx: drop the batch; 5xx: drop too (best effort).
  } catch {
    s.queue.unshift(...batch) // offline: retry on the next tick
    if (s.queue.length > MAX_QUEUE) s.queue.splice(MAX_QUEUE)
  } finally {
    s.inFlight = false
  }
}

function heartbeat(heartbeatMs: number, idleMs: number): void {
  const s = state
  if (!s || s.disabled) return
  const now = Date.now()
  const visible = typeof document === 'undefined' || document.visibilityState !== 'hidden'
  const engaged = now - s.lastInteraction < idleMs
  const seconds = Math.min((now - s.lastBeat) / 1000, (heartbeatMs / 1000) * 2)
  s.lastBeat = now
  if (visible && engaged) push('heartbeat', { value: Math.round(seconds) })
}

/**
 * Start collecting (idempotent). Returns a stop function. A no-op under the
 * test runner unless `force` is set, so component tests never see beacons.
 */
export function startTelemetry(opts: TelemetryOptions): () => void {
  if (state) return stopTelemetry
  if (import.meta.env?.MODE === 'test' && !opts.force) return () => {}
  if (typeof window === 'undefined') return () => {}
  const flushMs = opts.flushMs ?? 10_000
  const heartbeatMs = opts.heartbeatMs ?? 30_000
  const idleMs = opts.idleMs ?? 5 * 60_000
  const now = Date.now()
  state = {
    opts, visitId: randomId(), queue: [], disabled: false,
    lastInteraction: now, lastBeat: now, timers: [], cleanup: [], inFlight: false,
  }
  const s = state

  const onClick = (e: Event) => {
    s.lastInteraction = Date.now()
    const label = trackLabelFor(e.target)
    if (label) trackClick(label)
  }
  const onActivity = () => { s.lastInteraction = Date.now() }
  const onHide = () => {
    if (document.visibilityState === 'hidden') void flushTelemetry(true)
  }
  const onPageHide = () => {
    push('visit_end')
    void flushTelemetry(true)
  }

  document.addEventListener('click', onClick, { capture: true })
  for (const type of ['keydown', 'pointermove', 'wheel', 'touchstart', 'scroll'] as const) {
    document.addEventListener(type, onActivity, { capture: true, passive: true })
    s.cleanup.push(() => document.removeEventListener(type, onActivity, { capture: true }))
  }
  document.addEventListener('visibilitychange', onHide)
  window.addEventListener('pagehide', onPageHide)
  s.cleanup.push(
    () => document.removeEventListener('click', onClick, { capture: true }),
    () => document.removeEventListener('visibilitychange', onHide),
    () => window.removeEventListener('pagehide', onPageHide),
  )
  s.timers.push(
    setInterval(() => heartbeat(heartbeatMs, idleMs), heartbeatMs),
    setInterval(() => { void flushTelemetry(false) }, flushMs),
  )
  return stopTelemetry
}

export function stopTelemetry(): void {
  if (!state) return
  void flushTelemetry(true) // sign-out / unmount: send what is left
  state.timers.forEach(clearInterval)
  state.cleanup.forEach((fn) => fn())
  state = null
}

/** Test helper: the pending queue (read-only copy). */
export function _pendingTelemetry(): TelemetryEvent[] {
  return state ? [...state.queue] : []
}
