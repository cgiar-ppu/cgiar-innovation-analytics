/**
 * Feedback API client (restricted test rounds, Lane H 2026-09-26).
 *
 * Chat answers are identified by their ordinal among finished answers of the
 * chat (`r1`, `r2`, …), which is identical during streaming and after a
 * history reload. Voice sessions are identified by their voice request id.
 */
import { authHeaders } from '../../lib/api'

export type Channel = 'chat' | 'voice'
export type AdminChannel = Channel | 'general'
/** Categories of the global "Give feedback" form (MVP test release, item 1). */
export type FeedbackCategory = 'stuck' | 'wrong_result' | 'inappropriate_inaccurate' | 'other'
export const FEEDBACK_CATEGORIES: { value: FeedbackCategory; label: string; hint: string }[] = [
  { value: 'stuck', label: "I'm stuck", hint: "I don't know how to do what I want" },
  { value: 'wrong_result', label: 'This result looks wrong', hint: 'A number, list or chart does not match what I expect' },
  { value: 'inappropriate_inaccurate', label: 'Inappropriate or inaccurate', hint: 'The tone, wording or content is not acceptable' },
  { value: 'other', label: 'Other', hint: 'An idea, a question or anything else' },
]
export const categoryLabel = (value: string) => FEEDBACK_CATEGORIES.find(c => c.value === value)?.label ?? value
/** Screenshot limits (the server enforces the same: PNG/JPEG by file signature, max 5 MB). */
export const SCREENSHOT_TYPES = ['image/png', 'image/jpeg']
export const MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024
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
  channel: AdminChannel
  rating: number
  /** '' for general feedback (it has a category, not a rating). */
  sentiment: 'positive' | 'negative' | 'neutral' | ''
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
  /** General feedback only (empty for answer/voice ratings). */
  category?: FeedbackCategory | ''
  category_label?: string
  page?: string
  chat_id?: string
  answer_id?: string
  has_attachment?: boolean
  attachment_type?: string
  attachment_url?: string
}
export interface AdminFeedbackList {
  environment: string
  total: number
  returned: number
  counts: { positive: number; negative: number; neutral: number }
  by_category?: Record<FeedbackCategory, number>
  cohorts: string[]
  items: AdminFeedbackItem[]
}
export interface AdminFilters {
  from?: string
  to?: string
  rating?: '' | 'positive' | 'negative' | 'neutral'
  cohort?: string
  channel?: '' | AdminChannel
  category?: '' | FeedbackCategory
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

export function adminQuery(filters: AdminFilters, format?: 'csv' | 'zip') {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(filters)) if (value) query.set(key, String(value))
  if (format) query.set('format', format)
  const text = query.toString()
  return '/api/admin/feedback' + (text ? `?${text}` : '')
}

export function listAdminFeedback(filters: AdminFilters) {
  return request<AdminFeedbackList>(adminQuery(filters))
}

/**
 * Downloads the CSV (or, with `zip`, the CSV plus every screenshot) with the
 * bearer token (a plain link cannot send it).
 */
export async function downloadAdminCsv(filters: AdminFilters, format: 'csv' | 'zip' = 'csv') {
  const response = await fetch(adminQuery(filters, format), { headers: authHeaders() })
  if (!response.ok) throw new Error(`${format === 'zip' ? 'ZIP' : 'CSV'} export failed (${response.status})`)
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] || `ia-feedback.${format}`
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

export interface GeneralFeedbackInput {
  category: FeedbackCategory
  comment: string
  /** App route the form was opened on (path only). */
  page: string
  /** Current chat and its latest finished answer (`r<k>`), when the user is in a chat. */
  chatId?: string
  answerId?: string
  screenshot?: Blob | null
}
export interface GeneralFeedbackSaved {
  id: number
  channel: 'general'
  category: FeedbackCategory
  has_attachment: boolean
}

/** The global "Give feedback" form (multipart: the screenshot is a file, not base64). */
export async function sendGeneralFeedback(input: GeneralFeedbackInput) {
  const body = new FormData()
  body.set('category', input.category)
  body.set('comment', input.comment)
  body.set('page', input.page)
  if (input.chatId) body.set('chat_id', input.chatId)
  if (input.answerId) body.set('answer_id', input.answerId)
  if (input.screenshot) {
    const ext = input.screenshot.type === 'image/jpeg' ? 'jpg' : 'png'
    body.set('screenshot', input.screenshot, `screenshot.${ext}`)
  }
  const response = await fetch('/api/feedback/general', { method: 'POST', body, headers: authHeaders() })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Feedback could not be sent (${response.status})`
    if (response.status === 404 && /not enabled/i.test(detail)) throw new FeedbackDisabledError(detail)
    throw new Error(detail)
  }
  return data as GeneralFeedbackSaved
}

/** Fetches a screenshot with the bearer token and returns an object URL for <img>/<a>. */
export async function attachmentObjectUrl(url: string) {
  const response = await fetch(url, { headers: authHeaders() })
  if (!response.ok) throw new Error(`Screenshot could not be loaded (${response.status})`)
  return URL.createObjectURL(await response.blob())
}
