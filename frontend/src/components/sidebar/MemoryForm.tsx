import { useState } from 'react'
import { api } from '../../lib/api'

const CATEGORIES = [
  'user_profile',
  'project_context',
  'analysis_decision',
  'methodology_note',
  'best_practice',
  'escalation_record',
]

interface Props {
  onSaved: () => void
  onCancel: () => void
}

export function MemoryForm({ onSaved, onCancel }: Props) {
  const [category, setCategory] = useState(CATEGORIES[0]!)
  const [content, setContent] = useState('')
  const [importance, setImportance] = useState(5)
  const [tags, setTags] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!content.trim()) return
    setSaving(true)
    try {
      await api.createMemory({ category, content: content.trim(), importance, tags: tags.trim() })
      onSaved()
    } catch {
      // ignore
    }
    setSaving(false)
  }

  return (
    <div className="p-3 glass rounded-xl mx-2 mb-2 space-y-3">
      <div>
        <label className="text-[11px] font-medium text-text-muted block mb-1 uppercase tracking-wider">Category</label>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="w-full bg-surface-3 text-text-primary text-sm rounded-xl px-3 py-2 border border-border outline-none focus:border-accent"
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>{c.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-[11px] font-medium text-text-muted block mb-1 uppercase tracking-wider">Content</label>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          className="w-full bg-surface-3 text-text-primary text-sm rounded-xl px-3 py-2 border border-border outline-none focus:border-accent resize-none"
          placeholder="Memory content..."
        />
      </div>

      <div>
        <label className="text-[11px] font-medium text-text-muted block mb-1 uppercase tracking-wider">
          Importance: <span className="text-accent normal-case">{importance}</span>
        </label>
        <input
          type="range"
          min={1}
          max={10}
          value={importance}
          onChange={(e) => setImportance(Number(e.target.value))}
          className="w-full accent-accent"
        />
      </div>

      <div>
        <label className="text-[11px] font-medium text-text-muted block mb-1 uppercase tracking-wider">Tags (comma-separated)</label>
        <input
          value={tags}
          onChange={(e) => setTags(e.target.value)}
          className="w-full bg-surface-3 text-text-primary text-sm rounded-xl px-3 py-2 border border-border outline-none focus:border-accent"
          placeholder="analysis, python, visualization"
        />
      </div>

      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={!content.trim() || saving}
          className="flex-1 py-2 rounded-xl bg-purple text-white text-sm font-medium
            hover:opacity-90 transition-all disabled:opacity-50 shadow-sm"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2 rounded-xl glass text-text-muted text-sm hover:bg-surface-2 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
