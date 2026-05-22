import { useState, useEffect, useRef } from 'react'
import { Upload, RefreshCw, FileText, Download } from 'lucide-react'
import { api } from '../../lib/api'
import { formatSize, formatTimestamp } from '../../lib/utils'
import type { FileInfo } from '../../lib/types'

export function FileList() {
  const [files, setFiles] = useState<FileInfo[]>([])
  const [loading, setLoading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const load = async () => {
    setLoading(true)
    try {
      const { files } = await api.getFiles()
      setFiles(files)
    } catch {
      // ignore
    }
    setLoading(false)
  }

  useEffect(() => { load() }, [])

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    try {
      for (const file of Array.from(files)) {
        await api.uploadFile(file)
      }
      await load()
    } catch {
      // ignore
    }
    e.target.value = ''
  }

  const handleDownload = (filename: string) => {
    const a = document.createElement('a')
    a.href = api.downloadUrl(filename)
    a.download = filename.split('/').pop() ?? filename
    a.click()
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-2 p-3">
        <button
          onClick={() => fileInputRef.current?.click()}
          className="flex-1 flex items-center justify-center gap-1.5 py-2.5 rounded-xl text-white text-xs font-medium
            shadow-sm hover:shadow-md transition-all"
          style={{ background: 'var(--user-bubble)' }}
        >
          <Upload size={14} />
          Upload
        </button>
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-2.5 rounded-xl glass text-text-muted text-xs hover:bg-surface-2 transition-colors
            disabled:opacity-50"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleUpload} />
      </div>

      <div className="flex-1 overflow-y-auto px-2">
        {files.map((file) => (
          <button
            key={file.name}
            onClick={() => handleDownload(file.name)}
            className="w-full flex items-start gap-2.5 px-3 py-2.5 hover:bg-surface-2 transition-colors text-left rounded-xl my-0.5"
          >
            <FileText size={14} className="text-accent mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-sm text-accent truncate">{file.name}</div>
              <div className="text-[11px] text-text-muted">
                {formatSize(file.size)} &middot; {formatTimestamp(file.modified)}
              </div>
            </div>
            <Download size={12} className="text-text-muted mt-1 flex-shrink-0" />
          </button>
        ))}
        {files.length === 0 && !loading && (
          <div className="text-center text-text-muted text-xs py-8">
            No files in workspace
          </div>
        )}
      </div>
    </div>
  )
}
