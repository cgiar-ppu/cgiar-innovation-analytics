/**
 * Tests for the agents service (services/agents.ts).
 *
 * fetch is stubbed globally with vi.stubGlobal so no real network calls are
 * made. Each test installs its own mock return value and verifies both the
 * URL/method called and the parsed return value.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { agentsService } from '../agents'
import type { AgentInfo } from '../../lib/types-extended'

// Helper: create a minimal mock Response
function mockResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('agentsService', () => {
  // -----------------------------------------------------------------------
  // getAgents
  // -----------------------------------------------------------------------
  it('test_getAgents_parses_response', async () => {
    const agents: AgentInfo[] = [
      { id: 'a1', name: 'Agent 1', description: 'desc', type: 'custom', status: 'active', tools: [], model: 'sonnet' },
    ]
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({ agents }))
    vi.stubGlobal('fetch', fetchMock)

    const result = await agentsService.getAgents()

    expect(fetchMock).toHaveBeenCalledWith('/api/agents')
    expect(result).toEqual(agents)
  })

  it('test_getAgents_handles_flat_array_response', async () => {
    // The service returns `data.agents || data`, so also handle plain arrays
    const agents: AgentInfo[] = [
      { id: 'a2', name: 'Agent 2', description: 'desc', type: 'builtin', status: 'active', tools: [], model: 'opus' },
    ]
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(agents))
    vi.stubGlobal('fetch', fetchMock)

    const result = await agentsService.getAgents()
    expect(result).toEqual(agents)
  })

  it('test_getAgents_throws_on_error', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(null, false, 500))
    vi.stubGlobal('fetch', fetchMock)

    await expect(agentsService.getAgents()).rejects.toThrow('HTTP 500')
  })

  // -----------------------------------------------------------------------
  // createAgent
  // -----------------------------------------------------------------------
  it('test_createAgent_sends_post', async () => {
    const created: AgentInfo = {
      id: 'new-1',
      name: 'New Agent',
      description: 'A test agent',
      type: 'custom',
      status: 'active',
      tools: ['Read'],
      model: 'sonnet',
      color: '#ff0000',
    }
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(created))
    vi.stubGlobal('fetch', fetchMock)

    const payload = {
      name: 'New Agent',
      description: 'A test agent',
      system_prompt: 'You are helpful.',
      tools: ['Read'],
      model: 'sonnet',
      color: '#ff0000',
    }
    const result = await agentsService.createAgent(payload)

    expect(fetchMock).toHaveBeenCalledWith('/api/agents', expect.objectContaining({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }))
    expect(result).toEqual(created)
  })

  it('test_createAgent_throws_on_error', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(null, false, 422))
    vi.stubGlobal('fetch', fetchMock)

    await expect(agentsService.createAgent({
      name: 'x',
      description: '',
      system_prompt: '',
      tools: [],
      model: 'sonnet',
      color: '#000',
    })).rejects.toThrow('HTTP 422')
  })

  // -----------------------------------------------------------------------
  // deleteAgent
  // -----------------------------------------------------------------------
  it('test_deleteAgent_sends_delete', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse({}, true, 200))
    vi.stubGlobal('fetch', fetchMock)

    await agentsService.deleteAgent('agent-99')

    // The api.del helper now attaches auth headers (empty object when no token
    // is present) alongside the method — assert on the method + path.
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/agents/agent-99',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('test_deleteAgent_throws_on_error', async () => {
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(null, false, 404))
    vi.stubGlobal('fetch', fetchMock)

    await expect(agentsService.deleteAgent('ghost')).rejects.toThrow('HTTP 404')
  })

  // -----------------------------------------------------------------------
  // updateAgent
  // -----------------------------------------------------------------------
  it('test_updateAgent_sends_put', async () => {
    const updated: AgentInfo = {
      id: 'a1',
      name: 'Updated',
      description: 'updated',
      type: 'custom',
      status: 'active',
      tools: [],
      model: 'sonnet',
    }
    const fetchMock = vi.fn().mockResolvedValue(mockResponse(updated))
    vi.stubGlobal('fetch', fetchMock)

    const result = await agentsService.updateAgent('a1', { name: 'Updated' })

    expect(fetchMock).toHaveBeenCalledWith('/api/agents/a1', expect.objectContaining({
      method: 'PUT',
    }))
    expect(result).toEqual(updated)
  })
})
