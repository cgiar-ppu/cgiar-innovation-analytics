/**
 * @file fleet.ts
 * @module services
 *
 * REST API service for fleet operations. Wraps the low-level api helpers
 * from lib/api.ts with fleet-specific endpoints and typed payloads.
 */

import { api } from '../lib/api'
import type {
  Fleet,
  FleetAgent,
  FleetRun,
  FleetMessage,
  SystemHealth,
} from '../stores/fleet'

// ---------------------------------------------------------------------------
// Request payload types
// ---------------------------------------------------------------------------

export interface CreateFleetPayload {
  name: string
  description?: string
  project_path?: string
  tags?: string[]
  config?: Record<string, unknown>
}

export interface SpawnPayload {
  agents: Array<{
    name: string
    specialty: string
    system_prompt: string
  }>
  concurrency?: number
  initial_task?: string
}

export interface BroadcastPayload {
  message: string
  filter_status?: string[]
  concurrency?: number
}

export interface MediatePayload {
  agent_ids: string[]
  topic: string
  rounds?: number
}

// ---------------------------------------------------------------------------
// Response envelope types
// ---------------------------------------------------------------------------

interface FleetDetail extends Fleet {
  agents: FleetAgent[]
  runs: FleetRun[]
}

// ---------------------------------------------------------------------------
// API service
// ---------------------------------------------------------------------------

export const fleetApi = {
  // -- Fleets ---------------------------------------------------------------

  listFleets: () =>
    api.get<{ fleets: Fleet[] }>('/api/fleet'),

  createFleet: (data: CreateFleetPayload) =>
    api.post<Fleet>('/api/fleet', data),

  getFleet: (fleetId: string) =>
    api.get<FleetDetail>(`/api/fleet/${fleetId}`),

  updateFleet: (fleetId: string, data: Partial<Fleet>) =>
    api.patch<Fleet>(`/api/fleet/${fleetId}`, data),

  deleteFleet: (fleetId: string) =>
    api.del<{ status: string }>(`/api/fleet/${fleetId}`),

  // -- Agents ---------------------------------------------------------------

  listAgents: (fleetId: string) =>
    api.get<{ agents: FleetAgent[] }>(`/api/fleet/${fleetId}/agents`),

  getAgent: (fleetId: string, agentId: string) =>
    api.get<FleetAgent>(`/api/fleet/${fleetId}/agents/${agentId}`),

  getAgentMessages: (agentId: string) =>
    api.get<{ messages: FleetMessage[] }>(`/api/fleet/agent/${agentId}/messages`),

  // -- Operations -----------------------------------------------------------

  spawnAgents: (fleetId: string, data: SpawnPayload) =>
    api.post<{ status: string; agent_ids: string[] }>(`/api/fleet/${fleetId}/spawn`, data),

  broadcastMessage: (fleetId: string, data: BroadcastPayload) =>
    api.post<{ status: string; run_id: string }>(`/api/fleet/${fleetId}/broadcast`, data),

  mediateAgents: (fleetId: string, data: MediatePayload) =>
    api.post<{ status: string; run_id: string }>(`/api/fleet/${fleetId}/mediate`, data),

  resumeAgent: (agentId: string, message: string) =>
    api.post<{ status: string }>(`/api/fleet/agent/${agentId}/resume`, { message }),

  // -- Runs -----------------------------------------------------------------

  listRuns: (fleetId: string) =>
    api.get<{ runs: FleetRun[] }>(`/api/fleet/${fleetId}/runs`),

  getRun: (runId: string) =>
    api.get<FleetRun>(`/api/fleet/run/${runId}`),

  // -- Health ---------------------------------------------------------------

  getHealth: () =>
    api.get<SystemHealth>('/api/fleet/health'),
}
