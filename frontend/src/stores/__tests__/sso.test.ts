import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../auth'

const session = { token: 'short-app-token', user: {
  user_id: 'existing@cgiar.org', email: 'existing@cgiar.org', name: 'Existing', role: 'admin',
} }

describe('SSO session lifecycle', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    window.history.replaceState({}, '', '/')
    useAuthStore.setState({ token: null, user: null, ready: false, authRequired: true,
      ssoError: null, disclaimerAcknowledged: false })
  })

  it('consumes the callback marker and deduplicates simultaneous initialization', async () => {
    window.history.replaceState({}, '', '/?sso=complete')
    localStorage.setItem('ia-disclaimer-ack:existing@cgiar.org', 'true')
    const fetcher = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => session })
    vi.stubGlobal('fetch', fetcher)
    await Promise.all([useAuthStore.getState().initialize(), useAuthStore.getState().initialize()])
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(window.location.search).toBe('')
    expect(useAuthStore.getState().user?.userId).toBe('existing@cgiar.org')
    expect(useAuthStore.getState().disclaimerAcknowledged).toBe(true)
  })

  it('clears the previous bearer token when the server session expires', async () => {
    localStorage.setItem('ia-auth-method', 'sso')
    localStorage.setItem('ia-auth-token', 'previous-user-token')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 401,
      json: async () => ({ detail: 'Session expired' }) }))
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState().user).toBeNull()
    expect(localStorage.getItem('ia-auth-token')).toBeNull()
    expect(useAuthStore.getState().ssoError).toMatch(/sign in again/i)
  })

  it('shows canceled-login errors and clears any previous app token', async () => {
    window.history.replaceState({}, '', '/?sso_error=login_failed')
    localStorage.setItem('ia-auth-token', 'previous-token')
    await useAuthStore.getState().initialize()
    expect(useAuthStore.getState().ssoError).toMatch(/canceled/)
    expect(useAuthStore.getState().user).toBeNull()
    expect(window.location.search).toBe('')
    expect(localStorage.getItem('ia-auth-token')).toBeNull()
  })

  it('cannot restore a session from an in-flight refresh after logout', async () => {
    localStorage.setItem('ia-auth-method', 'sso')
    let resolve: (value: unknown) => void = () => {}
    vi.stubGlobal('fetch', vi.fn()
      .mockImplementationOnce(() => new Promise(r => { resolve = r }))
      .mockRejectedValueOnce(new Error('offline')))
    const refresh = useAuthStore.getState().refreshSso()
    useAuthStore.getState().logout()
    resolve({ ok: true, status: 200, json: async () => session })
    await refresh
    expect(useAuthStore.getState().user).toBeNull()
    expect(localStorage.getItem('ia-auth-token')).toBeNull()
  })
})
