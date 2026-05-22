import { useState, useEffect } from 'react'
import { Plus, Trash2, Star } from 'lucide-react'
import { api } from '../../lib/api'
import { truncate } from '../../lib/utils'
import { MemoryForm } from './MemoryForm'
import type { Memory } from '../../lib/types'

export function MemoryList() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [showForm, setShowForm] = useState(false)
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const { memories } = await api.getMemories()
      setMemories(memories)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this memory?')) return
    try {
      await api.deleteMemory(id)
      setMemories((prev) => prev.filter((m) => m.id !== id))
    } catch {
      // ignore
    }
  }

  const handleSaved = () => {
    setShowForm(false)
    load()
  }

  const grouped = memories.reduce<Record<string, Memory[]>>((acc, m) => {
    (acc[m.category] ??= []).push(m)
    return acc
  }, {})

  return (
    <div className="flex flex-col h-full">
      <div className="p-3">
        <button
          onClick={() => setShowForm(!showForm)}
          className="w-full flex items-center justify-center gap-1.5 py-2.5 rounded-xl bg-purple text-white text-xs font-medium
            hover:opacity-90 transition-all shadow-sm"
        >
          <Plus size={14} />
          Add Memory
        </button>
      </div>

      {showForm && (
        <MemoryForm onSaved={handleSaved} onCancel={() => setShowForm(false)} />
      )}

      <div className="flex-1 overflow-y-auto px-2">
        {Object.entries(grouped).map(([category, mems]) => (
          <div key={category} className="mb-3">
            <div className="px-3 py-1.5 text-[10px] font-semibold text-purple uppercase tracking-widest">
              {category.replace(/_/g, ' ')}
            </div>
            {mems.map((mem) => (
              <div
                key={mem.id}
                className="group flex items-start gap-2 px-3 py-2.5 hover:bg-surface-2 transition-colors rounded-xl my-0.5"
              >
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-text-primary leading-relaxed">
                    {truncate(mem.content, 150)}
                  </div>
                  <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                    <div className="flex items-center gap-0.5">
                      {Array.from({ length: Math.min(mem.importance, 5) }).map((_, i) => (
                        <Star key={i} size={10} className="text-warning fill-warning" />
                      ))}
                      <span className="text-[11px] text-text-muted ml-0.5">{mem.importance}</span>
                    </div>
                    {mem.tags && mem.tags.split(',').map((tag) => (
                      <span key={tag.trim()} className="text-[10px] px-2 py-0.5 rounded-full bg-accent-soft text-accent font-medium">
                        {tag.trim()}
                      </span>
                    ))}
                  </div>
                </div>
                <button
                  onClick={() => handleDelete(mem.id)}
                  className="p-1 rounded-lg hover:bg-danger-soft text-text-muted hover:text-danger
                    opacity-0 group-hover:opacity-100 transition-all flex-shrink-0"
                  aria-label="Delete memory"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        ))}
        {loading && memories.length === 0 && (
          <div className="text-center text-text-muted text-xs py-8">Loading...</div>
        )}
        {!loading && memories.length === 0 && (
          <div className="text-center text-text-muted text-xs py-8">No memories stored</div>
        )}
      </div>
    </div>
  )
}
