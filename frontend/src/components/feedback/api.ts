/**
 * Feedback API client (restricted test rounds, Lane H 2026-09-26).
 *
 * Chat answers are identified by their ordinal among finished answers of the
 * chat (`r1`, `r2`, …), which is identical during streaming and after a
 * history reload. Voice sessions are identified by their voice request id.
 */
import { authHeaders } from '../../lib/api'

export type Channel = 'chat' | 'voice'
export interface OwnFeedback {
  id: number
  channel: Channel
  session_id: string
  message_id: string
  rating: number
  comment: string
  expected: string
  share_answer: boolean
  created_at: number
  updated_at: number
}
export interface FeedbackInput {
  channel?: Channel
  session_id: string
  message_id?: string
  rating: number
  comment?: string
  expected?: string
  share_answer?: boolean
}
export interface AdminFeedbackItem {
  id: number
  created_at: string
  updated_at: string
  channel: Channel
  rating: number
  sentiment: 'positive' | 'negative' | 'neutral'
  comment: string
  expected: string
  shared_question: string | null
  shared_answer: string | null
  user_email: string
  user_name: string
  role: string
  cohort: string
  session_id: string
  message_id: string
  model: string
  persona: string
  scope: string
  app_version: string
  environment: string
}
export interface AdminFeedbackList {
  environment: string
  total: number
  returned: number
  counts: { positive: number; negative: number; neutral: number }
  cohorts: string[]
  items: AdminFeedbackItem[]
}
export interface AdminFilters {
  from?: string
  to?: string
  rating?: '' | 'positive' | 'negative' | 'neutral'
  cohort?: string
  channel?: '' | Channel
}

/** Thrown when feedback is switched off in this environment (HTTP 404 on the list call). */
export class FeedbackDisabledError extends Error {}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...init, headers: authHeaders(init.body ? { 'Content-Type': 'application/json' } : undefined) })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`
    if (response.status === 404 && /not enabled/i.test(detail)) throw new FeedbackDisabledError(detail)
    throw new Error(detail)
  }
  return data as T
}

export const answerId = (ordinal: number) => `r${ordinal}`

export function saveFeedback(input: FeedbackInput) {
  return request<OwnFeedback>('/api/feedback', { method: 'POST', body: JSON.stringify({ channel: 'chat', ...input }) })
}

export function getOwnFeedback(sessionId: string, channel: Channel = 'chat') {
  const query = new URLSearchParams({ session_id: sessionId, channel })
  return request<{ session_id: string; feedback: OwnFeedback[] }>(`/api/feedback?${query}`)
}

export function deleteFeedback(id: number) {
  return request<{ deleted: boolean }>(`/api/feedback/${id}`, { method: 'DELETE' })
}

export function adminQuery(filters: AdminFilters, format?: 'csv') {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, String(value))
  if (format) query.set('format', format)
  const text = query.toString()
  return '/api/admin/feedback' + (text ? `?${text}` : '')
}

export function listAdminFeedback(filters: AdminFilters) {
  return request<AdminFeedbackList>(adminQuery(filters))
}

/** Downloads the CSV with the bearer token (a plain link cannot send it). */
export async function downloadAdminCsv(filters: AdminFilters) {
  const response = await fetch(adminQuery(filters, 'csv'), { headers: authHeaders() })
  if (!response.ok) throw new Error(`CSV export failed (${response.status})`)
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] || 'ia-feedback.csv'
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  return name
}

/** Voice-session rating (1–5) and one improvement; used by the voice guide. */
export function saveVoiceFeedback(requestId: string, rating: number, improvement: string) {
  return saveFeedback({ channel: 'voice', session_id: requestId, rating, comment: improvement })
}
