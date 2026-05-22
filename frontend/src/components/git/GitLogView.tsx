/**
 * @file GitLogView.tsx
 * @module components/git
 *
 * Compact commit history view. Fetches and displays recent commits in a
 * collapsible section with short hash, message, and relative date.
 */

import { useState, useEffect } from 'react'
import { GitCommit, ChevronDown, ChevronRight } from 'lucide-react'
import { api } from '../../lib/api'
import type { GitLogCommit } from '../../lib/types'

export function GitLogView() {
  const [commits, setCommits] = useState<GitLogCommit[]>([])
  const [collapsed, setCollapsed] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api.getGitLog(15)
      .then((res) => {
        setCommits(res.commits)
        setError(null)
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load commits')
      })
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      {/* Section header */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-text-muted hover:bg-surface-2/50 transition-colors"
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        <GitCommit size={14} />
        <span>Recent Commits</span>
        {commits.length > 0 && (
          <span className="ml-auto text-[10px] text-text-muted/60">{commits.length}</span>
        )}
      </button>

      {!collapsed && (
        <div className="px-1">
          {loading && (
            <div className="px-3 py-2 text-xs text-text-muted">Loading commits...</div>
          )}
          {error && (
            <div className="px-3 py-2 text-xs text-red-400">{error}</div>
          )}
          {!loading && !error && commits.length === 0 && (
            <div className="px-3 py-2 text-xs text-text-muted">No commits found</div>
          )}
          {!loading && !error && commits.map((commit) => (
            <div
              key={commit.hash}
              className="flex items-start gap-2 px-3 py-1.5 rounded-md hover:bg-surface-2/50 transition-colors group"
            >
              <span
                className="font-mono text-[11px] text-[var(--accent)] flex-shrink-0 mt-px cursor-default"
                title={commit.hash}
              >
                {commit.short_hash}
              </span>
              <span className="text-xs text-text-primary truncate flex-1" title={commit.message}>
                {commit.message}
              </span>
              <span className="text-[10px] text-text-muted/60 flex-shrink-0 whitespace-nowrap mt-px">
                {commit.relative_date}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
