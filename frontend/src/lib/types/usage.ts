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
  voice: { sessions: number; minutes: number }
  /** `recorded` (per-question ledger), `estimated` (from chat history), `mixed` or `none`. */
  source: 'recorded' | 'estimated' | 'mixed' | 'none' | string
}

export interface AdminUsage {
  environment: string
  git_sha: string
  generated_at: string
  currency: string
  cost_basis: string
  policy: { researcher: ModelPolicy; admin: ModelPolicy }
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
