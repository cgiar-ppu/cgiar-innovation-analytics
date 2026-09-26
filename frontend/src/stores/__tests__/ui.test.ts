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
    sidebarTab: 'sessions' | 'files'
  }> = {}
) {
  useUIStore.setState({
    theme: 'dark',
    sidebarOpen: false,
    sidebarTab: 'sessions',
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
  // Removed Synapsis surfaces (2026-09-26): no desktop (VNC) or git panel
  // state any more - their backends were removed.
  // -----------------------------------------------------------------------
  it('test_no_desktop_or_git_panel_state', () => {
    const state = useUIStore.getState() as unknown as Record<string, unknown>
    for (const key of ['desktopPanelOpen', 'toggleDesktopPanel', 'setDesktopPanelOpen', 'gitPanelOpen', 'toggleGitPanel', 'setGitPanelOpen']) {
      expect(state[key]).toBeUndefined()
    }
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

    useUIStore.getState().setSidebarTab('sessions')
    expect(useUIStore.getState().sidebarTab).toBe('sessions')
  })
})
