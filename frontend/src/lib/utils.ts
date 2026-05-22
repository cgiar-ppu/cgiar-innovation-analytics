/**
 * @file utils.ts
 * @module lib
 *
 * General-purpose utility functions shared across the Synapsis frontend.
 * All exports are pure functions with no side effects (except {@link generateId}
 * which reads from the Web Crypto API).
 */

/**
 * Formats a byte count as a human-readable size string.
 *
 * @param bytes - Raw byte count (non-negative integer).
 * @returns A string like `"1.2 KB"`, `"3.4 MB"`, `"5.6 GB"`, or `"42 B"`.
 *
 * @example
 * formatSize(0)          // "0 B"
 * formatSize(1536)       // "1.5 KB"
 * formatSize(2097152)    // "2.0 MB"
 */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

/**
 * Formats a Unix timestamp or ISO date string as a relative time label.
 * - Numbers are assumed to be Unix seconds (multiplied by 1000 for `Date`).
 * - Strings are parsed directly by `new Date()`.
 *
 * @param ts - Unix timestamp in seconds, or an ISO 8601 date string.
 * @returns A human-friendly string such as `"just now"`, `"5m ago"`,
 *   `"2h ago"`, `"3d ago"`, or a locale date string for older dates.
 *
 * @example
 * formatTimestamp(Date.now() / 1000)  // "just now"
 * formatTimestamp('2024-01-01')       // "Jan 1, 2024" (locale-dependent)
 */
export function formatTimestamp(ts: string | number): string {
  const date = typeof ts === 'number' ? new Date(ts * 1000) : new Date(ts)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMin = Math.floor(diffMs / 60000)
  const diffHr = Math.floor(diffMs / 3600000)
  const diffDay = Math.floor(diffMs / 86400000)

  if (diffMin < 1) return 'just now'
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHr < 24) return `${diffHr}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return date.toLocaleDateString()
}

/**
 * Formats a duration in milliseconds as a human-readable string.
 *
 * @param ms - Duration in milliseconds (non-negative).
 * @returns A string like `"250ms"`, `"1.5s"`, or `"2m 30s"`.
 *
 * @example
 * formatDuration(500)    // "500ms"
 * formatDuration(2500)   // "2.5s"
 * formatDuration(90000)  // "1m 30s"
 */
export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const rem = Math.floor(s % 60)
  return `${m}m ${rem}s`
}

/**
 * Formats an API cost value for display, with special handling for
 * subscription-based billing and null/undefined costs.
 *
 * @param cost       - Estimated cost in USD, or `null` / `undefined` if
 *                     unavailable.
 * @param authMethod - The billing method reported by the server. When
 *                     `"subscription"`, returns `"Subscription"` regardless
 *                     of the `cost` value.
 * @returns A formatted string like `"$0.0042"`, `"Subscription"`, or `"—"`.
 *
 * @example
 * formatCost(0.0042)                    // "$0.0042"
 * formatCost(null, 'subscription')      // "Subscription"
 * formatCost(null)                      // "—"
 */
export function formatCost(cost: number | null | undefined, authMethod?: string): string {
  if (authMethod === 'subscription') return 'Subscription'
  if (cost == null) return '—'
  return `$${cost.toFixed(4)}`
}

/**
 * Truncates a string to at most `maxLen` characters, appending an ellipsis
 * character (`…`) when truncation occurs.
 *
 * @param text   - The string to truncate.
 * @param maxLen - Maximum allowed length (inclusive). Strings at or under
 *                 this length are returned unchanged.
 * @returns The original string if short enough, or a truncated version ending
 *   in `"…"`.
 *
 * @example
 * truncate('hello world', 5)   // "hello…"
 * truncate('hi', 5)            // "hi"
 */
export function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text
  return text.slice(0, maxLen) + '…'
}

/**
 * Generates a short random hex ID string suitable for use as a React key or
 * local message identifier (not a globally unique UUID).
 *
 * Uses `crypto.randomUUID()` where available (secure contexts), falling back
 * to `crypto.getRandomValues()`, and finally to `Math.random()` for plain
 * HTTP environments.
 *
 * @returns A 12-character hex string (from UUID) or a 12-character hex string
 *   from 6 random bytes.
 *
 * @example
 * generateId()  // e.g. "a1b2c3d4e5f6"
 */
export function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID().slice(0, 12)
  }
  // Fallback for non-secure contexts (plain HTTP)
  const bytes = new Uint8Array(6)
  if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('')
}

/**
 * Lightweight utility for conditionally joining class names. Falsy values
 * (`false`, `null`, `undefined`) are filtered out automatically.
 *
 * @param classes - Any number of class strings or falsy values.
 * @returns A single space-separated class string.
 *
 * @example
 * clsx('btn', isActive && 'btn--active', undefined)
 * // "btn btn--active"  (when isActive is true)
 * // "btn"              (when isActive is false)
 */
export function clsx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(' ')
}
