import { motion } from 'framer-motion';
import { ArrowRight, Loader2 } from 'lucide-react';
import type { StepState } from '../../hooks/usePipelineExecution';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function stepStatusColor(status: StepState['status']): string {
  switch (status) {
    case 'completed': return 'var(--success)';
    case 'running':   return 'var(--accent)';
    case 'failed':    return 'var(--danger)';
    case 'cancelled': return 'var(--warning)';
    default:          return 'var(--text-muted)';
  }
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface PipelineStatusBarProps {
  agentSequence: string[];
  steps: StepState[];
  expandedSteps: Record<number, boolean>;
  progressPct: number;
  onToggleStep: (idx: number) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PipelineStatusBar({
  agentSequence,
  steps,
  expandedSteps,
  progressPct,
  onToggleStep,
}: PipelineStatusBarProps) {
  const agentCount = agentSequence.length;

  return (
    <div
      className="px-5 py-4"
      style={{ borderBottom: '1px solid var(--border)' }}
    >
      {/* Horizontal step indicators */}
      <div className="flex items-center gap-1 overflow-x-auto pb-1">
        {agentSequence.map((_agentId, idx) => {
          const step = steps[idx];
          if (!step) return null;
          const color = stepStatusColor(step.status);
          const isActive = step.status === 'running';
          const isDone = step.status === 'completed';

          return (
            <div key={`step-ind-${idx}`} className="flex items-center shrink-0">
              <button
                onClick={() => onToggleStep(idx)}
                className="flex items-center gap-2 px-3 py-2 rounded-lg transition-colors hover:bg-[var(--surface-1)]"
                style={{
                  border: `1px solid color-mix(in srgb, ${color} 25%, var(--border))`,
                  background: expandedSteps[idx] ? 'var(--surface-1)' : 'transparent',
                }}
              >
                {/* Status dot */}
                <div
                  className="w-2.5 h-2.5 rounded-full shrink-0"
                  style={{
                    background: color,
                    boxShadow: isActive ? `0 0 6px ${color}` : 'none',
                  }}
                />
                <div className="text-left">
                  <div className="text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
                    Step {idx + 1}
                  </div>
                  <div className="text-xs font-medium whitespace-nowrap" style={{ color: 'var(--text)' }}>
                    {step.agent_name}
                  </div>
                </div>
                {isDone && step.durationS != null && (
                  <span className="text-[9px] font-mono ml-1" style={{ color: 'var(--success)' }}>
                    {step.durationS.toFixed(1)}s
                  </span>
                )}
                {isActive && (
                  <Loader2
                    className="w-3 h-3 animate-spin ml-1"
                    style={{ color: 'var(--accent)' }}
                  />
                )}
              </button>
              {idx < agentCount - 1 && (
                <ArrowRight className="w-4 h-4 mx-1 shrink-0" style={{ color: 'var(--border)' }} />
              )}
            </div>
          );
        })}
      </div>

      {/* Overall progress bar */}
      <div
        className="mt-3 w-full h-1 rounded-full overflow-hidden"
        style={{ background: 'var(--surface-1)' }}
      >
        <motion.div
          className="h-full rounded-full"
          style={{ background: 'var(--accent)' }}
          initial={{ width: '0%' }}
          animate={{ width: `${progressPct}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
      </div>
    </div>
  );
}
