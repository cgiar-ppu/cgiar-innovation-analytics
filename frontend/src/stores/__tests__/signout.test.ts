/**
 * L4-04 (logout leaves the previous user's chat on screen) and L4-08 (any SSO
 * refresh hiccup signed the user out) - Lane E, 2026-09-26.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore, setSsoRetryDelays, acceptInvitedSession } from '../auth'
import { useChatStore } from '../chat'
import { useSessionsStore } from '../sessions'
import { useAppConfigStore } from '../appConfig'
import { ACTIVE_SESSION_KEY, STATE_OWNER_KEY } from '../userStateReset'
import { navigation } from '../../lib/navigation'
import type { AppConfig } from '../../lib/types'

const alice = { userId: 'alice@cgiar.org', email: 'alice@cgiar.org', name: 'Alice', role: 'researcher' }

function seedAliceState() {
  localStorage.setItem('ia-auth-token', 'alice-token')
  localStorage.setItem('ia-auth-method', 'invited')
  localStorage.setItem(ACTIVE_SESSION_KEY, 'sess-A')
  localStorage.setItem(STATE_OWNER_KEY, alice.userId)
  useAuthStore.setState({ token: 'alice-token', user: alice, ready: true, authRequired: true, disclaimerAcknowledged: true })
  useSessionsStore.setState({ sessions: [{ session_id: 'sess-A', title: 'A private chat', model: 'claude-sonnet-5' }] as never, activeSessionId: 'sess-A', busySessions: new Set(['sess-A']) })
  useChatStore.setState({ messages: [{ id: '1', role: 'user', content: 'Alice question', timestamp: 1 }], streamingText: 'partial answer', isBusy: true })
  useChatStore.getState().cacheCurrentSession('sess-A')
  useAppConfigStore.setState({ config: { model: 'm', model_policy: { role: 'researcher' } } as unknown as AppConfig, loadedFor: alice.userId })
}

describe('sign-out wipes the previous user (L4-04)', () => {
  let hardNavigate: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    hardNavigate = vi.spyOn(navigation, 'hardNavigate').mockImplementation(() => {})
  })

  it('password/invited logout clears chat, sessions, cache, config and the persisted chat, then reloads', () => {
    seedAliceState()
    useAuthStore.getState().logout()

    const chat = useChatStore.getState()
    expect(chat.messages).toEqual([])
    expect(chat.streamingText).toBe('')
    expect(chat.isBusy).toBe(false)
    expect(chat._sessionCache.size).toBe(0)
    const sessions = useSessionsStore.getState()
    expect(sessions.activeSessionId).toBeNull()
    expect(sessions.sessions).toEqual([])
    expect(sessions.busySessions.size).toBe(0)
    expect(useAppConfigStore.getState().config).toBeNull()
    expect(localStorage.getItem(ACTIVE_SESSION_KEY)).toBeNull()
    expect(localStorage.getItem('ia-auth-token')).toBeNull()
    expect(hardNavigate).toHaveBeenCalledWith('/')
  })

  it('SSO logout wipes local state before leaving for the identity provider', async () => {
    seedAliceState()
    localStorage.setItem('ia-auth-method', 'sso')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ logout_url: 'https://idp.example/logout' }) }))
    useAuthStore.getState().logout()
    expect(useChatStore.getState().messages).toEqual([])
    expect(localStorage.getItem(ACTIVE_SESSION_KEY)).toBeNull()
    await vi.waitFor(() => expect(hardNavigate).toHaveBeenCalledWith('https://idp.example/logout'))
    vi.unstubAllGlobals()
  })

  it('a different user signing in on the same tab never sees the previous chat', () => {
    seedAliceState()
    acceptInvitedSession({ token: 'bob-token', user: { user_id: 'bob@example.org', email: 'bob@example.org', name: 'Bob', role: 'researcher' } })
    expect(useChatStore.getState().messages).toEqual([])
    expect(useSessionsStore.getState().activeSessionId).toBeNull()
    expect(localStorage.getItem(STATE_OWNER_KEY)).toBe('bob@example.org')
  })

  it('the same user signing in again keeps their open chat', () => {
    seedAliceState()
    acceptInvitedSession({ token: 'alice-token-2', user: { user_id: alice.userId, email: alice.email, name: 'Alice', role: 'researcher' } })
    expect(useSessionsStore.getState().activeSessionId).toBe('sess-A')
    expect(useChatStore.getState().messages).toHaveLength(1)
  })
})

describe('SSO refresh resilience (L4-08)', () => {
  const session = { token: 'fresh-app-token', user: { user_id: 'alice@cgiar.org', email: 'alice@cgiar.org', name: 'Alice', role: 'researcher' } }

  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    localStorage.setItem('ia-auth-method', 'sso')
    localStorage.setItem('ia-auth-token', 'current-token')
    localStorage.setItem(STATE_OWNER_KEY, 'alice@cgiar.org')
    setSsoRetryDelays([1, 1, 1])
    useAuthStore.setState({ token: 'current-token', user: { ...alice }, ready: true, authRequired: true, ssoError: null })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    setSsoRetryDelays([1_000, 4_000, 10_000])
  })

  it('retries a 5xx (deploy in progress) and keeps the user signed in', async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 502, json: async () => { throw new Error('html') } })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => session })
    vi.stubGlobal('fetch', fetcher)
    await useAuthStore.getState().refreshSso()
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(useAuthStore.getState().token).toBe('fresh-app-token')
    expect(useAuthStore.getState().user?.userId).toBe('alice@cgiar.org')
  })

  it('keeps the current session when the network stays down (next poll retries)', async () => {
    const fetcher = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetcher)
    await useAuthStore.getState().refreshSso()
    expect(fetcher).toHaveBeenCalledTimes(4) // first try + 3 retries
    expect(useAuthStore.getState().user?.userId).toBe('alice@cgiar.org')
    expect(useAuthStore.getState().token).toBe('current-token')
    expect(localStorage.getItem('ia-auth-token')).toBe('current-token')
  })

  it('signs out only on a real 401', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: 'expired' }) })
    vi.stubGlobal('fetch', fetcher)
    await useAuthStore.getState().refreshSso()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(useAuthStore.getState().user).toBeNull()
    expect(useAuthStore.getState().ssoError).toMatch(/sign in again/i)
  })

  it('on a first restore with no session, an unreachable server says so instead of "session ended"', async () => {
    useAuthStore.setState({ user: null })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({}) }))
    await useAuthStore.getState().refreshSso()
    expect(useAuthStore.getState().ready).toBe(true)
    expect(useAuthStore.getState().ssoError).toMatch(/could not be reached/i)
  })
})
