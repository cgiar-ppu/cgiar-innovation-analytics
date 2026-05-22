/**
 * @file AgentNode.tsx
 * @module components/fleet
 *
 * Individual agent node rendered as an SVG group within the fleet graph.
 * Displays a status-coloured circle with the agent name, a pulsing
 * animation when running, and an expanded tooltip on hover.
 */

import { useState } from 'react'
import { motion } from 'framer-motion'
import type { FleetAgent, AgentStatus } from '../../stores/fleet'

// ---------------------------------------------------------------------------
// Status colour mapping (CSS variable names)
// ---------------------------------------------------------------------------

const STATUS_COLORS: Record<AgentStatus, string> = {
  idle: 'var(--success)',
  queued: 'var(--warning)',
  running: 'var(--accent)',
  completed: 'var(--success)',
  error: 'var(--danger)',
  retired: 'var(--text-muted)',
}

const STATUS_LABELS: Record<AgentStatus, string> = {
  idle: 'Idle',
  queued: 'Queued',
  running: 'Running',
  completed: 'Completed',
  error: 'Error',
  retired: 'Retired',
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface AgentNodeProps {
  agent: FleetAgent
  x: number
  y: number
  isSelected: boolean
  onSelect: (agentId: string) => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function AgentNode({ agent, x, y, isSelected, onSelect }: AgentNodeProps) {
  const [isHovered, setIsHovered] = useState(false)
  const color = STATUS_COLORS[agent.status]
  const isRunning = agent.status === 'running'

  const radius = isSelected ? 28 : 24

  return (
    <motion.g
      initial={{ opacity: 0, scale: 0 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      style={{ cursor: 'pointer' }}
      onClick={(e) => {
        e.stopPropagation()
        onSelect(agent.agent_id)
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {/* Pulse ring when running */}
      {isRunning && (
        <>
          <motion.circle
            cx={x}
            cy={y}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={2}
            initial={{ r: radius, opacity: 0.6 }}
            animate={{ r: radius + 18, opacity: 0 }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'easeOut' }}
          />
          <motion.circle
            cx={x}
            cy={y}
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={1.5}
            initial={{ r: radius, opacity: 0.4 }}
            animate={{ r: radius + 12, opacity: 0 }}
            transition={{ duration: 1.5, repeat: Infinity, ease: 'easeOut', delay: 0.5 }}
          />
        </>
      )}

      {/* Selection ring */}
      {isSelected && (
        <motion.circle
          cx={x}
          cy={y}
          r={radius + 5}
          fill="none"
          stroke={color}
          strokeWidth={2}
          strokeDasharray="4 3"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.2 }}
        />
      )}

      {/* Outer glow */}
      <circle
        cx={x}
        cy={y}
        r={radius + 1}
        fill="none"
        stroke={color}
        strokeWidth={isHovered ? 2.5 : 1.5}
        opacity={isHovered ? 0.8 : 0.4}
      />

      {/* Main circle */}
      <motion.circle
        cx={x}
        cy={y}
        r={radius}
        fill={color}
        fillOpacity={0.15}
        stroke={color}
        strokeWidth={isSelected ? 2.5 : 2}
        animate={{
          fillOpacity: isHovered ? 0.25 : 0.15,
          r: radius,
        }}
        transition={{ duration: 0.2 }}
      />

      {/* Inner dot (status indicator) */}
      <circle cx={x} cy={y} r={5} fill={color} opacity={0.9} />

      {/* Agent name label */}
      <text
        x={x}
        y={y + radius + 16}
        textAnchor="middle"
        fill="var(--text)"
        fontSize={11}
        fontWeight={isSelected ? 600 : 500}
        style={{ pointerEvents: 'none', userSelect: 'none' }}
      >
        {agent.name.length > 14 ? agent.name.slice(0, 12) + '...' : agent.name}
      </text>

      {/* Status label */}
      <text
        x={x}
        y={y + radius + 30}
        textAnchor="middle"
        fill={color}
        fontSize={9}
        fontWeight={500}
        style={{ pointerEvents: 'none', userSelect: 'none' }}
      >
        {STATUS_LABELS[agent.status]}
      </text>

      {/* Hover tooltip */}
      {isHovered && (
        <motion.g
          initial={{ opacity: 0, y: 5 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.15 }}
        >
          <rect
            x={x - 90}
            y={y - radius - 58}
            width={180}
            height={44}
            rx={8}
            fill="var(--surface-2)"
            stroke="var(--border)"
            strokeWidth={1}
            opacity={0.95}
          />
          <text
            x={x}
            y={y - radius - 40}
            textAnchor="middle"
            fill="var(--text)"
            fontSize={10}
            fontWeight={600}
            style={{ pointerEvents: 'none' }}
          >
            {agent.specialty || 'General'}
          </text>
          <text
            x={x}
            y={y - radius - 26}
            textAnchor="middle"
            fill="var(--text-muted)"
            fontSize={9}
            style={{ pointerEvents: 'none' }}
          >
            {agent.turn_count} turns | {agent.status}
          </text>
        </motion.g>
      )}
    </motion.g>
  )
}
