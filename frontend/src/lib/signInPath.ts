/** Paths that only ever show the sign-in screen (bookmarks, old links). */
const SIGN_IN_PATHS = new Set(['/login', '/signin', '/sign-in'])

/**
 * After a successful sign-in on a sign-in-only URL, move to the dashboard so
 * the address bar, the router and the usage page views name the real page
 * (they used to stay on "/login"). popstate lets the router pick it up.
 */
export function leaveSignInPath(): void {
  if (!SIGN_IN_PATHS.has(window.location.pathname)) return
  window.history.replaceState({}, '', '/')
  window.dispatchEvent(new PopStateEvent('popstate'))
}
