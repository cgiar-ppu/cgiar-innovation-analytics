/** The top bar carries the global "Give feedback" button for every role (MVP test release item 1). */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import type { AppConfig } from '../../../lib/types'
import { useAppConfigStore } from '../../../stores/appConfig'
import { useAuthStore } from '../../../stores/auth'

vi.mock('../../../contexts/WebSocketContext', () => ({
  useWebSocketContext: () => ({ send: vi.fn(), isConnected: true, connectionStatus: 'connected', connect: vi.fn(), disconnect: vi.fn() }),
}))

import TopBar from '../TopBar'

describe('TopBar feedback entry point', () => {
  for (const role of ['researcher', 'admin'] as const) {
    it(`shows "Give feedback" to ${role}s on every page`, () => {
      useAuthStore.setState({ token: 't', user: { userId: role, email: `${role}@x`, name: role, role } } as never)
      useAppConfigStore.setState({ config: { model: 'm', feedback_enabled: true } as AppConfig, loadedFor: role })
      for (const path of ['/', '/chat', '/settings']) {
        const { unmount } = render(<MemoryRouter initialEntries={[path]}><TopBar config={null} /></MemoryRouter>)
        expect(screen.getByRole('button', { name: 'Give feedback' })).toBeInTheDocument()
        unmount()
      }
    })
  }

  it('hides it when the feedback kill-switch is off', () => {
    useAppConfigStore.setState({ config: { model: 'm', feedback_enabled: false } as AppConfig })
    render(<MemoryRouter><TopBar config={null} /></MemoryRouter>)
    expect(screen.queryByRole('button', { name: 'Give feedback' })).toBeNull()
  })
})
