/**
 * Voice feedback mode (Lane H): a normal End asks the rating question once
 * (respecting the call cap), a second End closes at once, the guide's
 * submit_feedback action is stored via /api/feedback (channel voice) and
 * never reaches the app adapter, and the hard time limit never waits.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveClient, FEEDBACK_GOODBYE_MS, FEEDBACK_WINDOW_MS } from '../liveClient'

let posts: { url: string; body: Record<string, unknown> }[]
beforeEach(() => {
  vi.useFakeTimers({ now: 1_000_000 })
  vi.stubGlobal('Audio', class { autoplay = false; pause() {}; play() { return Promise.resolve() } })
  posts = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    posts.push({ url, body: JSON.parse(String(init?.body ?? '{}')) })
    return new Response(JSON.stringify(url.startsWith('/api/feedback') ? { id: 1, rating: 4 } : { closed: true }), { status: 200 })
  }))
})
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })

function live({ callMs = 120_000, leftMs = 300_000, prompt = true } = {}) {
  const execute = vi.fn().mockResolvedValue({ ok: true })
  const cb = { status: vi.fn(), caption: vi.fn(), task: vi.fn(), playbackBlocked: vi.fn(), usage: vi.fn(), evidence: vi.fn(), feedback: vi.fn() }
  const client = new LiveClient(cb, { execute, subscribe: () => () => {} }) as any
  client.channel = { readyState: 'open', send: vi.fn(), close: vi.fn() }
  client.abort = new AbortController(); client.ready = true; client.requestId = '6f1c7d0e-9c1b-4a57-8f7a-2b3c4d5e6f70'
  client.connectedAt = Date.now() - callMs; client.expiresAt = Date.now() + leftMs
  client.setFeedbackPrompt(prompt)
  const frames = () => client.channel.send.mock.calls.map((c: any[]) => JSON.parse(c[0]))
  return { client, cb, execute, frames }
}

describe('End-of-call feedback', () => {
  it('asks once on a normal End, keeps the call open, and a second End closes immediately', () => {
    const { client, cb, frames } = live()
    client.end()
    expect(cb.feedback).toHaveBeenCalledWith('asking')
    expect(client.closing).toBe(false)
    const ask = frames().find((f: any) => f.event_id === 'ia_feedback')
    expect(ask.type).toBe('session.instructions.append')
    expect(ask.content).toMatch(/ask ONCE/i)
    expect(ask.content).toMatch(/Do not ask again/)
    client.onEvent({ type: 'session.instructions.appended', client_event_id: 'ia_feedback' })
    expect(frames().slice(-1)[0]!).toMatchObject({ type: 'session.commentary.append' })
    client.end()
    expect(client.closing).toBe(true)
    expect(frames().slice(-1)[0]!).toMatchObject({ type: 'session.close' })
    expect(frames().filter((f: any) => f.event_id === 'ia_feedback')).toHaveLength(1)
  })

  it('closes by itself if nobody answers within the feedback window', () => {
    const { client } = live()
    client.end()
    vi.advanceTimersByTime(FEEDBACK_WINDOW_MS)
    expect(client.closing).toBe(true)
  })

  it.each([
    ['the call was very short', { callMs: 5_000 }],
    ['the call is close to its time limit', { leftMs: 30_000 }],
    ['the environment switched the prompt off', { prompt: false }],
  ])('does not ask when %s', (_why, options) => {
    const { client, cb } = live(options)
    client.end()
    expect(cb.feedback).not.toHaveBeenCalledWith('asking')
    expect(client.closing).toBe(true)
  })

  it('the hard time limit ends without asking', () => {
    const { client, cb } = live()
    client.end({ skipFeedback: true })
    expect(cb.feedback).not.toHaveBeenCalledWith('asking')
    expect(client.closing).toBe(true)
  })

  it("stores the guide's submit_feedback call for this voice session, even with app actions paused, then closes after the goodbye", async () => {
    const { client, execute, cb, frames } = live()
    client.end(); client.paused = true
    const epoch = client.epoch
    client.onEvent({ type: 'response.event', delegation_id: 'd1', event: { type: 'response.created', response: { id: 'r1' } } })
    client.batches.get('r1').epoch = epoch
    client.onEvent({ type: 'response.event', delegation_id: 'd1', event: { type: 'response.output_item.done', response_id: 'r1', item: { type: 'function_call', call_id: 'c1', name: 'submit_feedback', arguments: '{"rating":4,"improvement":"Show sources sooner"}' } } })
    client.onEvent({ type: 'response.event', delegation_id: 'd1', event: { type: 'response.completed', response: { id: 'r1' } } })
    await vi.waitFor(() => expect(posts.some(p => p.url === '/api/feedback')).toBe(true))
    await client.actionQueue
    expect(execute).not.toHaveBeenCalled()
    expect(posts.find(p => p.url === '/api/feedback')!.body).toEqual({
      channel: 'voice', session_id: '6f1c7d0e-9c1b-4a57-8f7a-2b3c4d5e6f70', rating: 4, comment: 'Show sources sooner' })
    const output = frames().find((f: any) => f.item?.type === 'function_call_output')
    expect(JSON.parse(output.item.output)).toMatchObject({ ok: true })
    expect(cb.feedback).toHaveBeenLastCalledWith('saved')
    expect(client.closing).toBe(false)
    vi.advanceTimersByTime(FEEDBACK_GOODBYE_MS)
    expect(client.closing).toBe(true)
  })

  it('rejects an invented or out-of-range rating without calling the server', async () => {
    const { client } = live()
    expect(await client.rateSession(7, '')).toMatchObject({ ok: false })
    expect(await client.rateSession('4', '')).toMatchObject({ ok: false })
    expect(posts.filter(p => p.url === '/api/feedback')).toHaveLength(0)
  })

  it('the on-screen card saves and ends at once', async () => {
    const { client } = live()
    client.end()
    expect(await client.rateSession(5, '', true)).toMatchObject({ ok: true })
    vi.advanceTimersByTime(0)
    expect(client.closing).toBe(true)
  })
})
