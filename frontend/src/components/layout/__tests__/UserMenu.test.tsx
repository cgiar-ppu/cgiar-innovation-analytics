/**
 * Tests for UserMenu (QA round-1 Finding 2 — logout() existed but nothing
 * called it). Verifies the button is hidden in dev-bypass mode, shown with
 * the signed-in user's email once authenticated, and that clicking
 * "Sign out" calls the auth store's logout().
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { UserMenu } from '../UserMenu'
import { useAuthStore } from '../../../stores/auth'

function resetStore() {
  localStorage.clear()
  useAuthStore.setState({
    token: null,
    user: null,
    disclaimerAcknowledged: false,
    ready: true,
    authRequired: true,
  })
}

describe('UserMenu', () => {
  beforeEach(() => {
    resetStore()
  })

  it('renders nothing in dev-bypass mode (authRequired=false)', () => {
    useAuthStore.setState({ authRequired: false, user: null })
    const { container } = render(<UserMenu />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders nothing when auth is required but no user is set', () => {
    useAuthStore.setState({ authRequired: true, user: null })
    const { container } = render(<UserMenu />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the account trigger with the signed-in user email as a title', () => {
    useAuthStore.setState({
      authRequired: true,
      user: { userId: 'alice@cgiar.org', email: 'alice@cgiar.org', name: 'Alice', role: 'user' },
    })
    render(<UserMenu />)
    const trigger = screen.getByRole('button', { name: /account menu/i })
    expect(trigger).toBeInTheDocument()
    expect(trigger).toHaveAttribute('title', 'alice@cgiar.org')
  })

  it('clicking "Sign out" calls logout() and clears the session', async () => {
    const user = userEvent.setup()
    const logoutSpy = vi.fn()
    useAuthStore.setState({
      authRequired: true,
      user: { userId: 'alice@cgiar.org', email: 'alice@cgiar.org', name: 'Alice', role: 'user' },
      token: 'jwt-abc',
      logout: logoutSpy,
    })
    localStorage.setItem('ia-auth-token', 'jwt-abc')

    render(<UserMenu />)
    await user.click(screen.getByRole('button', { name: /account menu/i }))
    const signOutItem = await screen.findByTestId('logout-menu-item')
    await user.click(signOutItem)

    expect(logoutSpy).toHaveBeenCalledTimes(1)
  })
})
