/**
 * @file filePathUtils.ts
 * @module lib
 *
 * Utilities for detecting workspace file paths in text content and converting
 * them into download-ready relative paths for the `/api/files/` endpoint.
 *
 * Supports the following workspace path formats:
 * - `/Users/<username>/workspace/...`  (macOS local)
 * - `/home/<username>/workspace/...`   (Linux local)
 * - `~/workspace/...`                  (shell shorthand)
 * - `/workspace/...`                   (Docker container)
 */

/**
 * Regex to match full workspace file paths in text.
 *
 * Captures paths starting with known workspace prefixes and continuing until
 * whitespace, quotes, backticks, angle brackets, or closing delimiters.
 * Trailing punctuation (period, comma, semicolon, colon) is excluded to avoid
 * capturing sentence-ending characters as part of the path.
 */
const FILE_PATH_REGEX =
  /((?:\/Users\/[\w.-]+\/workspace|\/home\/[\w.-]+\/workspace|~\/workspace|\/workspace)\/[^\s"'`<>)}\],;:!?]+(?<![.,:;!?]))/g

/**
 * Ordered list of workspace prefix patterns. Most specific first so that
 * `/Users/smithai/workspace/` is matched before the generic `/workspace/`.
 */
const WORKSPACE_PREFIXES: RegExp[] = [
  /^\/Users\/[\w.-]+\/workspace\//,
  /^\/home\/[\w.-]+\/workspace\//,
  /^~\/workspace\//,
  /^\/workspace\//,
]

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A segment of parsed text — either plain text or a detected file path. */
export interface FilePathSegment {
  type: 'text' | 'filepath'
  /** The raw text value (for text) or the full absolute path (for filepath). */
  value: string
  /** Workspace-relative path — only present for `filepath` segments. */
  relativePath?: string
  /** Just the filename (last path component) — only present for `filepath` segments. */
  filename?: string
}

// ---------------------------------------------------------------------------
// Core functions
// ---------------------------------------------------------------------------

/**
 * Extracts the workspace-relative portion of an absolute file path.
 *
 * @param absolutePath - Full path, e.g. `/Users/smithai/workspace/outputs/report.html`
 * @returns The relative path (e.g. `outputs/report.html`), or `null` if the
 *   path doesn't match any known workspace prefix.
 *
 * @example
 * extractRelativePath('/Users/smithai/workspace/outputs/report.html')
 * // → 'outputs/report.html'
 *
 * extractRelativePath('/workspace/uploads/data.csv')
 * // → 'uploads/data.csv'
 */
export function extractRelativePath(absolutePath: string): string | null {
  for (const prefix of WORKSPACE_PREFIXES) {
    const match = absolutePath.match(prefix)
    if (match) {
      return absolutePath.slice(match[0].length)
    }
  }
  return null
}

/**
 * Builds a download URL for a workspace-relative file path.
 *
 * Encodes each path segment individually (rather than the whole path) to
 * ensure correct behavior with Nginx proxies and FastAPI's `{filename:path}`
 * route parameter.
 *
 * @param relativePath - Path relative to the workspace root.
 * @returns URL string like `/api/files/outputs/tunnel-architecture-speeds.html`
 *
 * @example
 * buildDownloadUrl('outputs/my report.html')
 * // → '/api/files/outputs/my%20report.html'
 */
export function buildDownloadUrl(relativePath: string): string {
  return (
    '/api/files/' +
    relativePath
      .split('/')
      .map(encodeURIComponent)
      .join('/')
  )
}

/**
 * Checks whether a string contains any workspace file paths.
 *
 * @param text - The text to scan.
 * @returns `true` if at least one workspace path is found.
 */
export function containsFilePaths(text: string): boolean {
  FILE_PATH_REGEX.lastIndex = 0
  return FILE_PATH_REGEX.test(text)
}

/**
 * Splits a text string into an array of plain-text and file-path segments.
 *
 * Each file-path segment includes the full original path, the extracted
 * workspace-relative path, and the bare filename for display purposes.
 *
 * @param text - The text to parse.
 * @returns An ordered array of segments covering the entire input string.
 *
 * @example
 * parseFilePathsInText('See /workspace/outputs/chart.png for details')
 * // → [
 * //     { type: 'text', value: 'See ' },
 * //     { type: 'filepath', value: '/workspace/outputs/chart.png',
 * //       relativePath: 'outputs/chart.png', filename: 'chart.png' },
 * //     { type: 'text', value: ' for details' },
 * //   ]
 */
export function parseFilePathsInText(text: string): FilePathSegment[] {
  const segments: FilePathSegment[] = []
  let lastIndex = 0

  // Reset global regex state before each scan
  FILE_PATH_REGEX.lastIndex = 0

  let match: RegExpExecArray | null
  while ((match = FILE_PATH_REGEX.exec(text)) !== null) {
    const fullPath = match[1] as string | undefined
    if (!fullPath) continue

    const relativePath = extractRelativePath(fullPath)

    // Skip paths we can't resolve to a workspace-relative form
    if (!relativePath) continue

    // Add any preceding plain text
    if (match.index > lastIndex) {
      segments.push({ type: 'text', value: text.slice(lastIndex, match.index) })
    }

    // Add the file path segment
    const parts = relativePath.split('/')
    const filename: string = parts[parts.length - 1] ?? relativePath
    segments.push({
      type: 'filepath' as const,
      value: fullPath,
      relativePath,
      filename,
    })

    lastIndex = match.index + match[0].length
  }

  // Trailing text after the last match (or the whole string if no matches)
  if (lastIndex < text.length) {
    segments.push({ type: 'text', value: text.slice(lastIndex) })
  }

  return segments
}
