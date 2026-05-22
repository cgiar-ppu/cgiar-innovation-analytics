/**
 * @file DiffView.tsx
 * @module components/chat
 *
 * Renders a unified diff view for file Edit and Write tool calls.
 * Uses shared diff utilities from lib/diff-utils and shared HunkView component.
 *
 * Supports two modes:
 * - **Edit**: Shows old_string -> new_string replacement diff
 * - **Write**: Shows full new file content (all additions)
 */

import { useMemo } from 'react'
import { FileEdit, FilePlus, Copy, Check } from 'lucide-react'
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard'
import {
  type DiffHunk,
  computeHunksFromStrings,
  computeStats,
} from '../../lib/diff-utils'
import { HunkView } from '../common/HunkView'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DiffViewProps {
  /** Tool name — 'Edit' or 'Write' */
  tool: string
  /** Tool input object from the tool_use message */
  toolInput: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Diff computation (adapts tool input to shared utilities)
// ---------------------------------------------------------------------------

/**
 * Generate structured diff hunks from Edit/Write tool input.
 * For Edit: compares old_string vs new_string
 * For Write: treats entire content as additions
 */
function computeHunks(tool: string, input: Record<string, unknown>): DiffHunk[] {
  const filePath = (input.file_path as string) || (input.path as string) || 'file'

  if (tool === 'Edit') {
    const oldStr = (input.old_string as string) || ''
    const newStr = (input.new_string as string) || ''
    return computeHunksFromStrings(filePath, oldStr, newStr)
  }

  if (tool === 'Write') {
    const content = (input.content as string) || ''
    if (!content) return []
    return computeHunksFromStrings(filePath, '', content, { maxLines: 100, isNewFile: true })
  }

  return []
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function DiffView({ tool, toolInput }: DiffViewProps) {
  const hunks = useMemo(() => computeHunks(tool, toolInput), [tool, toolInput])
  const stats = useMemo(() => computeStats(hunks), [hunks])
  const { copied, copyToClipboard } = useCopyToClipboard()

  const filePath = (toolInput.file_path as string) || (toolInput.path as string) || ''
  const fileName = filePath.split('/').pop() || filePath
  const isEdit = tool === 'Edit'
  const replaceAll = toolInput.replace_all as boolean | undefined

  // Content for copy button
  const copyContent = isEdit
    ? (toolInput.new_string as string) || ''
    : (toolInput.content as string) || ''

  if (hunks.length === 0) return null

  return (
    <div className="rounded-lg overflow-hidden border border-border bg-surface-3">
      {/* File header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-surface-2/50 border-b border-border/50 text-xs">
        {isEdit ? (
          <FileEdit size={13} className="text-amber-400 flex-shrink-0" />
        ) : (
          <FilePlus size={13} className="text-green-400 flex-shrink-0" />
        )}
        <span className="font-mono font-medium text-text-primary truncate" title={filePath}>
          {fileName}
        </span>
        {replaceAll && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 border border-amber-500/20 flex-shrink-0">
            replace all
          </span>
        )}
        <div className="flex items-center gap-2 ml-auto flex-shrink-0">
          <span className="text-green-400">+{stats.added}</span>
          {stats.removed > 0 && <span className="text-red-400">-{stats.removed}</span>}
          <button
            onClick={() => copyToClipboard(copyContent)}
            className="flex items-center gap-1 text-text-muted hover:text-text-primary transition-colors ml-1"
            title="Copy new content"
          >
            {copied ? <Check size={12} /> : <Copy size={12} />}
          </button>
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

      {/* Full file path footer (if truncated in header) */}
      {fileName !== filePath && (
        <div className="px-3 py-1.5 text-[10px] text-text-muted/50 font-mono border-t border-border/30 truncate" title={filePath}>
          {filePath}
        </div>
      )}
    </div>
  )
}

/**
 * Check if a tool call should render a diff view.
 */
export function shouldShowDiff(toolName: string | undefined): boolean {
  return toolName === 'Edit' || toolName === 'Write'
}
