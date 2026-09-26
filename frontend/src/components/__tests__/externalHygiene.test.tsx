/**
 * External-user hygiene (Lane E, 2026-09-26):
 *  - L4-07 disclaimer background is inert;
 *  - L4-05 no zombie WebSocket after sign-out/unmount;
 *  - L4-01 AI-produced HTML runs in an opaque-origin sandbox;
 *  - L4-10 a message that cannot be sent keeps the draft and says why;
 *  - voice cannot open the admin-only Agents page for researchers.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, renderHook, act, fireEvent } from '@testing-library/react'
import AuthGate from '../guardrails/AuthGate'
import { useAuthStore } from '../../stores/auth'
import { useAppConfigStore } from '../../stores/appConfig'
import { useWebSocket } from '../../hooks/useWebSocket'
import { InteractiveContent, HTML_SANDBOX } from '../chat/InteractiveContent'
import { ChatInput } from '../input/ChatInput'
import { useChatDraft } from '../../lib/chatCommands'
import { runWhileConnected } from '../../lib/connectionNotice'
import { makeAdapter } from '../../lib/voice/actions'
import type { AppConfig } from '../../lib/types'

describe('disclaimer gate (L4-07)', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({
      ready: true, authRequired: true, disclaimerAcknowledged: false, token: 't',
      user: { userId: 'u@cgiar.org', email: 'u@cgiar.org', name: 'U', role: 'researcher' },
      initialize: vi.fn(async () => {}),
    })
  })

  it('renders the app behind the modal as inert, so the keyboard cannot reach it', () => {
    render(<AuthGate><button>Send to the agent</button></AuthGate>)
    const background = screen.getByTestId('disclaimer-background')
    expect(background).toHaveAttribute('inert')
    expect(background).toHaveAttribute('aria-hidden', 'true')
    // Focus starts on the acknowledgement, inside the dialog.
    expect(document.activeElement).toBe(screen.getByTestId('disclaimer-understand'))
  })

  it('removes the inert wrapper once the user clicks "I understand"', () => {
    render(<AuthGate><button>Send to the agent</button></AuthGate>)
    fireEvent.click(screen.getByTestId('disclaimer-understand'))
    expect(screen.queryByTestId('disclaimer-background')).toBeNull()
    expect(screen.getByRole('button', { name: 'Send to the agent' })).toBeInTheDocument()
  })
})

describe('WebSocket lifecycle (L4-05)', () => {
  class FakeSocket {
    static instances: FakeSocket[] = []
    static OPEN = 1
    static CONNECTING = 0
    readyState = 0
    onopen: (() => void) | null = null
    onclose: (() => void) | null = null
    onmessage: ((e: unknown) => void) | null = null
    onerror: (() => void) | null = null
    url: string
    constructor(url: string) { this.url = url; FakeSocket.instances.push(this) }
    send() {}
    close() { this.readyState = 3; this.onclose?.() }
  }

  beforeEach(() => {
    vi.useFakeTimers()
    FakeSocket.instances = []
    vi.stubGlobal('WebSocket', FakeSocket)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('does not open a new socket after unmount (sign-out)', () => {
    const { unmount } = renderHook(() => useWebSocket())
    const opened = FakeSocket.instances.length
    expect(opened).toBeGreaterThan(0)
    unmount()
    act(() => { vi.advanceTimersByTime(120_000) })
    expect(FakeSocket.instances.length).toBe(opened)
  })

  it('still reconnects after an unexpected drop while mounted', () => {
    renderHook(() => useWebSocket())
    const first = FakeSocket.instances[FakeSocket.instances.length - 1]!
    act(() => { first.readyState = 3; first.onclose?.() })
    act(() => { vi.advanceTimersByTime(1_500) })
    expect(FakeSocket.instances.length).toBeGreaterThan(1)
  })
})

describe('AI-produced HTML (L4-01)', () => {
  it('runs in an opaque-origin sandbox and offers no same-origin "open in new tab"', () => {
    const { container } = render(<InteractiveContent content={'<!DOCTYPE html><html><body><script>1</script></body></html>'} />)
    const frame = container.querySelector('iframe')!
    expect(HTML_SANDBOX).toBe('allow-scripts')
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts')
    expect(frame.getAttribute('sandbox')).not.toContain('allow-same-origin')
    expect(screen.queryByText(/open in new tab/i)).toBeNull()
  })
})

describe('sending while disconnected (L4-10)', () => {
  beforeEach(() => useChatDraft.getState().setText(''))

  it('keeps the draft when the send fails', () => {
    const onSend = vi.fn(() => false)
    render(<ChatInput onSend={onSend} onCancel={vi.fn()} onFileUpload={vi.fn()} isBusy={false} />)
    const box = screen.getByPlaceholderText(/ask about cgiar/i)
    fireEvent.change(box, { target: { value: 'How many innovations in 2025?' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(onSend).toHaveBeenCalledWith('How many innovations in 2025?')
    expect(useChatDraft.getState().text).toBe('How many innovations in 2025?')
  })

  it('clears the draft when the send succeeds', () => {
    render(<ChatInput onSend={vi.fn(() => true)} onCancel={vi.fn()} onFileUpload={vi.fn()} isBusy={false} />)
    const box = screen.getByPlaceholderText(/ask about cgiar/i)
    fireEvent.change(box, { target: { value: 'hello' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(useChatDraft.getState().text).toBe('')
  })

  it('runWhileConnected turns a socket error into false instead of an uncaught throw', () => {
    expect(runWhileConnected(() => { throw new Error('Chat is disconnected.') })).toBe(false)
    expect(runWhileConnected(() => {})).toBe(true)
  })
})

describe('voice navigation (L4-03)', () => {
  const signal = new AbortController().signal
  function adapterFor(role: string) {
    useAuthStore.setState({ user: { userId: `${role}@x`, email: '', name: '', role } })
    useAppConfigStore.setState({ config: { model: 'm', model_policy: { role } } as unknown as AppConfig, loadedFor: `${role}@x` })
    const navigate = vi.fn()
    return { navigate, adapter: makeAdapter(vi.fn(), navigate, () => '/chat', () => true) }
  }

  it('refuses the Agents page for researchers', async () => {
    const { adapter, navigate } = adapterFor('researcher')
    const result = await adapter.execute('navigate', { page: 'agents' }, signal, () => true)
    expect(result.ok).toBe(false)
    expect(navigate).not.toHaveBeenCalled()
  })

  it('allows it for administrators', async () => {
    const { adapter, navigate } = adapterFor('admin')
    const result = await adapter.execute('navigate', { page: 'agents' }, signal, () => true)
    expect(result.ok).toBe(true)
    expect(navigate).toHaveBeenCalledWith('/agents')
  })
})
