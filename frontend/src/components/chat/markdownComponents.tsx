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
import type { Components } from 'react-markdown'

/* ---- Shared across both assistant & streaming messages ---- */

export const REMARK_PLUGINS = [remarkGfm]

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
}
