import { useCallback, useEffect, useState } from 'react'
import { Copy, UserPlus } from 'lucide-react'
import { getAuthToken, useAuthStore } from '../../stores/auth'
import GlassCard from '../common/GlassCard'

type Account = { email: string; name: string; enabled: number; activated: number; expires_at: number | null }

export default function InvitationManager() {
  const user = useAuthStore(s => s.user)
  const [accounts, setAccounts] = useState<Account[]>([])
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [link, setLink] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const call = useCallback(async (path: string, body?: object) => {
    const response = await fetch('/api/auth/invitations' + path, {
      method: body ? 'POST' : 'GET', headers: { Authorization: 'Bearer ' + getAuthToken(), 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    })
    const data = await response.json()
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Enter a valid external email and name.')
    return data
  }, [])
  const refresh = useCallback(() => call('').then(setAccounts).catch(error => setError(error.message)), [call])
  useEffect(() => { if (user?.role === 'admin') void refresh() }, [user?.role, refresh])
  if (user?.role !== 'admin') return null

  const invite = async (event: React.FormEvent) => {
    event.preventDefault(); setBusy(true); setError(''); setLink(''); setCopied(false)
    try {
      const data = await call('', { email: email.trim(), name: name.trim() })
      setLink(data.invitation_url); await refresh()
    } catch (error) { setError(error instanceof Error ? error.message : 'Invitation failed.') }
    finally { setBusy(false) }
  }
  return <GlassCard>
    <h2 className="flex items-center gap-2 text-sm font-semibold text-[var(--text)]"><UserPlus size={17} /> Invited external accounts</h2>
    <p className="mt-2 text-sm text-[var(--text-muted)]">Create a private invitation link for an external researcher. CGIAR staff use SSO.</p>
    {error && <p role="alert" className="mt-3 text-sm text-red-600">{error}</p>}
    <form onSubmit={invite} className="mt-4 flex flex-wrap items-end gap-3">
      <label className="min-w-40 flex-1 text-xs text-[var(--text-muted)]">Name
        <input required value={name} onChange={e => setName(e.target.value)} className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 py-2 text-sm text-[var(--text)]" />
      </label>
      <label className="min-w-48 flex-1 text-xs text-[var(--text-muted)]">External email
        <input required type="email" value={email} onChange={e => setEmail(e.target.value)} className="mt-1 w-full rounded-md border border-[var(--border)] bg-[var(--surface-1)] px-3 py-2 text-sm text-[var(--text)]" />
      </label>
      <button disabled={busy} className="rounded-md bg-[#d97832] px-4 py-2 text-sm font-semibold text-gray-900 disabled:opacity-50">{busy ? 'Creating…' : 'Create invitation link'}</button>
    </form>
    {link && <div className="mt-4 rounded-lg border border-[var(--border)] p-3">
      <p className="text-xs text-[var(--text-muted)]">Share this link privately. It expires in seven days and can be used once. No email has been sent.</p>
      <input aria-label="Invitation link" readOnly value={link} className="mt-2 w-full rounded border border-[var(--border)] bg-[var(--surface-1)] p-2 text-xs text-[var(--text)]" />
      <button type="button" className="mt-2 flex items-center gap-1 text-xs text-[var(--accent)]" onClick={async () => {
        try { await navigator.clipboard.writeText(link); setCopied(true) }
        catch { setError('Select and copy the invitation link above.') }
      }}><Copy size={14} /> {copied ? 'Copied' : 'Copy link'}</button>
    </div>}
    <div className="mt-5 space-y-3">
      {accounts.map(account => <div key={account.email} className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-3 text-sm">
        <div><p className="text-[var(--text)]">{account.name}</p><p className="text-xs text-[var(--text-muted)]">{account.email} · {!account.enabled ? 'Revoked' : account.activated ? 'Active' : 'Awaiting activation'}</p></div>
        <div className="flex gap-3 text-xs">
          <button type="button" className="text-[var(--accent)]" onClick={() => { setEmail(account.email); setName(account.name); setLink('') }}>Reissue / reset</button>
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
