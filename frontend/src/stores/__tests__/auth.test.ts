/**
 * Tests for the auth + guardrails store (July-7 Steps 1 & 3).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useAuthStore, getAuthToken } from '../auth'

function resetStore() {
  localStorage.clear()
  useAuthStore.setState({
    token: null,
    user: null,
    disclaimerAcknowledged: false,
    ready: false,
    authRequired: true,
  })
}

describe('auth store', () => {
  beforeEach(() => {
    resetStore()
    vi.restoreAllMocks()
  })

  it('initialize enters dev-bypass mode when /me returns a user without a token', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ user_id: 'legacy@innovation-analytics', email: 'dev@localhost', name: 'Dev', role: 'admin' }),
      }),
    )
    await useAuthStore.getState().initialize()
    const s = useAuthStore.getState()
    expect(s.ready).toBe(true)
    expect(s.authRequired).toBe(false) // dev bypass
    expect(s.user?.userId).toBe('legacy@innovation-analytics')
  })

  it('initialize with no token and 401 leaves the user logged out and auth required', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    await useAuthStore.getState().initialize()
    const s = useAuthStore.getState()
    expect(s.ready).toBe(true)
    expect(s.authRequired).toBe(true)
    expect(s.user).toBeNull()
  })

  it('login stores the token and resolves the identity via user_id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          token: 'jwt-abc',
          user: { user_id: 'alice@cgiar.org', email: 'alice@cgiar.org', name: 'Alice', role: 'admin' },
        }),
      }),
    )
    const err = await useAuthStore.getState().login('alice@cgiar.org', 'pw')
    expect(err).toBeNull()
    expect(getAuthToken()).toBe('jwt-abc')
    expect(useAuthStore.getState().user?.userId).toBe('alice@cgiar.org')
    expect(localStorage.getItem('ia-auth-token')).toBe('jwt-abc')
  })

  it('login returns an error message on 401', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    const err = await useAuthStore.getState().login('x@y.z', 'bad')
    expect(err).toMatch(/invalid/i)
    expect(getAuthToken()).toBeNull()
  })

  it('acknowledgeDisclaimer persists per-user and gates on the flag', () => {
    useAuthStore.setState({ user: { userId: 'alice@cgiar.org', email: 'a', name: 'A', role: 'user' } })
    expect(useAuthStore.getState().disclaimerAcknowledged).toBe(false)
    useAuthStore.getState().acknowledgeDisclaimer()
    expect(useAuthStore.getState().disclaimerAcknowledged).toBe(true)
    expect(localStorage.getItem('ia-disclaimer-ack:alice@cgiar.org')).toBe('true')
  })

  it('logout clears the token and user', () => {
    useAuthStore.setState({ token: 't', user: { userId: 'u', email: 'e', name: 'n', role: 'user' } })
    localStorage.setItem('ia-auth-token', 't')
    useAuthStore.getState().logout()
    expect(useAuthStore.getState().token).toBeNull()
    expect(useAuthStore.getState().user).toBeNull()
    expect(localStorage.getItem('ia-auth-token')).toBeNull()
  })
})
