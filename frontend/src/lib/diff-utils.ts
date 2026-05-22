/**
 * @file diff-utils.ts
 * @module lib
 *
 * Shared diff types and pure utility functions used by both DiffView (chat)
 * and GitDiffDetail (git). Extracted to eliminate ~210 lines of duplication.
 */

import { structuredPatch, diffWordsWithSpace } from 'diff'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface DiffHunk {
  oldStart: number
  oldLines: number
  newStart: number
  newLines: number
  lines: string[]
}

export interface DiffFragment {
  text: string
  highlighted: boolean
}

export type DiffLine =
  | { type: 'context'; text: string; fragments?: undefined }
  | { type: 'added'; text: string; fragments?: DiffFragment[] }
  | { type: 'removed'; text: string; fragments?: DiffFragment[] }

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const CONTEXT_LINES = 3

// ---------------------------------------------------------------------------
// Diff computation
// ---------------------------------------------------------------------------

/**
 * Compute structured diff hunks from old/new content strings.
 * Shared core used by both DiffView and GitDiffDetail.
 */
export function computeHunksFromStrings(
  filePath: string,
  oldContent: string,
  newContent: string,
  options?: { maxLines?: number; isNewFile?: boolean },
): DiffHunk[] {
  const maxLines = options?.maxLines
  const isNewFile = options?.isNewFile

  if (isNewFile || (!oldContent && newContent)) {
    const lines = newContent.split('\n')
    const truncated = maxLines != null && lines.length > maxLines
    const displayLines = truncated ? lines.slice(0, maxLines) : lines

    return [{
      oldStart: 0,
      oldLines: 0,
      newStart: 1,
      newLines: displayLines.length,
      lines: [
        ...displayLines.map(l => '+' + l),
        ...(truncated ? [` ... (${lines.length - maxLines!} more lines)`] : []),
      ],
    }]
  }

  if (!oldContent && !newContent) return []

  try {
    const patch = structuredPatch(filePath, filePath, oldContent, newContent, '', '', {
      context: CONTEXT_LINES,
    })
    return patch.hunks
  } catch {
    return []
  }
}

/**
 * Compute line-change stats from hunks.
 */
export function computeStats(hunks: DiffHunk[]): { added: number; removed: number } {
  let added = 0
  let removed = 0
  for (const hunk of hunks) {
    for (const line of hunk.lines) {
      if (line.startsWith('+')) added++
      else if (line.startsWith('-')) removed++
    }
  }
  return { added, removed }
}

// ---------------------------------------------------------------------------
// Word-level diff rendering
// ---------------------------------------------------------------------------

/**
 * Pair consecutive -/+ lines for word-level diffing.
 * Remaining unpaired lines are rendered normally.
 */
export function pairChangedLines(lines: string[]): DiffLine[] {
  const result: DiffLine[] = []

  let i = 0
  while (i < lines.length) {
    const line = lines[i]!
    const prefix = line[0]
    const content = line.slice(1)

    if (prefix === '-') {
      // Look ahead for a paired + line
      const removedLines: string[] = [content]
      let j = i + 1
      while (j < lines.length && lines[j]![0] === '-') {
        removedLines.push(lines[j]!.slice(1))
        j++
      }
      const addedLines: string[] = []
      let k = j
      while (k < lines.length && lines[k]![0] === '+') {
        addedLines.push(lines[k]!.slice(1))
        k++
      }

      // If we have paired changes, do word-level diff
      const pairCount = Math.min(removedLines.length, addedLines.length)
      for (let p = 0; p < pairCount; p++) {
        const wordDiff = diffWordsWithSpace(removedLines[p]!, addedLines[p]!)
        const removedFragments: DiffFragment[] = []
        const addedFragments: DiffFragment[] = []

        for (const part of wordDiff) {
          if (part.removed) {
            removedFragments.push({ text: part.value, highlighted: true })
          } else if (part.added) {
            addedFragments.push({ text: part.value, highlighted: true })
          } else {
            removedFragments.push({ text: part.value, highlighted: false })
            addedFragments.push({ text: part.value, highlighted: false })
          }
        }

        result.push({ type: 'removed', text: removedLines[p]!, fragments: removedFragments })
        result.push({ type: 'added', text: addedLines[p]!, fragments: addedFragments })
      }

      // Remaining unpaired removed lines
      for (let p = pairCount; p < removedLines.length; p++) {
        result.push({ type: 'removed', text: removedLines[p]! })
      }
      // Remaining unpaired added lines
      for (let p = pairCount; p < addedLines.length; p++) {
        result.push({ type: 'added', text: addedLines[p]! })
      }

      i = k
    } else if (prefix === '+') {
      result.push({ type: 'added', text: content })
      i++
    } else {
      result.push({ type: 'context', text: content })
      i++
    }
  }

  return result
}
