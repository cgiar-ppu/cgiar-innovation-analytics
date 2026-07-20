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

  it('signup stores the token and resolves the identity (immediate access, no confirmation)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          token: 'jwt-new',
          user: { user_id: 'new@cgiar.org', email: 'new@cgiar.org', name: 'New', role: 'researcher' },
        }),
      }),
    )
    const err = await useAuthStore.getState().signup('New', 'new@cgiar.org', 'a-strong-pw')
    expect(err).toBeNull()
    expect(getAuthToken()).toBe('jwt-new')
    expect(useAuthStore.getState().user?.role).toBe('researcher')
    expect(localStorage.getItem('ia-auth-token')).toBe('jwt-new')
  })

  it('signup returns a friendly error on 409 (duplicate email)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 409 }))
    const err = await useAuthStore.getState().signup('Dup', 'dup@cgiar.org', 'a-strong-pw')
    expect(err).toMatch(/already exists/i)
    expect(getAuthToken()).toBeNull()
  })

  it('signup returns a friendly error on 422 (weak password / bad email)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422 }))
    const err = await useAuthStore.getState().signup('Weak', 'weak@cgiar.org', 'short')
    expect(err).toMatch(/valid email|8 characters/i)
  })

  it('signup returns a friendly error on 404 (flag disabled)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
    const err = await useAuthStore.getState().signup('X', 'x@cgiar.org', 'a-strong-pw')
    expect(err).toMatch(/not available/i)
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
