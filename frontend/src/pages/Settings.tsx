import { useState, useEffect } from 'react';
import { Sun, Moon, Monitor, Shield, Brain, Cpu, RefreshCw, CheckCircle2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { useUIStore } from '../stores/ui';
import GlassCard from '../components/common/GlassCard';
import Badge from '../components/common/Badge';
import { api } from '../lib/api';
import type { AppConfig, HealthStatus } from '../lib/types';

export default function Settings() {
  const { theme, setTheme } = useUIStore();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.getConfig().catch(() => null),
      api.getHealth().catch(() => null),
    ]).then(([cfg, hp]) => {
      setConfig(cfg);
      setHealth(hp);
      setLoading(false);
    });
  }, []);

  const refreshHealth = async () => {
    setLoading(true);
    try {
      const hp = await api.getHealth();
      setHealth(hp);
    } catch {}
    setLoading(false);
  };

  return (
    <div className="max-w-screen-lg mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text)]">Settings</h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">Workspace configuration and system information</p>
      </div>

      {/* Theme */}
      <GlassCard>
        <h3 className="text-sm font-semibold text-[var(--text)] mb-4 flex items-center gap-2">
          <Monitor className="w-4 h-4" /> Appearance
        </h3>
        <div className="flex gap-3">
          {(['light', 'dark'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTheme(t)}
              className={`flex items-center gap-2 px-4 py-3 rounded-xl border transition-all ${
                theme === t
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                  : 'border-[var(--border)] hover:bg-[var(--surface-1)]'
              }`}
            >
              {t === 'light' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
              <span className="text-sm font-medium text-[var(--text)] capitalize">{t}</span>
              {theme === t && <CheckCircle2 className="w-4 h-4 text-[var(--accent)]" />}
            </button>
          ))}
        </div>
      </GlassCard>

      {/* Model Configuration */}
      <GlassCard>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
              <Cpu className="w-4 h-4" /> Model Configuration
            </h3>
            <p className="text-[10px] text-[var(--text-muted)] mt-0.5 ml-6">Read-only — configured via environment variables</p>
          </div>
          <button onClick={refreshHealth} className="p-1.5 rounded-lg hover:bg-[var(--surface-1)] text-[var(--text-muted)]">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="bg-[var(--surface-1)] rounded-lg p-3">
            <p className="text-xs text-[var(--text-muted)] mb-1">Primary Model</p>
            <p className="text-sm font-medium text-[var(--text)]">{health?.model ?? config?.model ?? 'Loading...'}</p>
          </div>
          <div className="bg-[var(--surface-1)] rounded-lg p-3">
            <p className="text-xs text-[var(--text-muted)] mb-1">Auth Method</p>
            <Badge variant={health?.auth_method === 'subscription' ? 'success' : 'accent'}>
              {health?.auth_method ?? 'Unknown'}
            </Badge>
          </div>
          <div className="bg-[var(--surface-1)] rounded-lg p-3">
            <p className="text-xs text-[var(--text-muted)] mb-1">Workspace</p>
            <p className="text-sm font-mono text-[var(--text)]">{health?.workspace ?? '~'}</p>
          </div>
          <div className="bg-[var(--surface-1)] rounded-lg p-3">
            <p className="text-xs text-[var(--text-muted)] mb-1">Version</p>
            <p className="text-sm text-[var(--text)]">{health?.version ?? '—'}</p>
          </div>
        </div>
      </GlassCard>

      {/* Safety */}
      <GlassCard>
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
            <Shield className="w-4 h-4" /> Safety & Audit
          </h3>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 ml-6">View only — these settings are system-managed</p>
        </div>
        <div className="space-y-2 text-sm text-[var(--text-muted)]">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-[var(--success)]" />
            <span>Dangerous command blocking (Bash safety hooks)</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-[var(--success)]" />
            <span>Pre/post tool audit logging</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-[var(--success)]" />
            <span>Soft-delete for memory audit trail</span>
          </div>
        </div>
      </GlassCard>

      {/* Memory Categories */}
      <GlassCard>
        <div className="mb-4">
          <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
            <Brain className="w-4 h-4" /> Memory Categories
          </h3>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 ml-6">Read-only — configured via environment variables</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {(config?.memory_categories ?? [
            'user_profile', 'project_context', 'analysis_decision',
            'methodology_note', 'best_practice', 'escalation_record',
          ]).map(cat => (
            <Badge key={cat} variant="muted">{cat}</Badge>
          ))}
        </div>
      </GlassCard>

      {/* About */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="text-center text-xs text-[var(--text-muted)] py-4"
      >
        CGIAR Innovation Analytics &middot; Powered by Claude Agent SDK
      </motion.div>
    </div>
  );
}
