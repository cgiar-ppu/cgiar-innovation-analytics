import { memo, useEffect, useRef, useState } from 'react'
import { Brain } from 'lucide-react'
import { Expandable } from '../common/Expandable'

interface Props {
  content: string
  isActive: boolean
}

export const ThinkingBlock = memo(function ThinkingBlock({ content, isActive }: Props) {
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(Date.now())

  useEffect(() => {
    if (!isActive) return
    startRef.current = Date.now()
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [isActive])

  return (
    <Expandable
      defaultExpanded={false}
      className={`animate-fade-in-up border-l-2 border-purple rounded-xl glass overflow-hidden ${
        isActive ? 'animate-thinking-pulse' : ''
      }`}
      buttonClassName="text-purple"
      header={
        <>
          <Brain size={14} className="flex-shrink-0" />
          <span className="font-medium">Thinking</span>
          {isActive && (
            <span className="text-xs text-text-muted ml-1">{elapsed}s</span>
          )}
        </>
      }
    >
      <div className="px-3 pb-3">
        <pre className="text-xs text-text-muted whitespace-pre-wrap font-mono leading-relaxed max-h-60 overflow-y-auto">
          {content}
        </pre>
      </div>
    </Expandable>
  )
})
