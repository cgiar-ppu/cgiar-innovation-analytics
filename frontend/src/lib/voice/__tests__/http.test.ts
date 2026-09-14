import { afterEach, describe, expect, it, vi } from 'vitest'
import { VoiceNetworkError, voicePost, voiceStart } from '../http'

const ok = (body: unknown, status = 201) => ({ ok: status < 400, status, json: () => Promise.resolve(body) }) as Response
const body = { request_id: 'req-1', sdp: 'v=0\r\noffer' }
const noDelay = () => Promise.resolve()

afterEach(() => { vi.unstubAllGlobals() })

describe('voice HTTP helper', () => {
  it('classifies a failed fetch as a network error and an HTTP error by its server detail', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(voicePost('sessions', body, { token: 't' })).rejects.toBeInstanceOf(VoiceNetworkError)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok({ detail: 'The voice provider rejected the request (HTTP 401 — check the API key); no automatic retry was made.' }, 503)))
    await expect(voicePost('sessions', body, { token: 't' })).rejects.toThrow(/HTTP 401/)
  })
  it('retries a start exactly once after a network error, re-sending the same request id and offer', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValueOnce(ok({ request_id: 'req-1', transport: { sdp: 'v=0\r\nanswer' }, expires_at: 1, max_seconds: 600 }))
    vi.stubGlobal('fetch', fetch)
    const result = await voiceStart(body, { token: 't', delay: noDelay })
    expect(result.transport.sdp).toBe('v=0\r\nanswer')
    expect(fetch).toHaveBeenCalledTimes(2)
    expect(fetch.mock.calls[0]![1].body).toBe(fetch.mock.calls[1]![1].body)
  })
  it('gives up after the second network failure', async () => {
    const fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetch)
    await expect(voiceStart(body, { token: 't', delay: noDelay })).rejects.toBeInstanceOf(VoiceNetworkError)
    expect(fetch).toHaveBeenCalledTimes(2)
  })
  it('never retries once the server has answered, even with 5xx', async () => {
    for (const status of [409, 429, 502, 503]) {
      const fetch = vi.fn().mockResolvedValue(ok({ detail: 'final answer ' + status }, status))
      vi.stubGlobal('fetch', fetch)
      await expect(voiceStart(body, { token: 't', delay: noDelay })).rejects.toThrow('final answer ' + status)
      expect(fetch).toHaveBeenCalledTimes(1)
    }
  })
  it('does not retry after the caller aborted', async () => {
    const controller = new AbortController()
    const fetch = vi.fn().mockImplementation(() => { controller.abort(); return Promise.reject(new TypeError('Failed to fetch')) })
    vi.stubGlobal('fetch', fetch)
    await expect(voiceStart(body, { token: 't', signal: controller.signal, delay: noDelay })).rejects.toBeInstanceOf(VoiceNetworkError)
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
