import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveClient } from '../liveClient'

beforeEach(() => { vi.stubGlobal('Audio', class { autoplay = false; pause() {}; play() { return Promise.resolve() } }) })
function fixture() {
  const execute = vi.fn().mockResolvedValue({ ok: true })
  const channel = { readyState: 'open', send: vi.fn() }
  const client = new LiveClient({ status: vi.fn(), caption: vi.fn(), task: vi.fn(), playbackBlocked: vi.fn(), usage: vi.fn(), evidence: vi.fn() }, { execute, subscribe: () => () => {} }) as any
  client.channel = channel; client.abort = new AbortController(); client.ready = true
  const event = (nested: object) => client.onEvent({ type: 'response.event', delegation_id: 'd1', event: nested })
  const begin = () => event({ type: 'response.created', response: { id: 'r1' } })
  const call = (name = 'read_app') => event({ type: 'response.output_item.done', response_id: 'r1', item: { type: 'function_call', call_id: 'c1', name, arguments: '{}' } })
  const done = () => event({ type: 'response.completed', response: { id: 'r1', output: [] } })
  return { client, execute, channel, begin, call, done }
}
describe('Live protocol and lifecycle', () => {
  it('executes complete calls even when terminal output is empty, and deduplicates events', async () => {
    const { client, execute, channel, begin, call, done } = fixture()
    begin(); call(); call(); done(); done(); await client.actionQueue
    expect(execute).toHaveBeenCalledTimes(1)
    const frames = channel.send.mock.calls.map((c: any[]) => JSON.parse(c[0]))
    expect(frames.map((f: any) => f.type)).toEqual(['response.item.create', 'response.create'])
  })
  it('blocks paused mutations but keeps registry-classified knowledge reads available', async () => {
    const f = fixture(); f.client.paused = true
    f.begin(); f.call('send_query'); f.done(); await f.client.actionQueue
    expect(f.execute).not.toHaveBeenCalled()
    const g = fixture(); g.client.paused = true
    g.begin(); g.call('read_knowledge'); g.done(); await g.client.actionQueue
    expect(g.execute).toHaveBeenCalledTimes(1)
  })
  it('blocks stale queued commands after manual state changes', async () => {
    const f = fixture(); f.begin(); f.call('new_chat'); f.client.epoch++; f.done(); await f.client.actionQueue
    expect(f.execute).not.toHaveBeenCalled()
  })
  it('releases a microphone granted after a cancelled start', async () => {
    let grant!: (stream: any) => void
    const stop = vi.fn()
    vi.stubGlobal('isSecureContext', true)
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: () => new Promise(resolve => { grant = resolve }) } })
    const client = new LiveClient({ status: vi.fn(), caption: vi.fn(), task: vi.fn(), playbackBlocked: vi.fn(), usage: vi.fn(), evidence: vi.fn() }, { execute: vi.fn(), subscribe: () => () => {} })
    const task = client.start(); client.end()
    grant({ getTracks: () => [{ stop }] }); await task
    expect(stop).toHaveBeenCalledTimes(1)
  })
})
