import { useEffect, useState } from 'react'
import { Eye, EyeOff, LogIn, ShieldCheck } from 'lucide-react'
import { useAuthStore } from '../../stores/auth'
import SignInCard from './SignInCard'

const fieldClass = 'mt-1.5 w-full rounded-md border border-[#d1d5db] bg-white px-3 py-2.5 text-sm text-[#111827] outline-none focus:border-[#d97832] focus:ring-2 focus:ring-[#d97832]/20'

export default function LoginScreen() {
  const login = useAuthStore(s => s.login)
  const signup = useAuthStore(s => s.signup)
  const ssoError = useAuthStore(s => s.ssoError)
  const [ssoEnabled, setSsoEnabled] = useState(false)
  const [passwordEnabled, setPasswordEnabled] = useState(false)
  const [invitedOnly, setInvitedOnly] = useState(false)
  const [configReady, setConfigReady] = useState(false)
  const [selfSignup, setSelfSignup] = useState(false)
  const [domains, setDomains] = useState<string[]>([])
  const [mode, setMode] = useState<'login' | 'signup'>('login')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showRecovery, setShowRecovery] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetch('/api/config').then(res => {
      if (!res.ok) throw new Error('Config unavailable')
      return res.json()
    }).then(data => {
      if (cancelled) return
      setSsoEnabled(Boolean(data.sso_enabled))
      setInvitedOnly(Boolean(data.invited_login_enabled))
      setPasswordEnabled(Boolean(data.invited_login_enabled) || data.password_login_enabled !== false)
      setSelfSignup(Boolean(data.self_signup) && !data.invited_login_enabled)
      setDomains(Array.isArray(data.signup_allowed_domains) ? data.signup_allowed_domains : [])
      setConfigReady(true)
    }).catch(() => {
      if (!cancelled) setError('Could not load sign-in settings. Please refresh and try again.')
    })
    return () => { cancelled = true }
  }, [])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    setBusy(true); setError(null)
    const problem = mode === 'signup'
      ? await signup(name.trim(), email.trim(), password)
      : await login(email.trim(), password)
    setBusy(false); setError(problem)
  }

  return (
    <SignInCard title={mode === 'signup' ? 'Create account' : 'Sign In'}
      subtitle="Explore the CGIAR innovation portfolio">
      {(error || ssoError) && <p role="alert" data-testid="login-error"
        className="mb-5 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">{error || ssoError}</p>}
      {!configReady && !error && <p className="text-center text-sm text-[#6b7280]">Loading sign-in…</p>}
      {ssoEnabled && <div>
        <p className="mb-2.5 text-center text-sm font-medium text-[#374151]">Sign in with your CGIAR account</p>
        <a href="/api/auth/sso/start" data-testid="sso-login"
          className="flex min-h-14 w-full items-center justify-center gap-2 rounded-lg bg-[#d97832] px-4 py-3 text-base font-semibold text-[#111827] shadow-sm transition hover:bg-[#cb6928] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#b95d22]">
          <ShieldCheck size={21} aria-hidden="true" /> Sign in with CGIAR SSO
        </a>
        <p className="mt-2 text-center text-xs text-[#8b93a1]">Recommended for all CGIAR staff</p>
      </div>}
      {ssoEnabled && passwordEnabled && <div className="my-6 flex items-center gap-3 text-[11px] text-[#8b93a1]">
        <span className="h-px flex-1 bg-[#e5e7eb]" /><span>OR SIGN IN WITH EMAIL</span><span className="h-px flex-1 bg-[#e5e7eb]" />
      </div>}
      {passwordEnabled && <form onSubmit={submit} className="space-y-4">
        {mode === 'signup' && <label className="block text-xs font-medium text-[#6b7280]">Full name
          <input required autoComplete="name" value={name} onChange={e => setName(e.target.value)} className={fieldClass} data-testid="signup-name" />
        </label>}
        <label className="block text-xs font-medium text-[#6b7280]" htmlFor="signin-email">Email
          <input id="signin-email" type="email" required autoComplete="username" value={email}
            onChange={e => setEmail(e.target.value)} className={fieldClass} data-testid="login-email" />
        </label>
        <div>
          <label className="text-xs font-medium text-[#6b7280]" htmlFor="signin-password">Password</label>
          <div className="relative">
            <input id="signin-password" type={showPassword ? 'text' : 'password'} required
              autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} minLength={mode === 'signup' ? 8 : undefined}
              value={password} onChange={e => setPassword(e.target.value)} className={fieldClass + ' pr-11'} data-testid="login-password" />
            <button type="button" aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword} onClick={() => setShowPassword(v => !v)}
              className="absolute inset-y-0 right-0 mt-1.5 flex w-11 items-center justify-center rounded-md text-[#6b7280] focus-visible:outline focus-visible:outline-[#d97832]">
              {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
            </button>
          </div>
        </div>
        {invitedOnly && <div className="text-right">
          <button type="button" className="text-xs text-[#b75c22] hover:underline" onClick={() => setShowRecovery(v => !v)}>Forgot password?</button>
          {showRecovery && <p role="status" className="mt-2 rounded-md bg-[#f6f7f6] p-3 text-left text-xs leading-relaxed text-[#6b7280]">
            Ask your administrator for a new invitation link. Opening that link lets you securely reset your password.
          </p>}
        </div>}
        {mode === 'signup' && domains.length > 0 && <p data-testid="signup-domain-hint" className="text-xs text-[#6b7280]">
          Sign-up is limited to CGIAR email addresses ({domains.map(d => '@' + d).join(', ')}).
        </p>}
        <button type="submit" disabled={busy} data-testid="login-submit"
          className="flex min-h-11 w-full items-center justify-center gap-2 rounded-md border border-[#d1d5db] bg-white px-3 py-2 text-sm font-semibold text-[#4b5563] transition hover:bg-[#f6f7f6] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[#d97832] disabled:opacity-50">
          <LogIn size={17} /> {busy ? 'Signing in…' : mode === 'signup' ? 'Create account' : 'Sign in with email'}
        </button>
      </form>}
      {invitedOnly && <p className="mt-3 text-center text-xs leading-relaxed text-[#8b93a1]">
        Email login is for invited users. Need access? Contact your administrator.
      </p>}
      {selfSignup && passwordEnabled && <button type="button" data-testid="signup-toggle"
        className="mt-4 w-full text-center text-xs text-[#b75c22] hover:underline"
        onClick={() => { setMode(mode === 'signup' ? 'login' : 'signup'); setError(null) }}>
        {mode === 'signup' ? 'Already have an account? Sign in' : 'Create account'}
      </button>}
      {configReady && <p className="mt-6 text-center text-[11px] leading-relaxed text-[#8b93a1]">
        AI outputs require human quality assurance. Signing out here does not sign you out of Microsoft.
      </p>}
    </SignInCard>
  )
}
