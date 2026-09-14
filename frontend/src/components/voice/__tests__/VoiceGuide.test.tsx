/**
 * The voice button must never be clickable when a start can only fail:
 * hidden when the feature is off, disabled with a clear message when the
 * server reports the provider as not configured or not OK (2026-09-14: a
 * dead key gave production a button that could only 503).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import VoiceGuide, { UNAVAILABLE_MESSAGE, isUnavailable } from '../VoiceGuide'
import { api } from '../../../lib/api'

const start = vi.fn()
vi.mock('../../../contexts/WebSocketContext', () => ({ useWebSocketContext: () => ({ send: vi.fn(), isConnected: true }) }))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn(), useLocation: () => ({ pathname: '/chat' }) }))
vi.mock('../../../lib/voice/liveClient', () => ({ LiveClient: class { start = start; dispose() {} contextChanged() {} } }))

const ok = { enabled: true, configured: true, provider_ok: true, max_seconds: 600 }
beforeEach(() => { vi.restoreAllMocks(); start.mockClear() })

describe('VoiceGuide availability', () => {
  it('renders nothing when voice is not enabled', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({ ...ok, enabled: false })
    const { container } = render(<VoiceGuide />)
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/voice/status'))
    expect(container).toBeEmptyDOMElement()
  })
  it.each([
    ['no key configured', { ...ok, configured: false, provider_ok: null }],
    ['provider probe failed', { ...ok, provider_ok: false }],
  ])('shows a disabled button with a clear message when %s', async (_label, status) => {
    vi.spyOn(api, 'get').mockResolvedValue(status)
    render(<VoiceGuide />)
    const button = await screen.findByRole('button', { name: UNAVAILABLE_MESSAGE })
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('title', UNAVAILABLE_MESSAGE)
    expect(screen.queryByRole('button', { name: 'Open voice guide' })).toBeNull()
  })
  it('offers a clickable guide when the provider is OK and derives the call length from the server', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ ...ok, max_seconds: 300 })
    const user = userEvent.setup()
    render(<VoiceGuide />)
    await user.click(await screen.findByRole('button', { name: 'Open voice guide' }))
    expect(screen.getByText(/Calls end after 5 minutes\./)).toBeInTheDocument()
    const begin = screen.getByRole('button', { name: 'Start voice conversation' })
    expect(begin).toBeEnabled()
    await user.click(begin)
    expect(start).toHaveBeenCalledTimes(1)
  })
  it('re-checks the server while unavailable and re-enables the button once the provider recovers', async () => {
    vi.useFakeTimers()
    try {
      const get = vi.spyOn(api, 'get').mockResolvedValueOnce({ ...ok, provider_ok: false }).mockResolvedValue(ok)
      render(<VoiceGuide />)
      await act(async () => { await Promise.resolve() })
      expect(screen.getByRole('button', { name: UNAVAILABLE_MESSAGE })).toBeDisabled()
      await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
      expect(get).toHaveBeenCalledTimes(2)
      expect(screen.getByRole('button', { name: 'Open voice guide' })).toBeEnabled()
      // Healthy state does not keep polling.
      await act(async () => { await vi.advanceTimersByTimeAsync(60000) })
      expect(get).toHaveBeenCalledTimes(2)
    } finally { vi.useRealTimers() }
  })
  it('isUnavailable treats an unknown probe with a configured key as available, and a missing key as unavailable', () => {
    expect(isUnavailable(null)).toBe(false)
    expect(isUnavailable({ ...ok, provider_ok: null })).toBe(false)
    expect(isUnavailable({ ...ok, configured: false })).toBe(true)
    expect(isUnavailable({ ...ok, provider_ok: false })).toBe(true)
  })
})
