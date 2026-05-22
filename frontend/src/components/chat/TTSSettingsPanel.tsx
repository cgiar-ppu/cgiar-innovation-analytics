import { useState, useRef, useEffect } from 'react'
import { Settings2, Play, Loader2 } from 'lucide-react'
import { useTTSStore } from '../../stores/tts'
import { useTTS } from '../../hooks/useTTS'

export function TTSSettingsPanel() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const enabled = useTTSStore((s) => s.enabled)
  const voices = useTTSStore((s) => s.voices)
  const settings = useTTSStore((s) => s.settings)
  const updateSettings = useTTSStore((s) => s.updateSettings)
  const { speakText, isPlaying } = useTTS()

  // Local state for the form
  const [localVoice, setLocalVoice] = useState(settings.voice)
  const [localInstructions, setLocalInstructions] = useState(settings.instructions)
  const [localSpeed, setLocalSpeed] = useState(settings.speed)
  const [localModel, setLocalModel] = useState(settings.model)
  const [testing, setTesting] = useState(false)

  // Reload voices when panel opens (retry if initial load failed)
  useEffect(() => {
    if (open && voices.length === 0) {
      useTTSStore.getState().loadVoices()
    }
  }, [open, voices.length])

  // Sync local state when settings change externally
  useEffect(() => {
    setLocalVoice(settings.voice)
    setLocalInstructions(settings.instructions)
    setLocalSpeed(settings.speed)
    setLocalModel(settings.model)
  }, [settings])

  // Close on outside click
  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  const handleApply = async () => {
    await updateSettings({
      voice: localVoice,
      instructions: localInstructions,
      speed: localSpeed,
      model: localModel,
    })
    setOpen(false)
  }

  const handleTest = async () => {
    setTesting(true)
    try {
      await speakText('Hello! This is a preview of my voice. How does it sound?', 'test-preview')
    } finally {
      setTesting(false)
    }
  }

  if (!enabled) return null

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="p-2 rounded-xl hover:bg-surface-2 transition-colors text-text-muted hover:text-text-primary"
        title="Voice settings"
      >
        <Settings2 size={14} />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 glass-strong rounded-2xl shadow-xl z-50 overflow-hidden">
          {/* Header */}
          <div className="px-4 py-3 border-b border-border">
            <p className="text-xs font-semibold text-text-primary">Voice Settings</p>
            <p className="text-[10px] text-text-muted mt-0.5">Configure text-to-speech</p>
          </div>

          {/* Voice selector */}
          <div className="px-4 py-3 border-b border-border max-h-40 overflow-y-auto">
            <p className="text-[10px] font-medium text-text-muted mb-2 uppercase tracking-wider">Voice</p>
            <div className="space-y-1">
              {voices.length === 0 && (
                <p className="text-[10px] text-text-muted py-2">Loading voices...</p>
              )}
              {voices.map((v) => (
                <button
                  key={v.id}
                  onClick={() => setLocalVoice(v.id)}
                  className={`w-full text-left px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
                    localVoice === v.id
                      ? 'bg-accent/15 text-accent border border-accent/30'
                      : 'hover:bg-surface-2 text-text-primary'
                  }`}
                >
                  <span className="font-medium">{v.name}</span>
                  <span className="text-text-muted ml-1.5">{v.description}</span>
                </button>
              ))}
            </div>
          </div>

          {/* Model selector */}
          <div className="px-4 py-3 border-b border-border">
            <p className="text-[10px] font-medium text-text-muted mb-2 uppercase tracking-wider">Model</p>
            <div className="flex gap-1.5">
              {['gpt-4o-mini-tts', 'tts-1', 'tts-1-hd'].map((m) => (
                <button
                  key={m}
                  onClick={() => setLocalModel(m)}
                  className={`px-2.5 py-1 rounded-lg text-[10px] font-mono transition-colors ${
                    localModel === m
                      ? 'bg-accent/15 text-accent border border-accent/30'
                      : 'glass hover:bg-surface-2 text-text-muted'
                  }`}
                >
                  {m}
                </button>
              ))}
            </div>
          </div>

          {/* Speed slider */}
          <div className="px-4 py-3 border-b border-border">
            <div className="flex items-center justify-between mb-1.5">
              <p className="text-[10px] font-medium text-text-muted uppercase tracking-wider">Speed</p>
              <span className="text-[10px] font-mono text-accent">{localSpeed.toFixed(2)}x</span>
            </div>
            <input
              type="range"
              min={0.25}
              max={4.0}
              step={0.25}
              value={localSpeed}
              onChange={(e) => setLocalSpeed(parseFloat(e.target.value))}
              className="w-full h-1.5 rounded-full appearance-none bg-surface-3 accent-[var(--accent)]"
            />
          </div>

          {/* Instructions */}
          <div className="px-4 py-3 border-b border-border">
            <p className="text-[10px] font-medium text-text-muted mb-1.5 uppercase tracking-wider">Instructions</p>
            <textarea
              value={localInstructions}
              onChange={(e) => setLocalInstructions(e.target.value)}
              placeholder="e.g. Speak like a British butler..."
              rows={2}
              className="w-full text-xs bg-surface-3 text-text-primary rounded-lg px-2.5 py-1.5 resize-none outline-none focus:ring-1 focus:ring-accent placeholder:text-text-muted"
            />
          </div>

          {/* Actions */}
          <div className="px-4 py-3 flex gap-2">
            <button
              onClick={handleTest}
              disabled={testing || isPlaying}
              className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl glass hover:bg-surface-2 transition-colors text-xs text-text-primary disabled:opacity-50"
            >
              {testing ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
              Preview
            </button>
            <button
              onClick={handleApply}
              className="flex-1 px-3 py-2 rounded-xl bg-accent text-white text-xs font-medium hover:bg-accent-hover transition-colors"
            >
              Apply
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
