import { NavLink, useLocation } from 'react-router-dom';
import { useState, useEffect, useRef, useCallback } from 'react';
import { LayoutDashboard, MessageSquare, Bot, Settings, Sparkles, Search, Menu, ChevronRight } from 'lucide-react';
import { motion } from 'framer-motion';
import { useWebSocketContext } from '../../contexts/WebSocketContext';
import { useUIStore } from '../../stores/ui';
import { ThemeToggle } from './ThemeToggle';
import { TTSToggle } from '../chat/TTSToggle';
import { ModelSelector } from './ModelSelector';
import { UserMenu } from './UserMenu';
import { useIsAdmin } from '../../stores/appConfig';
import type { AppConfig } from '../../lib/types';

/** `adminOnly` items are hidden for researchers / invited users (L4-03). */
export const NAV_ITEMS = [
  { to: '/chat', label: 'Chat', icon: MessageSquare, adminOnly: false },
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, adminOnly: false },
  { to: '/agents', label: 'Agents', icon: Bot, adminOnly: true },
  { to: '/settings', label: 'Settings', icon: Settings, adminOnly: false },
];

interface TopBarProps {
  config: AppConfig | null;
}

export default function TopBar({ config }: TopBarProps) {
  const location = useLocation();
  const { connectionStatus } = useWebSocketContext();
  const { toggleSidebar } = useUIStore();
  const isAdmin = useIsAdmin();
  const navItems = NAV_ITEMS.filter((item) => isAdmin || !item.adminOnly);
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
        <div className="flex items-center gap-2.5 mr-6">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[#427730] to-[#7AB800] flex items-center justify-center shadow-sm">
            <Sparkles className="w-4 h-4 text-white" />
          </div>
          <div className="hidden sm:flex flex-col">
            <span className="font-bold text-[var(--text)] text-sm leading-tight tracking-tight font-serif">CGIAR</span>
            <span className="text-[10px] text-[var(--text-muted)] leading-tight">Innovation Analytics</span>
          </div>
        </div>

        {/* Navigation Pills with scroll indicator */}
        <div className="relative flex-1 min-w-0">
          <nav ref={navRef} className="flex items-center gap-1 overflow-x-auto scrollbar-thin">
            {navItems.map(({ to, label, icon: Icon }) => {
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
          {/* Model selector pill — only when the caller may choose between models */}
          <ModelSelector config={config} />

          {/* Connection status — minimal dot indicator */}
          <div className="flex items-center gap-1.5 text-[11px] text-[var(--text-muted)] px-2 py-1 rounded-full border border-[var(--border)]" title={statusText}>
            <span className={`w-1.5 h-1.5 rounded-full ${statusColor}`} />
            <span className="hidden sm:inline">{statusText}</span>
          </div>

          {/* Search button */}
          <button
            onClick={() => useUIStore.getState().toggleSearch()}
            className="p-2 rounded-xl hover:bg-[var(--surface-2)] transition-all text-[var(--text-muted)] hover:text-[var(--text)]"
            title="Search (Cmd+K)"
            aria-label="Search chats"
          >
            <Search className="w-4 h-4" />
          </button>

          {/* TTS toggle */}
          <TTSToggle />

          {/* Theme toggle */}
          <ThemeToggle />

          {/* Account menu — user email + sign out (only when a real session exists) */}
          <UserMenu />
        </div>
      </div>
    </header>
  );
}
