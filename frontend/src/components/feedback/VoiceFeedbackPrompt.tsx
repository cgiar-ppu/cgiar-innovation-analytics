/**
 * On-screen twin of the voice guide's end-of-call question: rate the session
 * 1–5 and suggest one improvement, or skip. Shown only after the user pressed
 * End (the guide asks aloud at the same time) — see LiveClient.askFeedback.
 */
import { useState } from 'react'
import { Star } from 'lucide-react'
import type { FeedbackPhase } from '../../lib/voice/liveClient'

interface Props {
  phase: FeedbackPhase
  onSubmit: (rating: number, improvement: string) => Promise<{ ok: boolean; error?: string }>
  onSkip: () => void
}

export default function VoiceFeedbackPrompt({ phase, onSubmit, onSkip }: Props) {
  const [rating, setRating] = useState(0)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (phase === 'idle') return null
  if (phase === 'saved') return <p role="status" className="rounded-xl bg-accent/10 px-3 py-2 text-xs">Thank you, your feedback was saved. The call will close in a moment.</p>

  const send = async () => {
    setBusy(true); setError('')
    const result = await onSubmit(rating, text)
    if (!result.ok) setError(result.error || 'Feedback could not be saved.')
    setBusy(false)
  }
  return <div className="rounded-xl border border-border p-3 space-y-2 text-xs" role="group" aria-label="Rate this voice session">
    <p className="font-medium text-sm">How was this voice session?</p>
    <div className="flex gap-1" role="radiogroup" aria-label="Rating from 1 to 5">
      {[1, 2, 3, 4, 5].map(value => <button key={value} type="button" role="radio" aria-checked={rating === value} aria-label={`${value} of 5`}
        onClick={() => setRating(value)} className={`rounded-md p-1 ${value <= rating ? 'text-amber-500' : 'text-text-muted'} hover:bg-surface-2`}>
        <Star size={20} fill={value <= rating ? 'currentColor' : 'none'} />
      </button>)}
    </div>
    <label className="block text-text-muted">One thing that would make it better (optional)
      <input value={text} maxLength={2000} onChange={e => setText(e.target.value)} className="mt-1 w-full rounded-lg border border-border bg-transparent px-2.5 py-1.5 text-sm text-text-primary" />
    </label>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    <div className="flex gap-2">
      <button type="button" disabled={!rating || busy} onClick={() => void send()} className="rounded-lg bg-accent px-3 py-1.5 text-white disabled:opacity-50">{busy ? 'Saving…' : 'Send and end'}</button>
      <button type="button" onClick={onSkip} className="rounded-lg border border-border px-3 py-1.5">Skip and end</button>
    </div>
  </div>
}
