/** First-party, cookieless usage events (SYN-2305). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  _pendingTelemetry, flushTelemetry, startTelemetry, stopTelemetry, trackLabelFor, trackPageView,
} from '../telemetry'

function el(html: string): HTMLElement {
  const wrap = document.createElement('div')
  wrap.innerHTML = html
  document.body.appendChild(wrap)
  return wrap
}

describe('telemetry', () => {
  let token: string | null
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    vi.useFakeTimers()
    token = 'tok-123'
    fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    document.body.innerHTML = ''
    window.history.pushState({}, '', '/chat?q=secret#x')
  })

  afterEach(() => {
    stopTelemetry()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const start = (extra = {}) => startTelemetry({
    getToken: () => token, getChatSessionId: () => 'chat-abc123', force: true,
    flushMs: 10_000, heartbeatMs: 30_000, idleMs: 300_000, ...extra,
  })

  it('is a no-op under the test runner unless forced', () => {
    startTelemetry({ getToken: () => token })
    trackPageView()
    expect(_pendingTelemetry()).toEqual([])
  })

  it('labels clicks by data-track, then data-testid, else untagged:<tag>; ignores plain areas', () => {
    const w = el('<button data-track="chat.send"><span id="in">Send secret text</span></button>'
      + '<div data-testid="scope-clear"><b id="b">x</b></div><a id="a" href="#">Link text</a><p id="p">para</p>')
    expect(trackLabelFor(w.querySelector('#in'))).toBe('chat.send')
    expect(trackLabelFor(w.querySelector('#b'))).toBe('scope-clear')
    expect(trackLabelFor(w.querySelector('#a'))).toBe('untagged:a')
    expect(trackLabelFor(w.querySelector('#p'))).toBeNull()
  })

  it('queues page views and clicks with path only, visit and chat ids, never element text', () => {
    start()
    trackPageView()
    const w = el('<button data-track="chat.new">New chat about Kenya</button><p id="p">text</p>')
    ;(w.querySelector('button') as HTMLButtonElement).click()
    ;(w.querySelector('#p') as HTMLElement).click()
    const q = _pendingTelemetry()
    expect(q.map((e) => e.type)).toEqual(['page_view', 'click'])
    expect(q[0]!.path).toBe('/chat')
    expect(q[1]!.name).toBe('chat.new')
    expect(q[1]!.chat_session_id).toBe('chat-abc123')
    expect(q[0]!.visit_id).toBe(q[1]!.visit_id)
    expect(JSON.stringify(q)).not.toMatch(/Kenya|secret/)
  })

  it('flushes on a timer with fetch keepalive + bearer header', async () => {
    start()
    trackPageView()
    await vi.advanceTimersByTimeAsync(10_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]!
    expect(url).toBe('/api/telemetry')
    expect(init.keepalive).toBe(true)
    expect(init.headers.Authorization).toBe('Bearer tok-123')
    const body = JSON.parse(init.body)
    expect(body.events).toHaveLength(1)
    expect(body.token).toBeUndefined()
    expect(_pendingTelemetry()).toEqual([])
  })

  it('stops for good when the server answers 404 (switched off)', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 404 }))
    start()
    trackPageView()
    await flushTelemetry()
    trackPageView()
    expect(_pendingTelemetry()).toEqual([])
  })

  it('keeps events when offline and retries', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('offline'))
    start()
    trackPageView()
    await flushTelemetry()
    expect(_pendingTelemetry()).toHaveLength(1)
    await flushTelemetry()
    expect(_pendingTelemetry()).toHaveLength(0)
  })

  it('uses sendBeacon with the token in the body when the page is hidden', async () => {
    const beacon = vi.fn().mockReturnValue(true)
    Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true })
    start()
    trackPageView()
    window.dispatchEvent(new Event('pagehide'))
    expect(beacon).toHaveBeenCalledTimes(1)
    const [url, blob] = beacon.mock.calls[0]!
    expect(url).toBe('/api/telemetry')
    const body = JSON.parse(await (blob as Blob).text())
    expect(body.token).toBe('tok-123')
    expect(body.events.map((e: { type: string }) => e.type)).toEqual(['page_view', 'visit_end'])
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('sends heartbeats only while the user is active', async () => {
    start({ flushMs: 10_000_000 })
    await vi.advanceTimersByTimeAsync(30_000)
    expect(_pendingTelemetry().filter((e) => e.type === 'heartbeat')).toHaveLength(1)
    expect(_pendingTelemetry()[0]!.value).toBe(30)
    await vi.advanceTimersByTimeAsync(300_000) // idle for 5+ minutes
    const beats = _pendingTelemetry().filter((e) => e.type === 'heartbeat').length
    await vi.advanceTimersByTimeAsync(60_000)
    expect(_pendingTelemetry().filter((e) => e.type === 'heartbeat')).toHaveLength(beats)
    document.dispatchEvent(new KeyboardEvent('keydown'))
    await vi.advanceTimersByTimeAsync(30_000)
    expect(_pendingTelemetry().filter((e) => e.type === 'heartbeat')).toHaveLength(beats + 1)
  })

  it('stops listening after stop', () => {
    start()
    stopTelemetry()
    el('<button data-track="chat.send">x</button>').querySelector('button')!.click()
    expect(_pendingTelemetry()).toEqual([])
  })
})
