import { useState, useEffect } from 'react';
import { Outlet } from 'react-router-dom';
import TopBar from './TopBar';
import { ToastProvider } from '../common/Toast';
import { WebSocketProvider } from '../../contexts/WebSocketContext';
import { DesktopViewer } from '../desktop/DesktopViewer';
import { GitPanel } from '../git/GitPanel';
import { useUIStore } from '../../stores/ui';
import { api } from '../../lib/api';
import type { AppConfig } from '../../lib/types';

export default function Layout() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const { desktopPanelOpen, gitPanelOpen } = useUIStore();

  useEffect(() => {
    api.getConfig().then(setConfig).catch(() => {});
  }, []);

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

          {/* Global GitPanel — accessible from any page */}
          {gitPanelOpen && <GitPanel />}

          {/* Global DesktopViewer — accessible from any page */}
          {desktopPanelOpen && <DesktopViewer config={config} />}
        </div>

        <ToastProvider />
      </div>
    </WebSocketProvider>
  );
}
