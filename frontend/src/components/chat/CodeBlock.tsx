import { memo } from 'react'
import { Copy, Check } from 'lucide-react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { useCopyToClipboard } from '../../hooks/useCopyToClipboard'

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
