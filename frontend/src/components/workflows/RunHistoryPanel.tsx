import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Clock, ChevronDown, ChevronRight, Download,
  MessageSquare, RefreshCw, FileText, FileCode, FileJson,
} from 'lucide-react';
import Badge from '../common/Badge';
import RunDetailView from './RunDetailView';
import { stepStatusColor, stepBadgeVariant } from './workflowAgentUtils';
import { workflowsService } from '../../services/workflows';
import { useSessionsStore } from '../../stores/sessions';
import type { WorkflowRunSummary } from '../../lib/types-extended';

// ── Helpers ──────────────────────────────────────────────────────────────────

function formatDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ── Download dropdown ────────────────────────────────────────────────────────

function DownloadMenu({
  workflowId,
  runId,
}: {
  workflowId: string;
  runId: string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const handleDownload = async (format: string) => {
    setOpen(false);
    await workflowsService.downloadWorkflowRun(workflowId, runId, format);
  };

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(o => !o); }}
        className="p-1.5 rounded-md hover:bg-[var(--surface-1)] transition-colors"
        style={{ color: 'var(--text-muted)' }}
        title="Download"
      >
        <Download className="w-3.5 h-3.5" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="absolute right-0 top-full mt-1 z-50 bg-[var(--surface-2)] border border-[var(--border)] rounded-lg shadow-lg overflow-hidden min-w-[140px]"
          >
            {[
              { format: 'json', label: 'JSON', Icon: FileJson },
              { format: 'md',   label: 'Markdown', Icon: FileText },
              { format: 'html', label: 'HTML', Icon: FileCode },
            ].map(({ format, label, Icon }) => (
              <button
                key={format}
                onClick={(e) => { e.stopPropagation(); handleDownload(format); }}
                className="flex items-center gap-2 w-full px-3 py-2 text-xs hover:bg-[var(--surface-1)] transition-colors"
                style={{ color: 'var(--text)' }}
              >
                <Icon className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
                {label}
              </button>
            ))}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Run card ─────────────────────────────────────────────────────────────────

function RunCard({
  run,
  workflowId,
  isExpanded,
  onToggle,
}: {
  run: WorkflowRunSummary;
  workflowId: string;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const [continuing, setContinuing] = useState(false);
  const navigate = useNavigate();
  const { setActiveSession, loadSessions } = useSessionsStore();

  const handleContinue = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setContinuing(true);
    try {
      const { session_id } = await workflowsService.continueFromRun(workflowId, run.id);
      // Reload sessions so the new one appears in the sidebar
      await loadSessions();
      // Set the new session as active and navigate to the Chat page
      setActiveSession(session_id);
      navigate('/chat');
    } catch {
      // Silently fail -- the button will reset
    } finally {
      setContinuing(false);
    }
  };

  return (
    <div
      className="rounded-xl overflow-hidden border border-[var(--border)] transition-colors"
      style={{
        background: isExpanded
          ? 'color-mix(in srgb, var(--surface-1) 80%, transparent)'
          : 'transparent',
      }}
    >
      {/* Compact header */}
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-[var(--surface-1)] transition-colors"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          {/* Status dot */}
          <div
            className="w-2 h-2 rounded-full shrink-0"
            style={{ background: stepStatusColor(run.status) }}
          />

          {/* Date */}
          <span className="text-[11px] font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
            {formatDate(run.started_at)}
          </span>

          <Badge variant={stepBadgeVariant(run.status)} size="sm">
            {run.status}
          </Badge>

          {/* Duration */}
          {run.total_duration_s != null && (
            <span
              className="flex items-center gap-1 text-[10px] font-mono shrink-0"
              style={{ color: 'var(--text-muted)' }}
            >
              <Clock className="w-2.5 h-2.5" />
              {run.total_duration_s.toFixed(1)}s
            </span>
          )}

          {/* Cost */}
          {run.total_cost_usd != null && run.total_cost_usd > 0 && (
            <span className="text-[10px] font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
              ${run.total_cost_usd.toFixed(4)}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 shrink-0">
          <DownloadMenu workflowId={workflowId} runId={run.id} />

          {run.status === 'completed' && (
            <button
              onClick={handleContinue}
              disabled={continuing}
              className="p-1.5 rounded-md hover:bg-[var(--surface-1)] transition-colors"
              style={{ color: 'var(--text-muted)' }}
              title="Continue in Chat"
            >
              <MessageSquare className="w-3.5 h-3.5" />
            </button>
          )}

          {isExpanded
            ? <ChevronDown className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
            : <ChevronRight className="w-3.5 h-3.5" style={{ color: 'var(--text-muted)' }} />
          }
        </div>
      </button>

      {/* Collapsed summary */}
      {!isExpanded && run.initial_prompt && (
        <div className="px-3 pb-2">
          <p className="text-[10px] line-clamp-1" style={{ color: 'var(--text-muted)' }}>
            {run.initial_prompt}
          </p>
        </div>
      )}

      {/* Expanded detail */}
      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 border-t border-[var(--border)]">
              <RunDetailView workflowId={workflowId} runId={run.id} />
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Main panel ───────────────────────────────────────────────────────────────

interface RunHistoryPanelProps {
  workflowId: string;
}

export default function RunHistoryPanel({ workflowId }: RunHistoryPanelProps) {
  const [runs, setRuns] = useState<WorkflowRunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  const fetchRuns = async () => {
    setLoading(true);
    try {
      const { runs: data } = await workflowsService.getWorkflowRuns(workflowId);
      setRuns(data);
    } catch {
      // Silently degrade
      setRuns([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
    setExpandedRunId(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflowId]);

  if (loading) {
    return (
      <div className="glass rounded-xl border border-[var(--border)] p-4">
        <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
          <RefreshCw className="w-3.5 h-3.5 animate-spin" />
          Loading run history...
        </div>
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div className="glass rounded-xl border border-[var(--border)] p-4">
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          No runs yet. Execute the pipeline to see run history here.
        </p>
      </div>
    );
  }

  return (
    <div className="glass rounded-xl border border-[var(--border)] p-4 space-y-2">
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-semibold text-[var(--text)]">
          Run History
        </h4>
        <button
          onClick={fetchRuns}
          className="p-1 rounded hover:bg-[var(--surface-1)] transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-3 h-3" style={{ color: 'var(--text-muted)' }} />
        </button>
      </div>

      {/* Run list */}
      <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
        {runs.map(run => (
          <RunCard
            key={run.id}
            run={run}
            workflowId={workflowId}
            isExpanded={expandedRunId === run.id}
            onToggle={() => setExpandedRunId(prev => prev === run.id ? null : run.id)}
          />
        ))}
      </div>
    </div>
  );
}
