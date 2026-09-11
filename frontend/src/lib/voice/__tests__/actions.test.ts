import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../../api'
import { makeAdapter } from '../actions'
import { observeChatEvent, useChatDraft } from '../../chatCommands'
import { useChatStore } from '../../../stores/chat'
import { useSessionsStore } from '../../../stores/sessions'
import { useScopeStore } from '../../../stores/scope'
import { usePersonaStore } from '../../../stores/persona'

const chats = ['one', 'two'].map(id => ({ session_id: id, title: id, message_count: 0 })) as any
const signal = new AbortController().signal
beforeEach(() => {
  vi.restoreAllMocks()
  useSessionsStore.setState({ activeSessionId: 'one', sessions: chats, busySessions: new Set() })
  useChatStore.getState().clearMessages()
  useChatDraft.getState().setText('')
  useScopeStore.getState().clearScope()
  usePersonaStore.getState().clearPersona()
  vi.spyOn(api, 'getSessions').mockResolvedValue({ sessions: chats })
  vi.spyOn(api, 'getHistory').mockResolvedValue({ messages: [], session_id: 'two' })
})

function setup() {
  const send = vi.fn((message: any) => {
    queueMicrotask(() => {
      if (message.type === 'switch_session') observeChatEvent({ type: 'session', session_id: message.session_id })
      else if (message.message) observeChatEvent({ type: 'text', session_id: 'one', run_id: 'real-receipt', content: 'Working' })
    })
  })
  const navigate = vi.fn()
  return { send, navigate, adapter: makeAdapter(send, navigate, () => '/chat', () => true) }
}

describe('voice native chat actions', () => {
  it('reads app without mutating and rejects unsupported action/arguments', async () => {
    const { adapter, send, navigate } = setup()
    expect((await adapter.execute('read_app', {}, signal, () => true)).active_chat).toBe('one')
    expect((await adapter.execute('delete_chat', {}, signal, () => true)).ok).toBe(false)
    expect((await adapter.execute('read_app', { extra: true }, signal, () => true)).ok).toBe(false)
    expect(send).not.toHaveBeenCalled(); expect(navigate).not.toHaveBeenCalled()
  })
  it('cycles real session state and wraps to the previous chat', async () => {
    const { adapter } = setup()
    expect((await adapter.execute('cycle_chats', { direction: 'previous' }, signal, () => true)).session_id).toBe('two')
    expect(useSessionsStore.getState().activeSessionId).toBe('two')
  })
  it('manual change during server history fetch wins', async () => {
    let finish!: (value: any) => void
    vi.mocked(api.getHistory).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const { adapter, send } = setup()
    const task = adapter.execute('open_chat', { session_id: 'two' }, signal, () => true)
    await Promise.resolve(); await Promise.resolve()
    useSessionsStore.getState().setActiveSession('manual')
    finish({ messages: [], session_id: 'two' })
    expect((await task).ok).toBe(false)
    expect(useSessionsStore.getState().activeSessionId).toBe('manual')
    expect(send).not.toHaveBeenCalled()
  })
  it('preserves draft and rejects a stale chat ID and a busy chat', async () => {
    const { adapter, send } = setup()
    const query = { session_id: 'one', message: 'Check this' }
    useChatDraft.getState().setText('My unfinished draft')
    expect((await adapter.execute('send_query', query, signal, () => true)).ok).toBe(false)
    expect(useChatDraft.getState().text).toBe('My unfinished draft')
    useChatDraft.getState().setText('')
    expect((await adapter.execute('send_query', { ...query, session_id: 'two' }, signal, () => true)).ok).toBe(false)
    useChatStore.getState().setBusy(true)
    expect((await adapter.execute('send_query', query, signal, () => true)).ok).toBe(false)
    expect(send).not.toHaveBeenCalled()
  })
  it('submits through the shared chat command with scope/persona and a server receipt', async () => {
    useScopeStore.setState({ years: [2025], programs: ['SP09'] })
    usePersonaStore.getState().selectPersona('prms_data_analyst')
    const { adapter, send } = setup()
    const result = await adapter.execute('send_query', { session_id: 'one', message: 'Verify the cited result codes' }, signal, () => true)
    expect(result.status).toBe('accepted'); expect(result.run_id).toBe('real-receipt')
    expect(send).toHaveBeenCalledWith({ message: 'Verify the cited result codes', scope: { years: [2025], programs: ['SP09'] }, agent: 'prms_data_analyst' })
    expect(useChatStore.getState().messages.slice(-1)[0]?.content).toBe('Verify the cited result codes')
  })
})
