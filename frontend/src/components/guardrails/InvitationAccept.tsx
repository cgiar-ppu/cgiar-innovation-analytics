import { useEffect, useState } from 'react'
import { acceptInvitedSession } from '../../stores/auth'
import SignInCard from './SignInCard'

export default function InvitationAccept({ token }: { token: string }) {
  const [invitation, setInvitation] = useState<{ email: string; name: string } | null>(null)
  const [error, setError] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    window.history.replaceState({}, '', '/')
    let cancelled = false
    fetch('/api/auth/invitation/inspect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token }) })
      .then(async response => {
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail || 'Invitation unavailable')
        if (!cancelled) setInvitation(data)
      }).catch(error => { if (!cancelled) setError(error.message) })
    return () => { cancelled = true }
  }, [token])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); setError('')
    if (password !== confirm) { setError('The passwords do not match.'); return }
    setBusy(true)
    try {
      const response = await fetch('/api/auth/invitation/accept', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, password }) })
      const data = await response.json()
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Choose a password of 12–72 characters.')
      acceptInvitedSession(data)
      window.location.assign('/')
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not activate your account.') }
    finally { setBusy(false) }
  }

  return <SignInCard title="Set your password" subtitle="Your invitation to Innovation Analytics">
    {error && <p role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
    {!invitation && !error && <p className="text-sm text-gray-500">Checking your invitation…</p>}
    {invitation && <form onSubmit={submit} className="space-y-4">
      <p className="text-sm text-gray-600">Welcome, {invitation.name}. Set a password for <strong>{invitation.email}</strong>.</p>
      <label className="block text-sm text-gray-600">New password
        <input required type="password" minLength={12} maxLength={72} autoComplete="new-password" value={password}
          onChange={event => setPassword(event.target.value)} className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900" />
      </label>
      <p className="text-xs text-gray-500">Use at least 12 characters.</p>
      <label className="block text-sm text-gray-600">Confirm password
        <input required type="password" autoComplete="new-password" value={confirm} onChange={event => setConfirm(event.target.value)}
          className="mt-1 w-full rounded-md border border-gray-300 px-3 py-2 text-gray-900" />
      </label>
      <button disabled={busy} type="submit" className="w-full rounded-lg bg-[#d97832] px-4 py-3 font-semibold text-gray-900 disabled:opacity-50">
        {busy ? 'Saving…' : 'Save password and sign in'}
      </button>
    </form>}
    <a href="/" className="mt-5 block text-center text-sm text-[#b75c22] hover:underline">Back to sign in</a>
  </SignInCard>
}
