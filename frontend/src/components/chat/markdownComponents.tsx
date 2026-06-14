/**
 * Hoisted ReactMarkdown configuration objects.
 *
 * ReactMarkdown compares `components` and `remarkPlugins` by reference.
 * Defining them inline inside a render function creates new objects every
 * render, defeating memoisation. By hoisting them here as module-level
 * constants we guarantee stable references.
 */

import React from 'react'
import remarkGfm from 'remark-gfm'
import { CodeBlock } from './CodeBlock'
import { processChildrenForFilePaths } from './FileDownloadLink'
import { extractRelativePath, buildDownloadUrl } from '../../lib/filePathUtils'
import type { Components } from 'react-markdown'

/* ---- Shared across both assistant & streaming messages ---- */

export const REMARK_PLUGINS = [remarkGfm]

/**
 * Inline image renderer for markdown `![alt](src)`.
 *
 * Agent-generated images are saved to the workspace and referenced by their
 * absolute path (e.g. `/Users/.../workspace/outputs/chart.png`). A raw
 * filesystem path is not loadable by the browser, so we rewrite workspace
 * paths to the `/api/files/...` endpoint. Non-workspace srcs (http/https,
 * data URIs) are passed through unchanged.
 */
function MarkdownImage({ src, alt }: { src?: string; alt?: string }) {
  let resolvedSrc = src ?? ''
  if (resolvedSrc) {
    // Strip a leading file:// scheme if present.
    const cleaned = resolvedSrc.replace(/^file:\/\//, '')
    const rel = extractRelativePath(cleaned)
    if (rel) {
      resolvedSrc = buildDownloadUrl(rel)
    }
  }
  return (
    <img
      src={resolvedSrc}
      alt={alt ?? ''}
      loading="lazy"
      className="max-w-full h-auto rounded-xl border border-[var(--border)] my-2"
    />
  )
}

/* ---- Components for AssistantMessage (uses the full CodeBlock widget) ---- */

export const ASSISTANT_MD_COMPONENTS: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    const codeString = String(children).replace(/\n$/, '')
    if (match) {
      return <CodeBlock language={match[1]!} code={codeString} />
    }
    return (
      <code className={className} {...props}>
        {processChildrenForFilePaths(children)}
      </code>
    )
  },
  p({ children }) {
    return <p>{processChildrenForFilePaths(children)}</p>
  },
  li({ children }) {
    return <li>{processChildrenForFilePaths(children)}</li>
  },
  td({ children }) {
    return <td>{processChildrenForFilePaths(children)}</td>
  },
  img: MarkdownImage,
}

/* ---- Components for StreamingMessage (lightweight, no syntax highlighting) ---- */

const STREAMING_PRE_STYLE: React.CSSProperties = {
  backgroundColor: '#282c34',
  color: '#abb2bf',
  padding: '1em',
  borderRadius: '12px',
  overflow: 'auto',
  fontSize: '13px',
}

export const STREAMING_MD_COMPONENTS: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || '')
    const codeString = String(children).replace(/\n$/, '')
    if (match) {
      return (
        <pre style={STREAMING_PRE_STYLE}>
          <code>{codeString}</code>
        </pre>
      )
    }
    return (
      <code className={className} {...props}>
        {processChildrenForFilePaths(children)}
      </code>
    )
  },
  p({ children }) {
    return <p>{processChildrenForFilePaths(children)}</p>
  },
  li({ children }) {
    return <li>{processChildrenForFilePaths(children)}</li>
  },
  td({ children }) {
    return <td>{processChildrenForFilePaths(children)}</td>
  },
  img: MarkdownImage,
}
