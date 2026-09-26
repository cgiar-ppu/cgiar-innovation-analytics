/**
 * @file UsagePanel.tsx
 * @module components/admin
 *
 * Admin-only usage summary in Settings (Lane E, 2026-09-26). Reads Lane D's
 * `GET /api/admin/usage?days=N` - per-day questions, chats, distinct users,
 * USD cost by role and by model, voice sessions/minutes - for THIS
 * environment, and offers a CSV download. This is what Jose uses to answer
 * Jules's running-cost questions (call it on DEV and PROD for the split).
 *
 * The endpoint returns aggregates only (no identities, no message text).
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { BarChart3, Download, RefreshCw } from 'lucide-react'
import GlassCard from '../common/GlassCard'
import { api } from '../../lib/api'
import type { AdminUsage } from '../../lib/types/usage'

export const USAGE_DAY_OPTIONS = [7, 14, 30, 90] as const

const usd = (n: number | null | undefined) => `$${(n ?? 0).toFixed(2)}`

/** Build the CSV (one row per day) for a usage response. Exported for tests. */
export function usageToCsv(usage: AdminUsage): string {
  const roles = new Set<string>()
  const models = new Set<string>()
  for (const d of usage.daily) {
    Object.keys(d.by_role ?? {}).forEach((r) => roles.add(r))
    Object.keys(d.by_model ?? {}).forEach((m) => models.add(m))
  }
  const roleList = [...roles].sort()
  const modelList = [...models].sort()
  const header = [
    'environment', 'date', 'questions', 'chats', 'users', 'cost_usd', 'errors',
    ...roleList.flatMap((r) => [`questions_${r}`, `cost_usd_${r}`]),
    ...modelList.flatMap((m) => [`questions_${m}`, `cost_usd_${m}`]),
    'voice_sessions', 'voice_minutes', 'source',
  ]
  const esc = (v: unknown) => {
    const s = String(v ?? '')
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const rows = usage.daily.map((d) => [
    usage.environment, d.date, d.turns, d.sessions, d.users, (d.cost_usd ?? 0).toFixed(4), d.errors ?? 0,
    ...roleList.flatMap((r) => [d.by_role?.[r]?.turns ?? 0, (d.by_role?.[r]?.cost_usd ?? 0).toFixed(4)]),
    ...modelList.flatMap((m) => [d.by_model?.[m]?.turns ?? 0, (d.by_model?.[m]?.cost_usd ?? 0).toFixed(4)]),
    d.voice?.sessions ?? 0, (d.voice?.minutes ?? 0).toFixed(1), d.source,
  ])
  return [header, ...rows].map((row) => row.map(esc).join(',')).join('\n') + '\n'
}

export default function UsagePanel() {
  const [days, setDays] = useState<number>(14)
  const [usage, setUsage] = useState<AdminUsage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (n: number) => {
    setLoading(true)
    setError(null)
    try {
      setUsage(await api.getAdminUsage(n))
    } catch {
      setError('Usage figures could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load(days) }, [days, load])

  const rows = useMemo(() => [...(usage?.daily ?? [])].reverse(), [usage])

  const downloadCsv = () => {
    if (!usage) return
    const blob = new Blob([usageToCsv(usage)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ia-usage-${usage.environment}-${usage.days}d-${(usage.generated_at || '').slice(0, 10)}.csv`
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return (
    <GlassCard>
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
            <BarChart3 className="w-4 h-4" /> Usage and cost
            {usage && (
              <span className="text-[10px] font-normal px-1.5 py-0.5 rounded bg-[var(--surface-1)] text-[var(--text-muted)]">
                {usage.environment}
              </span>
            )}
          </h3>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 ml-6">Administrators only - aggregates for this environment, no user identities</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-[var(--text-muted)]" htmlFor="usage-days">Period</label>
          <select
            id="usage-days"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="text-xs rounded-lg border border-[var(--border)] bg-[var(--surface-1)] text-[var(--text)] px-2 py-1"
          >
            {USAGE_DAY_OPTIONS.map((n) => <option key={n} value={n}>Last {n} days</option>)}
          </select>
          <button onClick={() => void load(days)} className="p-1.5 rounded-lg hover:bg-[var(--surface-1)] text-[var(--text-muted)]" aria-label="Refresh usage">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            onClick={downloadCsv}
            disabled={!usage}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface-1)] disabled:opacity-50"
          >
            <Download className="w-3.5 h-3.5" /> CSV
          </button>
        </div>
      </div>

      {error && <p className="text-xs text-[var(--danger,#dc2626)]" role="alert">{error}</p>}

      {usage && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4" data-testid="usage-totals">
            {[
              ['Questions', String(usage.totals.turns)],
              ['Chats', String(usage.totals.sessions)],
              ['Users', String(usage.totals.users)],
              ['Model cost', usd(usage.totals.cost_usd)],
              ['Voice', `${(usage.totals.voice_minutes ?? 0).toFixed(1)} min`],
            ].map(([label, value]) => (
              <div key={label} className="bg-[var(--surface-1)] rounded-lg p-3">
                <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
                <p className="text-sm font-semibold text-[var(--text)]">{value}</p>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs text-[var(--text)]" data-testid="usage-table">
              <thead className="text-[var(--text-muted)] text-left">
                <tr>
                  <th className="py-1 pr-3 font-medium">Date</th>
                  <th className="py-1 pr-3 font-medium">Questions</th>
                  <th className="py-1 pr-3 font-medium">Users</th>
                  <th className="py-1 pr-3 font-medium">Cost</th>
                  <th className="py-1 pr-3 font-medium">By role</th>
                  <th className="py-1 pr-3 font-medium">By model</th>
                  <th className="py-1 pr-3 font-medium">Voice</th>
                  <th className="py-1 font-medium">Basis</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.date} className="border-t border-[var(--border)]">
                    <td className="py-1 pr-3 whitespace-nowrap">{d.date}</td>
                    <td className="py-1 pr-3">{d.turns}</td>
                    <td className="py-1 pr-3">{d.users}</td>
                    <td className="py-1 pr-3">{usd(d.cost_usd)}</td>
                    <td className="py-1 pr-3">
                      {Object.entries(d.by_role ?? {}).map(([r, b]) => `${r} ${usd(b.cost_usd)}`).join(' · ') || '—'}
                    </td>
                    <td className="py-1 pr-3">
                      {Object.entries(d.by_model ?? {}).map(([m, b]) => `${m} ${b.turns}`).join(' · ') || '—'}
                    </td>
                    <td className="py-1 pr-3">{d.voice?.minutes ? `${d.voice.minutes.toFixed(1)} min` : '—'}</td>
                    <td className="py-1 text-[var(--text-muted)]">{d.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-[var(--text-muted)] mt-3">{usage.cost_basis}</p>
        </>
      )}
    </GlassCard>
  )
}
