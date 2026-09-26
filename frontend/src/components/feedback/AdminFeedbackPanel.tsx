/**
 * Settings → Feedback (administrators only): everyone's answer and voice
 * feedback with date / rating / cohort / channel filters and a CSV download.
 * The server enforces admin-only access (GET /api/admin/feedback); this
 * component simply renders nothing for other roles.
 */
import { useCallback, useEffect, useState } from 'react'
import { Download, MessageSquareHeart, RefreshCw } from 'lucide-react'
import GlassCard from '../common/GlassCard'
import { useAuthStore } from '../../stores/auth'
import { downloadAdminCsv, FeedbackDisabledError, listAdminFeedback, type AdminFeedbackList, type AdminFilters } from './api'

const input = 'mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-2 py-1.5 text-sm text-[var(--text)]'

export function ratingLabel(channel: string, rating: number) {
  if (channel === 'chat') return rating > 0 ? 'Helpful' : 'Not helpful'
  return `${rating}/5`
}

export default function AdminFeedbackPanel() {
  const role = useAuthStore(s => s.user?.role)
  const [filters, setFilters] = useState<AdminFilters>({ rating: '', cohort: '', channel: '' })
  const [data, setData] = useState<AdminFeedbackList | null>(null)
  const [error, setError] = useState('')
  const [off, setOff] = useState(false)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async (current: AdminFilters) => {
    setBusy(true); setError('')
    try { setData(await listAdminFeedback(current)) }
    catch (e) {
      if (e instanceof FeedbackDisabledError) setOff(true)
      else setError(e instanceof Error ? e.message : 'Feedback could not be loaded.')
    } finally { setBusy(false) }
  }, [])
  useEffect(() => { if (role === 'admin') void refresh(filters) }, [role, filters, refresh])
  if (role !== 'admin' || off) return null

  const set = (key: keyof AdminFilters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setFilters(f => ({ ...f, [key]: e.target.value }))
  const csv = async () => {
    setError('')
    try { await downloadAdminCsv(filters) } catch (e) { setError(e instanceof Error ? e.message : 'CSV export failed.') }
  }

  return <GlassCard>
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div>
        <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]"><MessageSquareHeart size={17} /> Feedback</h2>
        <p className="mt-1 text-xs text-[var(--text-muted)]">Ratings and comments from testers on answers and voice sessions. Visible to administrators only; nothing is emailed.</p>
      </div>
      <div className="flex gap-2">
        <button type="button" onClick={() => void refresh(filters)} aria-label="Refresh feedback" className="rounded-lg p-1.5 text-[var(--text-muted)] hover:bg-[var(--surface-1)]"><RefreshCw size={16} className={busy ? 'animate-spin' : ''} /></button>
        <button type="button" onClick={() => void csv()} className="flex items-center gap-1 rounded-md border border-[var(--border)] px-3 py-1.5 text-xs text-[var(--text)]"><Download size={14} /> Download CSV</button>
      </div>
    </div>
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
      <label className="text-xs text-[var(--text-muted)]">From<input type="date" value={filters.from ?? ''} onChange={set('from')} className={input} /></label>
      <label className="text-xs text-[var(--text-muted)]">To<input type="date" value={filters.to ?? ''} onChange={set('to')} className={input} /></label>
      <label className="text-xs text-[var(--text-muted)]">Rating<select value={filters.rating} onChange={set('rating')} className={input}>
        <option value="">All</option><option value="positive">Positive</option><option value="negative">Negative</option><option value="neutral">Neutral (voice 3/5)</option>
      </select></label>
      <label className="text-xs text-[var(--text-muted)]">Cohort<select value={filters.cohort} onChange={set('cohort')} className={input}>
        <option value="">All</option>{(data?.cohorts ?? []).map(c => <option key={c} value={c}>{c}</option>)}<option value="__none__">No cohort (e.g. CGIAR SSO)</option>
      </select></label>
      <label className="text-xs text-[var(--text-muted)]">Channel<select value={filters.channel} onChange={set('channel')} className={input}>
        <option value="">All</option><option value="chat">Chat answers</option><option value="voice">Voice sessions</option>
      </select></label>
    </div>
    {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
    {data && <p className="mt-3 text-xs text-[var(--text-muted)]" data-testid="feedback-summary">
      {data.total} feedback item{data.total === 1 ? '' : 's'} · {data.counts.positive} positive · {data.counts.negative} negative · {data.counts.neutral} neutral
      {data.returned < data.total && ` · showing the newest ${data.returned}`}
    </p>}
    <div className="mt-3 max-h-[28rem] space-y-2 overflow-y-auto">
      {data?.items.map(item => <details key={item.id} className="rounded-lg border border-[var(--border)] p-3 text-sm">
        <summary className="cursor-pointer list-none">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${item.sentiment === 'positive' ? 'bg-emerald-500/15 text-emerald-700' : item.sentiment === 'negative' ? 'bg-red-500/15 text-red-700' : 'bg-amber-500/15 text-amber-700'}`}>{ratingLabel(item.channel, item.rating)}</span>
            <span className="text-xs text-[var(--text-muted)]">{item.channel === 'voice' ? 'Voice' : 'Chat'} · {item.created_at.slice(0, 16).replace('T', ' ')} UTC</span>
            <span className="text-xs text-[var(--text)]">{item.user_name || item.user_email || 'Unknown user'}</span>
            {item.cohort && <span className="rounded bg-[var(--surface-1)] px-1.5 py-0.5 text-xs text-[var(--text-muted)]">{item.cohort}</span>}
          </div>
          {item.comment && <p className="mt-1 whitespace-pre-wrap text-[var(--text)]">{item.comment}</p>}
        </summary>
        <dl className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 text-xs text-[var(--text-muted)] sm:grid-cols-2">
          {item.expected && <div className="sm:col-span-2"><dt className="font-medium">What it should have said</dt><dd className="whitespace-pre-wrap text-[var(--text)]">{item.expected}</dd></div>}
          <div><dt className="inline font-medium">User: </dt><dd className="inline">{item.user_email || '—'} ({item.role || '—'})</dd></div>
          <div><dt className="inline font-medium">Model: </dt><dd className="inline">{item.model || '—'}</dd></div>
          <div><dt className="inline font-medium">Specialist: </dt><dd className="inline">{item.persona || 'default'}</dd></div>
          <div><dt className="inline font-medium">Scope: </dt><dd className="inline">{item.scope || 'all data'}</dd></div>
          <div><dt className="inline font-medium">App version: </dt><dd className="inline">{item.app_version || '—'} · {item.environment}</dd></div>
          <div><dt className="inline font-medium">Answer: </dt><dd className="inline">{item.message_id || 'voice session'}</dd></div>
          {item.shared_question !== null && <div className="sm:col-span-2"><dt className="font-medium">Shared question</dt><dd className="whitespace-pre-wrap text-[var(--text)]">{item.shared_question}</dd></div>}
          {item.shared_answer !== null && <div className="sm:col-span-2"><dt className="font-medium">Shared answer</dt><dd className="max-h-60 overflow-y-auto whitespace-pre-wrap text-[var(--text)]">{item.shared_answer}</dd></div>}
          {item.shared_question === null && item.channel === 'chat' && <div className="sm:col-span-2 italic">The user did not share the question and answer.</div>}
        </dl>
      </details>)}
      {data && !data.items.length && <p className="text-xs text-[var(--text-muted)]">No feedback matches these filters yet.</p>}
    </div>
  </GlassCard>
}
