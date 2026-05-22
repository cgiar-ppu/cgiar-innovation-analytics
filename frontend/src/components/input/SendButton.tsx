import { ArrowUp } from 'lucide-react'

interface Props {
  disabled: boolean
  onClick: () => void
}

export function SendButton({ disabled, onClick }: Props) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="p-2.5 rounded-xl text-white transition-all
        disabled:opacity-30 disabled:cursor-not-allowed flex-shrink-0
        shadow-sm hover:shadow-md hover:-translate-y-0.5"
      style={{
        background: disabled ? 'var(--text-muted)' : 'var(--user-bubble)',
      }}
      aria-label="Send message"
    >
      <ArrowUp size={16} strokeWidth={2.5} />
    </button>
  )
}
