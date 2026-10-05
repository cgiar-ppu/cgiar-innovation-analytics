import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RealtimeClient, GREETING_INSTRUCTION } from '../realtimeClient'

beforeEach(() => { vi.stubGlobal('Audio', class { autoplay = false; pause() {}; play() { return Promise.resolve() } }) })
function fixture(rate?: (id: string, rating: number, text: string) => Promise<unknown>) {
  const execute = vi.fn().mockResolvedValue({ ok: true, effect: 'done' })
  const channel = { readyState: 'open', send: vi.fn(), close: vi.fn() }
  const cb = { status: vi.fn(), caption: vi.fn(), task: vi.fn(), playbackBlocked: vi.fn(), usage: vi.fn(), evidence: vi.fn() }
  const client = new RealtimeClient(cb, { execute, subscribe: () => () => {} }, rate) as any
  client.channel = channel; client.abort = new AbortController()
  const frames = () => channel.send.mock.calls.map((c: any[]) => JSON.parse(c[0]))
  const ev = (event: object) => client.onEvent(event)
  const begin = (id = 'r1') => ev({ type: 'response.created', response: { id } })
  const call = (name = 'read_app', id = 'r1', callId = 'c1') => ev({ type: 'response.output_item.done', response_id: id, item: { type: 'function_call', call_id: callId, name, arguments: '{}' } })
  const done = (id = 'r1', status = 'completed', output: object[] = []) => ev({ type: 'response.done', response: { id, status, output } })
  return { client, execute, channel, cb, frames, ev, begin, call, done }
}

describe('GA Realtime protocol', () => {
  it('becomes ready on session.created and greets with a system item + response.create', () => {
    const f = fixture()
    f.ev({ type: 'session.created', event_id: 'e1', session: {} })
    expect(f.client.ready).toBe(true)
    expect(f.cb.status).toHaveBeenCalledWith('connected', expect.any(String))
    const [item, create] = f.frames()
    expect(item).toMatchObject({ type: 'conversation.item.create', item: { type: 'message', role: 'system', content: [{ type: 'input_text', text: GREETING_INSTRUCTION }] } })
    expect(create.type).toBe('response.create')
  })
  it('runs a completed call once, returns its output and asks for the follow-up response', async () => {
    const f = fixture(); f.client.ready = true
    f.begin(); f.call(); f.call(); f.done('r1', 'completed', [{ type: 'function_call', call_id: 'c1', name: 'read_app', arguments: '{}' }])
    await f.client.actionQueue
    expect(f.execute).toHaveBeenCalledTimes(1)
    expect(f.frames().map((x: any) => x.type)).toEqual(['conversation.item.create', 'response.create'])
    expect(f.frames()[0].item).toMatchObject({ type: 'function_call_output', call_id: 'c1' })
  })
  it('picks up calls that only appear in response.done output', async () => {
    const f = fixture(); f.client.ready = true
    f.begin(); f.done('r1', 'completed', [{ type: 'function_call', call_id: 'c9', name: 'list_chats', arguments: '{}' }])
    await f.client.actionQueue
    expect(f.execute).toHaveBeenCalledWith('list_chats', {}, expect.anything(), expect.any(Function))
  })
  it('never runs actions of an interrupted response but closes them for the model', async () => {
    const f = fixture(); f.client.ready = true
    f.begin(); f.call('send_query'); f.done('r1', 'cancelled')
    await f.client.actionQueue
    expect(f.execute).not.toHaveBeenCalled()
    const frames = f.frames()
    expect(frames).toHaveLength(1)
    expect(JSON.parse(frames[0].item.output)).toMatchObject({ ok: false, cancelled: true })
  })
  it('blocks paused mutations but keeps reads, and blocks stale commands', async () => {
    const f = fixture(); f.client.ready = true; f.client.paused = true
    f.begin(); f.call('send_query'); f.done(); await f.client.actionQueue
    expect(f.execute).not.toHaveBeenCalled()
    const g = fixture(); g.client.ready = true; g.client.paused = true
    g.begin(); g.call('read_knowledge'); g.done(); await g.client.actionQueue
    expect(g.execute).toHaveBeenCalledTimes(1)
    const h = fixture(); h.client.ready = true
    h.begin(); h.call('new_chat'); h.client.epoch++; h.done(); await h.client.actionQueue
    expect(h.execute).not.toHaveBeenCalled()
  })
  it('streams user and guide captions; final user transcript only when no deltas came', () => {
    const f = fixture(); f.client.ready = true; f.client.connectedAt = Date.now()
    f.ev({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'Hello' })
    f.ev({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'Hello there' })
    f.ev({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i2', transcript: 'Second' })
    f.ev({ type: 'response.output_audio_transcript.delta', item_id: 'o1', delta: 'Hi!' })
    expect(f.cb.caption.mock.calls.map((c: any[]) => [c[0].speaker, c[0].delta])).toEqual([['user', 'Hello'], ['user', 'Second'], ['assistant', 'Hi!']])
  })
  it('typed messages go out as a user item + response.create, one at a time', () => {
    const f = fixture(); f.client.ready = true
    f.client.typeMessage('one'); f.client.typeMessage('two')
    expect(f.frames().map((x: any) => x.type)).toEqual(['conversation.item.create', 'response.create'])
    expect(f.frames()[0].item).toMatchObject({ role: 'user', content: [{ type: 'input_text', text: 'one' }] })
    f.begin('r2'); f.done('r2')
    return f.client.actionQueue.then(() => expect(f.frames().filter((x: any) => x.type === 'conversation.item.create')).toHaveLength(2))
  })
  it('a start error before ready fails the call; later benign errors are not alarming', () => {
    const f = fixture(); f.client.ready = true
    f.ev({ type: 'error', error: { code: 'conversation_already_has_active_response', message: 'busy' } })
    expect(f.cb.task).not.toHaveBeenCalled()
    f.ev({ type: 'error', error: { message: 'Bad thing' } })
    expect(f.cb.task).toHaveBeenCalledWith('Voice service: Bad thing')
  })
  it('end reports the call duration and closes on the server without a session.close event', () => {
    const f = fixture(); f.client.ready = true; f.client.requestId = 'req-1'; f.client.connectedAt = Date.now() - 5000
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ closed: true }) })
    vi.stubGlobal('fetch', fetchMock)
    f.client.end()
    expect(f.cb.usage).toHaveBeenCalledWith(5, true)
    expect(f.frames().some((x: any) => x.type === 'session.close')).toBe(false)
    expect(fetchMock).toHaveBeenCalledWith('/api/voice/sessions/req-1/close', expect.objectContaining({ body: JSON.stringify({ usage_seconds: 5 }) }))
    expect(f.cb.status).toHaveBeenLastCalledWith('idle', 'Conversation ended.')
  })
})
