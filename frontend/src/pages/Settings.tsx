import { useState, useEffect } from 'react';
import { Sun, Moon, Monitor, Cpu, RefreshCw, CheckCircle2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { useUIStore } from '../stores/ui';
import GlassCard from '../components/common/GlassCard';
import Badge from '../components/common/Badge';
import { api } from '../lib/api';
import type { HealthStatus } from '../lib/types';
import InvitationManager from '../components/guardrails/InvitationManager';
import UsagePanel from '../components/admin/UsagePanel';
import AdminFeedbackPanel from '../components/feedback/AdminFeedbackPanel';
import { useAppConfigStore, useIsAdmin } from '../stores/appConfig';

/**
 * Settings. Everyone gets Appearance. Administrators additionally get the
 * invitation manager, the Feedback panel, the usage/cost panel and the
 * deployment diagnostics (default model, selectable models, version). The Synapsis leftovers
 * ("Bash safety hooks", memory categories, workspace path) are gone (L4-09).
 */
export default function Settings() {
  const { theme, setTheme } = useUIStore();
  const config = useAppConfigStore((s) => s.config);
  const isAdmin = useIsAdmin();

  useEffect(() => { void useAppConfigStore.getState().load(); }, []);

  return (
    <div className="max-w-screen-lg mx-auto p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--text)]">Settings</h1>
        <p className="text-sm text-[var(--text-muted)] mt-1">
          {isAdmin ? 'Preferences, access and usage' : 'Your preferences'}
        </p>
      </div>

      {isAdmin && config?.invited_login_enabled && <InvitationManager />}
      {isAdmin && <AdminFeedbackPanel />}

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

      {isAdmin && <UsagePanel />}
      {isAdmin && <DeploymentCard />}

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="text-center text-xs text-[var(--text-muted)] py-4"
      >
        CGIAR Innovation Analytics{config?.version ? ` · version ${config.version}` : ''}
      </motion.div>
    </div>
  );
}

/** Administrators only: what this deployment runs (from /api/health + /api/config). */
function DeploymentCard() {
  const config = useAppConfigStore((s) => s.config);
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try { setHealth(await api.getHealth()); } catch { /* keep the last value */ }
    setLoading(false);
  };

  useEffect(() => { void refresh(); }, []);

  const policy = config?.model_policy;
  const models = (config?.selectable_models ?? []).map((m) => m.label).join(', ');

  return (
    <GlassCard>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-semibold text-[var(--text)] flex items-center gap-2">
            <Cpu className="w-4 h-4" /> Deployment
          </h3>
          <p className="text-[10px] text-[var(--text-muted)] mt-0.5 ml-6">Read-only — configured via environment variables</p>
        </div>
        <button onClick={refresh} className="p-1.5 rounded-lg hover:bg-[var(--surface-1)] text-[var(--text-muted)]" aria-label="Refresh deployment details">
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="bg-[var(--surface-1)] rounded-lg p-3">
          <p className="text-xs text-[var(--text-muted)] mb-1">Default model</p>
          <p className="text-sm font-medium text-[var(--text)]">{health?.model ?? config?.model ?? 'Loading...'}</p>
        </div>
        <div className="bg-[var(--surface-1)] rounded-lg p-3">
          <p className="text-xs text-[var(--text-muted)] mb-1">Models offered to administrators</p>
          <p className="text-sm text-[var(--text)]">{models || '—'}</p>
        </div>
        <div className="bg-[var(--surface-1)] rounded-lg p-3">
          <p className="text-xs text-[var(--text-muted)] mb-1">Cost ceilings (admin)</p>
          <p className="text-sm text-[var(--text)]">
            {policy?.max_budget_usd_per_turn != null ? `$${policy.max_budget_usd_per_turn.toFixed(2)} per question` : '—'}
            {policy ? ` · ${policy.max_turns} steps` : ''}
          </p>
        </div>
        <div className="bg-[var(--surface-1)] rounded-lg p-3">
          <p className="text-xs text-[var(--text-muted)] mb-1">Version</p>
          <p className="text-sm text-[var(--text)]">
            {health?.version ?? config?.version ?? '—'}
            {health?.git_sha && health.git_sha !== 'unknown' && (
              <Badge variant="muted">{health.git_sha.slice(0, 7)}</Badge>
            )}
          </p>
        </div>
      </div>
    </GlassCard>
  );
}
