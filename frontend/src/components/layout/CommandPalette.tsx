import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, MessageSquare, Bot,
  Settings, Search, Command
} from 'lucide-react';
import { useUIStore } from '../../stores/ui';
import { useAuthStore } from '../../stores/auth';
import { useIsAdmin } from '../../stores/appConfig';

// Only pages that exist. The number shortcuts (Ctrl/Cmd+1..5) were removed
// (L4-13): they took over the browser's own tab switching on every page, and
// "Go to Fleet" pointed at a page that no longer exists.
export const COMMANDS = [
  { id: 'chat', label: 'Go to Chat', icon: MessageSquare, path: '/chat', adminOnly: false },
  { id: 'dashboard', label: 'Go to Dashboard', icon: LayoutDashboard, path: '/', adminOnly: false },
  { id: 'agents', label: 'Go to Agents', icon: Bot, path: '/agents', adminOnly: true },
  { id: 'settings', label: 'Go to Settings', icon: Settings, path: '/settings', adminOnly: false },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const isAdmin = useIsAdmin();
  // Before "I understand" the app behind the disclaimer is inert: no shortcuts.
  const acknowledged = useAuthStore((s) => s.disclaimerAcknowledged || !s.authRequired);

  const filtered = COMMANDS.filter(c =>
    (isAdmin || !c.adminOnly) && c.label.toLowerCase().includes(query.toLowerCase())
  );

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (!acknowledged) return;
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      if (window.location.pathname.startsWith('/chat')) {
        useUIStore.getState().toggleSearch();
      } else {
        setOpen(prev => !prev);
        setQuery('');
        setSelectedIdx(0);
      }
    }
    if (e.key === 'Escape') setOpen(false);
  }, [acknowledged]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  const select = (path: string) => {
    navigate(path);
    setOpen(false);
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-start justify-center pt-[20vh]"
          onClick={() => setOpen(false)}
        >
          {/* Backdrop */}
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

          {/* Panel */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: -10 }}
            className="relative w-full max-w-lg mx-4 glass-strong rounded-xl border border-[var(--border)] shadow-2xl overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            {/* Search Input */}
            <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)]">
              <Search className="w-4 h-4 text-[var(--text-muted)]" />
              <input
                ref={inputRef}
                value={query}
                onChange={e => { setQuery(e.target.value); setSelectedIdx(0); }}
                onKeyDown={e => {
                  if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIdx(i => Math.min(i + 1, filtered.length - 1)); }
                  if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIdx(i => Math.max(i - 1, 0)); }
                  if (e.key === 'Enter' && filtered[selectedIdx]) select(filtered[selectedIdx].path);
                }}
                placeholder="Search commands..."
                className="flex-1 bg-transparent text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none text-sm"
              />
              <kbd className="text-xs text-[var(--text-muted)] bg-[var(--surface-1)] px-1.5 py-0.5 rounded border border-[var(--border)]">esc</kbd>
            </div>

            {/* Results */}
            <div className="max-h-64 overflow-y-auto py-1">
              {filtered.map((cmd, i) => (
                <button
                  key={cmd.id}
                  onClick={() => select(cmd.path)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm transition-colors ${
                    i === selectedIdx ? 'bg-[var(--accent)]/10 text-[var(--accent)]' : 'text-[var(--text)] hover:bg-[var(--surface-1)]'
                  }`}
                >
                  <cmd.icon className="w-4 h-4" />
                  <span className="flex-1 text-left">{cmd.label}</span>
                </button>
              ))}
              {filtered.length === 0 && (
                <div className="px-4 py-6 text-center text-sm text-[var(--text-muted)]">No results found</div>
              )}
            </div>

            {/* Footer hint */}
            <div className="flex items-center gap-4 px-4 py-2 border-t border-[var(--border)] text-xs text-[var(--text-muted)]">
              <span className="flex items-center gap-1"><Command className="w-3 h-3" />K to toggle</span>
              <span>↑↓ navigate</span>
              <span>↵ select</span>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
