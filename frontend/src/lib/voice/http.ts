import { getAuthToken } from '../../stores/auth'
export async function voicePost(path: string, body: unknown, options: { signal?: AbortSignal; keepalive?: boolean; token?: string | null } = {}) {
  const token = options.token === undefined ? getAuthToken() : options.token
  const response = await fetch('/api/voice/' + path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body), signal: options.signal, keepalive: options.keepalive,
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Voice request failed (' + response.status + ').')
  return result
}
