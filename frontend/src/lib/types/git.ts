/**
 * @file git.ts
 * @module lib/types
 *
 * Git-related types for the frontend git panel, covering status, diff,
 * log, and show responses from the REST API.
 */

/** Status of a single file in the git index or working tree. */
export interface GitFileStatus {
  /** Relative file path. */
  path: string
  /** Single-character status code (M, A, D, R, etc.). */
  status: string
}

/** Response from `GET /api/git/status`. */
export interface GitStatus {
  /** Current branch name. */
  branch: string
  /** Files staged for the next commit. */
  staged: GitFileStatus[]
  /** Files with unstaged modifications. */
  unstaged: GitFileStatus[]
  /** Untracked file paths. */
  untracked: string[]
  /** Number of commits ahead of the upstream. */
  ahead: number
  /** Number of commits behind the upstream. */
  behind: number
}

/** Response from `GET /api/git/diff`. */
export interface GitDiffResponse {
  /** File the diff pertains to. */
  file: string
  /** Raw unified diff string. */
  diff: string
  /** Original file content (before changes). */
  old_content: string
  /** New file content (after changes). */
  new_content: string
}

/** A single commit entry in the log. */
export interface GitLogCommit {
  /** Full commit hash. */
  hash: string
  /** Abbreviated commit hash. */
  short_hash: string
  /** Author name. */
  author: string
  /** Author email. */
  email: string
  /** Human-readable relative date (e.g. "2 hours ago"). */
  relative_date: string
  /** Commit message subject line. */
  message: string
}

/** Response from `GET /api/git/log`. */
export interface GitLogResponse {
  /** List of recent commits. */
  commits: GitLogCommit[]
}

/** Response from `GET /api/git/show`. */
export interface GitShowResponse {
  /** File content at the given ref. */
  content: string
  /** File path. */
  file: string
  /** Git ref the content was read from. */
  ref: string
}
