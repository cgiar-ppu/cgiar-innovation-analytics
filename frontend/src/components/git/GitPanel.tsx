/**
 * @file GitPanel.tsx
 * @module components/git
 *
 * Right side panel that displays git status, file changes, and diffs.
 * Auto-refreshes on open and supports manual refresh. Matches the layout
 * pattern established by DesktopViewer.
 */

import { useState, useEffect, useCallback } from 'react'
import { X, RefreshCw, GitBranch, ChevronDown, ChevronRight, FileEdit, FilePlus, FileX, File, Circle } from 'lucide-react'
import { useUIStore } from '../../stores/ui'
import { api } from '../../lib/api'
import { GitDiffDetail } from './GitDiffDetail'
import { GitLogView } from './GitLogView'
import type { GitStatus, GitDiffResponse } from '../../lib/types'

// ---------------------------------------------------------------------------
// Status icon helper
// ---------------------------------------------------------------------------

function StatusIcon({ status }: { status: string }) {
  switch (status) {
    case 'M':
      return <FileEdit size={13} className="text-amber-400 flex-shrink-0" />
    case 'A':
      return <FilePlus size={13} className="text-green-400 flex-shrink-0" />
    case 'D':
      return <FileX size={13} className="text-red-400 flex-shrink-0" />
    case 'R':
      return <File size={13} className="text-blue-400 flex-shrink-0" />
    case '?':
      return <Circle size={13} className="text-text-muted/50 flex-shrink-0" />
    default:
      return <File size={13} className="text-text-muted/50 flex-shrink-0" />
  }
}

function statusColor(status: string): string {
  switch (status) {
    case 'M': return 'text-amber-400'
    case 'A': return 'text-green-400'
    case 'D': return 'text-red-400'
    case 'R': return 'text-blue-400'
    default: return 'text-text-muted/50'
  }
}

// ---------------------------------------------------------------------------
// File list section
// ---------------------------------------------------------------------------

interface FileSectionProps {
  title: string
  files: { path: string; status: string }[]
  selectedFile: string | null
  onSelect: (path: string, staged: boolean) => void
  staged: boolean
  defaultOpen?: boolean
}

function FileSection({ title, files, selectedFile, onSelect, staged, defaultOpen = true }: FileSectionProps) {
  const [open, setOpen] = useState(defaultOpen)

  if (files.length === 0) return null

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center gap-2 px-3 py-2 text-xs font-medium text-text-muted hover:bg-surface-2/50 transition-colors"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>{title}</span>
        <span className="ml-auto text-[10px] text-text-muted/60 bg-surface-2 px-1.5 py-0.5 rounded-full">
          {files.length}
        </span>
      </button>

      {open && (
        <div className="px-1">
          {files.map((file) => {
            const fileName = file.path.split('/').pop() || file.path
            const isSelected = selectedFile === file.path
            return (
              <button
                key={file.path}
                onClick={() => onSelect(file.path, staged)}
                className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-md text-left transition-colors ${
                  isSelected
                    ? 'bg-[var(--accent)]/10 border border-[var(--accent)]/20'
                    : 'hover:bg-surface-2/50'
                }`}
                title={file.path}
              >
                <StatusIcon status={file.status} />
                <span className="text-xs text-text-primary truncate flex-1">{fileName}</span>
                <span className={`text-[10px] font-mono font-semibold flex-shrink-0 ${statusColor(file.status)}`}>
                  {file.status}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function GitPanel() {
  const { setGitPanelOpen } = useUIStore()

  const [status, setStatus] = useState<GitStatus | null>(null)
  const [selectedFile, setSelectedFile] = useState<string | null>(null)
  const [selectedStaged, setSelectedStaged] = useState(false)
  const [diffData, setDiffData] = useState<GitDiffResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [diffLoading, setDiffLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [spinning, setSpinning] = useState(false)

  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true)
      setError(null)
      const data = await api.getGitStatus()
      setStatus(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch git status')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchDiff = useCallback(async (file: string, staged: boolean) => {
    try {
      setDiffLoading(true)
      const data = await api.getGitDiff(file, staged)
      setDiffData(data)
    } catch {
      setDiffData(null)
    } finally {
      setDiffLoading(false)
    }
  }, [])

  // Auto-refresh on mount
  useEffect(() => {
    fetchStatus()
  }, [fetchStatus])

  const handleRefresh = useCallback(() => {
    setSpinning(true)
    fetchStatus().finally(() => {
      setTimeout(() => setSpinning(false), 600)
    })
    // Clear selected file on refresh
    setSelectedFile(null)
    setDiffData(null)
  }, [fetchStatus])

  const handleFileSelect = useCallback((path: string, staged: boolean) => {
    if (selectedFile === path && selectedStaged === staged) {
      // Deselect if clicking the same file
      setSelectedFile(null)
      setDiffData(null)
      return
    }
    setSelectedFile(path)
    setSelectedStaged(staged)
    fetchDiff(path, staged)
  }, [selectedFile, selectedStaged, fetchDiff])

  // Build file lists
  const stagedFiles: { path: string; status: string }[] = status?.staged ?? []
  const unstagedFiles: { path: string; status: string }[] = status?.unstaged ?? []
  const untrackedFiles: { path: string; status: string }[] = (status?.untracked ?? []).map(
    (p) => ({ path: p, status: '?' }),
  )
  const totalChanges = stagedFiles.length + unstagedFiles.length + untrackedFiles.length

  // Determine if selected file is new/untracked
  const isNewFile =
    untrackedFiles.some((f) => f.path === selectedFile) ||
    stagedFiles.some((f) => f.path === selectedFile && f.status === 'A')

  return (
    <div className="flex flex-col border-l border-border glass w-[50%] min-w-[400px]">
      {/* Header */}
      <div className="flex items-center justify-between px-4 h-10 bg-surface-2 border-b border-border flex-shrink-0">
        <div className="flex items-center gap-2">
          <GitBranch size={14} className="text-text-muted" />
          <span className="text-xs font-medium text-text-muted">Git Changes</span>
          {totalChanges > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[var(--accent)]/15 text-[var(--accent)] font-medium">
              {totalChanges}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={handleRefresh}
            className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-muted"
            title="Refresh git status"
          >
            <RefreshCw size={14} className={spinning ? 'animate-spin' : ''} />
          </button>
          <button
            onClick={() => setGitPanelOpen(false)}
            className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-muted"
            title="Close git panel"
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {/* Loading state */}
        {loading && (
          <div className="flex items-center justify-center py-8">
            <RefreshCw size={16} className="animate-spin text-text-muted" />
            <span className="ml-2 text-sm text-text-muted">Loading git status...</span>
          </div>
        )}

        {/* Error state */}
        {error && !loading && (
          <div className="p-4">
            <div className="rounded-lg bg-red-500/10 border border-red-500/20 p-3 text-xs text-red-400">
              {error}
            </div>
          </div>
        )}

        {/* Status content */}
        {status && !loading && (
          <>
            {/* Branch status bar */}
            <div className="px-4 py-2.5 border-b border-border/50 flex items-center gap-2">
              <GitBranch size={13} className="text-[var(--accent)]" />
              <span className="text-xs font-mono font-medium text-text-primary">{status.branch}</span>
              {(status.ahead > 0 || status.behind > 0) && (
                <div className="flex items-center gap-1.5 ml-auto text-[10px]">
                  {status.ahead > 0 && (
                    <span className="text-green-400" title={`${status.ahead} commit(s) ahead`}>
                      {status.ahead}&uarr;
                    </span>
                  )}
                  {status.behind > 0 && (
                    <span className="text-red-400" title={`${status.behind} commit(s) behind`}>
                      {status.behind}&darr;
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* File sections */}
            {totalChanges === 0 ? (
              <div className="p-4 text-sm text-text-muted text-center">
                Working tree clean
              </div>
            ) : (
              <div className="divide-y divide-border/30">
                <FileSection
                  title="Staged Changes"
                  files={stagedFiles}
                  selectedFile={selectedFile}
                  onSelect={handleFileSelect}
                  staged={true}
                />
                <FileSection
                  title="Changes"
                  files={unstagedFiles}
                  selectedFile={selectedFile}
                  onSelect={handleFileSelect}
                  staged={false}
                />
                <FileSection
                  title="Untracked Files"
                  files={untrackedFiles}
                  selectedFile={selectedFile}
                  onSelect={handleFileSelect}
                  staged={false}
                />
              </div>
            )}

            {/* Diff detail */}
            {selectedFile && (
              <div className="p-3 border-t border-border/50">
                {diffLoading ? (
                  <div className="flex items-center justify-center py-4">
                    <RefreshCw size={14} className="animate-spin text-text-muted" />
                    <span className="ml-2 text-xs text-text-muted">Loading diff...</span>
                  </div>
                ) : diffData ? (
                  <GitDiffDetail
                    filePath={diffData.file}
                    oldContent={diffData.old_content}
                    newContent={diffData.new_content}
                    isNewFile={isNewFile}
                  />
                ) : (
                  <div className="text-xs text-text-muted text-center py-4">
                    Unable to load diff
                  </div>
                )}
              </div>
            )}

            {/* Commit log */}
            <div className="border-t border-border/50">
              <GitLogView />
            </div>
          </>
        )}
      </div>
    </div>
  )
}
