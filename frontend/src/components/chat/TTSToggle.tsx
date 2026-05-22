import { Volume2, VolumeX } from 'lucide-react'
import { useTTSStore } from '../../stores/tts'
import { warmAudioContext } from '../../hooks/useTTS'

export function TTSToggle() {
  const enabled = useTTSStore((s) => s.enabled)
  const isPlaying = useTTSStore((s) => s.isPlaying)
  const toggleEnabled = useTTSStore((s) => s.toggleEnabled)

  const handleClick = () => {
    // When enabling TTS, warm the AudioContext from this user-gesture context.
    // Browsers require a user gesture to create/resume an AudioContext.
    if (!enabled) {
      warmAudioContext()
    }
    toggleEnabled()
  }

  return (
    <button
      onClick={handleClick}
      className={`p-2 rounded-xl transition-all ${
        enabled
          ? 'bg-[var(--accent)] text-white shadow-sm'
          : 'hover:bg-surface-2 text-text-muted hover:text-text-primary'
      } ${isPlaying ? 'animate-pulse' : ''}`}
      title={enabled ? 'Disable auto-read (TTS on)' : 'Enable auto-read (TTS off)'}
      aria-label={enabled ? 'Disable text-to-speech' : 'Enable text-to-speech'}
    >
      {enabled ? <Volume2 size={16} /> : <VolumeX size={16} />}
    </button>
  )
}
