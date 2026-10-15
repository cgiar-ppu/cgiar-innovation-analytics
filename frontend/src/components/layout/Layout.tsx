import { useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import TopBar from './TopBar';
import VoiceGuide from '../voice/VoiceGuide';
import { ToastProvider } from '../common/Toast';
import { WebSocketProvider } from '../../contexts/WebSocketContext';
import DisclaimerFooter from '../guardrails/DisclaimerFooter';
import { useAppConfigStore } from '../../stores/appConfig';
import { getAuthToken, useAuthStore } from '../../stores/auth';
import { useSessionsStore } from '../../stores/sessions';
import { startTelemetry, trackPageView } from '../../lib/telemetry';

export default function Layout() {
  const config = useAppConfigStore((s) => s.config);
  const userId = useAuthStore((s) => s.user?.userId ?? null);

  // /api/config is role-aware: (re)load it for whoever is signed in.
  useEffect(() => {
    void useAppConfigStore.getState().load();
  }, [userId]);

  // First-party, cookieless usage events (SYN-2305): same-origin only.
  const { pathname } = useLocation();
  useEffect(
    () =>
      startTelemetry({
        getToken: getAuthToken,
        getChatSessionId: () => useSessionsStore.getState().activeSessionId ?? null,
      }),
    [userId],
  );
  useEffect(() => {
    trackPageView();
  }, [pathname, userId]);

  return (
    <WebSocketProvider>
      <div className="h-dvh flex flex-col bg-[var(--bg)] overflow-hidden">
        {/* Animated mesh background */}
        <div className="bg-mesh" aria-hidden="true" />

        <TopBar config={config} />

        <div className="flex-1 flex overflow-hidden relative z-10">
          <main className="flex-1 overflow-y-auto">
            <Outlet />
          </main>
        </div>

        {/* Persistent AI-content disclaimer — visible on every view */}
        <DisclaimerFooter />

        <VoiceGuide />
        <ToastProvider />
      </div>
    </WebSocketProvider>
  );
}
