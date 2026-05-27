/**
 * @file ui.ts
 * @module stores
 *
 * Zustand store for UI-level state that is not tied to a specific domain model:
 * the colour theme, sidebar open/close state, the active sidebar tab, and the
 * desktop side-panel toggle.
 *
 * Theme persistence is handled at the module level — the initial theme is read
 * from localStorage (with a `prefers-color-scheme` fallback) and applied to
 * `document.documentElement` immediately so there is no flash of the wrong
 * theme on load.
 */

import { create } from 'zustand'

/** The two supported colour themes. */
type Theme = 'dark' | 'light'

/**
 * Shape of the UI Zustand store.
 * Combines reactive state fields with action methods.
 */
interface UIState {
  /** Currently active colour theme. */
  theme: Theme

  /** Whether the left sidebar is visible. */
  sidebarOpen: boolean

  /** Which tab is selected inside the sidebar. */
  sidebarTab: 'sessions' | 'files' | 'memory'

  /** Whether the floating desktop panel (e.g. VNC viewer) is open. */
  desktopPanelOpen: boolean

  /** Whether the git side-panel is open. */
  gitPanelOpen: boolean

  /** Whether the chat is in expanded view (showing all tool calls, thinking, etc. individually). */
  expandedView: boolean

  /** Whether the search panel is open. */
  searchOpen: boolean

  /**
   * Explicitly opens or closes the search panel.
   *
   * @param open - `true` to show the panel, `false` to hide it.
   */
  setSearchOpen: (open: boolean) => void

  /** Flips the search panel between open and closed. */
  toggleSearch: () => void

  /**
   * Sets the active theme, persists it to localStorage, and applies the
   * `data-theme` attribute to `<html>`.
   *
   * @param theme - The theme to activate.
   */
  setTheme: (theme: Theme) => void

  /**
   * Toggles between `"dark"` and `"light"`, persisting the new value.
   */
  toggleTheme: () => void

  /**
   * Explicitly opens or closes the sidebar.
   *
   * @param open - `true` to show the sidebar, `false` to hide it.
   */
  setSidebarOpen: (open: boolean) => void

  /** Flips the sidebar between open and closed. */
  toggleSidebar: () => void

  /**
   * Switches the active sidebar tab.
   *
   * @param tab - The tab to make active.
   */
  setSidebarTab: (tab: 'sessions' | 'files' | 'memory') => void

  /**
   * Explicitly opens or closes the desktop panel.
   *
   * @param open - `true` to show the panel, `false` to hide it.
   */
  setDesktopPanelOpen: (open: boolean) => void

  /** Flips the desktop panel between open and closed. */
  toggleDesktopPanel: () => void

  /**
   * Explicitly opens or closes the git panel.
   *
   * @param open - `true` to show the panel, `false` to hide it.
   */
  setGitPanelOpen: (open: boolean) => void

  /** Flips the git panel between open and closed. */
  toggleGitPanel: () => void

  /** Explicitly sets the expanded view mode. */
  setExpandedView: (expanded: boolean) => void

  /** Flips expanded view between on and off. */
  toggleExpandedView: () => void
}

/**
 * Reads the persisted theme from localStorage, falling back to light mode
 * when no preference has been saved. Light is the platform default so
 * first-time visitors see the polished light design; users can toggle to
 * dark mode and the choice is remembered.
 *
 * @returns The theme to use on initial render.
 */
function getInitialTheme(): Theme {
  const stored = localStorage.getItem('synapsis-theme')
  if (stored === 'light' || stored === 'dark') return stored
  return 'light'
}

/**
 * Applies a theme by writing the `data-theme` attribute to `<html>` and
 * persisting the value to localStorage.
 *
 * @param theme - The theme to apply.
 */
function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  localStorage.setItem('synapsis-theme', theme)
}

// Apply the theme at module load time to avoid a flash of the wrong theme.
const initialTheme = getInitialTheme()
applyTheme(initialTheme)

/** @internal Zustand store instance. Use the exported {@link useUIStore} hook. */
export const useUIStore = create<UIState>((set) => ({
  theme: initialTheme,
  sidebarOpen: window.innerWidth >= 768,
  sidebarTab: 'sessions',
  expandedView: false,
  desktopPanelOpen: false,
  gitPanelOpen: false,
  searchOpen: false,

  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
  },
  toggleTheme: () =>
    set((s) => {
      const next = s.theme === 'dark' ? 'light' : 'dark'
      applyTheme(next)
      return { theme: next }
    }),
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  setSidebarTab: (tab) => set({ sidebarTab: tab }),
  setDesktopPanelOpen: (open) => set({ desktopPanelOpen: open }),
  toggleDesktopPanel: () => set((s) => ({ desktopPanelOpen: !s.desktopPanelOpen })),
  setGitPanelOpen: (open) => set({ gitPanelOpen: open }),
  toggleGitPanel: () => set((s) => ({ gitPanelOpen: !s.gitPanelOpen })),
  setExpandedView: (expanded) => set({ expandedView: expanded }),
  toggleExpandedView: () => set((s) => ({ expandedView: !s.expandedView })),
  setSearchOpen: (open) => set({ searchOpen: open }),
  toggleSearch: () => set((s) => ({ searchOpen: !s.searchOpen })),
}))
