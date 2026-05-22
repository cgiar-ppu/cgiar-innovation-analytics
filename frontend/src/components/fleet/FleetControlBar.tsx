/**
 * @file FleetControlBar.tsx
 * @module components/fleet
 *
 * Top control bar for the Fleet page. Contains the fleet selector dropdown,
 * action buttons (Spawn, Broadcast), and system health indicators.
 */

import { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ChevronDown,
  Plus,
  Radio,
  Zap,
  Activity,
  Cpu,
  HardDrive,
  Users,
  Loader2,
} from 'lucide-react'
import { useFleetStore } from '../../stores/fleet'
import type { Fleet } from '../../stores/fleet'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FleetControlBarProps {
  onSpawnClick: () => void
  onBroadcastClick: () => void
  onNewFleetClick: () => void
}

// ---------------------------------------------------------------------------
// Fleet selector dropdown
// ---------------------------------------------------------------------------

function FleetSelector({
  fleets,
  activeFleetId,
  onSelect,
}: {
  fleets: Fleet[]
  activeFleetId: string | null
  onSelect: (fleetId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  const active = fleets.find((f) => f.fleet_id === activeFleetId)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2 px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors min-w-[180px]"
      >
        <Users className="w-4 h-4 text-[var(--accent)]" />
        <span className="flex-1 text-left truncate">
          {active?.name || 'Select a fleet'}
        </span>
        <ChevronDown
          className={`w-4 h-4 text-[var(--text-muted)] transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute z-50 top-full mt-1 left-0 min-w-[220px] max-h-60 overflow-y-auto glass-strong border border-[var(--border)] rounded-xl shadow-xl"
          >
            {fleets.length === 0 ? (
              <div className="px-3 py-4 text-xs text-[var(--text-muted)] text-center">
                No fleets created yet
              </div>
            ) : (
              fleets.map((fleet) => (
                <button
                  key={fleet.fleet_id}
                  onClick={() => {
                    onSelect(fleet.fleet_id)
                    setOpen(false)
                  }}
                  className={`w-full px-3 py-2 text-left text-sm hover:bg-[var(--surface-2)] transition-colors flex items-center gap-2 ${
                    fleet.fleet_id === activeFleetId
                      ? 'text-[var(--accent)] bg-[var(--accent)]/5'
                      : 'text-[var(--text)]'
                  }`}
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-medium truncate">{fleet.name}</p>
                    {fleet.description && (
                      <p className="text-xs text-[var(--text-muted)] truncate">
                        {fleet.description}
                      </p>
                    )}
                  </div>
                  <span className="text-[10px] text-[var(--text-muted)] shrink-0">
                    {fleet.status}
                  </span>
                </button>
              ))
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Health indicator mini bars
// ---------------------------------------------------------------------------

function HealthIndicators() {
  const health = useFleetStore((s) => s.health)

  if (!health) return null

  return (
    <div className="flex items-center gap-3">
      {/* RAM */}
      <div className="flex items-center gap-1.5" title={`RAM: ${health.ram_used_pct.toFixed(0)}%`}>
        <HardDrive className="w-3.5 h-3.5 text-[var(--text-muted)]" />
        <div className="w-16 h-1.5 bg-[var(--surface)] rounded-full overflow-hidden">
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

      {/* CPU */}
      <div className="flex items-center gap-1.5" title={`CPU: ${health.cpu_pct.toFixed(0)}%`}>
        <Cpu className="w-3.5 h-3.5 text-[var(--text-muted)]" />
        <div className="w-16 h-1.5 bg-[var(--surface)] rounded-full overflow-hidden">
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

      {/* Active agents count */}
      <div
        className="flex items-center gap-1 text-xs text-[var(--text-muted)]"
        title={`${health.active_agents} active, ${health.claude_processes} processes`}
      >
        <Activity className="w-3.5 h-3.5" />
        <span>{health.active_agents}</span>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main control bar
// ---------------------------------------------------------------------------

export default function FleetControlBar({
  onSpawnClick,
  onBroadcastClick,
  onNewFleetClick,
}: FleetControlBarProps) {
  const fleets = useFleetStore((s) => s.fleets)
  const activeFleetId = useFleetStore((s) => s.activeFleetId)
  const setActiveFleet = useFleetStore((s) => s.setActiveFleet)
  const isSpawning = useFleetStore((s) => s.isSpawning)
  const agents = useFleetStore((s) => s.agents)

  return (
    <div className="shrink-0 px-6 pt-6 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--border)]">
      {/* Left section: title + fleet selector */}
      <div className="flex items-center gap-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--text)]">Fleet</h1>
          <p className="text-sm text-[var(--text-muted)] mt-0.5">
            Manage persistent agent clusters
          </p>
        </div>

        <div className="hidden sm:block h-8 w-px bg-[var(--border)]" />

        <FleetSelector
          fleets={fleets}
          activeFleetId={activeFleetId}
          onSelect={setActiveFleet}
        />

        <button
          onClick={onNewFleetClick}
          className="p-1.5 rounded-lg border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-colors"
          title="Create new fleet"
        >
          <Plus className="w-4 h-4" />
        </button>
      </div>

      {/* Right section: actions + health */}
      <div className="flex items-center gap-3 flex-wrap">
        <HealthIndicators />

        {/* Agent count badge */}
        {agents.length > 0 && (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/20">
            {agents.length} agent{agents.length !== 1 ? 's' : ''}
          </span>
        )}

        <div className="hidden sm:block h-6 w-px bg-[var(--border)]" />

        {/* Broadcast button */}
        <button
          onClick={onBroadcastClick}
          disabled={!activeFleetId || agents.length === 0}
          className="flex items-center gap-2 px-3 py-1.5 border border-[var(--border)] rounded-lg text-sm text-[var(--text)] hover:bg-[var(--surface)] disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        >
          <Radio className="w-4 h-4" />
          Broadcast
        </button>

        {/* Spawn button */}
        <button
          onClick={onSpawnClick}
          disabled={!activeFleetId || isSpawning}
          className="flex items-center gap-2 px-4 py-1.5 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
        >
          {isSpawning ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Zap className="w-4 h-4" />
          )}
          {isSpawning ? 'Spawning...' : 'Spawn Agents'}
        </button>
      </div>
    </div>
  )
}
