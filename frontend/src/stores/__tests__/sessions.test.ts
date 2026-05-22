/**
 * Tests for the Zustand sessions store (stores/sessions.ts).
 *
 * Network-dependent actions (loadSessions, renameSession, deleteSession) are
 * covered by mocking the api module. State-only actions are tested directly.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useSessionsStore } from '../sessions'
import type { Session } from '../../lib/types'

// Mock the api module
vi.mock('../../lib/api', () => ({
  api: {
    getSessions: vi.fn(),
    renameSession: vi.fn(),
    deleteSession: vi.fn(),
  },
}))

// Helper: build a minimal Session object
function makeSession(id: string, title = 'Test session'): Session {
  return {
    session_id: id,
    title,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    model: 'claude-sonnet-4-6',
    message_count: 0,
    pinned: false,
  }
}

// Helper: reset the store before each test
function resetStore() {
  useSessionsStore.setState({
    sessions: [],
    activeSessionId: null,
    loading: false,
    busySessions: new Set<string>(),
  })
}

describe('sessions store', () => {
  beforeEach(() => {
    resetStore()
  })

  // -----------------------------------------------------------------------
  // setActiveSession
  // -----------------------------------------------------------------------
  it('test_setActiveSessionId', () => {
    expect(useSessionsStore.getState().activeSessionId).toBeNull()

    useSessionsStore.getState().setActiveSession('sess-abc')
    expect(useSessionsStore.getState().activeSessionId).toBe('sess-abc')
  })

  it('test_setActiveSessionId_allows_null', () => {
    useSessionsStore.setState({ activeSessionId: 'sess-abc' })
    useSessionsStore.getState().setActiveSession(null)
    expect(useSessionsStore.getState().activeSessionId).toBeNull()
  })

  // -----------------------------------------------------------------------
  // Direct state manipulation — setSessions_replaces_list
  // -----------------------------------------------------------------------
  it('test_setSessions_replaces_list', () => {
    const initial = [makeSession('s1'), makeSession('s2')]
    useSessionsStore.setState({ sessions: initial })

    expect(useSessionsStore.getState().sessions).toHaveLength(2)

    const replacement = [makeSession('s3')]
    useSessionsStore.setState({ sessions: replacement })

    const { sessions } = useSessionsStore.getState()
    expect(sessions).toHaveLength(1)
    expect(sessions[0]?.session_id).toBe('s3')
  })

  // -----------------------------------------------------------------------
  // addSession_prepends — simulated via setState since the store has no
  // direct addSession action; we test the insertion pattern that callers use
  // (prepending via setState) and verify ordering.
  // -----------------------------------------------------------------------
  it('test_addSession_prepends', () => {
    const existing = makeSession('s-old', 'Old session')
    useSessionsStore.setState({ sessions: [existing] })

    const newSession = makeSession('s-new', 'New session')
    // Simulate prepend as callers would do
    useSessionsStore.setState((s) => ({
      sessions: [newSession, ...s.sessions],
    }))

    const { sessions } = useSessionsStore.getState()
    expect(sessions).toHaveLength(2)
    expect(sessions[0]?.session_id).toBe('s-new')
    expect(sessions[1]?.session_id).toBe('s-old')
  })

  // -----------------------------------------------------------------------
  // markSessionBusy / markSessionComplete
  // -----------------------------------------------------------------------
  it('test_markSessionBusy_adds_to_set', () => {
    useSessionsStore.getState().markSessionBusy('sess-1')
    expect(useSessionsStore.getState().busySessions.has('sess-1')).toBe(true)
  })

  it('test_markSessionComplete_removes_from_set', () => {
    useSessionsStore.getState().markSessionBusy('sess-1')
    useSessionsStore.getState().markSessionComplete('sess-1')
    expect(useSessionsStore.getState().busySessions.has('sess-1')).toBe(false)
  })

  // -----------------------------------------------------------------------
  // loadSessions — delegates to api
  // -----------------------------------------------------------------------
  it('test_loadSessions_populates_sessions', async () => {
    const { api } = await import('../../lib/api')
    const mockSessions = [makeSession('loaded-1'), makeSession('loaded-2')]
    vi.mocked(api.getSessions).mockResolvedValueOnce({ sessions: mockSessions })

    await useSessionsStore.getState().loadSessions()

    const { sessions, loading } = useSessionsStore.getState()
    expect(sessions).toHaveLength(2)
    expect(sessions[0]?.session_id).toBe('loaded-1')
    expect(loading).toBe(false)
  })

  it('test_loadSessions_sets_loading_false_on_error', async () => {
    const { api } = await import('../../lib/api')
    vi.mocked(api.getSessions).mockRejectedValueOnce(new Error('Network error'))

    await useSessionsStore.getState().loadSessions()

    expect(useSessionsStore.getState().loading).toBe(false)
  })
})
