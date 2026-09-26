import { useCallback, useEffect, useMemo, useState } from 'react'
import { Copy, UserPlus, Users } from 'lucide-react'
import { getAuthToken, useAuthStore } from '../../stores/auth'
import GlassCard from '../common/GlassCard'

type Account = { email: string; name: string; enabled: number; activated: number; expires_at: number | null; cohort?: string }
type Invitee = { email: string; name: string }
type Created = Invitee & { invitation_url: string }
type BulkResult = { cohort: string; expires_in_days: number; invitations: Created[]; errors: { email: string; error: string }[] }

const EXPIRY_CHOICES = [7, 14, 30]
const inputClass = 'mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 py-2 text-sm text-[var(--text)]'

/** "Jane Doe" from jane.doe@example.org when no name is given. */
function nameFromEmail(email: string) {
  return email.split('@')[0]!.split(/[._-]+/).filter(Boolean).map(p => p[0]!.toUpperCase() + p.slice(1)).join(' ') || email
}

/**
 * One person per line: `Name <email>`, `email, Name`, `Name, email` or just `email`.
 * Lines without an email address are reported, not guessed.
 */
export function parseInvitees(text: string): { invitees: Invitee[]; problems: string[] } {
  const invitees: Invitee[] = []
  const problems: string[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    const angle = /^(.*?)<\s*([^<>\s]+@[^<>\s]+)\s*>\s*,?$/.exec(line)
    if (angle) {
      const email = angle[2]!.trim()
      invitees.push({ email, name: angle[1]!.replace(/["',;]+/g, ' ').trim() || nameFromEmail(email) })
      continue
    }
    const parts = line.split(/[,;\t]/).map(p => p.trim().replace(/^"|"$/g, '')).filter(Boolean)
    const email = parts.find(p => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(p))
    if (!email) { problems.push(line); continue }
    const name = parts.filter(p => p !== email).join(' ').trim()
    invitees.push({ email, name: name || nameFromEmail(email) })
  }
  return { invitees, problems }
}

function CopyButton({ text, label = 'Copy link', onError }: { text: string; label?: string; onError: (message: string) => void }) {
  const [copied, setCopied] = useState(false)
  return <button type="button" className="flex items-center gap-1 text-xs text-[var(--accent)]" onClick={async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true) }
    catch { onError('Select and copy the invitation link manually.') }
  }}><Copy size={14} /> {copied ? 'Copied' : label}</button>
}

export default function InvitationManager() {
  const user = useAuthStore(s => s.user)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [mode, setMode] = useState<'one' | 'many'>('one')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [bulkText, setBulkText] = useState('')
  const [cohort, setCohort] = useState('')
  const [expiry, setExpiry] = useState(7)
  const [link, setLink] = useState('')
  const [bulk, setBulk] = useState<BulkResult | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [cohortFilter, setCohortFilter] = useState('')
  const call = useCallback(async (path: string, body?: object) => {
    const response = await fetch('/api/auth/invitations' + path, {
      method: body ? 'POST' : 'GET', headers: { Authorization: 'Bearer ' + getAuthToken(), 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    const data = await response.json()
    if (!response.ok) {
      const detail = Array.isArray(data.detail) ? String(data.detail[0]?.msg ?? '').replace(/^Value error, /, '') : data.detail
      throw new Error(typeof detail === 'string' && detail ? detail : 'Enter a valid external email and name.')
    }
    return data
  }, [])
  const refresh = useCallback(() => call('').then(setAccounts).catch(error => setError(error.message)), [call])
  useEffect(() => { if (user?.role === 'admin') void refresh() }, [user?.role, refresh])
  const cohorts = useMemo(() => [...new Set(accounts.map(a => a.cohort || '').filter(Boolean))].sort(), [accounts])
  const parsed = useMemo(() => parseInvitees(bulkText), [bulkText])
  if (user?.role !== 'admin') return null

  const reset = () => { setBusy(true); setError(''); setNotice(''); setLink(''); setBulk(null) }
  const invite = async (event: React.FormEvent) => {
    event.preventDefault(); reset()
    try {
      if (mode === 'one') {
        const data = await call('', { email: email.trim(), name: name.trim(), cohort: cohort.trim(), expires_in_days: expiry })
        setLink(data.invitation_url)
      } else {
        if (!parsed.invitees.length) throw new Error('Add at least one line with an email address.')
        setBulk(await call('/bulk', { invitees: parsed.invitees, cohort: cohort.trim(), expires_in_days: expiry }))
      }
      await refresh()
    } catch (error) { setError(error instanceof Error ? error.message : 'Invitation failed.') }
    finally { setBusy(false) }
  }
  const revokeCohort = async () => {
    if (!cohortFilter || !window.confirm(`Revoke access for everyone in "${cohortFilter}"? Their links and sign-ins stop working immediately.`)) return
    reset()
    try {
      const data = await call('/revoke-cohort', { cohort: cohortFilter })
      setNotice(`Revoked ${data.revoked} account${data.revoked === 1 ? '' : 's'} in "${cohortFilter}".`); await refresh()
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not revoke the cohort.') }
    finally { setBusy(false) }
  }
  const expiryNote = (days: number) => `It expires in ${days === 7 ? 'seven' : days} days and can be used once. No email has been sent.`
  const shown = cohortFilter ? accounts.filter(a => (a.cohort || '') === cohortFilter) : accounts

  return <GlassCard>
    <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]"><UserPlus size={17} /> Invited external accounts</h2>
    <p className="mt-2 text-sm text-[var(--text-muted)]">Create a private invitation link for an external researcher, or links for a whole test group. CGIAR staff use SSO.</p>
    {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
    {notice && <p role="status" className="mt-3 text-sm text-[var(--text)]">{notice}</p>}
    <div className="mt-4 flex gap-2 text-xs" role="tablist" aria-label="Invitation mode">
      {(['one', 'many'] as const).map(m => <button key={m} type="button" role="tab" aria-selected={mode === m} onClick={() => { setMode(m); setLink(''); setBulk(null) }}
        className={`rounded-md border px-3 py-1.5 ${mode === m ? 'border-[var(--accent)] text-[var(--text)]' : 'border-[var(--border)] text-[var(--text-muted)]'}`}>
        {m === 'one' ? 'One person' : 'Several people (test group)'}</button>)}
    </div>
    <form onSubmit={invite} className="mt-3 flex flex-wrap items-end gap-3">
      {mode === 'one' ? <>
        <label className="min-w-40 flex-1 text-xs text-[var(--text-muted)]">Name
          <input required value={name} onChange={e => setName(e.target.value)} className={inputClass} />
        </label>
        <label className="min-w-48 flex-1 text-xs text-[var(--text-muted)]">External email
          <input required type="email" value={email} onChange={e => setEmail(e.target.value)} className={inputClass} />
        </label>
      </> : <label className="w-full text-xs text-[var(--text-muted)]">People to invite (one per line: <code>Name &lt;email&gt;</code>, <code>email, Name</code> or just the email)
        <textarea required rows={5} value={bulkText} onChange={e => setBulkText(e.target.value)} className={inputClass + ' font-mono'} placeholder={'Jane Doe <jane.doe@worldbank.org>\njohn.smith@fcdo.gov.uk, John Smith'} />
        <span className="mt-1 block">{parsed.invitees.length} recognised{parsed.problems.length ? ` · ${parsed.problems.length} line(s) without an email will be skipped` : ''} · up to 50 at a time</span>
      </label>}
      <label className="min-w-48 flex-1 text-xs text-[var(--text-muted)]">Test cohort (optional)
        <input value={cohort} maxLength={60} list="ia-cohorts" onChange={e => setCohort(e.target.value)} placeholder="e.g. WB TTLs Oct-2026" className={inputClass} />
        <datalist id="ia-cohorts">{cohorts.map(c => <option key={c} value={c} />)}</datalist>
      </label>
      <label className="w-32 text-xs text-[var(--text-muted)]">Link valid for
        <select value={expiry} onChange={e => setExpiry(Number(e.target.value))} className={inputClass}>
          {EXPIRY_CHOICES.map(d => <option key={d} value={d}>{d} days</option>)}
        </select>
      </label>
      <button disabled={busy} className="rounded-md bg-[#d97832] px-4 py-2 text-sm font-semibold text-gray-900 disabled:opacity-50">
        {busy ? 'Creating…' : mode === 'one' ? 'Create invitation link' : `Create ${parsed.invitees.length || ''} links`.replace('  ', ' ')}</button>
    </form>
    {link && <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
      <p className="text-xs text-[var(--text-muted)]">Share this link privately. {expiryNote(expiry)}</p>
      <input aria-label="Invitation link" readOnly value={link} className="mt-2 w-full rounded border border-[var(--border)] bg-[var(--surface-1)] p-2 text-xs text-[var(--text)]" />
      <div className="mt-2"><CopyButton text={link} onError={setError} /></div>
    </div>}
    {bulk && <div className="mt-4 rounded-lg border border-[var(--border)] p-3" data-testid="bulk-links">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-[var(--text-muted)]">{bulk.invitations.length} link{bulk.invitations.length === 1 ? '' : 's'}{bulk.cohort ? ` for "${bulk.cohort}"` : ''}. Send each person only their own link. {expiryNote(bulk.expires_in_days)}</p>
        {bulk.invitations.length > 1 && <CopyButton label="Copy all (name, email, link)" onError={setError}
          text={bulk.invitations.map(i => `${i.name}\t${i.email}\t${i.invitation_url}`).join('\n')} />}
      </div>
      <ul className="mt-2 space-y-2">
        {bulk.invitations.map(i => <li key={i.email} className="text-xs">
          <p className="text-[var(--text)]">{i.name} · {i.email}</p>
          <input aria-label={`Invitation link for ${i.email}`} readOnly value={i.invitation_url} className="mt-1 w-full rounded border border-[var(--border)] bg-[var(--surface-1)] p-1.5 text-[var(--text)]" />
          <div className="mt-1"><CopyButton text={i.invitation_url} onError={setError} /></div>
        </li>)}
      </ul>
      {!!bulk.errors.length && <div className="mt-3 text-xs text-red-600" role="alert">
        <p className="font-medium">Not invited:</p>
        <ul>{bulk.errors.map((e, n) => <li key={n}>{e.email || '(blank)'}: {e.error}</li>)}</ul>
      </div>}
    </div>}
    <div className="mt-5 flex flex-wrap items-end gap-3 border-t border-[var(--border)] pt-3">
      <label className="text-xs text-[var(--text-muted)]"><Users size={13} className="mr-1 inline" />Show cohort
        <select value={cohortFilter} onChange={e => setCohortFilter(e.target.value)} className={inputClass}>
          <option value="">All accounts</option>{cohorts.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
      </label>
      {cohortFilter && <button type="button" disabled={busy} onClick={() => void revokeCohort()} className="rounded-md border border-red-600/40 px-3 py-2 text-xs text-red-600">End test round: revoke everyone in this cohort</button>}
    </div>
    <div className="mt-3 space-y-3">
      {shown.map(account => <div key={account.email} className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-3 text-sm">
        <div><p className="text-[var(--text)]">{account.name}{account.cohort ? <span className="ml-2 rounded bg-[var(--surface-1)] px-1.5 py-0.5 text-[10px] text-[var(--text-muted)]">{account.cohort}</span> : null}</p>
          <p className="text-xs text-[var(--text-muted)]">{account.email} · {!account.enabled ? 'Revoked' : account.activated ? 'Active' : 'Awaiting activation'}</p></div>
        <div className="flex gap-3 text-xs">
          <button type="button" className="text-[var(--accent)]" onClick={() => { setMode('one'); setEmail(account.email); setName(account.name); setCohort(account.cohort || ''); setLink(''); setBulk(null) }}>Reissue / reset</button>
          {Boolean(account.enabled) && <button type="button" className="text-red-600" onClick={async () => {
            try { await call('/revoke', { email: account.email, name: account.name }); setLink(''); await refresh() }
            catch (error) { setError(error instanceof Error ? error.message : 'Could not revoke access.') }
          }}>Revoke access</button>}
        </div>
      </div>)}
      {!accounts.length && <p className="text-xs text-[var(--text-muted)]">No external accounts have been invited.</p>}
    </div>
  </GlassCard>
}
