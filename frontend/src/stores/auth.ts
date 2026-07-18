/**
 * @file auth.ts
 * @module stores
 *
 * Zustand store for authentication + the guardrails acknowledgment gate.
 *
 * This store is the frontend half of the July-7 guardrails sprint. It holds:
 *  - the JWT session token and the resolved user identity (Step 3 — login);
 *  - the "I understand" disclaimer acknowledgment flag (Step 1 — guardrails).
 *
 * Identity is deliberately modelled as an abstraction: the rest of the app
 * only ever reads `user.userId` (a stable string claim). Today that claim is
 * the app-password user's email (JWT `sub`); when CGIAR Entra ID SSO is
 * federated via Cognito it becomes the Cognito `sub` — no consumer changes.
 *
 * Persistence:
 *  - The token is persisted to localStorage so a page reload stays logged in.
 *  - The disclaimer acknowledgment is persisted per-user in localStorage now;
 *    once the server-side per-user record lands it is mirrored there too.
 */

import { create } from 'zustand'

const TOKEN_KEY = 'ia-auth-token'
const ACK_KEY_PREFIX = 'ia-disclaimer-ack:'

/** The resolved, identity-provider-agnostic user. */
export interface AuthUser {
  /** Stable identity claim (JWT `sub`). The ONLY field downstream code should key on. */
  userId: string
  email: string
  name: string
  role: string
}

interface AuthState {
  /** JWT bearer token, or null when logged out. */
  token: string | null
  /** Resolved user identity, or null when logged out. */
  user: AuthUser | null
  /** Whether the current user has clicked "I understand" on the disclaimer modal. */
  disclaimerAcknowledged: boolean
  /** True once the initial token-restore + /me check has completed. */
  ready: boolean
  /** Whether the backend requires authentication (false in dev-bypass mode). */
  authRequired: boolean

  /** Restore token from storage and validate it against /api/auth/me. */
  initialize: () => Promise<void>
  /** Log in with email + password. Returns null on success, or an error string. */
  login: (email: string, password: string) => Promise<string | null>
  /** Clear the session (token + user). The disclaimer ack persists per-user. */
  logout: () => void
  /** Record the "I understand" acknowledgment (persisted per-user). */
  acknowledgeDisclaimer: () => void
}

/** Read the per-user disclaimer ack flag from localStorage. */
function readAck(userId: string | null): boolean {
  const key = ACK_KEY_PREFIX + (userId ?? 'anon')
  return localStorage.getItem(key) === 'true'
}

/** Persist the per-user disclaimer ack flag to localStorage. */
function writeAck(userId: string | null): void {
  const key = ACK_KEY_PREFIX + (userId ?? 'anon')
  localStorage.setItem(key, 'true')
}

/** Map a raw /api server user payload to the identity-agnostic {@link AuthUser}. */
function toAuthUser(raw: { email?: string; name?: string; role?: string; user_id?: string; sub?: string }): AuthUser {
  const email = raw.email ?? ''
  // Prefer an explicit user_id / sub claim; fall back to email as the stable id.
  const userId = raw.user_id ?? raw.sub ?? email
  return { userId, email, name: raw.name ?? '', role: raw.role ?? 'user' }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem(TOKEN_KEY),
  user: null,
  disclaimerAcknowledged: false,
  ready: false,
  authRequired: true,

  initialize: async () => {
    // Discover whether the backend enforces auth (dev-bypass returns a user
    // from /me with no token). This keeps local dev frictionless while the
    // deployed dev URL requires a real login.
    const token = localStorage.getItem(TOKEN_KEY)
    try {
      const res = await fetch('/api/auth/me', {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      })
      if (res.ok) {
        const raw = await res.json()
        const user = toAuthUser(raw)
        set({
          token,
          user,
          disclaimerAcknowledged: readAck(user.userId),
          ready: true,
          // If /me succeeded WITHOUT a token, the backend is in dev-bypass mode.
          authRequired: Boolean(token),
        })
        return
      }
    } catch {
      // Network / backend error — fall through to logged-out state.
    }
    // No valid session.
    if (token) localStorage.removeItem(TOKEN_KEY)
    set({ token: null, user: null, disclaimerAcknowledged: readAck(null), ready: true, authRequired: true })
  },

  login: async (email, password) => {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      if (!res.ok) {
        return res.status === 401 ? 'Invalid email or password.' : `Login failed (${res.status}).`
      }
      const data = await res.json()
      const token: string = data.token
      const user = toAuthUser(data.user ?? {})
      localStorage.setItem(TOKEN_KEY, token)
      set({
        token,
        user,
        disclaimerAcknowledged: readAck(user.userId),
        authRequired: true,
      })
      return null
    } catch {
      return 'Could not reach the server. Please try again.'
    }
  },

  logout: () => {
    localStorage.removeItem(TOKEN_KEY)
    set({ token: null, user: null, disclaimerAcknowledged: false })
  },

  acknowledgeDisclaimer: () => {
    const { user } = get()
    writeAck(user?.userId ?? null)
    set({ disclaimerAcknowledged: true })
  },
}))

/** Returns the current bearer token (for attaching to fetch / WebSocket calls). */
export function getAuthToken(): string | null {
  return useAuthStore.getState().token
}
