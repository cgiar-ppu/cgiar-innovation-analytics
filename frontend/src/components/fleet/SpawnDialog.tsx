/**
 * @file SpawnDialog.tsx
 * @module components/fleet
 *
 * Modal dialog for spawning new agents into a fleet. Allows configuring
 * agent name patterns, specialties, system prompts, concurrency, and an
 * initial task. Includes a live preview of agents that will be created.
 */

import { useState, useMemo, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  X,
  Zap,
  Eye,
  Plus,
  Trash2,
  Loader2,
} from 'lucide-react'
import { useFleetStore } from '../../stores/fleet'
import { fleetApi } from '../../services/fleet'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentTemplate {
  name: string
  specialty: string
  system_prompt: string
}

interface SpawnDialogProps {
  onClose: () => void
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

const DEFAULT_TEMPLATE: AgentTemplate = {
  name: 'Agent',
  specialty: 'General',
  system_prompt: 'You are a helpful assistant working as part of a team.',
}

const SPECIALTY_PRESETS = [
  'Frontend',
  'Backend',
  'Database',
  'Testing',
  'DevOps',
  'Security',
  'Documentation',
  'Code Review',
  'Research',
  'Data Analysis',
]

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function SpawnDialog({ onClose }: SpawnDialogProps) {
  const activeFleetId = useFleetStore((s) => s.activeFleetId)
  const setSpawning = useFleetStore((s) => s.setSpawning)

  const [templates, setTemplates] = useState<AgentTemplate[]>([
    { ...DEFAULT_TEMPLATE },
  ])
  const [agentCount, setAgentCount] = useState(3)
  const [concurrency, setConcurrency] = useState(3)
  const [initialTask, setInitialTask] = useState('')
  const [useTemplatePerAgent, setUseTemplatePerAgent] = useState(false)
  const [showPreview, setShowPreview] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState('')

  // Generate preview agents
  const previewAgents = useMemo(() => {
    if (useTemplatePerAgent) {
      return templates.map((t, i) => ({
        name: t.name || `Agent-${i + 1}`,
        specialty: t.specialty,
        system_prompt: t.system_prompt,
      }))
    }
    const base = templates[0] || DEFAULT_TEMPLATE
    return Array.from({ length: agentCount }, (_, i) => ({
      name: `${base.name}-${i + 1}`,
      specialty: base.specialty,
      system_prompt: base.system_prompt,
    }))
  }, [templates, agentCount, useTemplatePerAgent])

  const updateTemplate = useCallback(
    (index: number, field: keyof AgentTemplate, value: string) => {
      setTemplates((prev) =>
        prev.map((t, i) => (i === index ? { ...t, [field]: value } : t)),
      )
    },
    [],
  )

  const addTemplate = () => {
    setTemplates((prev) => [
      ...prev,
      {
        ...DEFAULT_TEMPLATE,
        name: `Agent-${prev.length + 1}`,
        specialty: SPECIALTY_PRESETS[prev.length % SPECIALTY_PRESETS.length] || 'General',
      },
    ])
  }

  const removeTemplate = (index: number) => {
    if (templates.length <= 1) return
    setTemplates((prev) => prev.filter((_, i) => i !== index))
  }

  const handleSpawn = async () => {
    if (!activeFleetId) return
    setError('')
    setIsSubmitting(true)
    setSpawning(true)

    try {
      await fleetApi.spawnAgents(activeFleetId, {
        agents: previewAgents,
        concurrency,
        initial_task: initialTask || undefined,
      })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to spawn agents')
      setSpawning(false)
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Dialog */}
      <motion.div
        className="relative glass-strong border border-[var(--border)] rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-hidden flex flex-col"
        initial={{ scale: 0.95, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95, y: 20 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-[var(--border)]">
          <div>
            <h2 className="text-lg font-bold text-[var(--text)]">Spawn Agents</h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Create new agent instances in the fleet
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Mode toggle */}
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-sm text-[var(--text)] cursor-pointer">
              <input
                type="checkbox"
                checked={useTemplatePerAgent}
                onChange={(e) => setUseTemplatePerAgent(e.target.checked)}
                className="accent-[var(--accent)]"
              />
              Define each agent individually
            </label>
          </div>

          {/* Agent count (only when using single template) */}
          {!useTemplatePerAgent && (
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">
                Number of Agents
              </label>
              <input
                type="number"
                min={1}
                max={50}
                value={agentCount}
                onChange={(e) => setAgentCount(Math.max(1, Math.min(50, parseInt(e.target.value) || 1)))}
                className="w-24 text-sm bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-1.5 text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
              />
            </div>
          )}

          {/* Agent templates */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-[var(--text-muted)]">
                {useTemplatePerAgent ? 'Agent Definitions' : 'Agent Template'}
              </label>
              {useTemplatePerAgent && (
                <button
                  onClick={addTemplate}
                  className="flex items-center gap-1 text-xs text-[var(--accent)] hover:underline"
                >
                  <Plus className="w-3 h-3" /> Add Agent
                </button>
              )}
            </div>

            {templates.map((tmpl, idx) => (
              <div
                key={idx}
                className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-3 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-[var(--text)]">
                    {useTemplatePerAgent ? `Agent ${idx + 1}` : 'Template'}
                  </span>
                  {useTemplatePerAgent && templates.length > 1 && (
                    <button
                      onClick={() => removeTemplate(idx)}
                      className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--danger)] transition-colors"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-[10px] text-[var(--text-muted)] block mb-0.5">
                      Name{!useTemplatePerAgent && ' pattern'}
                    </label>
                    <input
                      type="text"
                      value={tmpl.name}
                      onChange={(e) => updateTemplate(idx, 'name', e.target.value)}
                      placeholder="Agent"
                      className="w-full text-xs bg-[var(--bg)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
                    />
                  </div>
                  <div>
                    <label className="text-[10px] text-[var(--text-muted)] block mb-0.5">
                      Specialty
                    </label>
                    <select
                      value={
                        SPECIALTY_PRESETS.includes(tmpl.specialty) ? tmpl.specialty : '__custom'
                      }
                      onChange={(e) => {
                        if (e.target.value !== '__custom') {
                          updateTemplate(idx, 'specialty', e.target.value)
                        }
                      }}
                      className="w-full text-xs bg-[var(--bg)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-[var(--text)] focus:outline-none focus:border-[var(--accent)]"
                    >
                      {SPECIALTY_PRESETS.map((s) => (
                        <option key={s} value={s}>
                          {s}
                        </option>
                      ))}
                      <option value="__custom">Custom...</option>
                    </select>
                  </div>
                </div>

                <div>
                  <label className="text-[10px] text-[var(--text-muted)] block mb-0.5">
                    System Prompt
                  </label>
                  <textarea
                    value={tmpl.system_prompt}
                    onChange={(e) => updateTemplate(idx, 'system_prompt', e.target.value)}
                    rows={2}
                    className="w-full text-xs bg-[var(--bg)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-[var(--text)] focus:outline-none focus:border-[var(--accent)] resize-none"
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Concurrency */}
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">
              Concurrency
            </label>
            <div className="flex items-center gap-2">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  onClick={() => setConcurrency(n)}
                  className={`w-9 h-9 rounded-lg text-sm font-medium transition-all ${
                    concurrency === n
                      ? 'bg-[var(--accent)] text-white'
                      : 'bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:text-[var(--text)]'
                  }`}
                >
                  {n}
                </button>
              ))}
              <span className="text-xs text-[var(--text-muted)] ml-1">
                parallel agents
              </span>
            </div>
          </div>

          {/* Initial task */}
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">
              Initial Task (optional)
            </label>
            <textarea
              value={initialTask}
              onChange={(e) => setInitialTask(e.target.value)}
              rows={3}
              placeholder="Enter a task for all agents to work on after spawning..."
              className="w-full text-xs bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] resize-none"
            />
          </div>

          {/* Preview */}
          <div>
            <button
              onClick={() => setShowPreview(!showPreview)}
              className="flex items-center gap-1.5 text-xs font-medium text-[var(--accent)] hover:underline mb-2"
            >
              <Eye className="w-3.5 h-3.5" />
              {showPreview ? 'Hide' : 'Show'} Preview ({previewAgents.length} agent
              {previewAgents.length !== 1 ? 's' : ''})
            </button>

            {showPreview && (
              <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-3 max-h-40 overflow-y-auto">
                <div className="space-y-1.5">
                  {previewAgents.map((a, i) => (
                    <div
                      key={i}
                      className="flex items-center justify-between text-xs"
                    >
                      <span className="text-[var(--text)] font-medium">
                        {a.name}
                      </span>
                      <span className="text-[var(--text-muted)]">
                        {a.specialty}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/20 rounded-lg px-3 py-2 text-xs text-[var(--danger)]">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-5 border-t border-[var(--border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSpawn}
            disabled={isSubmitting || !activeFleetId || previewAgents.length === 0}
            className="flex items-center gap-2 px-5 py-2 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
          >
            {isSubmitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Zap className="w-4 h-4" />
            )}
            Spawn {previewAgents.length} Agent{previewAgents.length !== 1 ? 's' : ''}
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}
