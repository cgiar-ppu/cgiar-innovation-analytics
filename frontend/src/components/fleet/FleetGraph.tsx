/**
 * @file FleetGraph.tsx
 * @module components/fleet
 *
 * SVG-based node graph visualization for a fleet. Renders agents in a
 * radial layout around a central hub node (the fleet project). Connecting
 * lines link each agent to the hub, and dashed lines show mediation
 * connections between agents.
 */

import { useMemo, useRef, useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import type { FleetAgent } from '../../stores/fleet'
import AgentNode from './AgentNode'

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface FleetGraphProps {
  agents: FleetAgent[]
  fleetName: string
  selectedAgentId: string | null
  onSelectAgent: (agentId: string | null) => void
}

// ---------------------------------------------------------------------------
// Layout helpers
// ---------------------------------------------------------------------------

/** Calculates radial positions for agents around a center point. */
function calculateRadialLayout(
  agentCount: number,
  centerX: number,
  centerY: number,
  radius: number,
): Array<{ x: number; y: number }> {
  if (agentCount === 0) return []
  // Offset so first node is at the top
  const angleOffset = -Math.PI / 2
  return Array.from({ length: agentCount }, (_, i) => {
    const angle = angleOffset + (2 * Math.PI * i) / agentCount
    return {
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    }
  })
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FleetGraph({
  agents,
  fleetName,
  selectedAgentId,
  onSelectAgent,
}: FleetGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 600, height: 500 })

  // Measure container
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 0 && height > 0) {
          setDimensions({ width, height })
        }
      }
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const centerX = dimensions.width / 2
  const centerY = dimensions.height / 2

  // Determine the ring radius based on container size and agent count
  const ringRadius = useMemo(() => {
    const minDim = Math.min(dimensions.width, dimensions.height)
    const base = minDim * 0.35
    // Scale down slightly when there are many agents so labels don't clip
    return Math.max(100, Math.min(base, 260))
  }, [dimensions])

  const positions = useMemo(
    () => calculateRadialLayout(agents.length, centerX, centerY, ringRadius),
    [agents.length, centerX, centerY, ringRadius],
  )

  // Count agents by status for the hub display
  const statusCounts = useMemo(() => {
    const counts = { running: 0, idle: 0, error: 0, total: agents.length }
    for (const a of agents) {
      if (a.status === 'running') counts.running++
      else if (a.status === 'error') counts.error++
      else if (a.status === 'idle') counts.idle++
    }
    return counts
  }, [agents])

  const handleBackgroundClick = () => {
    onSelectAgent(null)
  }

  return (
    <div
      ref={containerRef}
      className="w-full h-full relative overflow-hidden"
      style={{ minHeight: 300 }}
    >
      <svg
        width={dimensions.width}
        height={dimensions.height}
        className="absolute inset-0"
        onClick={handleBackgroundClick}
      >
        <defs>
          {/* Gradient for connection lines */}
          <linearGradient id="fleet-line-grad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.1} />
            <stop offset="50%" stopColor="var(--accent)" stopOpacity={0.3} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.1} />
          </linearGradient>

          {/* Glow filter for hub */}
          <filter id="fleet-hub-glow" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="6" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Connection lines from agents to hub */}
        {positions.map((pos, i) => {
          const agent = agents[i]
          if (!agent) return null
          return (
            <motion.line
              key={`line-${agent.agent_id}`}
              x1={centerX}
              y1={centerY}
              x2={pos.x}
              y2={pos.y}
              stroke="url(#fleet-line-grad)"
              strokeWidth={
                selectedAgentId === agent.agent_id ? 2 : 1
              }
              initial={{ pathLength: 0, opacity: 0 }}
              animate={{ pathLength: 1, opacity: 1 }}
              transition={{ duration: 0.6, delay: i * 0.05 }}
            />
          )
        })}

        {/* Mediation connections (dashed lines between agents that share a run) */}
        {agents.length > 1 &&
          agents.map((agent, i) => {
            // Show mediation connections for agents currently in a running state
            // connected to adjacent agents also running -- a simple heuristic
            if (agent.status !== 'running') return null
            const nextIdx = (i + 1) % agents.length
            const nextAgent = agents[nextIdx]
            const posI = positions[i]
            const posNext = positions[nextIdx]
            if (!nextAgent || nextAgent.status !== 'running' || !posI || !posNext) return null
            return (
              <motion.line
                key={`mediate-${agent.agent_id}-${nextAgent.agent_id}`}
                x1={posI.x}
                y1={posI.y}
                x2={posNext.x}
                y2={posNext.y}
                stroke="var(--purple)"
                strokeWidth={1}
                strokeDasharray="6 4"
                opacity={0.4}
                initial={{ opacity: 0 }}
                animate={{ opacity: 0.4 }}
                transition={{ duration: 0.4 }}
              />
            )
          })}

        {/* Central hub node */}
        <g onClick={(e) => e.stopPropagation()}>
          {/* Hub outer rotating ring — uses native SVG animateTransform */}
          <circle
            cx={centerX}
            cy={centerY}
            r={54}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={1}
            strokeDasharray="3 3"
            opacity={0.3}
          >
            <animateTransform
              attributeName="transform"
              type="rotate"
              from={`0 ${centerX} ${centerY}`}
              to={`360 ${centerX} ${centerY}`}
              dur="30s"
              repeatCount="indefinite"
            />
          </circle>

          {/* Hub background */}
          <circle
            cx={centerX}
            cy={centerY}
            r={48}
            fill="var(--surface-2)"
            stroke="var(--accent)"
            strokeWidth={2}
            opacity={0.9}
            filter="url(#fleet-hub-glow)"
          />

          {/* Hub inner accent */}
          <circle
            cx={centerX}
            cy={centerY}
            r={46}
            fill="var(--accent)"
            fillOpacity={0.08}
          />

          {/* Hub network icon — pure SVG (3 nodes + connecting lines) */}
          <g
            style={{ pointerEvents: 'none' }}
            stroke="var(--accent)"
            fill="var(--accent)"
          >
            {/* Center node */}
            <circle cx={centerX} cy={centerY - 12} r={2.5} />
            {/* Bottom-left node */}
            <circle cx={centerX - 8} cy={centerY - 2} r={2} />
            {/* Bottom-right node */}
            <circle cx={centerX + 8} cy={centerY - 2} r={2} />
            {/* Lines connecting nodes */}
            <line
              x1={centerX} y1={centerY - 12}
              x2={centerX - 8} y2={centerY - 2}
              strokeWidth={1.2} fill="none"
            />
            <line
              x1={centerX} y1={centerY - 12}
              x2={centerX + 8} y2={centerY - 2}
              strokeWidth={1.2} fill="none"
            />
            <line
              x1={centerX - 8} y1={centerY - 2}
              x2={centerX + 8} y2={centerY - 2}
              strokeWidth={1.2} fill="none"
            />
          </g>

          {/* Fleet name */}
          <text
            x={centerX}
            y={centerY + 8}
            textAnchor="middle"
            dominantBaseline="central"
            fill="var(--text)"
            fontSize={10}
            fontWeight={700}
            style={{ pointerEvents: 'none', userSelect: 'none' }}
          >
            {fleetName.length > 16 ? fleetName.slice(0, 14) + '...' : fleetName}
          </text>

          {/* Agent count */}
          <text
            x={centerX}
            y={centerY + 22}
            textAnchor="middle"
            dominantBaseline="central"
            fill="var(--text-muted)"
            fontSize={9}
            style={{ pointerEvents: 'none', userSelect: 'none' }}
          >
            {statusCounts.total} agent{statusCounts.total !== 1 ? 's' : ''}
            {statusCounts.running > 0 && ` (${statusCounts.running} active)`}
          </text>
        </g>

        {/* Agent nodes */}
        <AnimatePresence>
          {agents.map((agent, i) => {
            const pos = positions[i]
            if (!pos) return null
            return (
            <AgentNode
              key={agent.agent_id}
              agent={agent}
              x={pos.x}
              y={pos.y}
              isSelected={selectedAgentId === agent.agent_id}
              onSelect={(id) => {
                // stopPropagation equivalent: prevent the background click handler
                onSelectAgent(id)
              }}
            />
            )
          })}
        </AnimatePresence>
      </svg>

      {/* Empty state */}
      {agents.length === 0 && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="text-center mt-32">
            <svg
              width={64}
              height={64}
              viewBox="0 0 64 64"
              className="mx-auto mb-4"
              style={{ opacity: 0.35 }}
            >
              <circle cx={32} cy={20} r={5} fill="var(--accent)" />
              <circle cx={16} cy={44} r={4} fill="var(--accent)" />
              <circle cx={48} cy={44} r={4} fill="var(--accent)" />
              <line x1={32} y1={20} x2={16} y2={44} stroke="var(--accent)" strokeWidth={1.5} />
              <line x1={32} y1={20} x2={48} y2={44} stroke="var(--accent)" strokeWidth={1.5} />
              <line x1={16} y1={44} x2={48} y2={44} stroke="var(--accent)" strokeWidth={1.5} strokeDasharray="4 3" />
            </svg>
            <p className="text-sm text-[var(--text-muted)]" style={{ opacity: 0.6 }}>
              No agents in this fleet yet
            </p>
            <p className="text-xs text-[var(--text-muted)] mt-1.5" style={{ opacity: 0.45 }}>
              Spawn agents to see them appear in the graph
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
