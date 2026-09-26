/**
 * Read-aloud (TTS) auth and settings — review L6-05 / L6-06.
 *
 * The read-aloud request used to carry no bearer token, so every click was a
 * silent 401 in any environment with login enabled; and changing the voice
 * POSTed to /api/tts/settings, changing it for every user of the server.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { useAuthStore } from '../../stores/auth'
import { useTTSStore } from '../../stores/tts'
import { requestTTSAudio } from '../useTTS'

describe('read-aloud request', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(new Response(new ArrayBuffer(8), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useAuthStore.setState({ token: null })
  })

  it('sends the signed-in user\'s bearer token to /api/tts', async () => {
    useAuthStore.setState({ token: 'tok-123' })
    await requestTTSAudio('Hello there.', 'opus')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/tts')
    expect(init.method).toBe('POST')
    const headers = init.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer tok-123')
    expect(headers['Content-Type']).toBe('application/json')
  })

  it('reads the token at call time (fresh after an SSO refresh)', async () => {
    useAuthStore.setState({ token: 'old' })
    await requestTTSAudio('One.', 'opus')
    useAuthStore.setState({ token: 'new' })
    await requestTTSAudio('Two.', 'mp3')
    const auth = fetchMock.mock.calls.map(([, init]) => (init.headers as Record<string, string>).Authorization)
    expect(auth).toEqual(['Bearer old', 'Bearer new'])
  })

  it('sends the user\'s own voice/speed but lets the server pick the model', async () => {
    useAuthStore.setState({ token: 't' })
    useTTSStore.setState({ settings: { voice: 'sage', model: 'tts-1-hd', instructions: 'calm', speed: 1.25 } })
    await requestTTSAudio('Text.', 'mp3')
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body).toMatchObject({ text: 'Text.', voice: 'sage', speed: 1.25, instructions: 'calm', response_format: 'mp3' })
    expect(body).not.toHaveProperty('model')
  })
})

describe('TTS settings are per user', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('updateSettings keeps the choice locally and never posts server-wide settings', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    await useTTSStore.getState().updateSettings({ voice: 'cedar', speed: 0.9 })
    expect(fetchMock).not.toHaveBeenCalled()
    expect(useTTSStore.getState().settings.voice).toBe('cedar')
    expect(JSON.parse(localStorage.getItem('synapsis-tts') || '{}')).toMatchObject({ voice: 'cedar', speed: 0.9 })
  })
})
