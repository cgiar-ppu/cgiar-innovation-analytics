/**
 * @file GitDiffDetail.tsx
 * @module components/git
 *
 * Renders a unified diff view for git file changes. Takes raw old/new content
 * strings and uses shared diff utilities to compute and render hunks.
 */

import { useMemo } from 'react'
import { computeHunksFromStrings, computeStats } from '../../lib/diff-utils'
import { HunkView } from '../common/HunkView'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GitDiffDetailProps {
  filePath: string
  oldContent: string
  newContent: string
  isNewFile?: boolean
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_LINES = 300

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function GitDiffDetail({ filePath, oldContent, newContent, isNewFile }: GitDiffDetailProps) {
  const hunks = useMemo(
    () => computeHunksFromStrings(filePath, oldContent, newContent, { maxLines: MAX_LINES, isNewFile }),
    [filePath, oldContent, newContent, isNewFile],
  )
  const stats = useMemo(() => computeStats(hunks), [hunks])

  if (hunks.length === 0) {
    return (
      <div className="p-4 text-sm text-text-muted text-center">
        No changes to display
      </div>
    )
  }

  const fileName = filePath.split('/').pop() || filePath

  return (
    <div className="rounded-lg overflow-hidden border border-border bg-surface-3">
      {/* File header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-surface-2/50 border-b border-border/50 text-xs">
        <span className="font-mono font-medium text-text-primary truncate" title={filePath}>
          {fileName}
        </span>
        <div className="flex items-center gap-2 ml-auto flex-shrink-0">
          <span className="text-green-400">+{stats.added}</span>
          {stats.removed > 0 && <span className="text-red-400">-{stats.removed}</span>}
        </div>
      </div>

      {/* Hunks */}
      <div className="overflow-x-auto">
        {hunks.map((hunk, i) => (
          <div key={i}>
            {i > 0 && (
              <div className="flex items-center gap-2 px-3 py-0.5 text-[10px] text-text-muted/40 font-mono">
                <span className="flex-1 border-t border-dashed border-border/30" />
              </div>
            )}
            <HunkView hunk={hunk} startCollapsed={hunks.length > 3 && i > 0} />
          </div>
        ))}
      </div>

      {/* Full file path footer */}
      {fileName !== filePath && (
        <div className="px-3 py-1.5 text-[10px] text-text-muted/50 font-mono border-t border-border/30 truncate" title={filePath}>
          {filePath}
        </div>
      )}
    </div>
  )
}
