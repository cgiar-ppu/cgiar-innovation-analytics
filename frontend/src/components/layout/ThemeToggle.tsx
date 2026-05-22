import { Sun, Moon } from 'lucide-react'
import { useUIStore } from '../../stores/ui'

export function ThemeToggle() {
  const { theme, toggleTheme } = useUIStore()

  return (
    <button
      onClick={toggleTheme}
      className="p-2 rounded-xl hover:bg-surface-2 transition-all text-text-muted hover:text-text-primary"
      aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
    >
      {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  )
}
