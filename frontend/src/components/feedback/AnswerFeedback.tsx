/**
 * "Was this answer helpful?" under the last assistant message of each finished
 * answer: thumbs up/down, optional comment, optional "what should it have
 * said?", and an opt-in to share the question and answer with the team.
 *
 * One feedback per user per answer; clicking again edits it. Visible to the
 * user and to administrators only (Settings → Feedback). Nothing is emailed.
 */
import { useEffect, useMemo, useState } from 'react'
import { Check, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { ChatMessage } from '../../lib/types'
import { useChatStore } from '../../stores/chat'
import { useSessionsStore } from '../../stores/sessions'
import { answerId, deleteFeedback, saveFeedback } from './api'
import { useFeedbackStore } from './store'

/**
 * 1-based ordinal of the finished answer that `messageId` concludes, or null
 * when it is not the last assistant text of a finished, successful answer
 * (more text follows, the answer is still streaming, or it ended in an error).
 * Matches the server's `r<k>` = k-th `result` row of the chat.
 */
export function answerOrdinal(messages: ChatMessage[], messageId: string): number | null {
  const index = messages.findIndex(m => m.id === messageId)
  if (index < 0) return null
  for (let j = index + 1; j < messages.length; j++) {
    const message = messages[j]!
    if (message.role === 'assistant' || message.role === 'user') return null
    if (message.role === 'result') {
      if (message.isError) return null
      let ordinal = 0
      for (let i = 0; i <= j; i++) if (messages[i]!.role === 'result') ordinal++
      return ordinal
    }
  }
  return null
}

const field = 'mt-1 w-full rounded-lg border border-border bg-transparent px-2.5 py-1.5 text-sm text-text-primary'

export default function AnswerFeedback({ messageId }: { messageId: string }) {
  const messages = useChatStore(s => s.messages)
  const sessionId = useSessionsStore(s => s.activeSessionId)
  const ordinal = useMemo(() => answerOrdinal(messages, messageId), [messages, messageId])
  const id = ordinal ? answerId(ordinal) : ''
  const disabled = useFeedbackStore(s => s.disabled)
  const load = useFeedbackStore(s => s.load)
  const put = useFeedbackStore(s => s.put)
  const remove = useFeedbackStore(s => s.remove)
  const saved = useFeedbackStore(s => (sessionId && id ? s.bySession[sessionId]?.[id] : undefined))
  const [open, setOpen] = useState(false)
  const [comment, setComment] = useState('')
  const [expected, setExpected] = useState('')
  const [share, setShare] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [thanks, setThanks] = useState(false)

  useEffect(() => { if (sessionId && id) void load(sessionId) }, [sessionId, id, load])
  if (!sessionId || !ordinal || disabled) return null

  const openForm = () => {
    setComment(saved?.comment ?? ''); setExpected(saved?.expected ?? ''); setShare(saved?.share_answer ?? false)
    setError(''); setOpen(true)
  }
  const submit = async (rating: number, details = { comment, expected, share }) => {
    setBusy(true); setError('')
    try {
      const row = await saveFeedback({
        session_id: sessionId, message_id: id, rating,
        comment: details.comment, expected: rating < 0 ? details.expected : '', share_answer: details.share,
      })
      put(sessionId, row); setThanks(true)
      return true
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Feedback could not be saved.')
      return false
    } finally { setBusy(false) }
  }
  const rate = async (rating: number) => {
    // Keep what was already written; a new rating never silently drops a comment.
    const details = { comment: saved?.comment ?? '', expected: saved?.expected ?? '', share: saved?.share_answer ?? false }
    if (await submit(rating, details)) {
      setComment(details.comment); setExpected(details.expected); setShare(details.share); setOpen(true)
    }
  }
  const withdraw = async () => {
    if (!saved) return
    setBusy(true); setError('')
    try { await deleteFeedback(saved.id); remove(sessionId, id); setOpen(false); setThanks(false) }
    catch (e) { setError(e instanceof Error ? e.message : 'Feedback could not be removed.') }
    finally { setBusy(false) }
  }
  const rating = saved?.rating ?? 0
  const button = (value: number, active: boolean) => `flex items-center gap-1 rounded-lg px-2 py-1 transition-colors disabled:opacity-50 ${
    active ? (value > 0 ? 'bg-emerald-500/15 text-emerald-600' : 'bg-red-500/15 text-red-600') : 'hover:bg-surface-2 hover:text-text-primary'}`

  return (
    <div className="mt-2 text-xs text-text-muted" data-testid="answer-feedback">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1">{saved ? (thanks ? 'Thanks for your feedback.' : 'Your feedback:') : 'Was this answer helpful?'}</span>
        <button type="button" disabled={busy} aria-pressed={rating > 0} aria-label="Helpful" title="Helpful"
          onClick={() => void rate(1)} className={button(1, rating > 0)}><ThumbsUp size={14} /></button>
        <button type="button" disabled={busy} aria-pressed={rating < 0} aria-label="Not helpful" title="Not helpful"
          onClick={() => void rate(-1)} className={button(-1, rating < 0)}><ThumbsDown size={14} /></button>
        {saved && !open && <button type="button" onClick={openForm} className="ml-1 underline-offset-2 hover:underline hover:text-text-primary">
          {saved.comment || saved.expected ? 'Edit comment' : 'Add a comment'}</button>}
      </div>
      {open && saved && <form className="mt-2 max-w-xl space-y-2 rounded-xl border border-border p-3" onSubmit={e => { e.preventDefault(); void submit(rating).then(ok => { if (ok) setOpen(false) }) }}>
        <label className="block">Comment (optional)
          <textarea value={comment} maxLength={2000} rows={2} onChange={e => setComment(e.target.value)} className={field} />
        </label>
        {rating < 0 && <label className="block">What should it have said? (optional)
          <textarea value={expected} maxLength={4000} rows={3} onChange={e => setExpected(e.target.value)} className={field} />
        </label>}
        <label className="flex items-start gap-2">
          <input type="checkbox" checked={share} onChange={e => setShare(e.target.checked)} className="mt-0.5" />
          <span>Share this question and answer with the Innovation Analytics team so they can review it.</span>
        </label>
        <p className="text-[11px]">Only you and the Innovation Analytics administrators can see your feedback. Without the box above, they see your rating and comment, not your chat.</p>
        {error && <p role="alert" className="text-red-600">{error}</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button disabled={busy} className="flex items-center gap-1 rounded-lg bg-accent px-3 py-1.5 text-white disabled:opacity-50"><Check size={13} />{busy ? 'Saving…' : 'Save'}</button>
          <button type="button" onClick={() => setOpen(false)} className="hover:text-text-primary">Close</button>
          <button type="button" disabled={busy} onClick={() => void withdraw()} className="ml-auto text-red-600 hover:underline">Remove my feedback</button>
        </div>
      </form>}
      {error && !open && <p role="alert" className="mt-1 text-red-600">{error}</p>}
    </div>
  )
}
