import { getAuthToken } from '../../stores/auth'

/** The request never produced an HTTP response (offline, DNS, connection reset). The server may or may not have seen it. */
export class VoiceNetworkError extends Error {
  constructor(message = 'The voice service could not be reached. Check your network connection.') { super(message); this.name = 'VoiceNetworkError' }
}

type Options = { signal?: AbortSignal; keepalive?: boolean; token?: string | null }

export async function voicePost(path: string, body: unknown, options: Options = {}) {
  const token = options.token === undefined ? getAuthToken() : options.token
  let response: Response
  try {
    response = await fetch('/api/voice/' + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify(body), signal: options.signal, keepalive: options.keepalive,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    throw new VoiceNetworkError()
  }
  const result = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Voice request failed (' + response.status + ').')
  return result
}

export const START_RETRY_DELAY_MS = 1500

/**
 * Start a voice session with at most ONE retry, and only for a network-level failure
 * (no HTTP response at all). The retry re-sends the SAME request_id and offer, which the
 * server treats idempotently: an unseen request is created, an already-active one is
 * replayed, and one still in flight answers 409 so we stop. Any HTTP response — including
 * 5xx/503 — is final: the server has already decided about that request, and an
 * uncertain provider outcome is never retried automatically.
 */
export async function voiceStart(body: { request_id: string; sdp: string | undefined }, options: Options & { retry?: boolean; delay?: (ms: number) => Promise<void> } = {}) {
  const delay = options.delay ?? (ms => new Promise<void>(resolve => setTimeout(resolve, ms)))
  try {
    return await voicePost('sessions', body, options)
  } catch (error) {
    if (!(error instanceof VoiceNetworkError) || options.retry === false || options.signal?.aborted) throw error
    await delay(START_RETRY_DELAY_MS)
    if (options.signal?.aborted) throw error
    return await voicePost('sessions', body, options)
  }
}
