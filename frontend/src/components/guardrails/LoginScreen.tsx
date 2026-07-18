/**
 * @file LoginScreen.tsx
 *
 * App-level password login surface (Step 3 — Option A: issued passwords via the
 * backend JWT/bcrypt allow-list). CGIAR staff will later reach the same tool via
 * Cognito + Entra ID SSO; this screen is the issued-password path that runs now
 * and stays as the external-user path afterwards.
 */

import { useState } from 'react'
import { motion } from 'framer-motion'
import { Lock } from 'lucide-react'
import { useAuthStore } from '../../stores/auth'

export default function LoginScreen() {
  const login = useAuthStore((s) => s.login)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    const err = await login(email.trim(), password)
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
            <Lock className="w-6 h-6 text-[var(--accent)]" />
          </div>
          <h1 className="text-lg font-semibold text-[var(--text)]">CGIAR Innovation Analytics</h1>
          <p className="text-xs text-[var(--text-muted)] mt-1">Sign in to continue</p>
        </div>

        <form onSubmit={onSubmit} className="space-y-3">
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
            autoComplete="current-password"
            required
            placeholder="Password"
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
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="text-[10px] text-[var(--text-muted)] text-center mt-5 leading-relaxed">
          CGIAR staff SSO (Microsoft Entra ID) is being enabled. For now, use the
          password issued to you. AI outputs are for guidance only and require
          human quality assurance.
        </p>
      </motion.div>
    </div>
  )
}
