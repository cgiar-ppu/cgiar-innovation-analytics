/**
 * Tests for the Zustand chat store (stores/chat.ts).
 *
 * Each test resets the store to a clean slate before running, using
 * useChatStore.setState directly so tests are fully independent.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { useChatStore } from '../chat'
import { flushStreamingDeltas } from '../chat/messageHandlers'

// Mock the api module so loadHistory tests don't hit the network
vi.mock('../../lib/api', () => ({
  api: {
    getHistory: vi.fn(),
  },
}))

// Helper: reset the store to its initial state before every test
function resetStore() {
  useChatStore.setState({
    messages: [],
    streamingText: '',
    streamingThinking: '',
    isBusy: false,
    cancelled: false,
    activeAgent: null,
    aupError: null,
  })
}

describe('chat store', () => {
  beforeEach(() => {
    resetStore()
  })

  // -----------------------------------------------------------------------
  // addUserMessage
  // -----------------------------------------------------------------------
  it('test_addMessage_appends_to_messages', () => {
    const { addUserMessage } = useChatStore.getState()
    expect(useChatStore.getState().messages).toHaveLength(0)

    addUserMessage('Hello, world')

    const { messages } = useChatStore.getState()
    expect(messages).toHaveLength(1)
    expect(messages[0]?.role).toBe('user')
    expect(messages[0]?.content).toBe('Hello, world')
  })

  it('test_addMessage_sets_busy', () => {
    useChatStore.getState().addUserMessage('hi')
    expect(useChatStore.getState().isBusy).toBe(true)
  })

  // -----------------------------------------------------------------------
  // clearStreamingBuffers (via clearMessages which resets them)
  // -----------------------------------------------------------------------
  it('test_clearStreamingBuffers', () => {
    // Manually populate buffers then clear them
    useChatStore.setState({ streamingText: 'partial text', streamingThinking: 'partial think' })
    expect(useChatStore.getState().streamingText).toBe('partial text')
    expect(useChatStore.getState().streamingThinking).toBe('partial think')

    useChatStore.getState().clearMessages()

    expect(useChatStore.getState().streamingText).toBe('')
    expect(useChatStore.getState().streamingThinking).toBe('')
    expect(useChatStore.getState().messages).toHaveLength(0)
  })

  // -----------------------------------------------------------------------
  // handleServerMessage — text
  // -----------------------------------------------------------------------
  it('test_handleServerMessage_text', () => {
    const { handleServerMessage } = useChatStore.getState()

    handleServerMessage({ type: 'text', content: 'Hello ' })
    flushStreamingDeltas()
    expect(useChatStore.getState().streamingText).toBe('Hello ')

    handleServerMessage({ type: 'text', content: 'world' })
    flushStreamingDeltas()
    expect(useChatStore.getState().streamingText).toBe('Hello world')
  })

  it('test_handleServerMessage_text_accumulates', () => {
    const { handleServerMessage } = useChatStore.getState()
    handleServerMessage({ type: 'text', content: 'chunk1' })
    handleServerMessage({ type: 'text', content: 'chunk2' })
    flushStreamingDeltas()
    expect(useChatStore.getState().streamingText).toBe('chunk1chunk2')
  })

  // -----------------------------------------------------------------------
  // handleServerMessage — tool_use
  // -----------------------------------------------------------------------
  it('test_handleServerMessage_tool_use', () => {
    const { handleServerMessage } = useChatStore.getState()

    handleServerMessage({
      type: 'tool_use',
      tool: 'bash',
      input: { command: 'ls' },
      tool_use_id: 'tu-001',
    })

    const { messages } = useChatStore.getState()
    expect(messages).toHaveLength(1)
    expect(messages[0]?.role).toBe('tool_use')
    expect(messages[0]?.tool).toBe('bash')
    expect(messages[0]?.toolInput).toEqual({ command: 'ls' })
    expect(messages[0]?.toolUseId).toBe('tu-001')
  })

  it('test_handleServerMessage_tool_use_finalizes_streaming_text', () => {
    // Pre-load a streaming text buffer
    useChatStore.setState({ streamingText: 'partial response' })

    useChatStore.getState().handleServerMessage({
      type: 'tool_use',
      tool: 'read_file',
      input: {},
      tool_use_id: 'tu-002',
    })

    const { messages, streamingText } = useChatStore.getState()
    // The streaming text should have been flushed into an assistant message
    expect(streamingText).toBe('')
    // messages: [assistant from flush, tool_use]
    expect(messages).toHaveLength(2)
    expect(messages[0]?.role).toBe('assistant')
    expect(messages[0]?.content).toBe('partial response')
    expect(messages[1]?.role).toBe('tool_use')
  })

  // -----------------------------------------------------------------------
  // handleServerMessage — result
  // -----------------------------------------------------------------------
  it('test_handleServerMessage_result', () => {
    // Pre-load a streaming text buffer
    useChatStore.setState({ streamingText: 'final text', isBusy: true })

    useChatStore.getState().handleServerMessage({
      type: 'result',
      estimated_cost: 0.005,
      turns: 3,
      duration_ms: 1200,
      session_id: 'sess-1',
      is_error: false,
      auth_method: 'api_key',
    })

    const { messages, isBusy, streamingText } = useChatStore.getState()
    // Streaming text flushed + result message appended
    expect(streamingText).toBe('')
    expect(isBusy).toBe(false)
    // messages: [assistant, result]
    const resultMsg = messages.find(m => m.role === 'result')
    expect(resultMsg).toBeDefined()
    expect(resultMsg?.estimatedCost).toBe(0.005)
    expect(resultMsg?.turns).toBe(3)
    expect(resultMsg?.durationMs).toBe(1200)
  })

  it('test_handleServerMessage_result_clears_busy', () => {
    useChatStore.setState({ isBusy: true })
    useChatStore.getState().handleServerMessage({
      type: 'result',
      estimated_cost: null,
      turns: 1,
      duration_ms: 500,
      session_id: 'sess-1',
      is_error: false,
      auth_method: 'api_key',
    })
    expect(useChatStore.getState().isBusy).toBe(false)
  })

  // -----------------------------------------------------------------------
  // setBusy / setCancelled
  // -----------------------------------------------------------------------
  it('test_setBusy_and_clear', () => {
    const { setBusy } = useChatStore.getState()

    expect(useChatStore.getState().isBusy).toBe(false)
    setBusy(true)
    expect(useChatStore.getState().isBusy).toBe(true)
    setBusy(false)
    expect(useChatStore.getState().isBusy).toBe(false)
  })

  it('test_setCancelled_toggles', () => {
    const { setCancelled } = useChatStore.getState()

    setCancelled(true)
    expect(useChatStore.getState().cancelled).toBe(true)
    setCancelled(false)
    expect(useChatStore.getState().cancelled).toBe(false)
  })

  // -----------------------------------------------------------------------
  // handleServerMessage — thinking
  // -----------------------------------------------------------------------
  it('test_handleServerMessage_thinking_accumulates', () => {
    const { handleServerMessage } = useChatStore.getState()

    handleServerMessage({ type: 'thinking', content: 'think ' })
    handleServerMessage({ type: 'thinking', content: 'more' })
    flushStreamingDeltas()

    expect(useChatStore.getState().streamingThinking).toBe('think more')
  })
})
