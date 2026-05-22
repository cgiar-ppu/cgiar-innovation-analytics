import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard, MessageSquare, Bot, Network,
  Settings, Search, Command
} from 'lucide-react';
import { useUIStore } from '../../stores/ui';

const COMMANDS = [
  { id: 'chat', label: 'Go to Chat', icon: MessageSquare, path: '/chat', shortcut: '⌘1' },
  { id: 'dashboard', label: 'Go to Dashboard', icon: LayoutDashboard, path: '/', shortcut: '⌘2' },
  { id: 'agents', label: 'Go to Agents', icon: Bot, path: '/agents', shortcut: '⌘3' },
  // { id: 'workflows', label: 'Go to Workflows', icon: GitBranch, path: '/workflows', shortcut: '⌘4' },  // temporarily hidden
  { id: 'fleet', label: 'Go to Fleet', icon: Network, path: '/fleet', shortcut: '⌘4' },
  // { id: 'files', label: 'Go to Files', icon: FolderOpen, path: '/files', shortcut: '⌘6' },              // temporarily hidden
  { id: 'settings', label: 'Go to Settings', icon: Settings, path: '/settings', shortcut: '⌘5' },
];

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const filtered = COMMANDS.filter(c =>
    c.label.toLowerCase().includes(query.toLowerCase())
  );

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
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
    // Number shortcuts
    if ((e.metaKey || e.ctrlKey) && e.key >= '1' && e.key <= '5') {
      e.preventDefault();
      const idx = parseInt(e.key) - 1;
      if (COMMANDS[idx]) {
        navigate(COMMANDS[idx].path);
        setOpen(false);
      }
    }
    if (e.key === 'Escape') setOpen(false);
  }, [navigate]);

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
                  <span className="text-xs text-[var(--text-muted)]">{cmd.shortcut}</span>
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
