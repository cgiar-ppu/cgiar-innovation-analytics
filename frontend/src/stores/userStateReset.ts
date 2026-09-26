/**
 * @file userStateReset.ts
 * @module stores
 *
 * Sign-out / identity-change wipe (L4-04). Stores that hold per-user data
 * (open chat, session list and cache, role-aware config, ...) register a
 * reset callback here at module load; `auth.logout()` and an identity change
 * on the same tab call {@link resetUserState}. This avoids importing every
 * store into the auth store (which would create import cycles).
 */

/** localStorage key the sessions store uses for the last open chat. */
export const ACTIVE_SESSION_KEY = 'synapsis_active_session'
/** localStorage key recording whose per-user state this tab holds. */
export const STATE_OWNER_KEY = 'ia-state-owner'

const resetters = new Set<() => void>()

/** Register a callback that clears one store's per-user state. */
export function onUserStateReset(fn: () => void): () => void {
  resetters.add(fn)
  return () => { resetters.delete(fn) }
}

/** Clear every registered store plus the persisted per-user keys. */
export function resetUserState(): void {
  for (const fn of resetters) {
    try { fn() } catch { /* one store failing must not keep another user's data */ }
  }
  try {
    localStorage.removeItem(ACTIVE_SESSION_KEY)
    localStorage.removeItem(STATE_OWNER_KEY)
  } catch { /* storage unavailable */ }
}

/**
 * Called whenever a user is accepted (login, SSO restore, invitation, page
 * reload). If this tab (or its localStorage) holds state that belongs to
 * someone else - or to an unknown owner, e.g. state written before this
 * guard existed - wipe it first, then record the new owner.
 */
export function claimUserState(userId: string): void {
  let owner: string | null = null
  try { owner = localStorage.getItem(STATE_OWNER_KEY) } catch { /* ignore */ }
  if (owner !== userId) resetUserState()
  try { localStorage.setItem(STATE_OWNER_KEY, userId) } catch { /* ignore */ }
}
