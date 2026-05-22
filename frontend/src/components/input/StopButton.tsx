import { Square } from 'lucide-react'

interface Props {
  onClick: () => void
}

export function StopButton({ onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="p-2.5 rounded-xl bg-danger text-white hover:bg-red-600 transition-all flex-shrink-0 shadow-sm hover:shadow-md"
      aria-label="Stop generation"
    >
      <Square size={14} fill="currentColor" />
    </button>
  )
}
