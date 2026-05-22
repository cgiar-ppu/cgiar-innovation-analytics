/**
 * @file FleetDetailPanel.tsx
 * @module components/fleet
 *
 * Right-side detail panel for the Fleet page. Displays either:
 * - Agent details + message history when an agent is selected.
 * - Fleet overview + system health when no agent is selected.
 */

import { useState, useRef, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  User,
  Activity,
  Clock,
  Hash,
  ChevronDown,
  ChevronRight,
  Send,
  AlertCircle,
  CheckCircle,
  Loader2,
  Cpu,
  HardDrive,
  Play,
  Tag,
  FolderOpen,
  Zap,
} from 'lucide-react'
import { useFleetStore } from '../../stores/fleet'
import type { FleetAgent, FleetMessage, Fleet, SystemHealth, FleetRun } from '../../stores/fleet'
import { fleetApi } from '../../services/fleet'

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

const STATUS_VARIANT: Record<string, string> = {
  idle: 'bg-[var(--success)]/15 text-[var(--success)] border-[var(--success)]/30',
  queued: 'bg-[var(--warning)]/15 text-[var(--warning)] border-[var(--warning)]/30',
  running: 'bg-[var(--accent)]/15 text-[var(--accent)] border-[var(--accent)]/30',
  completed: 'bg-[var(--success)]/15 text-[var(--success)] border-[var(--success)]/30',
  error: 'bg-[var(--danger)]/15 text-[var(--danger)] border-[var(--danger)]/30',
  retired: 'bg-[var(--text-muted)]/15 text-[var(--text-muted)] border-[var(--text-muted)]/30',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border ${STATUS_VARIANT[status] || STATUS_VARIANT.idle}`}
    >
      {status === 'running' && <Loader2 className="w-3 h-3 animate-spin" />}
      {status === 'completed' && <CheckCircle className="w-3 h-3" />}
      {status === 'error' && <AlertCircle className="w-3 h-3" />}
      {status}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Agent detail view
// ---------------------------------------------------------------------------

function AgentDetail({
  agent,
  messages,
  onResume,
}: {
  agent: FleetAgent
  messages: FleetMessage[]
  onResume: (message: string) => void
}) {
  const [input, setInput] = useState('')
  const [resultExpanded, setResultExpanded] = useState(false)
  const [sending, setSending] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  const handleSend = useCallback(async () => {
    if (!input.trim() || sending) return
    setSending(true)
    try {
      onResume(input.trim())
      setInput('')
    } finally {
      setSending(false)
    }
  }, [input, sending, onResume])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const lastActive = agent.last_active
    ? new Date(agent.last_active * 1000).toLocaleTimeString()
    : 'Never'

  return (
    <div className="flex flex-col h-full">
      {/* Agent header */}
      <div className="p-4 border-b border-[var(--border)]">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-8 h-8 rounded-full bg-[var(--accent)]/10 flex items-center justify-center shrink-0">
              <User className="w-4 h-4 text-[var(--accent)]" />
            </div>
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[var(--text)] truncate">
                {agent.name}
              </h3>
              <p className="text-xs text-[var(--text-muted)] truncate">
                {agent.specialty || 'General Agent'}
              </p>
            </div>
          </div>
          <StatusBadge status={agent.status} />
        </div>

        {/* Meta info */}
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
          <div className="flex items-center gap-1.5 text-[var(--text-muted)]">
            <Hash className="w-3 h-3" />
            <span className="truncate">{agent.claude_session_id?.slice(0, 8) || 'N/A'}</span>
          </div>
          <div className="flex items-center gap-1.5 text-[var(--text-muted)]">
            <Activity className="w-3 h-3" />
            <span>{agent.turn_count} turns</span>
          </div>
          <div className="flex items-center gap-1.5 text-[var(--text-muted)]">
            <Clock className="w-3 h-3" />
            <span>{lastActive}</span>
          </div>
          <div className="flex items-center gap-1.5 text-[var(--text-muted)]">
            <Cpu className="w-3 h-3" />
            <span className="truncate">{agent.worker_node || 'local'}</span>
          </div>
        </div>
      </div>

      {/* Context summary */}
      {agent.context_summary && (
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <p className="text-xs font-medium text-[var(--text-muted)] mb-1">Context</p>
          <p className="text-xs text-[var(--text)] leading-relaxed">
            {agent.context_summary}
          </p>
        </div>
      )}

      {/* Last result (collapsible) */}
      {agent.result && (
        <div className="px-4 py-2 border-b border-[var(--border)]">
          <button
            onClick={() => setResultExpanded(!resultExpanded)}
            className="flex items-center gap-1 text-xs font-medium text-[var(--text-muted)] hover:text-[var(--text)] transition-colors w-full"
          >
            {resultExpanded ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronRight className="w-3 h-3" />
            )}
            Last Result
          </button>
          <AnimatePresence>
            {resultExpanded && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.2 }}
                className="overflow-hidden"
              >
                <pre className="mt-2 text-xs text-[var(--text)] bg-[var(--surface)] rounded-lg p-3 overflow-x-auto whitespace-pre-wrap max-h-40 overflow-y-auto">
                  {agent.result}
                </pre>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* Error message */}
      {agent.error_message && (
        <div className="px-4 py-2 border-b border-[var(--border)]">
          <div className="flex items-start gap-2 bg-[var(--danger)]/10 rounded-lg p-2">
            <AlertCircle className="w-3.5 h-3.5 text-[var(--danger)] shrink-0 mt-0.5" />
            <p className="text-xs text-[var(--danger)]">{agent.error_message}</p>
          </div>
        </div>
      )}

      {/* Message history */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-2">
        {messages.length === 0 && (
          <p className="text-xs text-[var(--text-muted)] text-center py-8">
            No messages yet
          </p>
        )}
        {messages.map((msg) => (
          <div
            key={msg.message_id}
            className={`text-xs rounded-lg p-2.5 ${
              msg.role === 'user'
                ? 'bg-[var(--accent)]/10 ml-4'
                : 'bg-[var(--surface)] mr-4'
            }`}
          >
            <div className="flex items-center justify-between mb-1">
              <span className="font-medium text-[var(--text-muted)] capitalize">
                {msg.role}
              </span>
              <span className="text-[var(--text-muted)]" style={{ fontSize: 10 }}>
                T{msg.turn_number}
              </span>
            </div>
            <p className="text-[var(--text)] leading-relaxed whitespace-pre-wrap">
              {msg.content.length > 500
                ? msg.content.slice(0, 500) + '...'
                : msg.content}
            </p>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Resume input */}
      <div className="p-3 border-t border-[var(--border)]">
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message to resume..."
            className="flex-1 text-xs bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] transition-colors"
            disabled={agent.status === 'retired'}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || sending || agent.status === 'retired'}
            className="p-2 rounded-lg bg-[var(--accent)] text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            {sending ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Send className="w-3.5 h-3.5" />
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Fleet overview (no agent selected)
// ---------------------------------------------------------------------------

function FleetOverview({
  fleet,
  health,
  runs,
}: {
  fleet: Fleet | null
  health: SystemHealth | null
  runs: FleetRun[]
}) {
  return (
    <div className="flex flex-col h-full overflow-y-auto">
      {/* Fleet info */}
      {fleet && (
        <div className="p-4 border-b border-[var(--border)]">
          <h3 className="text-sm font-semibold text-[var(--text)] mb-1">
            {fleet.name}
          </h3>
          {fleet.description && (
            <p className="text-xs text-[var(--text-muted)] mb-3 leading-relaxed">
              {fleet.description}
            </p>
          )}

          <div className="space-y-2 text-xs">
            {fleet.project_path && (
              <div className="flex items-center gap-2 text-[var(--text-muted)]">
                <FolderOpen className="w-3 h-3" />
                <span className="truncate">{fleet.project_path}</span>
              </div>
            )}
            {(fleet.tags?.length ?? 0) > 0 && (
              <div className="flex items-center gap-2">
                <Tag className="w-3 h-3 text-[var(--text-muted)]" />
                <div className="flex flex-wrap gap-1">
                  {fleet.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-1.5 py-0.5 rounded bg-[var(--accent)]/10 text-[var(--accent)] text-[10px] font-medium"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* System health */}
      {health && (
        <div className="p-4 border-b border-[var(--border)]">
          <h4 className="text-xs font-semibold text-[var(--text)] mb-3 flex items-center gap-1.5">
            <Activity className="w-3 h-3" />
            System Health
          </h4>

          {/* RAM bar */}
          <div className="mb-3">
            <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] mb-1">
              <span className="flex items-center gap-1">
                <HardDrive className="w-3 h-3" /> RAM
              </span>
              <span>
                {health.ram_available_gb.toFixed(1)} / {health.ram_total_gb.toFixed(1)} GB free
              </span>
            </div>
            <div className="h-2 bg-[var(--surface)] rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${health.ram_used_pct}%`,
                  backgroundColor:
                    health.ram_used_pct > 85
                      ? 'var(--danger)'
                      : health.ram_used_pct > 65
                        ? 'var(--warning)'
                        : 'var(--success)',
                }}
              />
            </div>
          </div>

          {/* CPU bar */}
          <div className="mb-3">
            <div className="flex items-center justify-between text-[10px] text-[var(--text-muted)] mb-1">
              <span className="flex items-center gap-1">
                <Cpu className="w-3 h-3" /> CPU
              </span>
              <span>{health.cpu_pct.toFixed(0)}%</span>
            </div>
            <div className="h-2 bg-[var(--surface)] rounded-full overflow-hidden">
              <div
                className="h-full rounded-full transition-all duration-500"
                style={{
                  width: `${health.cpu_pct}%`,
                  backgroundColor:
                    health.cpu_pct > 85
                      ? 'var(--danger)'
                      : health.cpu_pct > 65
                        ? 'var(--warning)'
                        : 'var(--accent)',
                }}
              />
            </div>
          </div>

          {/* Process stats */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-[var(--surface)] rounded-lg p-2 text-center">
              <p className="text-lg font-bold text-[var(--text)]">
                {health.active_agents}
              </p>
              <p className="text-[10px] text-[var(--text-muted)]">Active Agents</p>
            </div>
            <div className="bg-[var(--surface)] rounded-lg p-2 text-center">
              <p className="text-lg font-bold text-[var(--text)]">
                {health.claude_processes}
              </p>
              <p className="text-[10px] text-[var(--text-muted)]">Claude Procs</p>
            </div>
          </div>

          {health.can_spawn_more && (
            <p className="text-[10px] text-[var(--success)] mt-2 flex items-center gap-1">
              <Zap className="w-3 h-3" />
              Ready to spawn (recommended concurrency: {health.recommended_concurrency})
            </p>
          )}
        </div>
      )}

      {/* Recent runs */}
      <div className="p-4 flex-1">
        <h4 className="text-xs font-semibold text-[var(--text)] mb-3 flex items-center gap-1.5">
          <Play className="w-3 h-3" />
          Recent Runs
        </h4>

        {runs.length === 0 ? (
          <p className="text-xs text-[var(--text-muted)] text-center py-6">
            No runs yet
          </p>
        ) : (
          <div className="space-y-2">
            {runs.slice(0, 10).map((run) => (
              <div
                key={run.run_id}
                className="bg-[var(--surface)] rounded-lg p-2.5"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-[var(--text)]">
                    {run.run_type}
                  </span>
                  <StatusBadge status={run.status} />
                </div>
                {run.prompt && (
                  <p className="text-[10px] text-[var(--text-muted)] truncate">
                    {run.prompt}
                  </p>
                )}
                {run.progress_total > 0 && (
                  <div className="mt-1.5 h-1 bg-[var(--surface-2)] rounded-full overflow-hidden">
                    <div
                      className="h-full bg-[var(--accent)] rounded-full transition-all"
                      style={{
                        width: `${(run.progress_current / run.progress_total) * 100}%`,
                      }}
                    />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel component
// ---------------------------------------------------------------------------

export default function FleetDetailPanel() {
  const selectedAgentId = useFleetStore((s) => s.selectedAgentId)
  const agents = useFleetStore((s) => s.agents)
  const agentMessages = useFleetStore((s) => s.agentMessages)
  const fleets = useFleetStore((s) => s.fleets)
  const activeFleetId = useFleetStore((s) => s.activeFleetId)
  const health = useFleetStore((s) => s.health)
  const runs = useFleetStore((s) => s.runs)
  const setAgentMessages = useFleetStore((s) => s.setAgentMessages)
  const addAgentMessage = useFleetStore((s) => s.addAgentMessage)

  const selectedAgent = agents.find((a) => a.agent_id === selectedAgentId) || null
  const activeFleet = fleets.find((f) => f.fleet_id === activeFleetId) || null

  // Load agent messages when selection changes
  useEffect(() => {
    if (!selectedAgentId) {
      setAgentMessages([])
      return
    }
    let cancelled = false
    fleetApi
      .getAgentMessages(selectedAgentId)
      .then((data) => {
        if (!cancelled) setAgentMessages(data.messages)
      })
      .catch(() => {
        if (!cancelled) setAgentMessages([])
      })
    return () => {
      cancelled = true
    }
  }, [selectedAgentId, setAgentMessages])

  const handleResume = useCallback(
    async (message: string) => {
      if (!selectedAgentId) return
      // Optimistically add the user message
      const optimistic: FleetMessage = {
        message_id: Date.now(),
        agent_id: selectedAgentId,
        role: 'user',
        content: message,
        turn_number: agentMessages.length,
        created_at: Date.now() / 1000,
      }
      addAgentMessage(optimistic)

      try {
        await fleetApi.resumeAgent(selectedAgentId, message)
      } catch (err) {
        console.error('[Fleet] Failed to resume agent:', err)
      }
    },
    [selectedAgentId, agentMessages.length, addAgentMessage],
  )

  return (
    <div className="h-full glass border-l border-[var(--border)] flex flex-col">
      <AnimatePresence mode="wait">
        {selectedAgent ? (
          <motion.div
            key={`agent-${selectedAgent.agent_id}`}
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
            className="h-full flex flex-col"
          >
            <AgentDetail
              agent={selectedAgent}
              messages={agentMessages}
              onResume={handleResume}
            />
          </motion.div>
        ) : (
          <motion.div
            key="overview"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
            className="h-full"
          >
            <FleetOverview fleet={activeFleet} health={health} runs={runs} />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
