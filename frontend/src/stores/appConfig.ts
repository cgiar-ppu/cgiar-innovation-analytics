/**
 * @file appConfig.ts
 * @module stores
 *
 * One shared copy of `GET /api/config` for the whole app. The response is
 * role-aware (Lane D, 2026-09-26): the model list, the cost policy and
 * `model_policy.role` depend on the caller's token, so the store re-fetches
 * whenever the signed-in identity changes and forgets everything on sign-out.
 *
 * Role-aware UI (L4-03/L4-09) reads the helpers below:
 *  - {@link useIsAdmin}   — Agents page, admin panels in Settings, diagnostics;
 *  - {@link useShowCost}  — the per-answer $ cost in ResultBanner;
 *  - {@link useGuardrailContacts} — the "reach out if in doubt" contacts.
 *
 * The server still enforces every rule; hiding is only about not showing
 * developer surfaces to invited external users.
 */

import { create } from 'zustand'
import { api } from '../lib/api'
import type { AppConfig, GuardrailContactInfo } from '../lib/types'
import { useAuthStore } from './auth'
import { onUserStateReset } from './userStateReset'
import { DEFAULT_GUARDRAIL_CONTACTS } from '../components/guardrails/contacts'

interface AppConfigState {
  config: AppConfig | null
  /** Identity (userId or 'anonymous') the loaded config belongs to. */
  loadedFor: string | null
  loading: boolean
  /** Fetch `/api/config` for the current identity (deduplicated). */
  load: (force?: boolean) => Promise<AppConfig | null>
  reset: () => void
}

let inflight: Promise<AppConfig | null> | null = null
let inflightFor: string | null = null

function identity(): string {
  return useAuthStore.getState().user?.userId ?? 'anonymous'
}

export const useAppConfigStore = create<AppConfigState>((set, get) => ({
  config: null,
  loadedFor: null,
  loading: false,

  load: async (force = false) => {
    const who = identity()
    if (!force && get().loadedFor === who && get().config) return get().config
    if (inflight && inflightFor === who) return inflight
    inflightFor = who
    set({ loading: true })
    inflight = api.getConfig()
      .then((config) => {
        // Ignore a response that belongs to a previous identity.
        if (identity() !== who) return get().config
        set({ config, loadedFor: who, loading: false })
        return config
      })
      .catch(() => {
        set({ loading: false })
        return get().config
      })
      .finally(() => {
        if (inflightFor === who) { inflight = null; inflightFor = null }
      })
    return inflight
  },

  reset: () => {
    inflight = null
    inflightFor = null
    set({ config: null, loadedFor: null, loading: false })
  },
}))

// A role-aware config must never outlive the identity it was fetched for.
onUserStateReset(() => useAppConfigStore.getState().reset())
useAuthStore.subscribe((state, previous) => {
  if (state.user?.userId !== previous.user?.userId) useAppConfigStore.getState().reset()
})

/** Pure role check, exported for tests and non-React callers. */
export function isAdmin(config: AppConfig | null, role?: string | null): boolean {
  if (config?.model_policy?.role) return config.model_policy.role === 'admin'
  return role === 'admin'
}

/**
 * True when the caller is an administrator. Uses the server-resolved
 * `model_policy.role` once `/api/config` has loaded, the signed-in user's
 * role claim before that. Defaults to false (hide) when neither is known.
 */
export function useIsAdmin(): boolean {
  const config = useAppConfigStore((s) => s.config)
  const role = useAuthStore((s) => s.user?.role ?? null)
  return isAdmin(config, role)
}

/** Whether per-answer cost may be shown (administrators only). */
export function useShowCost(): boolean {
  const config = useAppConfigStore((s) => s.config)
  return config?.model_policy?.show_cost === true
}

/** Contacts from `/api/config`, or the built-in defaults until it loads. */
export function useGuardrailContacts(): GuardrailContactInfo[] {
  const contacts = useAppConfigStore((s) => s.config?.contacts)
  return contacts && contacts.length > 0 ? contacts : DEFAULT_GUARDRAIL_CONTACTS
}
