import { memo } from 'react'
import { Copy, Check } from 'lucide-react'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import r from 'react-syntax-highlighter/dist/esm/languages/prism/r'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard'

// L4-12: register only the languages IA answers use (PRMS SQL, Python/R
// snippets, JSON/YAML, shell, web, Markdown) instead of bundling all ~300
// Prism grammars. Unknown languages render as plain monospaced text.
const LANGUAGES: Record<string, unknown> = {
  bash, sh: bash, shell: bash, zsh: bash, css, json, javascript, js: javascript,
  typescript, ts: typescript, markdown, md: markdown, markup, html: markup, xml: markup,
  python, py: python, r, sql, yaml, yml: yaml,
}
for (const [name, grammar] of Object.entries(LANGUAGES)) {
  SyntaxHighlighter.registerLanguage(name, grammar)
}

interface CodeBlockProps {
  code: string
  language: string
}

/** Hoisted to avoid creating a new object on every render */
const CODE_BLOCK_STYLE = {
  margin: 0,
  borderTopLeftRadius: 0,
  borderTopRightRadius: 0,
  borderBottomLeftRadius: '12px',
  borderBottomRightRadius: '12px',
  fontSize: '13px',
}

export const CodeBlock = memo(function CodeBlock({ language, code }: CodeBlockProps) {
  const { copied, copyToClipboard } = useCopyToClipboard()

  return (
    <div className="relative group/code rounded-xl overflow-hidden border border-border">
      <div className="flex items-center justify-between px-4 py-2 bg-surface-3 text-xs text-text-muted">
        <span className="font-mono font-medium">{language}</span>
        <button
          onClick={() => copyToClipboard(code)}
          className="flex items-center gap-1.5 hover:text-text-primary transition-colors"
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          <span>{copied ? 'Copied' : 'Copy'}</span>
        </button>
      </div>
      <SyntaxHighlighter
        style={oneDark}
        language={language}
        customStyle={CODE_BLOCK_STYLE}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
})
