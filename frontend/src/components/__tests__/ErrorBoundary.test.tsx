/**
 * Tests for ErrorBoundary (components/common/ErrorBoundary.tsx).
 *
 * React error boundaries require a throwing child component.
 * console.error is suppressed during tests to keep output clean.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import ErrorBoundary from '../common/ErrorBoundary'

// Suppress React's own error logging and the ErrorBoundary console.error calls
let consoleErrorSpy: ReturnType<typeof vi.spyOn>

beforeEach(() => {
  consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
})

afterEach(() => {
  consoleErrorSpy.mockRestore()
})

// A child that throws on render when the `shouldThrow` prop is true
function ThrowingChild({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('Test render error')
  }
  return <div data-testid="child-content">Child rendered OK</div>
}

describe('ErrorBoundary', () => {
  // -----------------------------------------------------------------------
  // test_renders_children_normally
  // -----------------------------------------------------------------------
  it('test_renders_children_normally', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={false} />
      </ErrorBoundary>
    )

    expect(screen.getByTestId('child-content')).toBeInTheDocument()
    expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test_shows_fallback_on_error
  // -----------------------------------------------------------------------
  it('test_shows_fallback_on_error', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
    // The error message from ThrowingChild should be displayed
    expect(screen.getByText(/test render error/i)).toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test_reload_button_present
  // -----------------------------------------------------------------------
  it('test_reload_button_present', () => {
    render(
      <ErrorBoundary>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    )

    const button = screen.getByRole('button', { name: /reload page/i })
    expect(button).toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test_custom_fallback_rendered_when_provided
  // -----------------------------------------------------------------------
  it('test_custom_fallback_rendered_when_provided', () => {
    render(
      <ErrorBoundary fallback={<div data-testid="custom-fallback">Custom error UI</div>}>
        <ThrowingChild shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByTestId('custom-fallback')).toBeInTheDocument()
    // The default "Something went wrong" UI should NOT be shown
    expect(screen.queryByText(/something went wrong/i)).not.toBeInTheDocument()
  })

  // -----------------------------------------------------------------------
  // test_no_children_dont_crash
  // -----------------------------------------------------------------------
  it('test_no_children_do_not_crash', () => {
    // An empty boundary should simply render nothing without throwing
    const { container } = render(
      <ErrorBoundary>
        <span />
      </ErrorBoundary>
    )
    expect(container).toBeInTheDocument()
  })
})
