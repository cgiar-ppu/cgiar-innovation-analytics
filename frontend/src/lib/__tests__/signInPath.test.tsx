/**
 * After signing in on "/login" (a sign-in-only URL), the app moves to "/" so
 * the router and the usage page views name the real page (verification round,
 * Oct 2026: dashboard views were recorded as "/login").
 */
import { act, render, screen } from '@testing-library/react'
import { BrowserRouter, useLocation } from 'react-router-dom'
import { describe, it, expect, afterEach } from 'vitest'
import { leaveSignInPath } from '../signInPath'

function Where() {
  return <span data-testid="where">{useLocation().pathname}</span>
}

afterEach(() => window.history.replaceState({}, '', '/'))

describe('leaveSignInPath', () => {
  it('moves the router from /login to /', () => {
    window.history.replaceState({}, '', '/login')
    render(<BrowserRouter><Where /></BrowserRouter>)
    expect(screen.getByTestId('where')).toHaveTextContent('/login')
    act(() => leaveSignInPath())
    expect(window.location.pathname).toBe('/')
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/$/)
  })

  it('leaves real app routes alone', () => {
    window.history.replaceState({}, '', '/chat')
    leaveSignInPath()
    expect(window.location.pathname).toBe('/chat')
  })
})
