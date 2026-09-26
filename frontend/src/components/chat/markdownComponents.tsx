/**
 * Hoisted ReactMarkdown configuration objects.
 *
 * ReactMarkdown compares `components` and `remarkPlugins` by reference.
 * Defining them inline inside a render function creates new objects every
 * render, defeating memoisation. By hoisting them here as module-level
 * constants we guarantee stable references.
 */

import React, { useEffect, useState } from 'react'
import remarkGfm from 'remark-gfm'
import { CodeBlock } from './CodeBlock'
import { processChildrenForFilePaths } from './FileDownloadLink'
import { extractRelativePath, buildDownloadUrl, resolveWorkspaceHref, isWorkspaceHref } from '../../lib/filePathUtils'
import { fetchAuthenticatedImageUrl, withFreshToken } from '../../lib/downloads'
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
  const raw = src ?? ''
  const rel = raw ? extractRelativePath(raw.replace(/^file:\/\//, '')) : null
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  // Workspace images are fetched with the CURRENT token (Authorization
  // header) instead of a token baked into src at render time (L4-06).
  useEffect(() => {
    if (!rel) return
    const controller = new AbortController()
    let url: string | null = null
    fetchAuthenticatedImageUrl(buildDownloadUrl(rel), controller.signal)
      .then((u) => { url = u; setBlobUrl(u) })
      .catch(() => { if (!controller.signal.aborted) setFailed(true) })
    return () => {
      controller.abort()
      if (url) URL.revokeObjectURL(url)
    }
  }, [rel])

  if (rel && !blobUrl) {
    return failed
      ? <span className="text-xs text-[var(--text-muted)]">[image unavailable{alt ? `: ${alt}` : ''}]</span>
      : null
  }
  return (
    <img
      src={rel ? blobUrl ?? '' : raw}
      alt={alt ?? ''}
      loading="lazy"
      className="max-w-full h-auto rounded-xl border border-[var(--border)] my-2"
    />
  )
}

/**
 * Anchor renderer for markdown `[text](href)` links.
 *
 * Agent replies sometimes contain markdown links pointing at an absolute
 * workspace path (e.g. `[report](/workspace/outputs/report.docx)`). Left as
 * a raw href, clicking it navigates the browser to a path that is neither a
 * frontend route nor an API route — the SPA catch-all serves `index.html`
 * (200, blank/broken page) instead of the file. Workspace-prefixed hrefs are
 * rewritten to the authenticated `/api/files/...` download endpoint;
 * anything else (external URLs, PRMS citation links, etc.) passes through
 * unchanged.
 */
const MarkdownAnchor: Components['a'] = ({ href, children, node: _node, ...rest }) => {
  const workspaceLink = Boolean(href && isWorkspaceHref(href))
  // Token-free href; the current token is added at click time (L4-06).
  const resolvedHref = href ? resolveWorkspaceHref(href) : href

  if (workspaceLink) {
    return (
      <a href={resolvedHref} download target="_blank" rel="noopener noreferrer" {...rest}
        onClick={withFreshToken} onAuxClick={withFreshToken}>
        {children}
      </a>
    )
  }

  // External and PRMS citation links open in a new tab so a click never
  // leaves the app or drops a streaming answer (L4-14).
  const external = Boolean(href && /^https?:\/\//i.test(href))
  return (
    <a href={resolvedHref} {...(external ? { target: '_blank', rel: 'noopener noreferrer' } : {})} {...rest}
      onClick={(e) => e.stopPropagation()}>
      {children}
    </a>
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
  a: MarkdownAnchor,
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
  a: MarkdownAnchor,
}
