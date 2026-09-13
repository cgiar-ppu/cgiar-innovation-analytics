/**
 * @file AuthGate.tsx
 *
 * Top-level gate that sequences the July-7 guardrails:
 *   1. initialize() — restore session, detect whether auth is required
 *   2. if auth is required and no user → LoginScreen (Step 3)
 *   3. if the disclaimer has not been acknowledged → DisclaimerModal (Step 1)
 *   4. otherwise → render the app (children)
 *
 * The persistent DisclaimerFooter is rendered by the Layout, not here, so it is
 * visible on every in-app view. This gate only governs entry.
 */

import { useEffect, useState, type ReactNode } from 'react'
import { isSsoSession, useAuthStore } from '../../stores/auth'
import LoginScreen from './LoginScreen'
import DisclaimerModal from './DisclaimerModal'
import InvitationAccept from './InvitationAccept'

export default function AuthGate({ children }: { children: ReactNode }) {
  const { ready, authRequired, user, disclaimerAcknowledged, initialize } = useAuthStore()
  const [invitationToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('invite'))

  useEffect(() => {
    if (!invitationToken) initialize()
  }, [initialize, invitationToken])

  useEffect(() => {
    const refresh = () => {
      if (isSsoSession()) void useAuthStore.getState().refreshSso()
    }
    const timer = window.setInterval(refresh, 120_000)
    window.addEventListener('focus', refresh)
    return () => { window.clearInterval(timer); window.removeEventListener('focus', refresh) }
  }, [])

  // While restoring the session, render nothing (avoids a flash of the login
  // screen for already-authenticated users).
  if (invitationToken) return <InvitationAccept token={invitationToken} />
  if (!ready) return null

  // Step 3 — must be authenticated (unless the backend is in dev-bypass mode).
  if (authRequired && !user) {
    return <LoginScreen />
  }

  // Step 1 — must acknowledge the disclaimer before reaching the tool.
  if (!disclaimerAcknowledged) {
    return (
      <>
        {/* Render children behind the modal so the transition into the app is
            seamless once "I understand" is clicked, but the modal blocks all
            interaction until then. */}
        <div aria-hidden="true" className="pointer-events-none select-none opacity-40">
          {children}
        </div>
        <DisclaimerModal />
      </>
    )
  }

  return <>{children}</>
}
