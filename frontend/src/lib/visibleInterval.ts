/**
 * @file visibleInterval.ts
 *
 * `setInterval` that pauses while the tab is hidden (AWS cost sprint, Nov 2026).
 *
 * Dev/test servers now sleep when nobody uses them. A forgotten background tab
 * that keeps polling (SSO refresh every 120 s, voice status every 60 s) looked
 * like a user and kept the server awake around the clock. With this helper a
 * hidden tab sends nothing; when it becomes visible again, a tick that was
 * skipped while hidden runs at once, so the session/status catches up.
 */

export function visibleInterval(fn: () => void, ms: number): () => void {
  const hidden = () => typeof document !== 'undefined' && document.visibilityState === 'hidden'
  let missed = false

  const timer = window.setInterval(() => {
    if (hidden()) {
      missed = true
      return
    }
    fn()
  }, ms)

  const onVisibility = () => {
    if (!hidden() && missed) {
      missed = false
      fn()
    }
  }
  document.addEventListener('visibilitychange', onVisibility)

  return () => {
    window.clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisibility)
  }
}
