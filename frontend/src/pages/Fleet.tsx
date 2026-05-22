/**
 * @file Fleet.tsx
 * @module pages
 *
 * Main Fleet page. Visualizes and manages persistent Claude Code agent
 * clusters. Layout:
 *
 * - Top: FleetControlBar with fleet selector, spawn/broadcast buttons, health
 * - Center-left: FleetGraph SVG visualization (radial node layout)
 * - Center-right: FleetDetailPanel (agent details or fleet overview)
 *
 * Real-time updates are received over WebSocket via useFleetConnection.
 * The page fetches initial state from REST endpoints on mount.
 */

import { useEffect, useState, useCallback } from 'react'
import { AnimatePresence } from 'framer-motion'
import { Loader2, AlertTriangle, RefreshCw } from 'lucide-react'
import { useFleetStore } from '../stores/fleet'
import { fleetApi } from '../services/fleet'
import { useFleetConnection } from '../hooks/useFleetConnection'
import FleetControlBar from '../components/fleet/FleetControlBar'
import FleetGraph from '../components/fleet/FleetGraph'
import FleetDetailPanel from '../components/fleet/FleetDetailPanel'
import SpawnDialog from '../components/fleet/SpawnDialog'

// ---------------------------------------------------------------------------
// Broadcast dialog (inline, lightweight)
// ---------------------------------------------------------------------------

import { motion } from 'framer-motion'
import { X, Radio, Loader2 as Loader2Icon } from 'lucide-react'

function BroadcastDialog({ onClose }: { onClose: () => void }) {
  const activeFleetId = useFleetStore((s) => s.activeFleetId)
  const agents = useFleetStore((s) => s.agents)
  const [message, setMessage] = useState('')
  const [concurrency, setConcurrency] = useState(3)
  const [filterRunning, setFilterRunning] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const handleSend = async () => {
    if (!activeFleetId || !message.trim()) return
    setSending(true)
    setError('')
    try {
      await fleetApi.broadcastMessage(activeFleetId, {
        message: message.trim(),
        concurrency,
        filter_status: filterRunning ? ['idle', 'completed'] : undefined,
      })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to broadcast')
    } finally {
      setSending(false)
    }
  }

  const targetCount = filterRunning
    ? agents.filter((a) => a.status === 'idle' || a.status === 'completed').length
    : agents.length

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <motion.div
        className="relative glass-strong border border-[var(--border)] rounded-2xl shadow-2xl w-full max-w-md overflow-hidden"
        initial={{ scale: 0.95, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95, y: 20 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
      >
        <div className="flex items-center justify-between p-5 border-b border-[var(--border)]">
          <div>
            <h2 className="text-lg font-bold text-[var(--text)]">Broadcast Message</h2>
            <p className="text-xs text-[var(--text-muted)] mt-0.5">
              Send a message to {targetCount} agent{targetCount !== 1 ? 's' : ''}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">
              Message
            </label>
            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              rows={4}
              placeholder="Enter a message to send to all agents..."
              className="w-full text-sm bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] resize-none"
              autoFocus
            />
          </div>

          <div className="flex items-center gap-4">
            <div>
              <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">
                Concurrency
              </label>
              <div className="flex items-center gap-1">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button
                    key={n}
                    onClick={() => setConcurrency(n)}
                    className={`w-7 h-7 rounded text-xs font-medium transition-all ${
                      concurrency === n
                        ? 'bg-[var(--accent)] text-white'
                        : 'bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)]'
                    }`}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </div>

            <label className="flex items-center gap-2 text-xs text-[var(--text)] cursor-pointer mt-4">
              <input
                type="checkbox"
                checked={filterRunning}
                onChange={(e) => setFilterRunning(e.target.checked)}
                className="accent-[var(--accent)]"
              />
              Skip running agents
            </label>
          </div>

          {error && (
            <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/20 rounded-lg px-3 py-2 text-xs text-[var(--danger)]">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-5 border-t border-[var(--border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSend}
            disabled={sending || !message.trim()}
            className="flex items-center gap-2 px-5 py-2 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
          >
            {sending ? (
              <Loader2Icon className="w-4 h-4 animate-spin" />
            ) : (
              <Radio className="w-4 h-4" />
            )}
            Broadcast
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// New Fleet dialog (inline, lightweight)
// ---------------------------------------------------------------------------

function NewFleetDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [projectPath, setProjectPath] = useState('')
  const [tags, setTags] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const handleCreate = async () => {
    if (!name.trim()) return
    setCreating(true)
    setError('')
    try {
      await fleetApi.createFleet({
        name: name.trim(),
        description: description.trim() || undefined,
        project_path: projectPath.trim() || undefined,
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
      })
      onCreated()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create fleet')
    } finally {
      setCreating(false)
    }
  }

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <motion.div
        className="relative glass-strong border border-[var(--border)] rounded-2xl shadow-2xl w-full max-w-md overflow-hidden"
        initial={{ scale: 0.95, y: 20 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.95, y: 20 }}
        transition={{ type: 'spring', damping: 25, stiffness: 300 }}
      >
        <div className="flex items-center justify-between p-5 border-b border-[var(--border)]">
          <h2 className="text-lg font-bold text-[var(--text)]">New Fleet</h2>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--surface)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-5 space-y-3">
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My Fleet"
              className="w-full text-sm bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">Description</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="What this fleet is for..."
              className="w-full text-sm bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)] resize-none"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">Project Path</label>
            <input
              type="text"
              value={projectPath}
              onChange={(e) => setProjectPath(e.target.value)}
              placeholder="/path/to/project"
              className="w-full text-sm bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          <div>
            <label className="text-xs font-medium text-[var(--text-muted)] block mb-1">Tags (comma-separated)</label>
            <input
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="frontend, refactor"
              className="w-full text-sm bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-2 text-[var(--text)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--accent)]"
            />
          </div>
          {error && (
            <div className="bg-[var(--danger)]/10 border border-[var(--danger)]/20 rounded-lg px-3 py-2 text-xs text-[var(--danger)]">
              {error}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-3 p-5 border-t border-[var(--border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            className="flex items-center gap-2 px-5 py-2 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
          >
            {creating && <Loader2 className="w-4 h-4 animate-spin" />}
            Create Fleet
          </button>
        </div>
      </motion.div>
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Fleet() {
  const fleets = useFleetStore((s) => s.fleets)
  const activeFleetId = useFleetStore((s) => s.activeFleetId)
  const agents = useFleetStore((s) => s.agents)
  const selectedAgentId = useFleetStore((s) => s.selectedAgentId)
  const isLoading = useFleetStore((s) => s.isLoading)
  const setFleets = useFleetStore((s) => s.setFleets)
  const setActiveFleet = useFleetStore((s) => s.setActiveFleet)
  const setAgents = useFleetStore((s) => s.setAgents)
  const setRuns = useFleetStore((s) => s.setRuns)
  const setHealth = useFleetStore((s) => s.setHealth)
  const setLoading = useFleetStore((s) => s.setLoading)
  const setSelectedAgent = useFleetStore((s) => s.setSelectedAgent)

  const [showSpawnDialog, setShowSpawnDialog] = useState(false)
  const [showBroadcastDialog, setShowBroadcastDialog] = useState(false)
  const [showNewFleetDialog, setShowNewFleetDialog] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // WebSocket connection for real-time updates
  const { connected } = useFleetConnection({
    fleetId: activeFleetId,
    enabled: !!activeFleetId,
  })

  // Fetch fleets on mount
  const fetchFleets = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fleetApi.listFleets()
      setFleets(data.fleets)

      // Auto-select the first fleet if none is active
      const firstFleet = data.fleets[0]
      if (!activeFleetId && firstFleet) {
        setActiveFleet(firstFleet.fleet_id)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load fleets')
    } finally {
      setLoading(false)
    }
  }, [activeFleetId, setFleets, setActiveFleet, setLoading])

  useEffect(() => {
    fetchFleets()
  }, [fetchFleets])

  // Fetch fleet details when active fleet changes
  useEffect(() => {
    if (!activeFleetId) return
    let cancelled = false

    const fetchDetail = async () => {
      try {
        const [detail, healthData] = await Promise.all([
          fleetApi.getFleet(activeFleetId),
          fleetApi.getHealth().catch(() => null),
        ])
        if (cancelled) return
        setAgents(detail.agents || [])
        setRuns(detail.runs || [])
        if (healthData) setHealth(healthData)
      } catch {
        // Non-critical: WebSocket will provide state
      }
    }

    fetchDetail()
    return () => {
      cancelled = true
    }
  }, [activeFleetId, setAgents, setRuns, setHealth])

  // Periodically refresh health
  useEffect(() => {
    if (!activeFleetId) return
    const interval = setInterval(async () => {
      try {
        const healthData = await fleetApi.getHealth()
        setHealth(healthData)
      } catch {
        // Ignore
      }
    }, 15_000)
    return () => clearInterval(interval)
  }, [activeFleetId, setHealth])

  const activeFleet = fleets.find((f) => f.fleet_id === activeFleetId)

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Control bar */}
      <FleetControlBar
        onSpawnClick={() => setShowSpawnDialog(true)}
        onBroadcastClick={() => setShowBroadcastDialog(true)}
        onNewFleetClick={() => setShowNewFleetDialog(true)}
      />

      {/* Connection status badge */}
      {activeFleetId && (
        <div className="shrink-0 px-6 py-1.5 flex items-center gap-2 text-xs text-[var(--text-muted)]">
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              connected ? 'bg-[var(--success)]' : 'bg-[var(--warning)]'
            }`}
          />
          {connected ? 'Live' : 'Connecting...'}
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="shrink-0 mx-6 mt-2 flex items-center gap-3 bg-[var(--danger)]/10 border border-[var(--danger)]/20 text-[var(--danger)] rounded-xl px-4 py-3">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span className="text-xs flex-1">{error}</span>
          <button
            onClick={fetchFleets}
            className="flex items-center gap-1 text-xs font-medium hover:underline"
          >
            <RefreshCw className="w-3 h-3" />
            Retry
          </button>
        </div>
      )}

      {/* Main content */}
      {isLoading ? (
        <div className="flex-1 flex items-center justify-center">
          <Loader2 className="w-8 h-8 text-[var(--accent)] animate-spin" />
        </div>
      ) : (
        <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-5 gap-0">
          {/* Graph area (3/5) */}
          <div className="lg:col-span-3 flex flex-col overflow-hidden">
            <FleetGraph
              agents={agents}
              fleetName={activeFleet?.name || 'Fleet'}
              selectedAgentId={selectedAgentId}
              onSelectAgent={setSelectedAgent}
            />
          </div>

          {/* Detail panel (2/5) */}
          <div className="lg:col-span-2 overflow-hidden">
            <FleetDetailPanel />
          </div>
        </div>
      )}

      {/* Dialogs */}
      <AnimatePresence>
        {showSpawnDialog && (
          <SpawnDialog onClose={() => setShowSpawnDialog(false)} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showBroadcastDialog && (
          <BroadcastDialog onClose={() => setShowBroadcastDialog(false)} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {showNewFleetDialog && (
          <NewFleetDialog
            onClose={() => setShowNewFleetDialog(false)}
            onCreated={fetchFleets}
          />
        )}
      </AnimatePresence>
    </div>
  )
}
