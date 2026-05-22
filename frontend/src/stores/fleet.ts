/**
 * @file fleet.ts
 * @module stores
 *
 * Zustand store for fleet state management. Tracks fleets, agents, runs,
 * messages, system health, and UI selections. All WebSocket and REST
 * handlers update this store, which the Fleet page and its sub-components
 * consume reactively.
 */

import { create } from 'zustand'

// ---------------------------------------------------------------------------
// Domain types
// ---------------------------------------------------------------------------

export type AgentStatus = 'idle' | 'queued' | 'running' | 'completed' | 'error' | 'retired'

export interface FleetAgent {
  agent_id: string
  fleet_id: string
  name: string
  specialty: string
  system_prompt: string
  claude_session_id: string
  worker_node: string
  status: AgentStatus
  turn_count: number
  last_active: number | null
  context_summary: string
  result: string
  error_message: string
  created_at: number
  updated_at: number
}

export interface Fleet {
  fleet_id: string
  name: string
  description: string
  project_path: string
  tags: string[]
  status: string
  created_at: number
  updated_at: number
  chat_session_id: string
  config: Record<string, unknown>
}

export interface FleetRun {
  run_id: string
  fleet_id: string
  run_type: string
  status: string
  agent_ids: string[]
  concurrency: number
  prompt: string
  result_summary: string
  progress_current: number
  progress_total: number
  started_at: number | null
  completed_at: number | null
}

export interface FleetMessage {
  message_id: number
  agent_id: string
  role: 'user' | 'assistant'
  content: string
  turn_number: number
  created_at: number
}

export interface SystemHealth {
  ram_total_gb: number
  ram_available_gb: number
  ram_used_pct: number
  cpu_pct: number
  active_agents: number
  claude_processes: number
  can_spawn_more: boolean
  recommended_concurrency: number
}

// ---------------------------------------------------------------------------
// Store shape
// ---------------------------------------------------------------------------

interface FleetState {
  // Data
  fleets: Fleet[]
  activeFleetId: string | null
  agents: FleetAgent[]
  runs: FleetRun[]
  selectedAgentId: string | null
  agentMessages: FleetMessage[]
  health: SystemHealth | null

  // UI state
  isLoading: boolean
  isSpawning: boolean

  // Actions
  setFleets: (fleets: Fleet[]) => void
  setActiveFleet: (fleetId: string | null) => void
  setAgents: (agents: FleetAgent[]) => void
  updateAgent: (agentId: string, updates: Partial<FleetAgent>) => void
  setSelectedAgent: (agentId: string | null) => void
  setAgentMessages: (messages: FleetMessage[]) => void
  addAgentMessage: (message: FleetMessage) => void
  setRuns: (runs: FleetRun[]) => void
  updateRun: (runId: string, updates: Partial<FleetRun>) => void
  setHealth: (health: SystemHealth) => void
  setLoading: (loading: boolean) => void
  setSpawning: (spawning: boolean) => void
}

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

export const useFleetStore = create<FleetState>((set) => ({
  // Initial state
  fleets: [],
  activeFleetId: null,
  agents: [],
  runs: [],
  selectedAgentId: null,
  agentMessages: [],
  health: null,
  isLoading: false,
  isSpawning: false,

  // Actions
  setFleets: (fleets) => set({ fleets }),

  setActiveFleet: (fleetId) => set({
    activeFleetId: fleetId,
    selectedAgentId: null,
    agentMessages: [],
    agents: [],
    runs: [],
  }),

  setAgents: (agents) => set({ agents }),

  updateAgent: (agentId, updates) =>
    set((s) => ({
      agents: s.agents.map((a) =>
        a.agent_id === agentId ? { ...a, ...updates } : a
      ),
    })),

  setSelectedAgent: (agentId) => set({ selectedAgentId: agentId }),

  setAgentMessages: (messages) => set({ agentMessages: messages }),

  addAgentMessage: (message) =>
    set((s) => ({ agentMessages: [...s.agentMessages, message] })),

  setRuns: (runs) => set({ runs }),

  updateRun: (runId, updates) =>
    set((s) => ({
      runs: s.runs.map((r) =>
        r.run_id === runId ? { ...r, ...updates } : r
      ),
    })),

  setHealth: (health) => set({ health }),

  setLoading: (loading) => set({ isLoading: loading }),

  setSpawning: (spawning) => set({ isSpawning: spawning }),
}))
