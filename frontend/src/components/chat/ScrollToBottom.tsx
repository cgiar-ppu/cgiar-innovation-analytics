import { ArrowDown } from 'lucide-react'

interface Props {
  visible: boolean
  onClick: () => void
}

export function ScrollToBottom({ visible, onClick }: Props) {
  if (!visible) return null

  return (
    <button
      onClick={onClick}
      className="absolute bottom-24 right-6 p-2.5 rounded-xl glass
        shadow-lg hover:shadow-xl transition-all text-text-muted hover:text-text-primary z-10
        hover:-translate-y-0.5"
      aria-label="Scroll to bottom"
    >
      <ArrowDown size={18} />
    </button>
  )
}
