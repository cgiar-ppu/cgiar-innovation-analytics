import { X, FileText } from 'lucide-react'
import type { PendingAttachment } from '../../lib/types'

interface Props {
  attachments: PendingAttachment[]
  onRemove: (filePath: string) => void
}

export function AttachmentChips({ attachments, onRemove }: Props) {
  if (attachments.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1.5 px-1 pt-1">
      {attachments.map((a) => (
        <div
          key={a.filePath}
          className="flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-lg bg-accent/10 border border-accent/20 text-xs group"
        >
          <FileText size={12} className="text-accent flex-shrink-0" />
          <span className="text-text-primary font-medium truncate max-w-[200px]" title={a.filePath}>
            {a.fileName}
          </span>
          <button
            onClick={() => onRemove(a.filePath)}
            className="p-0.5 rounded hover:bg-accent/20 text-text-muted hover:text-text-primary transition-colors"
            aria-label={`Remove ${a.fileName}`}
          >
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  )
}
