/**
 * Global "Give feedback" button (top bar, every page) and its form
 * (MVP test release item 1, 14 Oct 2026; requirement of 9 Oct: "attach screenshots;
 * flag when they are stuck, when a result looks wrong, or when the tool is
 * inappropriate/inaccurate").
 *
 * The form takes a category, free text and an optional screenshot (choose a
 * PNG/JPEG file or paste an image). The page, the current chat and its latest
 * answer are attached as ids only (never chat text); the server adds the
 * account, test group, environment and app version itself. Submissions are
 * visible to the Innovation Analytics administrators only (Settings ->
 * Feedback). Hidden when the server's feedback kill-switch is off.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import { ImagePlus, MessageSquarePlus, X } from 'lucide-react'
import { useAppConfigStore } from '../../stores/appConfig'
import { useChatStore } from '../../stores/chat'
import { useSessionsStore } from '../../stores/sessions'
import {
  answerId, FEEDBACK_CATEGORIES, FeedbackDisabledError, MAX_SCREENSHOT_BYTES, SCREENSHOT_TYPES,
  sendGeneralFeedback, type FeedbackCategory,
} from './api'

/** Problem with a candidate screenshot, or '' when it is acceptable. */
export function screenshotProblem(file: Blob): string {
  if (!SCREENSHOT_TYPES.includes(file.type)) return 'Please use a PNG or JPEG image.'
  if (file.size > MAX_SCREENSHOT_BYTES) return 'The screenshot is larger than 5 MB.'
  return ''
}

/** First image on the clipboard of a paste event, if any. */
export function pastedImage(event: Pick<ClipboardEvent, 'clipboardData'>): File | null {
  const items = event.clipboardData?.items
  if (!items) return null
  for (const item of Array.from(items)) {
    if (item.kind === 'file' && item.type.startsWith('image/')) return item.getAsFile()
  }
  return null
}

const field = 'mt-1 w-full rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-2.5 py-1.5 text-sm text-[var(--text)]'

export function GiveFeedbackForm({ onClose }: { onClose: () => void }) {
  const location = useLocation()
  const sessionId = useSessionsStore(s => s.activeSessionId)
  const results = useChatStore(s => s.messages.filter(m => m.role === 'result').length)
  const inChat = location.pathname.startsWith('/chat') && !!sessionId
  const [category, setCategory] = useState<FeedbackCategory | ''>('')
  const [comment, setComment] = useState('')
  const [screenshot, setScreenshot] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const dialog = useRef<HTMLDivElement>(null)
  const titleId = useId()

  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    // Once on open: focus the first category; Escape closes.
    dialog.current?.querySelector<HTMLInputElement>('input[type=radio]')?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeRef.current() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  useEffect(() => {
    if (!screenshot || typeof URL.createObjectURL !== 'function') { setPreview(''); return }
    const url = URL.createObjectURL(screenshot)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [screenshot])

  const pick = (file: File | null) => {
    if (!file) return
    const problem = screenshotProblem(file)
    if (problem) { setError(problem); return }
    setError(''); setScreenshot(file)
  }
  const onPaste = (e: React.ClipboardEvent) => {
    const image = pastedImage(e)
    if (image) { e.preventDefault(); pick(image) }
  }
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!category) { setError('Please choose what kind of feedback this is.'); return }
    if (!comment.trim() && !screenshot) { setError('Please describe what happened or add a screenshot.'); return }
    setBusy(true); setError('')
    try {
      await sendGeneralFeedback({
        category, comment, page: location.pathname,
        chatId: inChat ? sessionId! : undefined,
        answerId: inChat && results > 0 ? answerId(results) : undefined,
        screenshot,
      })
      setSent(true)
    } catch (err) {
      if (err instanceof FeedbackDisabledError) setError('Feedback is switched off in this environment.')
      else setError(err instanceof Error ? err.message : 'Feedback could not be sent.')
    } finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm sm:items-center" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}>
      <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} onPaste={onPaste}
        className="w-full max-w-lg rounded-2xl border border-[var(--border)] bg-[var(--surface-solid)] p-5 text-sm text-[var(--text)] shadow-xl" data-testid="give-feedback-dialog">
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-base font-semibold">Give feedback</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1 text-[var(--text-muted)] hover:bg-[var(--surface-2)]"><X size={16} /></button>
        </div>
        {sent ? <div className="mt-4 space-y-4">
          <p role="status">Thank you. Your feedback was sent to the Innovation Analytics team.</p>
          <button type="button" onClick={onClose} className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-white">Close</button>
        </div> : <form className="mt-3 space-y-4" onSubmit={e => void submit(e)}>
          <fieldset>
            <legend className="text-xs font-medium text-[var(--text-muted)]">What kind of feedback is this?</legend>
            <div className="mt-2 grid gap-2 sm:grid-cols-2">
              {FEEDBACK_CATEGORIES.map(c => <label key={c.value} className={`flex cursor-pointer items-start gap-2 rounded-lg border p-2 ${category === c.value ? 'border-[var(--accent)] bg-[var(--accent)]/10' : 'border-[var(--border)]'}`}>
                <input type="radio" name="feedback-category" value={c.value} checked={category === c.value} onChange={() => setCategory(c.value)} className="mt-0.5" />
                <span><span className="block font-medium">{c.label}</span><span className="block text-xs text-[var(--text-muted)]">{c.hint}</span></span>
              </label>)}
            </div>
          </fieldset>
          <label className="block text-xs font-medium text-[var(--text-muted)]">What happened?
            <textarea value={comment} maxLength={4000} rows={4} onChange={e => setComment(e.target.value)} className={field}
              placeholder="Describe what you were doing and what you expected." />
          </label>
          <div>
            <p className="text-xs font-medium text-[var(--text-muted)]">Screenshot (optional)</p>
            {screenshot ? <div className="mt-1 flex items-center gap-3">
              {preview && <img src={preview} alt="Screenshot preview" className="h-16 max-w-[8rem] rounded border border-[var(--border)] object-cover" />}
              <span className="min-w-0 flex-1 truncate text-xs">{screenshot.name || 'Pasted image'} · {Math.max(1, Math.round(screenshot.size / 1024))} KB</span>
              <button type="button" onClick={() => setScreenshot(null)} className="text-xs text-red-600 hover:underline">Remove</button>
            </div> : <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--text-muted)]">
              <button type="button" onClick={() => fileInput.current?.click()} className="flex items-center gap-1 rounded-lg border border-[var(--border)] px-2.5 py-1.5 text-[var(--text)] hover:bg-[var(--surface-2)]"><ImagePlus size={14} /> Choose image</button>
              <span>or paste one here (Ctrl/Cmd+V). PNG or JPEG, up to 5 MB.</span>
            </div>}
            <input ref={fileInput} type="file" accept="image/png,image/jpeg" className="hidden" data-testid="feedback-screenshot-input"
              onChange={e => { pick(e.target.files?.[0] ?? null); e.target.value = '' }} />
          </div>
          <p className="text-[11px] text-[var(--text-muted)]">
            Sent with your feedback: this page ({location.pathname}){inChat ? ', the id of this chat and of its latest answer (not the chat text)' : ''}, your account and test group, and the app version. Only the Innovation Analytics administrators can see it.
          </p>
          {error && <p role="alert" className="text-red-600">{error}</p>}
          <div className="flex items-center gap-3">
            <button type="submit" disabled={busy} className="rounded-lg bg-[var(--accent)] px-3 py-1.5 text-white disabled:opacity-50">{busy ? 'Sending…' : 'Send feedback'}</button>
            <button type="button" onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text)]">Cancel</button>
          </div>
        </form>}
      </div>
    </div>
  )
}

export default function GiveFeedbackButton() {
  const enabled = useAppConfigStore(s => s.config?.feedback_enabled !== false)
  const [open, setOpen] = useState(false)
  if (!enabled) return null
  return <>
    <button type="button" onClick={() => setOpen(true)} data-testid="give-feedback"
      className="flex items-center gap-1.5 rounded-xl px-2 py-1.5 text-xs font-medium text-[var(--text-muted)] transition-all hover:bg-[var(--surface-2)] hover:text-[var(--text)]"
      title="Give feedback" aria-label="Give feedback" aria-haspopup="dialog">
      <MessageSquarePlus className="h-4 w-4" />
      <span className="hidden lg:inline">Feedback</span>
    </button>
    {/* Portal: the top bar's backdrop blur would otherwise trap a fixed overlay inside the bar. */}
    {open && createPortal(<GiveFeedbackForm onClose={() => setOpen(false)} />, document.body)}
  </>
}
