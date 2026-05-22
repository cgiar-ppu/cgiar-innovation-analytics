import { Routes, Route } from 'react-router-dom';
import Layout from './components/layout/Layout';
import CommandPalette from './components/layout/CommandPalette';
import Dashboard from './pages/Dashboard';
import Chat from './pages/Chat';
import Agents from './pages/Agents';
import Workflows from './pages/Workflows';
import Fleet from './pages/Fleet';
import Files from './pages/Files';
import Settings from './pages/Settings';
import ErrorBoundary from './components/common/ErrorBoundary';

export default function App() {
  return (
    <ErrorBoundary>
      <>
        <CommandPalette />
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/agents" element={<Agents />} />
            <Route path="/workflows" element={<Workflows />} />
            <Route path="/fleet" element={<Fleet />} />
            <Route path="/files" element={<Files />} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </>
    </ErrorBoundary>
  );
}
