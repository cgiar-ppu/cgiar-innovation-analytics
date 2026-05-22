import { Sparkles } from 'lucide-react'

export function TypingIndicator() {
  return (
    <div className="flex items-center gap-3">
      <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] flex items-center justify-center flex-shrink-0 shadow-sm">
        <Sparkles size={14} className="text-white" />
      </div>
      <div className="flex gap-1.5 px-4 py-3 rounded-2xl glass">
        <span className="w-2 h-2 rounded-full bg-accent/60 animate-bounce-dot" style={{ animationDelay: '0s' }} />
        <span className="w-2 h-2 rounded-full bg-accent/60 animate-bounce-dot" style={{ animationDelay: '0.16s' }} />
        <span className="w-2 h-2 rounded-full bg-accent/60 animate-bounce-dot" style={{ animationDelay: '0.32s' }} />
      </div>
    </div>
  )
}
