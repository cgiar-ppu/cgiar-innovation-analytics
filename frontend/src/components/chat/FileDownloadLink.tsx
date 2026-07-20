/**
 * @file FileDownloadLink.tsx
 * @module components/chat
 *
 * Inline download button for workspace file paths detected in chat messages
 * and tool outputs. Renders a compact, styled link that triggers a browser
 * download via the `/api/files/` endpoint.
 *
 * Also exports helper functions for integrating file-path detection into
 * ReactMarkdown components and `<pre>` blocks.
 */

import { type ReactNode, Fragment } from 'react'
import { Download } from 'lucide-react'
import {
  buildDownloadUrl,
  containsFilePaths,
  parseFilePathsInText,
} from '../../lib/filePathUtils'
import { getAuthToken } from '../../stores/auth'

// ---------------------------------------------------------------------------
// FileDownloadLink — the core button component
// ---------------------------------------------------------------------------

interface FileDownloadLinkProps {
  /** Workspace-relative path for the download API. */
  relativePath: string
  /** Display name (usually the last path segment). */
  filename: string
  /** Original absolute path, shown in the tooltip. */
  fullPath: string
}

/**
 * A compact inline download button that links to the file download API.
 *
 * Renders as an `<a>` tag with `download` attribute so the browser triggers a
 * save dialog rather than navigating away.
 */
export function FileDownloadLink({ relativePath, filename, fullPath }: FileDownloadLinkProps) {
  // `GET /api/files/{path}` requires auth (2026-07-20); this button renders
  // a plain <a> (no Authorization header), so attach the JWT as ?token=
  // (same pattern the export links and MarkdownAnchor use).
  const url = buildDownloadUrl(relativePath, getAuthToken())

  return (
    <a
      href={url}
      download
      target="_blank"
      rel="noopener noreferrer"
      title={`Download ${fullPath}`}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md
        bg-accent/10 hover:bg-accent/20 text-accent text-[11px] font-medium
        transition-colors border border-accent/20 hover:border-accent/40
        no-underline cursor-pointer align-middle whitespace-nowrap"
      onClick={(e) => e.stopPropagation()}
    >
      <Download size={11} className="flex-shrink-0" />
      <span className="truncate max-w-[200px]">{filename}</span>
    </a>
  )
}

// ---------------------------------------------------------------------------
// processChildrenForFilePaths — for ReactMarkdown component overrides
// ---------------------------------------------------------------------------

/**
 * Recursively processes React children, replacing workspace file paths found
 * in string children with inline {@link FileDownloadLink} components.
 *
 * Designed to be used inside ReactMarkdown custom component overrides for
 * `p`, `li`, `code` (inline), and `td` elements.
 *
 * Non-string children (other React elements) are passed through unchanged.
 *
 * @param children - The React children to process.
 * @returns Transformed children with file paths replaced by download links.
 */
export function processChildrenForFilePaths(children: ReactNode): ReactNode {
  if (typeof children === 'string') {
    if (!containsFilePaths(children)) return children

    const segments = parseFilePathsInText(children)
    // If parsing found no actual file segments, return unchanged
    if (segments.length === 1 && segments[0]?.type === 'text') return children

    return (
      <>
        {segments.map((seg, i) =>
          seg.type === 'filepath' ? (
            <Fragment key={i}>
              <code className="text-accent text-[0.85em]">{seg.value}</code>
              {' '}
              <FileDownloadLink
                relativePath={seg.relativePath ?? ''}
                filename={seg.filename ?? ''}
                fullPath={seg.value}
              />
            </Fragment>
          ) : (
            <Fragment key={i}>{seg.value}</Fragment>
          ),
        )}
      </>
    )
  }

  if (Array.isArray(children)) {
    let hasChange = false
    const mapped = children.map((child) => {
      const processed = processChildrenForFilePaths(child)
      if (processed !== child) hasChange = true
      return processed
    })
    // Avoid unnecessary re-renders if nothing changed
    return hasChange ? mapped : children
  }

  return children
}

// ---------------------------------------------------------------------------
// renderPreWithFileLinks — for <pre> blocks in ToolCallCard
// ---------------------------------------------------------------------------

/**
 * Renders a text string inside a `<pre>` block, replacing detected workspace
 * file paths with inline download buttons.
 *
 * If no file paths are found, returns the text as-is (plain string) so
 * it can be rendered as a normal text node inside `<pre>`.
 *
 * @param text - The raw text content to render.
 * @returns Either the unchanged string or a React fragment with embedded links.
 */
export function renderPreWithFileLinks(text: string): ReactNode {
  if (!containsFilePaths(text)) return text

  const segments = parseFilePathsInText(text)
  if (segments.length === 1 && segments[0]?.type === 'text') return text

  return (
    <>
      {segments.map((seg, i) =>
        seg.type === 'filepath' ? (
          <Fragment key={i}>
            <span className="text-accent">{seg.value}</span>
            {' '}
            <FileDownloadLink
              relativePath={seg.relativePath ?? ''}
              filename={seg.filename ?? ''}
              fullPath={seg.value}
            />
          </Fragment>
        ) : (
          <Fragment key={i}>{seg.value}</Fragment>
        ),
      )}
    </>
  )
}
