/**
 * @file EngagementPanel.tsx
 * @module components/admin
 *
 * Admin-only engagement read-out (SYN-2305, 2026-10-14) shown inside the
 * Usage card: questions, clicks and session length per day, per test cohort
 * and per account (pseudonymous `user_key`), plus the most-clicked tagged
 * controls and a CSV download (one row per day x account) for the regular
 * reviews. Data comes from the first-party, cookieless event log
 * (`GET /api/admin/engagement`); see `lib/telemetry.ts`.
 */

import { useCallback, useEffect, useState } from 'react'
import { Download, MousePointerClick } from 'lucide-react'
import { api } from '../../lib/api'
import type { AdminEngagement } from '../../lib/types/usage'

const usd = (n: number | null | undefined) => `$${(n ?? 0).toFixed(2)}`
const min = (n: number | null | undefined) => `${(n ?? 0).toFixed(1)} min`

export default function EngagementPanel({ days }: { days: number }) {
  const [data, setData] = useState<AdminEngagement | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async (n: number) => {
    setError(null)
    try {
      setData(await api.getAdminEngagement(n))
    } catch {
      setError('Engagement figures could not be loaded.')
    }
  }, [])

  useEffect(() => { void load(days) }, [days, load])

  const downloadCsv = async () => {
    try {
      const blob = await api.getAdminEngagementCsv(days)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `ia-engagement-${data?.environment ?? 'env'}-${days}d-${(data?.generated_at || '').slice(0, 10)}.csv`
      a.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch {
      setError('The engagement CSV could not be downloaded.')
    }
  }

  return (
    <div className="mt-6 pt-4 border-t border-[var(--border)]" data-testid="engagement-panel">
      <div className="flex items-center justify-between gap-3 mb-3 flex-wrap">
        <div>
          <h4 className="text-xs font-semibold text-[var(--text)] flex items-center gap-2">
            <MousePointerClick className="w-4 h-4" /> Engagement (questions, clicks, session length)
          </h4>
          {data && <p className="text-[10px] text-[var(--text-muted)] mt-0.5 ml-6">{data.tracking}</p>}
        </div>
        <button
          onClick={() => void downloadCsv()}
          disabled={!data}
          data-track="admin.engagement-csv"
          className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface-1)] disabled:opacity-50"
        >
          <Download className="w-3.5 h-3.5" /> Engagement CSV
        </button>
      </div>

      {error && <p className="text-xs text-[var(--danger,#dc2626)]" role="alert">{error}</p>}

      {data && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-3" data-testid="engagement-totals">
            {[
              ['Visits', String(data.totals.visits)],
              ['Page views', String(data.totals.page_views)],
              ['Clicks', String(data.totals.clicks)],
              ['Questions', String(data.totals.questions)],
              ['Avg session', min(data.totals.session_minutes_avg)],
            ].map(([label, value]) => (
              <div key={label} className="bg-[var(--surface-1)] rounded-lg p-3">
                <p className="text-[10px] text-[var(--text-muted)]">{label}</p>
                <p className="text-sm font-semibold text-[var(--text)]">{value}</p>
              </div>
            ))}
          </div>

          {data.by_cohort.length > 0 && (
            <div className="mb-3" data-testid="engagement-cohorts">
              <p className="text-[10px] text-[var(--text-muted)] mb-1">By cohort</p>
              <ul className="flex flex-wrap gap-2 text-xs text-[var(--text)]">
                {data.by_cohort.map((c) => (
                  <li key={c.cohort} className="bg-[var(--surface-1)] rounded-lg px-2.5 py-1">
                    <span className="font-medium">{c.cohort}</span>: {c.users} users · {c.questions} questions ·{' '}
                    {c.clicks} clicks · {min(c.session_minutes_avg)} avg
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.by_user.length > 0 ? (
            <div className="overflow-x-auto mb-3">
              <table className="w-full text-xs text-[var(--text)]" data-testid="engagement-users">
                <thead className="text-[var(--text-muted)] text-left">
                  <tr>
                    <th className="py-1 pr-3 font-medium">Account</th>
                    <th className="py-1 pr-3 font-medium">Role</th>
                    <th className="py-1 pr-3 font-medium">Cohort</th>
                    <th className="py-1 pr-3 font-medium">Days</th>
                    <th className="py-1 pr-3 font-medium">Questions</th>
                    <th className="py-1 pr-3 font-medium">Cost</th>
                    <th className="py-1 pr-3 font-medium">Clicks</th>
                    <th className="py-1 pr-3 font-medium">Visits</th>
                    <th className="py-1 pr-3 font-medium">Avg session</th>
                    <th className="py-1 font-medium">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {data.by_user.map((u) => (
                    <tr key={u.user_key} className="border-t border-[var(--border)]">
                      <td className="py-1 pr-3 font-mono">{u.user_key}</td>
                      <td className="py-1 pr-3">{u.role || '—'}</td>
                      <td className="py-1 pr-3">{u.cohort || '—'}</td>
                      <td className="py-1 pr-3">{u.days_active}</td>
                      <td className="py-1 pr-3">{u.questions}</td>
                      <td className="py-1 pr-3">{usd(u.cost_usd)}</td>
                      <td className="py-1 pr-3">{u.clicks}</td>
                      <td className="py-1 pr-3">{u.visits}</td>
                      <td className="py-1 pr-3">{min(u.session_minutes_avg)}</td>
                      <td className="py-1 whitespace-nowrap">{u.last_seen}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-[var(--text-muted)] mb-3">No engagement events in this period yet.</p>
          )}

          {data.top_targets.length > 0 && (
            <div data-testid="engagement-targets">
              <p className="text-[10px] text-[var(--text-muted)] mb-1">Most-clicked controls</p>
              <ul className="flex flex-wrap gap-2 text-xs text-[var(--text)]">
                {data.top_targets.slice(0, 12).map((t) => (
                  <li key={t.name} className="bg-[var(--surface-1)] rounded-lg px-2 py-0.5 font-mono">
                    {t.name} · {t.clicks}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  )
}
