import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useRef, useCallback } from 'react';
import { LayoutDashboard, MessageSquare, Bot, Network, Settings, Sparkles, Wifi, WifiOff, Monitor, Search, Menu, Code2, ChevronRight } from 'lucide-react';
import { motion } from 'framer-motion';
import { useWebSocketContext } from '../../contexts/WebSocketContext';
import { useUIStore } from '../../stores/ui';
import { ThemeToggle } from './ThemeToggle';
import { TTSToggle } from '../chat/TTSToggle';
import type { AppConfig } from '../../lib/types';

const NAV_ITEMS = [
  { to: '/chat', label: 'Chat', icon: MessageSquare },
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/agents', label: 'Agents', icon: Bot },
  // { to: '/workflows', label: 'Workflows', icon: GitBranch },  // temporarily hidden
  { to: '/fleet', label: 'Fleet', icon: Network },
  // { to: '/files', label: 'Files', icon: FolderOpen },          // temporarily hidden
  { to: '/settings', label: 'Settings', icon: Settings },
];

interface TopBarProps {
  config: AppConfig | null;
}

export default function TopBar({ config }: TopBarProps) {
  const location = useLocation();
  const { connectionStatus } = useWebSocketContext();
  const { desktopPanelOpen, toggleDesktopPanel, gitPanelOpen, toggleGitPanel, toggleSidebar } = useUIStore();
  const navRef = useRef<HTMLElement>(null);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const checkScroll = useCallback(() => {
    const el = navRef.current;
    if (!el) return;
    setCanScrollRight(el.scrollWidth - el.scrollLeft - el.clientWidth > 4);
  }, []);

  useEffect(() => {
    const el = navRef.current;
    if (!el) return;
    checkScroll();
    el.addEventListener('scroll', checkScroll, { passive: true });
    window.addEventListener('resize', checkScroll);
    return () => {
      el.removeEventListener('scroll', checkScroll);
      window.removeEventListener('resize', checkScroll);
    };
  }, [checkScroll]);

  const statusColor =
    connectionStatus === 'connected' ? 'bg-[var(--success)]' :
    connectionStatus === 'connecting' ? 'bg-[var(--warning)]' :
    'bg-[var(--danger)]';

  const statusText =
    connectionStatus === 'connected' ? 'Connected' :
    connectionStatus === 'connecting' ? 'Connecting...' :
    connectionStatus === 'error' ? 'Error' :
    'Reconnecting...';

  return (
    <header className="sticky top-0 z-40 glass-strong border-b border-[var(--border)]">
      <div className="flex items-center justify-between h-14 px-4 max-w-screen-2xl mx-auto">
        {/* Mobile sidebar toggle */}
        <button
          onClick={toggleSidebar}
          className="p-2 -ml-1 mr-1 rounded-xl hover:bg-[var(--surface-2)] transition-colors text-[var(--text-muted)] hover:text-[var(--text)] md:hidden"
          aria-label="Toggle sidebar"
        >
          <Menu className="w-5 h-5" />
        </button>

        {/* Logo */}
        <div className="flex items-center gap-2 mr-6">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <span className="font-semibold text-[var(--text)] text-lg hidden sm:block">Innovation Analytics</span>
        </div>

        {/* Navigation Pills with scroll indicator */}
        <div className="relative flex-1 min-w-0">
          <nav ref={navRef} className="flex items-center gap-1 overflow-x-auto scrollbar-thin">
            {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
              const isActive = to === '/' ? location.pathname === '/' : location.pathname.startsWith(to);
              return (
                <NavLink
                  key={to}
                  to={to}
                  className="relative flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap"
                >
                  {isActive && (
                    <motion.div
                      layoutId="nav-pill"
                      className="absolute inset-0 rounded-lg bg-[var(--accent)]/15 border border-[var(--accent)]/30"
                      transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }}
                    />
                  )}
                  <Icon className={`w-4 h-4 relative z-10 ${isActive ? 'text-[var(--accent)]' : 'text-[var(--text-muted)]'}`} />
                  <span className={`relative z-10 hidden md:inline ${isActive ? 'text-[var(--accent)]' : 'text-[var(--text-muted)] hover:text-[var(--text)]'}`}>
                    {label}
                  </span>
                </NavLink>
              );
            })}
          </nav>
          {/* Mobile scroll-right hint: gradient fade + chevron */}
          {canScrollRight && (
            <div className="absolute right-0 top-0 bottom-0 flex items-center pointer-events-none md:hidden">
              <div className="w-8 h-full bg-gradient-to-l from-[var(--surface-0)] to-transparent" />
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-[var(--text-muted)]"
              >
                <ChevronRight className="w-4 h-4" />
              </motion.div>
            </div>
          )}
        </div>

        {/* Right side: status, controls */}
        <div className="flex items-center gap-2 ml-4">
          {/* Model badge */}
          {config && (
            <span className="text-[11px] px-2.5 py-1 rounded-full glass text-[var(--text-muted)] hidden md:inline-block font-mono">
              {config.model}
            </span>
          )}

          {/* Auth method badge */}
          {config && (
            <span className={`text-[11px] px-2.5 py-1 rounded-full font-medium hidden sm:inline-block ${
              config.auth_method === 'subscription'
                ? 'bg-[var(--success)]/15 text-[var(--success)]'
                : config.auth_method === 'api_key'
                ? 'bg-[var(--accent)]/15 text-[var(--accent)]'
                : 'bg-[var(--danger)]/15 text-[var(--danger)]'
            }`}>
              {config.auth_method === 'subscription' ? 'Pro' : config.auth_method === 'api_key' ? 'API' : 'No Auth'}
            </span>
          )}

          {/* Connection status */}
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] px-2 py-1 rounded-full glass">
            {connectionStatus === 'connected' ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            <span className={`w-1.5 h-1.5 rounded-full ${statusColor}`} />
            <span className="hidden sm:inline">{statusText}</span>
          </div>

          {/* Search button */}
          <button
            onClick={() => useUIStore.getState().toggleSearch()}
            className="p-2 rounded-xl hover:bg-[var(--surface-2)] transition-all text-[var(--text-muted)] hover:text-[var(--text)]"
            title="Search (Cmd+K)"
          >
            <Search className="w-4 h-4" />
          </button>

          {/* TTS toggle */}
          <TTSToggle />

          {/* Theme toggle */}
          <ThemeToggle />

          {/* Git panel toggle */}
          <button
            onClick={toggleGitPanel}
            className={`p-2 rounded-xl transition-all ${
              gitPanelOpen
                ? 'bg-[var(--accent)] text-white shadow-sm'
                : 'hover:bg-[var(--surface-2)] text-[var(--text-muted)]'
            }`}
            title={gitPanelOpen ? 'Hide git panel' : 'Show git panel'}
          >
            <Code2 className="w-4 h-4" />
          </button>

          {/* Desktop panel toggle */}
          {config?.vnc_available && (
            <button
              onClick={toggleDesktopPanel}
              className={`p-2 rounded-xl transition-all ${
                desktopPanelOpen
                  ? 'bg-[var(--accent)] text-white shadow-sm'
                  : 'hover:bg-[var(--surface-2)] text-[var(--text-muted)]'
              }`}
              title={desktopPanelOpen ? 'Hide desktop' : 'Show desktop'}
            >
              <Monitor className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
