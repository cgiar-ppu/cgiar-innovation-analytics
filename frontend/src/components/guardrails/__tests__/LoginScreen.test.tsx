/**
 * Tests for LoginScreen's interim self-signup toggle (2026-07-20).
 *
 * Covers:
 * - the "Create account" toggle is hidden when the backend reports
 *   self_signup: false (or the /api/config call fails/hasn't resolved yet);
 * - it appears and switches the form into signup mode when self_signup: true;
 * - submitting the signup form calls the auth store's signup() with the
 *   trimmed field values;
 * - submitting the login form (default mode) still calls login(), unaffected.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LoginScreen from '../LoginScreen'
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

function stubConfig(selfSignup: boolean) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ self_signup: selfSignup }),
    }),
  )
}

describe('LoginScreen', () => {
  beforeEach(() => {
    resetStore()
    vi.restoreAllMocks()
  })

  it('does not show the "Create account" toggle when self_signup is false', async () => {
    stubConfig(false)
    render(<LoginScreen />)
    await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/config'))
    expect(screen.queryByTestId('signup-toggle')).not.toBeInTheDocument()
  })

  it('does not show the toggle while /api/config has not resolved / errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network down')))
    render(<LoginScreen />)
    await waitFor(() => expect(fetch).toHaveBeenCalled())
    expect(screen.queryByTestId('signup-toggle')).not.toBeInTheDocument()
  })

  it('shows the "Create account" toggle when self_signup is true, and switches modes', async () => {
    stubConfig(true)
    const user = userEvent.setup()
    render(<LoginScreen />)

    const toggle = await screen.findByTestId('signup-toggle')
    expect(toggle).toHaveTextContent(/create account/i)

    await user.click(toggle)
    expect(screen.getByTestId('signup-name')).toBeInTheDocument()
    expect(screen.getByTestId('signup-toggle')).toHaveTextContent(/already have an account/i)
  })

  it('submitting the signup form calls signup() with trimmed field values', async () => {
    stubConfig(true)
    const signupSpy = vi.fn().mockResolvedValue(null)
    useAuthStore.setState({ signup: signupSpy })
    const user = userEvent.setup()
    render(<LoginScreen />)

    await user.click(await screen.findByTestId('signup-toggle'))
    await user.type(screen.getByTestId('signup-name'), '  New Researcher  ')
    await user.type(screen.getByTestId('login-email'), '  new.researcher@cgiar.org  ')
    await user.type(screen.getByTestId('login-password'), 'a-strong-pw')
    await user.click(screen.getByTestId('login-submit'))

    await waitFor(() =>
      expect(signupSpy).toHaveBeenCalledWith('New Researcher', 'new.researcher@cgiar.org', 'a-strong-pw'),
    )
  })

  it('shows the error returned by signup() on failure', async () => {
    stubConfig(true)
    useAuthStore.setState({ signup: vi.fn().mockResolvedValue('An account with this email already exists.') })
    const user = userEvent.setup()
    render(<LoginScreen />)

    await user.click(await screen.findByTestId('signup-toggle'))
    await user.type(screen.getByTestId('signup-name'), 'Dup')
    await user.type(screen.getByTestId('login-email'), 'dup@cgiar.org')
    await user.type(screen.getByTestId('login-password'), 'a-strong-pw')
    await user.click(screen.getByTestId('login-submit'))

    expect(await screen.findByTestId('login-error')).toHaveTextContent(/already exists/i)
  })

  it('login mode (default) still calls login(), not signup()', async () => {
    stubConfig(false)
    const loginSpy = vi.fn().mockResolvedValue(null)
    const signupSpy = vi.fn()
    useAuthStore.setState({ login: loginSpy, signup: signupSpy })
    const user = userEvent.setup()
    render(<LoginScreen />)

    await user.type(screen.getByTestId('login-email'), 'alice@cgiar.org')
    await user.type(screen.getByTestId('login-password'), 'correct-horse')
    await user.click(screen.getByTestId('login-submit'))

    await waitFor(() => expect(loginSpy).toHaveBeenCalledWith('alice@cgiar.org', 'correct-horse'))
    expect(signupSpy).not.toHaveBeenCalled()
  })
})
