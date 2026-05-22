import { useState } from 'react'
import type { ReactNode } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

interface ExpandableProps {
  header: ReactNode
  children: ReactNode
  defaultExpanded?: boolean
  className?: string
  buttonClassName?: string
}

export function Expandable({
  header,
  children,
  defaultExpanded = false,
  className = '',
  buttonClassName = 'text-text-primary',
}: ExpandableProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  return (
    <div className={className}>
      <button
        onClick={() => setExpanded((prev) => !prev)}
        className={`w-full flex items-center gap-2 px-3 py-2.5 text-sm hover:bg-surface-2/50 transition-colors ${buttonClassName}`}
      >
        {header}
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
      </button>
      <div
        className="grid transition-[grid-template-rows] duration-200"
        style={{ gridTemplateRows: expanded ? '1fr' : '0fr' }}
      >
        <div className="overflow-hidden">
          {children}
        </div>
      </div>
    </div>
  )
}
