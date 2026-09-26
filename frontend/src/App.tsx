import { lazy, Suspense, type ReactNode } from 'react';
import { Routes, Route } from 'react-router-dom';
import Layout from './components/layout/Layout';
import CommandPalette from './components/layout/CommandPalette';
import Dashboard from './pages/Dashboard';
import Chat from './pages/Chat';
import Settings from './pages/Settings';
import NotFound from './pages/NotFound';
import ErrorBoundary from './components/common/ErrorBoundary';
import { useIsAdmin } from './stores/appConfig';

// Admin-only page, loaded on demand (not part of the researchers' bundle path).
const Agents = lazy(() => import('./pages/Agents'));

/** Renders children for administrators, the 404 page for everyone else. */
export function AdminOnly({ children }: { children: ReactNode }) {
  return useIsAdmin() ? <>{children}</> : <NotFound />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <>
        <CommandPalette />
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/chat" element={<Chat />} />
            <Route
              path="/agents"
              element={<AdminOnly><Suspense fallback={null}><Agents /></Suspense></AdminOnly>}
            />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </>
    </ErrorBoundary>
  );
}
