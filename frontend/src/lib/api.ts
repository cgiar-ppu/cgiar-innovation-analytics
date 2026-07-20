/**
 * @file api.ts
 * @module lib
 *
 * Thin REST API client for the Synapsis backend. All HTTP verbs are wrapped in
 * small typed helpers ({@link get}, {@link post}, {@link patch}, {@link del},
 * {@link postForm}) that throw on non-OK responses.
 *
 * The public surface is a single `api` object whose methods map 1-to-1 to
 * backend routes. History responses are normalised from the wire format
 * ({@link HistoryMessage}) to the UI {@link ChatMessage} model by
 * {@link mapHistoryMessage}.
 */

import type { Session, FileInfo, Memory, NewMemory, AppConfig, HealthStatus, ChatMessage, SearchResult, GitStatus, GitDiffResponse, GitLogResponse, GitShowResponse, TTSVoice, TTSSettings } from './types'
import { isSuppressedSystemMessage } from '../stores/chat/systemMessageFilter'
import type { SkillInfo } from './types-extended'
import { getAuthToken } from '../stores/auth'

const BASE = ''

/**
 * Builds request headers with the JWT bearer token attached when present.
 * The token is read from the auth store at call time so it always reflects the
 * current session (login/logout without a reload).
 */
function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getAuthToken()
  const headers: Record<string, string> = { ...(extra as Record<string, string>) }
  if (token) headers.Authorization = `Bearer ${token}`
  return headers
}

/**
 * Performs a GET request and returns the parsed JSON response.
 *
 * @param path   - API path (relative to `BASE`).
 * @param signal - Optional AbortSignal for cancellation.
 * @returns Parsed response body typed as `T`.
 * @throws {Error} When the response status is not OK.
 */
async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders(), ...(signal ? { signal } : {}) })
  if (!res.ok) throw new Error(`GET ${path}: ${res.status}`)
  return res.json() as Promise<T>
}

/**
 * Performs a POST request with a JSON body and returns the parsed JSON response.
 *
 * @param path - API path (relative to `BASE`).
 * @param body - Request payload (will be serialised with `JSON.stringify`).
 * @returns Parsed response body typed as `T`.
 * @throws {Error} When the response status is not OK.
 */
async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path}: ${res.status}`)
  return res.json() as Promise<T>
}

/**
 * Performs a PATCH request with a JSON body and returns the parsed JSON response.
 *
 * @param path - API path (relative to `BASE`).
 * @param body - Partial update payload (will be serialised with `JSON.stringify`).
 * @returns Parsed response body typed as `T`.
 * @throws {Error} When the response status is not OK.
 */
async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'PATCH',
    headers: authHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`PATCH ${path}: ${res.status}`)
  return res.json() as Promise<T>
}

/**
 * Performs a DELETE request and returns the parsed JSON response.
 *
 * @param path - API path (relative to `BASE`).
 * @returns Parsed response body typed as `T`.
 * @throws {Error} When the response status is not OK.
 */
async function del<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'DELETE', headers: authHeaders() })
  if (!res.ok) throw new Error(`DELETE ${path}: ${res.status}`)
  return res.json() as Promise<T>
}

/**
 * Performs a multipart/form-data POST (file upload) and returns the parsed
 * JSON response.
 *
 * @param path - API path (relative to `BASE`).
 * @param file - The file to upload, appended as the `"file"` field.
 * @returns Parsed response body typed as `T`.
 * @throws {Error} When the response status is not OK.
 */
async function postForm<T>(path: string, file: File): Promise<T> {
  const fd = new FormData()
  fd.append('file', file)
  const res = await fetch(`${BASE}${path}`, { method: 'POST', body: fd, headers: authHeaders() })
  if (!res.ok) throw new Error(`POST ${path}: ${res.status}`)
  return res.json() as Promise<T>
}

/**
 * Wire-format shape of a message returned by `/api/history/:id`.
 * Differs from {@link ChatMessage} in that it uses snake_case and omits
 * UI-specific fields like `id` and `timestamp`.
 *
 * @internal
 */
interface HistoryMessage {
  type: string
  content?: string
  tool?: string
  input?: Record<string, unknown>
  tool_use_id?: string
  is_error?: boolean
  estimated_cost?: number | null
  turns?: number
  duration_ms?: number
  auth_method?: string
  subtype?: string
  data?: unknown
  /** Text output from slash commands stored alongside the result. */
  result_text?: string
}

/**
 * Converts a single {@link HistoryMessage} from the API wire format into the
 * UI {@link ChatMessage} model.
 *
 * @param msg   - The raw history message from the server.
 * @param index - The message's position in the history array, used as a
 *   stable ID prefix (`"hist-{index}"`).
 * @returns A fully-shaped {@link ChatMessage} ready to be inserted into the
 *   chat store.
 */
/**
 * Maps a single history message to one or more ChatMessages.
 *
 * Returns an array because slash-command results may produce both an
 * assistant message (the command output) and a result banner.
 */
function mapHistoryMessage(msg: HistoryMessage, index: number): ChatMessage[] {
  const base = {
    id: `hist-${index}`,
    timestamp: Date.now(),
  }
  switch (msg.type) {
    case 'user':
      return [{ ...base, role: 'user', content: msg.content ?? '' }]
    case 'text':
      return [{ ...base, role: 'assistant', content: msg.content ?? '' }]
    case 'thinking':
      return [{ ...base, role: 'thinking', content: msg.content ?? '', isActive: false }]
    case 'tool_use':
      return [{ ...base, role: 'tool_use', content: '', tool: msg.tool, toolInput: msg.input, toolUseId: msg.tool_use_id }]
    case 'tool_result':
      return [{ ...base, role: 'tool_result', content: msg.content ?? '', toolUseId: msg.tool_use_id, isError: msg.is_error }]
    case 'result': {
      const messages: ChatMessage[] = []
      // Slash commands (e.g. /config, /usage) that returned text output
      // without streaming: inject an assistant message so the output is visible.
      if (msg.result_text) {
        messages.push({ id: `hist-${index}-rt`, timestamp: Date.now(), role: 'assistant', content: msg.result_text })
      }
      messages.push({ ...base, role: 'result', content: '', estimatedCost: msg.estimated_cost, turns: msg.turns, durationMs: msg.duration_ms, authMethod: msg.auth_method, resultText: msg.result_text })
      return messages
    }
    default: {
      const content = typeof msg.data === 'string' ? msg.data : JSON.stringify(msg.data ?? msg.content ?? '')
      // Drop SDK per-turn token/usage telemetry ("thinking_tokens" pills) on
      // reload so history doesn't resurrect them. flatMap drops the empty array.
      if (isSuppressedSystemMessage(msg.subtype, content)) return []
      return [{ ...base, role: 'system', content, subtype: msg.subtype }]
    }
  }
}

/**
 * Typed REST API client. Import and call methods directly:
 *
 * @example
 * ```ts
 * const { sessions } = await api.getSessions()
 * await api.renameSession(id, 'New title')
 * // Or use the low-level helpers for arbitrary routes:
 * const data = await api.get<MyType>('/api/custom-route')
 * ```
 */
export const api = {
  /** Low-level GET helper — use when no named method exists for the route. */
  get: get as <T>(path: string, signal?: AbortSignal) => Promise<T>,

  /** Low-level POST helper — use when no named method exists for the route. */
  post: post as <T>(path: string, body: unknown) => Promise<T>,

  /** Low-level PATCH helper — use when no named method exists for the route. */
  patch: patch as <T>(path: string, body: unknown) => Promise<T>,

  /** Low-level DELETE helper — use when no named method exists for the route. */
  del: del as <T>(path: string) => Promise<T>,

  /** Low-level multipart POST helper — use when no named method exists for the route. */
  postForm: postForm as <T>(path: string, file: File) => Promise<T>,

  /** Fetches the application configuration (model name, feature flags, etc.). */
  getConfig: () => get<AppConfig>('/api/config'),

  /** Fetches the backend health status. */
  getHealth: () => get<HealthStatus>('/api/health'),

  /** Returns the list of all chat sessions. */
  getSessions: () => get<{ sessions: Session[] }>('/api/sessions'),

  /**
   * Fetches the message history for a session and maps it to {@link ChatMessage} objects.
   *
   * @param id     - The session ID to load.
   * @param signal - Optional AbortSignal for cancellation.
   */
  getHistory: async (id: string, signal?: AbortSignal) => {
    const res = await get<{ messages: HistoryMessage[]; session_id: string }>(`/api/history/${id}`, signal)
    const mapped = res.messages.flatMap(mapHistoryMessage)

    // Deduplicate: when a `result` DB row carries `result_text` that is
    // identical to a preceding `text` (assistant) message, mapHistoryMessage
    // creates a redundant assistant ChatMessage from the result_text.  This
    // causes the same response to appear twice in the chat.  Remove the
    // duplicate by collecting all assistant-message contents that came from
    // real `text` DB rows, then filtering out result_text-sourced assistant
    // messages whose content already appeared.
    const seenAssistantContent = new Set<string>()
    const deduped: typeof mapped = []
    for (const msg of mapped) {
      if (msg.role === 'assistant' && !msg.id.includes('-rt')) {
        // Real assistant message (from a `text` DB row) — track its content
        seenAssistantContent.add(msg.content)
      }
      if (msg.role === 'assistant' && msg.id.includes('-rt') && seenAssistantContent.has(msg.content)) {
        // This is a result_text-sourced assistant message that duplicates
        // a real assistant message — skip it
        continue
      }
      deduped.push(msg)
    }

    return {
      messages: deduped,
      session_id: res.session_id,
    }
  },

  /**
   * Renames a session.
   *
   * @param id    - The session ID.
   * @param title - The new title.
   */
  renameSession: (id: string, title: string) => patch<{ status: string }>(`/api/sessions/${id}`, { title }),

  /**
   * Deletes a session permanently.
   *
   * @param id - The session ID to delete.
   */
  deleteSession: (id: string) => del<{ status: string }>(`/api/sessions/${id}`),

  /** Returns the list of files in the workspace. */
  getFiles: () => get<{ files: FileInfo[] }>('/api/files'),

  /**
   * Uploads a file to the workspace.
   *
   * @param file - The browser `File` object to upload.
   */
  uploadFile: (file: File) => postForm<{ path: string; size: number }>('/api/upload', file),

  /**
   * Returns the direct download URL for a workspace file.
   *
   * `GET /api/files/{path}` requires auth (2026-07-20); this is rendered as
   * a plain `<a href>` (see `pages/Files.tsx`), which can't attach an
   * `Authorization` header, so the JWT is appended as `?token=` — the same
   * pattern used by `buildDownloadUrl` in `lib/filePathUtils.ts`.
   *
   * @param filename - The filename as returned by {@link getFiles}.
   */
  downloadUrl: (filename: string) => {
    const token = getAuthToken()
    const url = `${BASE}/api/files/${encodeURIComponent(filename)}`
    return token ? `${url}?token=${encodeURIComponent(token)}` : url
  },

  /** Returns the list of stored memories. */
  getMemories: () => get<{ memories: Memory[] }>('/api/memories'),

  /**
   * Creates a new memory entry.
   *
   * @param m - The memory data to store.
   */
  createMemory: (m: NewMemory) => post<{ id: number; status: string }>('/api/memories', m),

  /**
   * Deletes a memory entry.
   *
   * @param id - The numeric ID of the memory to delete.
   */
  deleteMemory: (id: number) => del<{ status: string }>(`/api/memories/${id}`),

  /** Search across all conversations. */
  searchConversations: (q: string, limit?: number) =>
    get<{ results: SearchResult[]; query: string }>(`/api/search?q=${encodeURIComponent(q)}&limit=${limit ?? 50}`),

  /** Generate a URL for exporting a conversation.
   *  The JWT is appended as a query param because the download is triggered via
   *  window.open, which cannot attach an Authorization header. */
  exportUrl: (sessionId: string, format: string, detail: string = 'standard') => {
    const token = getAuthToken()
    const tokenParam = token ? `&token=${encodeURIComponent(token)}` : ''
    return `${BASE}/api/export/${sessionId}?format=${format}&detail=${detail}${tokenParam}`
  },

  /** Auto-generate a title for a session. */
  autoTitle: (sessionId: string) =>
    post<{ title: string; session_id: string }>(`/api/sessions/${sessionId}/auto-title`, {}),

  /** Toggle pin status on a session. */
  pinSession: (sessionId: string, pinned: boolean) =>
    post<{ status: string; pinned: boolean }>(`/api/sessions/${sessionId}/pin`, { pinned }),

  // -- Git operations --

  /** Fetches git status (branch, staged, unstaged, untracked files). */
  getGitStatus: () => get<GitStatus>('/api/git/status'),

  /** Fetches a diff for a specific file (or all files if no file specified). */
  getGitDiff: (file?: string, staged?: boolean) => {
    const params = new URLSearchParams()
    if (file) params.set('file', file)
    if (staged) params.set('staged', 'true')
    return get<GitDiffResponse>(`/api/git/diff?${params}`)
  },

  /** Fetches recent commit log. */
  getGitLog: (limit = 15) => get<GitLogResponse>(`/api/git/log?limit=${limit}`),

  /** Fetches the content of a file at a given ref. */
  getGitShow: (file: string, ref = 'HEAD') =>
    get<GitShowResponse>(`/api/git/show?file=${encodeURIComponent(file)}&ref=${ref}`),

  // -- Skills discovery --

  /** Fetches available skills and SDK commands for slash-command autocomplete. */
  getSkills: (invocableOnly = false) =>
    get<{ skills: SkillInfo[] }>(`/api/skills${invocableOnly ? '?invocable_only=true' : ''}`),

  // -- TTS (text-to-speech) --

  /** Fetches available TTS voices and current settings. */
  getTTSVoices: () => get<{ voices: TTSVoice[]; current: TTSSettings }>('/api/tts/voices'),

  /** Updates TTS settings on the backend. */
  updateTTSSettings: (settings: Partial<TTSSettings>) =>
    post<{ settings: TTSSettings }>('/api/tts/settings', settings),

  /** Base URL for TTS audio generation (used by the useTTS hook via fetch). */
  ttsUrl: `${BASE}/api/tts`,
}
