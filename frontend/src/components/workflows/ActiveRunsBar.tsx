/**
 * @file ActiveRunsBar.tsx
 * @module components/workflows
 *
 * Compact horizontal bar showing all active and recently completed workflow
 * runs as clickable chips. Each chip shows the workflow name, a live status
 * indicator, and elapsed duration. Clicking a chip sets it as the active run.
 */

import { useEffect, useState } from 'react';
import { Loader2, CheckCircle2, XCircle, Ban } from 'lucide-react';
import { useWorkflowRunsStore, type RunStatus } from '../../stores/workflowRuns';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function statusIcon(status: RunStatus) {
  switch (status) {
    case 'running':
      return <Loader2 className="w-3 h-3 animate-spin" style={{ color: 'var(--accent)' }} />;
    case 'completed':
      return <CheckCircle2 className="w-3 h-3" style={{ color: 'var(--success)' }} />;
    case 'failed':
      return <XCircle className="w-3 h-3" style={{ color: 'var(--danger)' }} />;
    case 'cancelled':
      return <Ban className="w-3 h-3" style={{ color: 'var(--warning)' }} />;
    default:
      return <div className="w-2 h-2 rounded-full" style={{ background: 'var(--text-muted)' }} />;
  }
}

function statusDotColor(status: RunStatus): string {
  switch (status) {
    case 'running':   return 'var(--accent)';
    case 'completed': return 'var(--success)';
    case 'failed':    return 'var(--danger)';
    case 'cancelled': return 'var(--warning)';
    default:          return 'var(--text-muted)';
  }
}

function formatDuration(startedAt: number, totalDurationS: number | null): string {
  if (totalDurationS !== null) {
    return `${totalDurationS.toFixed(1)}s`;
  }
  const elapsed = Math.floor((Date.now() - startedAt) / 1000);
  if (elapsed < 60) return `${elapsed}s`;
  const mins = Math.floor(elapsed / 60);
  const secs = elapsed % 60;
  return `${mins}m ${secs}s`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ActiveRunsBar() {
  const runs = useWorkflowRunsStore(s => s.runs);
  const activeRunId = useWorkflowRunsStore(s => s.activeRunId);
  const setActiveRun = useWorkflowRunsStore(s => s.setActiveRun);

  // Force re-render every second to update live duration counters
  const [, setTick] = useState(0);
  const hasRunning = Object.values(runs).some(r => r.status === 'running');
  useEffect(() => {
    if (!hasRunning) return;
    const interval = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(interval);
  }, [hasRunning]);

  const runList = Object.values(runs);
  if (runList.length === 0) return null;

  return (
    <div
      className="shrink-0 px-6 py-2 flex items-center gap-2 overflow-x-auto"
      style={{ borderBottom: '1px solid var(--border)' }}
    >
      <span className="text-[10px] font-semibold uppercase tracking-wider shrink-0" style={{ color: 'var(--text-muted)' }}>
        Runs
      </span>

      {runList.map(run => {
        const isActive = run.runId === activeRunId;
        const borderColor = isActive
          ? statusDotColor(run.status)
          : 'var(--border)';

        return (
          <button
            key={run.runId}
            onClick={() => setActiveRun(run.runId)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all hover:bg-[var(--surface-1)] shrink-0"
            style={{
              border: `1px solid ${borderColor}`,
              background: isActive ? 'var(--surface-1)' : 'transparent',
            }}
          >
            {statusIcon(run.status)}

            <span
              className="font-medium truncate max-w-[120px]"
              style={{ color: 'var(--text)' }}
            >
              {run.workflowName || 'Workflow'}
            </span>

            <span
              className="font-mono text-[10px]"
              style={{ color: 'var(--text-muted)' }}
            >
              {formatDuration(run.startedAt, run.totalDurationS)}
            </span>

            {run.status === 'running' && (
              <div
                className="w-1.5 h-1.5 rounded-full animate-pulse"
                style={{ background: 'var(--accent)' }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
