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
  const linkSso = useAuthStore((s) => s.linkSso)
  const ssoLinkEmail = useAuthStore((s) => s.ssoLinkEmail)
  const ssoError = useAuthStore((s) => s.ssoError)
  const logout = useAuthStore((s) => s.logout)
  const [ssoEnabled, setSsoEnabled] = useState(false)

  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [selfSignupEnabled, setSelfSignupEnabled] = useState(false)
  // Email domains self-signup accepts (config.signup_allowed_domains).
  // Empty = no restriction, so no hint is shown.
  const [allowedDomains, setAllowedDomains] = useState<string[]>([])

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
        if (!cancelled && data) {
          setSelfSignupEnabled(Boolean(data.self_signup))
          setSsoEnabled(Boolean(data.sso_enabled))
          setAllowedDomains(
            Array.isArray(data.signup_allowed_domains) ? data.signup_allowed_domains : []
          )
        }
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
      ssoLinkEmail
        ? await linkSso(password)
        : mode === 'signup'
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
            {ssoLinkEmail ? 'Connect your existing account' : mode === 'signup' ? 'Create your account' : 'Sign in to continue'}
          </p>
        </div>

        {ssoEnabled && !ssoLinkEmail && (
          <a href="/api/auth/sso/start" data-testid="sso-login"
            className="block w-full text-center mb-5 px-4 py-2.5 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 focus-visible:ring-2 focus-visible:ring-[var(--accent)]">
            Sign in with CGIAR
          </a>
        )}
        {ssoLinkEmail && (
          <p className="text-sm text-[var(--text-muted)] mb-4" data-testid="sso-link-help">
            Microsoft verified {ssoLinkEmail}. Enter your existing Innovation Analytics password once
            to keep your personal chats and access. Use your application password, not your Microsoft password.
          </p>
        )}
        {ssoError && <p role="alert" className="text-xs text-red-500 mb-4">{ssoError}</p>}
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
            value={ssoLinkEmail || email}
            readOnly={Boolean(ssoLinkEmail)}
            aria-label="Email"
            onChange={(e) => setEmail(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
            data-testid="login-email"
          />
          <input
            type="password"
            aria-label={ssoLinkEmail ? 'Existing application password' : 'Password'}
            autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
            required
            minLength={mode === 'signup' ? 8 : undefined}
            placeholder={mode === 'signup' ? 'Password (min. 8 characters)' : 'Password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-3 py-2 rounded-lg border border-[var(--border)] bg-transparent text-sm text-[var(--text)] focus:outline-none focus:ring-2 focus:ring-[var(--accent)]/40"
            data-testid="login-password"
          />

          {mode === 'signup' && allowedDomains.length > 0 && (
            <p className="text-xs text-[var(--text-muted)]" data-testid="signup-domain-hint">
              Sign-up is limited to CGIAR email addresses (
              {allowedDomains.map((d) => `@${d}`).join(', ')}).
            </p>
          )}

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
            {ssoLinkEmail ? (busy ? 'Connecting…' : 'Connect account') : busy
              ? mode === 'signup'
                ? 'Creating account…'
                : 'Signing in…'
              : mode === 'signup'
                ? 'Create account'
                : 'Sign in'}
          </button>
        </form>

        {ssoLinkEmail && <button type="button" onClick={logout}
          className="w-full text-center mt-4 text-xs text-[var(--accent)] hover:underline">Cancel and sign out</button>}
        {selfSignupEnabled && !ssoLinkEmail && (
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
          {ssoEnabled
            ? 'Use your CGIAR Microsoft account, or your existing application password below. Signing out of this tool does not sign you out of Microsoft. AI outputs require human quality assurance.'
            : mode === 'signup'
            ? 'Self-signup is an interim measure — no email confirmation is required, so use your real work email. AI outputs are for guidance only and require human quality assurance.'
            : 'CGIAR staff SSO (Microsoft Entra ID) is being enabled. For now, use the password issued to you. AI outputs are for guidance only and require human quality assurance.'}
        </p>
      </motion.div>
    </div>
  )
}
