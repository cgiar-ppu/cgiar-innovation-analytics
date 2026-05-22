import { useState, useRef, useCallback, useEffect } from 'react'
import { Mic, MicOff, Loader2 } from 'lucide-react'

interface Props {
  onTranscription: (text: string) => void
  disabled?: boolean
}

type VoiceState = 'idle' | 'recording' | 'transcribing'

/**
 * Check whether the browser can access getUserMedia.
 * It requires a secure context (HTTPS or localhost).
 */
function canUseMedia(): { ok: boolean; reason?: string } {
  if (!window.isSecureContext) {
    return {
      ok: false,
      reason: 'Microphone requires HTTPS. Access this page via https:// instead of http://',
    }
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    return {
      ok: false,
      reason: 'Your browser does not support microphone access',
    }
  }
  return { ok: true }
}

export function VoiceButton({ onTranscription, disabled }: Props) {
  const [state, setState] = useState<VoiceState>('idle')
  const [error, setError] = useState<string | null>(null)
  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  // Auto-dismiss errors after 6 seconds
  useEffect(() => {
    if (!error) return
    const t = setTimeout(() => setError(null), 6000)
    return () => clearTimeout(t)
  }, [error])

  const stopRecording = useCallback(() => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    }
    // Stop all tracks to release the microphone
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop())
      streamRef.current = null
    }
  }, [])

  const startRecording = useCallback(async () => {
    setError(null)

    // Pre-check: secure context & API availability
    const check = canUseMedia()
    if (!check.ok) {
      setError(check.reason!)
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      // Prefer webm/opus, fall back to whatever the browser supports
      const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : 'audio/mp4'

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: mimeType })
        chunksRef.current = []

        if (blob.size < 100) {
          setState('idle')
          return
        }

        setState('transcribing')

        try {
          const ext = mimeType.includes('webm') ? 'webm' : 'mp4'
          const file = new File([blob], `recording.${ext}`, { type: mimeType })
          const fd = new FormData()
          fd.append('file', file)

          const res = await fetch('/api/transcribe', { method: 'POST', body: fd })

          if (!res.ok) {
            const errData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
            const detail = typeof errData.detail === 'string'
              ? errData.detail
              : Array.isArray(errData.detail)
                ? errData.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join('; ')
                : `Transcription failed: ${res.status}`
            throw new Error(detail)
          }

          const { text } = await res.json()
          if (text) {
            onTranscription(text)
          }
        } catch (err) {
          console.error('Transcription error:', err)
          setError(err instanceof Error ? err.message : 'Transcription failed')
        } finally {
          setState('idle')
        }
      }

      recorder.start(250) // collect data every 250ms
      setState('recording')
    } catch (err: unknown) {
      console.error('Microphone access error:', err)
      const name = err instanceof DOMException ? err.name : ''
      if (name === 'NotAllowedError') {
        setError('Microphone permission denied. Allow microphone in browser settings.')
      } else if (name === 'NotFoundError') {
        setError('No microphone found on this device.')
      } else if (name === 'NotReadableError') {
        setError('Microphone is in use by another app.')
      } else {
        setError(err instanceof Error ? err.message : 'Could not access microphone')
      }
      setState('idle')
    }
  }, [onTranscription])

  const handleClick = useCallback(() => {
    if (state === 'recording') {
      stopRecording()
    } else if (state === 'idle') {
      startRecording()
    }
    // Do nothing while transcribing
  }, [state, startRecording, stopRecording])

  return (
    <div className="relative">
      <button
        onClick={handleClick}
        disabled={disabled || state === 'transcribing'}
        className={`p-1.5 rounded-xl transition-all flex-shrink-0 mb-0.5
          ${state === 'recording'
            ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30 animate-pulse'
            : state === 'transcribing'
              ? 'text-accent opacity-70 cursor-wait'
              : 'hover:bg-surface-2 text-text-muted hover:text-text-primary'
          }
          ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
        aria-label={
          state === 'recording' ? 'Stop recording'
            : state === 'transcribing' ? 'Transcribing...'
              : 'Start voice input'
        }
        title={
          state === 'recording' ? 'Click to stop and transcribe'
            : state === 'transcribing' ? 'Transcribing your voice...'
              : 'Voice input'
        }
      >
        {state === 'transcribing' ? (
          <Loader2 size={18} className="animate-spin" />
        ) : state === 'recording' ? (
          <MicOff size={18} />
        ) : (
          <Mic size={18} />
        )}
      </button>

      {/* Recording indicator pulse ring */}
      {state === 'recording' && (
        <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-red-500 animate-ping" />
      )}

      {/* Error tooltip */}
      {error && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-1.5
          text-xs text-red-400 bg-surface-solid border border-red-500/30 rounded-lg
          max-w-[250px] text-center shadow-lg z-50 animate-fade-in"
          onClick={() => setError(null)}
        >
          {error}
        </div>
      )}
    </div>
  )
}
