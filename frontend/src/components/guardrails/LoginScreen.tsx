/**
 * @file LoginScreen.tsx
 *
 * App-level password login surface (Step 3 — Option A: issued passwords via the
 * backend JWT/bcrypt allow-list). CGIAR staff will later reach the same tool via
 * Cognito + Entra ID SSO; this screen is the issued-password path that runs now
 * and stays as the external-user path afterwards.
 *
 * Also hosts the interim self-signup toggle (no email confirmation) — shown
 * only when the backend reports `self_signup: true` (IA_SELF_SIGNUP), so
 * closed deployments (the current prod lineage) never see the option.
 */

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Lock, UserPlus } from 'lucide-react'
import { useAuthStore } from '../../stores/auth'

export default function LoginScreen() {
  const login = useAuthStore((s) => s.login)
  const signup = useAuthStore((s) => s.signup)

  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [selfSignupEnabled, setSelfSignupEnabled] = useState(false)

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // Discover whether self-signup is available. Fetched directly (not via the
  // authenticated api client) because LoginScreen renders before any token
  // exists, and /api/config is intentionally unauthenticated.
  useEffect(() => {
    let cancelled = false
    fetch('/api/config')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!cancelled && data) setSelfSignupEnabled(Boolean(data.self_signup))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  const switchMode = (next: 'login' | 'signup') => {
    setMode(next)
    setError(null)
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const err =
      mode === 'signup'
        ? await signup(name.trim(), email.trim(), password)
        : await login(email.trim(), password)
    setBusy(false)
    if (err) setError(err)
  }

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-[var(--bg)]">
      <div className="bg-mesh" aria-hidden="true" />
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative glass-strong rounded-2xl border border-[var(--border)] shadow-2xl w-full max-w-sm p-7"
      >
        <div className="flex flex-col items-center text-center mb-6">
          <div className="w-12 h-12 rounded-xl flex items-center justify-center bg-[var(--accent)]/10 mb-3">
            {mode === 'signup' ? (
              <UserPlus className="w-6 h-6 text-[var(--accent)]" />
            ) : (
              <Lock className="w-6 h-6 text-[var(--accent)]" />
            )}
          </div>
          <h1 className="text-lg font-semibold text-[var(--text)]">CGIAR Innovation Analytics</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {mode === 'signup' ? 'Create your account' : 'Sign in to continue'}
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
          {mode === 'signup' && (
            <input
              type="text"
              autoComplete="name"
              required
              placeholder="Full name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
              data-testid="signup-name"
            />
          )}
          <input
            type="email"
            autoComplete="username"
            required
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
            data-testid="login-email"
          />
          <input
            type="password"
            autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
            required
            minLength={mode === 'signup' ? 8 : undefined}
            placeholder={mode === 'signup' ? 'Password (min. 8 characters)' : 'Password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
            data-testid="login-password"
          />

          {error && (
            <p className="text-xs text-red-500" role="alert" data-testid="login-error">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 transition disabled:opacity-50"
            data-testid="login-submit"
          >
            {busy
              ? mode === 'signup'
                ? 'Creating account…'
                : 'Signing in…'
              : mode === 'signup'
                ? 'Create account'
                : 'Sign in'}
          </button>
        </form>

        {selfSignupEnabled && (
          <button
            type="button"
            onClick={() => switchMode(mode === 'signup' ? 'login' : 'signup')}
            className="w-full text-center mt-4 text-xs text-[var(--accent)] hover:underline"
            data-testid="signup-toggle"
          >
            {mode === 'signup' ? 'Already have an account? Sign in' : 'Create account'}
          </button>
        )}

        <p className="text-[10px] text-[var(--text-muted)] text-center mt-5 leading-relaxed">
          {mode === 'signup'
            ? 'Self-signup is an interim measure — no email confirmation is required, so use your real work email. AI outputs are for guidance only and require human quality assurance.'
            : 'CGIAR staff SSO (Microsoft Entra ID) is being enabled. For now, use the password issued to you. AI outputs are for guidance only and require human quality assurance.'}
        </p>
      </motion.div>
    </div>
  )
}
