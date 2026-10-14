/**
 * @file usage.ts
 * @module lib/types
 *
 * Shape of the admin-only `GET /api/admin/usage?days=N` response (Lane D,
 * 2026-09-26). Aggregates only: no user identities or message content.
 */

import type { ModelPolicy } from './common'

export interface UsageBucket {
  turns: number
  cost_usd: number
  users?: number
}

export interface UsageDay {
  /** ISO date (UTC), e.g. `2026-09-26`. */
  date: string
  turns: number
  sessions: number
  users: number
  cost_usd: number
  errors?: number
  by_role: Record<string, UsageBucket>
  by_model: Record<string, UsageBucket>
  /** Invited-tester cohort label → questions/cost (Lane H; absent before). */
  by_cohort?: Record<string, UsageBucket>
  voice: { sessions: number; minutes: number }
  /** `recorded` (per-question ledger), `estimated` (from chat history), `mixed` or `none`. */
  source: 'recorded' | 'estimated' | 'mixed' | 'none' | string
}

/** MVP test budget block of `/api/admin/usage` (SYN-2306). */
export interface TestBudget {
  enabled: boolean
  budget_usd: number | null
  spent_usd: number
  remaining_usd: number | null
  /** Percent of the budget used (null when disabled). */
  pct: number | null
  state: 'open' | 'exhausted' | 'ended' | 'not_started' | 'disabled' | string
  window: { start: string | null; end: string | null; start_source: string; end_source: string; days_left: number }
  /** Alert thresholds in percent, e.g. [50, 75, 90]. */
  thresholds: number[]
  /** Thresholds already crossed in this window (logged once each). */
  alerts: { pct: number; fraction: number; spent_usd: number; crossed_at: string | null }[]
  session_budget_usd: number | null
  questions?: number
  voice: { minutes: number; usd: number; usd_per_minute: number }
  basis: string
}

export interface AdminUsage {
  environment: string
  git_sha: string
  generated_at: string
  currency: string
  cost_basis: string
  policy: { researcher: ModelPolicy; admin: ModelPolicy }
  /** Absent on servers before SYN-2306. */
  test_budget?: TestBudget
  from?: string
  to?: string
  days: number
  ledger_since?: string | null
  totals: {
    turns: number
    sessions: number
    users: number
    cost_usd: number
    errors?: number
    voice_sessions: number
    voice_minutes: number
  }
  daily: UsageDay[]
}

/** First-party usage events read-out, `GET /api/admin/engagement` (SYN-2305). */
export interface EngagementUser {
  user_key: string
  role: string
  cohort: string
  days_active: number
  questions: number
  cost_usd: number
  visits: number
  page_views: number
  clicks: number
  session_minutes_avg: number
  session_minutes_total: number
  last_seen: string
}

export interface AdminEngagement {
  environment: string
  generated_at: string
  tracking: string
  telemetry_enabled: boolean
  from: string
  to: string
  days: number
  events_since: string | null
  totals: {
    users: number
    visits: number
    page_views: number
    clicks: number
    questions: number
    session_minutes_avg: number
    session_minutes_median: number
  }
  daily: { date: string; users: number; visits: number; page_views: number; clicks: number; questions: number; session_minutes_avg: number }[]
  by_user: EngagementUser[]
  by_cohort: { cohort: string; users: number; questions: number; visits: number; clicks: number; session_minutes_avg: number; session_minutes_total: number }[]
  top_targets: { name: string; clicks: number }[]
}
