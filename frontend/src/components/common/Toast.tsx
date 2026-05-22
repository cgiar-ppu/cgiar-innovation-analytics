import { Toaster } from 'sonner'
import { useUIStore } from '../../stores/ui'

export function ToastProvider() {
  const theme = useUIStore((s) => s.theme)

  return (
    <Toaster
      theme={theme}
      position="bottom-right"
      toastOptions={{
        style: {
          background: 'var(--surface-2)',
          border: '1px solid var(--border)',
          color: 'var(--text)',
        },
      }}
    />
  )
}
