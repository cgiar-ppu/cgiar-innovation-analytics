import { Link } from 'react-router-dom'
import { Compass } from 'lucide-react'

/** Shown for unknown routes (and admin-only pages for everyone else). */
export default function NotFound() {
  return (
    <div className="max-w-lg mx-auto p-10 text-center space-y-4" data-testid="not-found">
      <Compass className="w-10 h-10 mx-auto text-[var(--text-muted)]" aria-hidden="true" />
      <h1 className="text-xl font-semibold text-[var(--text)]">Page not found</h1>
      <p className="text-sm text-[var(--text-muted)]">
        This page does not exist or is not available for your account.
      </p>
      <div className="flex justify-center gap-3 text-sm">
        <Link to="/chat" className="px-4 py-2 rounded-lg bg-[var(--accent)] text-white hover:opacity-90">Go to Chat</Link>
        <Link to="/" className="px-4 py-2 rounded-lg border border-[var(--border)] text-[var(--text)] hover:bg-[var(--surface-1)]">Dashboard</Link>
      </div>
    </div>
  )
}
