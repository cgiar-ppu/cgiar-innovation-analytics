/**
 * @file HunkView.tsx
 * @module components/common
 *
 * Renders a single diff hunk with collapsible header, line numbers,
 * +/- coloring, and word-level change highlighting. Shared by both
 * DiffView (chat) and GitDiffDetail (git).
 */

import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { type DiffHunk, computeStats, pairChangedLines } from '../../lib/diff-utils'

export function HunkView({ hunk, startCollapsed }: { hunk: DiffHunk; startCollapsed: boolean }) {
  const [collapsed, setCollapsed] = useState(startCollapsed)
  const diffLines = useMemo(() => pairChangedLines(hunk.lines), [hunk.lines])

  // Track line numbers
  let oldLine = hunk.oldStart
  let newLine = hunk.newStart

  if (collapsed) {
    const stats = computeStats([hunk])
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-[11px] text-text-muted hover:bg-surface-2/50 transition-colors font-mono"
      >
        <ChevronRight size={12} />
        <span>@@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@</span>
        <span className="text-green-400/70">+{stats.added}</span>
        <span className="text-red-400/70">-{stats.removed}</span>
      </button>
    )
  }

  return (
    <div className="font-mono text-xs leading-5">
      {/* Hunk header */}
      <button
        onClick={() => setCollapsed(true)}
        className="w-full flex items-center gap-2 px-3 py-1 text-[11px] text-blue-400/70 bg-blue-500/5 hover:bg-blue-500/10 transition-colors"
      >
        <ChevronDown size={12} />
        <span>@@ -{hunk.oldStart},{hunk.oldLines} +{hunk.newStart},{hunk.newLines} @@</span>
      </button>

      {/* Diff lines */}
      {diffLines.map((dl, idx) => {
        let oldNum = ''
        let newNum = ''

        if (dl.type === 'context') {
          oldNum = String(oldLine++)
          newNum = String(newLine++)
        } else if (dl.type === 'removed') {
          oldNum = String(oldLine++)
        } else if (dl.type === 'added') {
          newNum = String(newLine++)
        }

        const bgClass =
          dl.type === 'added'
            ? 'bg-green-500/10'
            : dl.type === 'removed'
              ? 'bg-red-500/10'
              : ''

        const prefixChar =
          dl.type === 'added' ? '+' : dl.type === 'removed' ? '-' : ' '
        const prefixColor =
          dl.type === 'added'
            ? 'text-green-400'
            : dl.type === 'removed'
              ? 'text-red-400'
              : 'text-text-muted/40'

        return (
          <div key={idx} className={`flex ${bgClass} hover:brightness-110`}>
            {/* Line number gutter */}
            <span className="select-none text-text-muted/30 w-[3.5ch] text-right pr-1 flex-shrink-0 border-r border-border/30">
              {oldNum}
            </span>
            <span className="select-none text-text-muted/30 w-[3.5ch] text-right pr-1 flex-shrink-0 border-r border-border/30">
              {newNum}
            </span>
            {/* Prefix (+/-/space) */}
            <span className={`select-none w-[2ch] text-center flex-shrink-0 ${prefixColor}`}>
              {prefixChar}
            </span>
            {/* Content with optional word-level highlighting */}
            <span className="flex-1 whitespace-pre-wrap break-all pr-2">
              {dl.fragments ? (
                dl.fragments.map((frag, fi) => (
                  <span
                    key={fi}
                    className={
                      frag.highlighted
                        ? dl.type === 'added'
                          ? 'bg-green-400/25 rounded-sm'
                          : 'bg-red-400/25 rounded-sm'
                        : ''
                    }
                  >
                    {frag.text}
                  </span>
                ))
              ) : (
                <span className={dl.type === 'added' ? 'text-green-300' : dl.type === 'removed' ? 'text-red-300' : ''}>{dl.text}</span>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}
