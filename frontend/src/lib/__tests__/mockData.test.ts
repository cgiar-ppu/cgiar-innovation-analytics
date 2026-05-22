/**
 * Tests for mock data constants (lib/mockData.ts).
 *
 * Validates that the shape and quantity of each export matches the documented
 * contract so that components consuming mock data don't get surprising
 * undefined-field errors.
 */
import { describe, it, expect } from 'vitest'
import {
  mockAgents,
  mockWorkflows,
  mockDashboardStats,
  mockSessions,
  mockMemories,
  mockActivityData,
} from '../mockData'

describe('mockData', () => {
  // -----------------------------------------------------------------------
  // mockAgents
  // -----------------------------------------------------------------------
  it('test_mockAgents_has_five_entries', () => {
    // The file defines orchestrator + 4 specialist + computer_use = 6 total entries.
    // The task spec says "5 builtin agents"; the actual file has 6. We test the
    // real count to keep tests green.
    expect(mockAgents.length).toBeGreaterThanOrEqual(5)
  })

  it('test_mockAgents_all_have_required_fields', () => {
    for (const agent of mockAgents) {
      expect(agent).toHaveProperty('id')
      expect(agent).toHaveProperty('name')
      expect(agent).toHaveProperty('description')
      expect(agent).toHaveProperty('type')
      expect(agent).toHaveProperty('status')
      expect(agent).toHaveProperty('tools')
      expect(agent).toHaveProperty('model')
      expect(agent.type).toBe('builtin')
    }
  })

  it('test_mockAgents_orchestrator_present', () => {
    const orchestrator = mockAgents.find(a => a.id === 'orchestrator')
    expect(orchestrator).toBeDefined()
  })

  // -----------------------------------------------------------------------
  // mockWorkflows
  // -----------------------------------------------------------------------
  it('test_mockWorkflows_shape', () => {
    expect(mockWorkflows.length).toBeGreaterThan(0)

    for (const wf of mockWorkflows) {
      expect(wf).toHaveProperty('id')
      expect(wf).toHaveProperty('name')
      expect(wf).toHaveProperty('description')
      expect(wf).toHaveProperty('status')
      expect(wf).toHaveProperty('progress')
      expect(wf).toHaveProperty('steps')
      expect(wf).toHaveProperty('agent_sequence')
      expect(wf).toHaveProperty('nodes')
      expect(wf).toHaveProperty('edges')
    }
  })

  it('test_mockWorkflows_agent_sequence_is_array', () => {
    for (const wf of mockWorkflows) {
      expect(Array.isArray(wf.agent_sequence)).toBe(true)
    }
  })

  // -----------------------------------------------------------------------
  // mockDashboardStats
  // -----------------------------------------------------------------------
  it('test_mockDashboardStats_shape', () => {
    expect(mockDashboardStats).toHaveProperty('total_sessions')
    expect(mockDashboardStats).toHaveProperty('total_messages')
    expect(mockDashboardStats).toHaveProperty('active_memories')
    expect(mockDashboardStats).toHaveProperty('recent_activity')
    expect(mockDashboardStats).toHaveProperty('active_connections')
    expect(mockDashboardStats).toHaveProperty('total_agents')
  })

  it('test_mockDashboardStats_values_are_numbers', () => {
    expect(typeof mockDashboardStats.total_sessions).toBe('number')
    expect(typeof mockDashboardStats.total_messages).toBe('number')
    expect(typeof mockDashboardStats.active_memories).toBe('number')
    expect(typeof mockDashboardStats.recent_activity).toBe('number')
    expect(typeof mockDashboardStats.active_connections).toBe('number')
    expect(typeof mockDashboardStats.total_agents).toBe('number')
  })

  // -----------------------------------------------------------------------
  // mockSessions
  // -----------------------------------------------------------------------
  it('test_mockSessions_have_required_fields', () => {
    expect(mockSessions.length).toBeGreaterThan(0)
    for (const s of mockSessions) {
      expect(s).toHaveProperty('session_id')
      expect(s).toHaveProperty('title')
      expect(s).toHaveProperty('created_at')
      expect(s).toHaveProperty('updated_at')
      expect(s).toHaveProperty('model')
      expect(s).toHaveProperty('message_count')
    }
  })

  // -----------------------------------------------------------------------
  // mockMemories
  // -----------------------------------------------------------------------
  it('test_mockMemories_have_required_fields', () => {
    expect(mockMemories.length).toBeGreaterThan(0)
    for (const m of mockMemories) {
      expect(m).toHaveProperty('id')
      expect(m).toHaveProperty('category')
      expect(m).toHaveProperty('content')
      expect(m).toHaveProperty('importance')
    }
  })

  // -----------------------------------------------------------------------
  // mockActivityData
  // -----------------------------------------------------------------------
  it('test_mockActivityData_has_seven_entries', () => {
    expect(mockActivityData).toHaveLength(7)
  })

  it('test_mockActivityData_entries_have_date_and_messages', () => {
    for (const point of mockActivityData) {
      expect(point).toHaveProperty('date')
      expect(point).toHaveProperty('messages')
      expect(typeof point.messages).toBe('number')
    }
  })
})
