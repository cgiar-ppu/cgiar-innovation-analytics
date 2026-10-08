/**
 * Role-aware UI for invited external users and researchers (L4-03 / L4-09 /
 * L4-10 / L4-13, Lane E 2026-09-26). The server enforces every rule; these
 * tests pin what each role SEES.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import type { AppConfig, ChatMessage } from '../../../lib/types'
import { useAppConfigStore } from '../../../stores/appConfig'
import { useAuthStore } from '../../../stores/auth'
import { useSessionsStore } from '../../../stores/sessions'
import { useChatStore } from '../../../stores/chat'
import { routeWebSocketMessage } from '../../../hooks/wsMessageRouter'

const send = vi.fn()
vi.mock('../../../contexts/WebSocketContext', () => ({
  useWebSocketContext: () => ({ send, isConnected: true, connectionStatus: 'connected', connect: vi.fn(), disconnect: vi.fn() }),
}))

import TopBar from '../TopBar'
import { ModelSelector } from '../ModelSelector'
import CommandPalette from '../CommandPalette'
import { Sidebar } from '../Sidebar'
import { ResultBanner } from '../../chat/ResultBanner'
import { AdminOnly } from '../../../App'
import NotFound from '../../../pages/NotFound'
import Settings from '../../../pages/Settings'
import { api } from '../../../lib/api'
import { useUIStore } from '../../../stores/ui'

const SONNET = { id: 'claude-sonnet-5', label: 'Sonnet 5' }
const OPUS55 = { id: 'claude-opus-5-5', label: 'Opus 5.5' }

function configFor(role: 'researcher' | 'admin'): AppConfig {
  const models = role === 'admin' ? [SONNET, OPUS55] : [SONNET]
  return {
    model: 'claude-sonnet-5', fallback_model: role === 'admin' ? 'claude-opus-5' : '',
    selectable_models: models, available_models: models.map((m) => m.id),
    model_policy: { role, default_model: 'claude-sonnet-5', allowed_models: models.map((m) => m.id),
      max_budget_usd_per_turn: role === 'admin' ? 5 : 1, daily_budget_usd: role === 'admin' ? null : 5,
      max_turns: 60, show_cost: role === 'admin' },
    max_turns: 60, auth_method: 'api_key', version: '1.0.0', agent_type: 'synapsis_analytics', personas: [],
    invited_login_enabled: false, contacts: [],
  } as AppConfig
}

function signIn(role: 'researcher' | 'admin') {
  useAuthStore.setState({ token: 't', ready: true, authRequired: true, disclaimerAcknowledged: true,
    user: { userId: `${role}@cgiar.org`, email: `${role}@cgiar.org`, name: role, role } })
  useAppConfigStore.setState({ config: configFor(role), loadedFor: `${role}@cgiar.org` })
}

beforeEach(() => {
  send.mockReset()
  localStorage.clear()
  useSessionsStore.setState({ sessions: [{ session_id: 's1', title: 't', model: 'claude-sonnet-5' }] as never, activeSessionId: 's1', pendingModelSwitch: null })
  useChatStore.setState({ isBusy: false, messages: [] })
})

describe('top navigation', () => {
  it('researchers see Chat, Dashboard, Settings - no Agents, no Git, no desktop panel', () => {
    signIn('researcher')
    render(<MemoryRouter><TopBar config={configFor('researcher')} /></MemoryRouter>)
    const links = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
    expect(links).toEqual(['/chat', '/', '/settings'])
    expect(screen.queryByTitle(/git panel/i)).toBeNull()
    expect(screen.queryByTitle(/desktop/i)).toBeNull()
  })

  it('administrators keep the Agents page', () => {
    signIn('admin')
    render(<MemoryRouter><TopBar config={configFor('admin')} /></MemoryRouter>)
    expect(screen.getAllByRole('link').map((a) => a.getAttribute('href'))).toContain('/agents')
    expect(screen.queryByTitle(/git panel/i)).toBeNull()
  })
})

describe('model picker (L4-09 / L4-10)', () => {
  it('is hidden when the role has a single model', () => {
    signIn('researcher')
    const { container } = render(<ModelSelector config={configFor('researcher')} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('lists exactly the models /api/config offers the caller', async () => {
    signIn('admin')
    render(<ModelSelector config={configFor('admin')} />)
    await userEvent.setup().click(screen.getByRole('button', { name: /sonnet 5/i }))
    const items = screen.getAllByRole('menuitem').map((el) => el.textContent)
    expect(items).toEqual([expect.stringContaining('Sonnet 5'), expect.stringContaining('Opus 5.5')])
  })

  it('rolls the label back when the socket is down', async () => {
    signIn('admin')
    send.mockImplementation(() => { throw new Error('Chat is disconnected.') })
    render(<ModelSelector config={configFor('admin')} />)
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /sonnet 5/i }))
    await user.click(screen.getByRole('menuitem', { name: /opus 5\.5/i }))
    expect(useSessionsStore.getState().sessions[0]!.model).toBe('claude-sonnet-5')
    expect(useSessionsStore.getState().pendingModelSwitch).toBeNull()
  })

  it('rolls the label back when the server answers model_not_allowed', () => {
    signIn('admin')
    useSessionsStore.getState().beginModelSwitch('s1', 'claude-opus-5-5')
    expect(useSessionsStore.getState().sessions[0]!.model).toBe('claude-opus-5-5')
    act(() => {
      routeWebSocketMessage({ type: 'error', code: 'model_not_allowed', message: 'Not allowed.' } as never,
        { getLastSessionComplete: () => null, setLastSessionComplete: () => {} })
    })
    expect(useSessionsStore.getState().sessions[0]!.model).toBe('claude-sonnet-5')
  })

  it('confirms the switch on model_switched', () => {
    signIn('admin')
    useSessionsStore.getState().beginModelSwitch('s1', 'claude-opus-5-5')
    routeWebSocketMessage({ type: 'model_switched', session_id: 's1', model: 'claude-opus-5-5' } as never,
      { getLastSessionComplete: () => null, setLastSessionComplete: () => {} })
    expect(useSessionsStore.getState().pendingModelSwitch).toBeNull()
    expect(useSessionsStore.getState().sessions[0]!.model).toBe('claude-opus-5-5')
  })
})

describe('cost pill (L4-09)', () => {
  const result: ChatMessage = { id: 'r', role: 'result', content: '', timestamp: 1, estimatedCost: 0.4312, turns: 7, durationMs: 72_000, authMethod: 'api_key' }

  it('is hidden for researchers (duration only)', () => {
    signIn('researcher')
    render(<ResultBanner message={result} />)
    expect(screen.queryByTestId('result-cost')).toBeNull()
    expect(screen.queryByText(/\$0\.43/)).toBeNull()
    expect(screen.queryByText(/7 turns/)).toBeNull()
  })

  it('is shown to administrators', () => {
    signIn('admin')
    render(<ResultBanner message={result} />)
    expect(screen.getByTestId('result-cost')).toHaveTextContent('$0.4312')
  })
})

describe('command palette (L4-13)', () => {
  it('has no Fleet entry, hides Agents for researchers and leaves Ctrl/Cmd+1..5 to the browser', () => {
    signIn('researcher')
    render(<MemoryRouter><CommandPalette /></MemoryRouter>)
    const digit = new KeyboardEvent('keydown', { key: '4', ctrlKey: true, cancelable: true })
    window.dispatchEvent(digit)
    expect(digit.defaultPrevented).toBe(false)
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(screen.queryByText(/fleet/i)).toBeNull()
    expect(screen.queryByText('Go to Agents')).toBeNull()
    expect(screen.getByText('Go to Settings')).toBeInTheDocument()
  })

  it('ignores shortcuts before the disclaimer is acknowledged', () => {
    signIn('researcher')
    useAuthStore.setState({ disclaimerAcknowledged: false })
    render(<MemoryRouter><CommandPalette /></MemoryRouter>)
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(screen.queryByText('Go to Settings')).toBeNull()
  })
})

describe('sidebar', () => {
  it('offers the user their own files and no shared Memory tab', () => {
    signIn('researcher')
    useUIStore.setState({ sidebarOpen: true, sidebarTab: 'sessions' })
    vi.spyOn(api, 'getSessions').mockResolvedValue({ sessions: [] })
    render(<Sidebar send={vi.fn()} />)
    expect(screen.getByRole('button', { name: /my files/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /memory/i })).toBeNull()
  })
})

describe('routes', () => {
  it('admin-only pages render the 404 page for researchers', () => {
    signIn('researcher')
    render(<MemoryRouter initialEntries={['/agents']}><Routes>
      <Route path="/agents" element={<AdminOnly><div>agents page</div></AdminOnly>} />
    </Routes></MemoryRouter>)
    expect(screen.getByTestId('not-found')).toBeInTheDocument()
    expect(screen.queryByText('agents page')).toBeNull()
  })

  it('admin-only pages render for administrators', () => {
    signIn('admin')
    render(<MemoryRouter initialEntries={['/agents']}><Routes>
      <Route path="/agents" element={<AdminOnly><div>agents page</div></AdminOnly>} />
    </Routes></MemoryRouter>)
    expect(screen.getByText('agents page')).toBeInTheDocument()
  })

  it('unknown routes show a 404 page instead of a blank screen', () => {
    render(<MemoryRouter initialEntries={['/fleet']}><Routes>
      <Route path="/" element={<div>home</div>} />
      <Route path="*" element={<NotFound />} />
    </Routes></MemoryRouter>)
    expect(screen.getByText(/page not found/i)).toBeInTheDocument()
  })
})

describe('settings', () => {
  it('researchers see preferences only - no system, safety, memory or usage cards', () => {
    signIn('researcher')
    const usage = vi.spyOn(api, 'getAdminUsage')
    render(<Settings />)
    expect(screen.getByText('Appearance')).toBeInTheDocument()
    for (const text of [/bash safety hooks/i, /memory categories/i, /usage and cost/i, /deployment/i, /workspace/i, /auth method/i]) {
      expect(screen.queryByText(text)).toBeNull()
    }
    expect(usage).not.toHaveBeenCalled()
  })
})
