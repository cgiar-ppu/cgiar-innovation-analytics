/**
 * Tests for the Zustand UI store (stores/ui.ts).
 *
 * localStorage and matchMedia are shimmed in src/test/setup.ts so the store
 * can initialise cleanly before these tests run.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useUIStore } from '../ui'

function resetStore(
  overrides: Partial<{
    theme: 'dark' | 'light'
    sidebarOpen: boolean
    sidebarTab: 'sessions' | 'files' | 'memory'
    desktopPanelOpen: boolean
  }> = {}
) {
  useUIStore.setState({
    theme: 'dark',
    sidebarOpen: false,
    sidebarTab: 'sessions',
    desktopPanelOpen: false,
    ...overrides,
  })
}

describe('ui store', () => {
  beforeEach(() => {
    localStorage.clear()
    resetStore()
  })

  // -----------------------------------------------------------------------
  // toggleTheme
  // -----------------------------------------------------------------------
  it('test_toggleTheme', () => {
    useUIStore.setState({ theme: 'dark' })
    useUIStore.getState().toggleTheme()
    expect(useUIStore.getState().theme).toBe('light')

    useUIStore.getState().toggleTheme()
    expect(useUIStore.getState().theme).toBe('dark')
  })

  it('test_toggleTheme_persists_to_localStorage', () => {
    useUIStore.setState({ theme: 'dark' })
    useUIStore.getState().toggleTheme()
    expect(localStorage.getItem('synapsis-theme')).toBe('light')
  })

  it('test_setTheme_sets_specific_theme', () => {
    useUIStore.setState({ theme: 'dark' })
    useUIStore.getState().setTheme('light')
    expect(useUIStore.getState().theme).toBe('light')
  })

  // -----------------------------------------------------------------------
  // toggleDesktopPanel
  // -----------------------------------------------------------------------
  it('test_toggleDesktopPanel', () => {
    useUIStore.setState({ desktopPanelOpen: false })

    useUIStore.getState().toggleDesktopPanel()
    expect(useUIStore.getState().desktopPanelOpen).toBe(true)

    useUIStore.getState().toggleDesktopPanel()
    expect(useUIStore.getState().desktopPanelOpen).toBe(false)
  })

  it('test_setDesktopPanelOpen', () => {
    useUIStore.setState({ desktopPanelOpen: false })
    useUIStore.getState().setDesktopPanelOpen(true)
    expect(useUIStore.getState().desktopPanelOpen).toBe(true)

    useUIStore.getState().setDesktopPanelOpen(false)
    expect(useUIStore.getState().desktopPanelOpen).toBe(false)
  })

  // -----------------------------------------------------------------------
  // toggleSidebar
  // -----------------------------------------------------------------------
  it('test_toggleSidebar', () => {
    useUIStore.setState({ sidebarOpen: false })

    useUIStore.getState().toggleSidebar()
    expect(useUIStore.getState().sidebarOpen).toBe(true)

    useUIStore.getState().toggleSidebar()
    expect(useUIStore.getState().sidebarOpen).toBe(false)
  })

  it('test_setSidebarOpen', () => {
    useUIStore.setState({ sidebarOpen: false })
    useUIStore.getState().setSidebarOpen(true)
    expect(useUIStore.getState().sidebarOpen).toBe(true)
  })

  // -----------------------------------------------------------------------
  // setSidebarTab
  // -----------------------------------------------------------------------
  it('test_setSidebarTab', () => {
    useUIStore.getState().setSidebarTab('files')
    expect(useUIStore.getState().sidebarTab).toBe('files')

    useUIStore.getState().setSidebarTab('memory')
    expect(useUIStore.getState().sidebarTab).toBe('memory')

    useUIStore.getState().setSidebarTab('sessions')
    expect(useUIStore.getState().sidebarTab).toBe('sessions')
  })
})
