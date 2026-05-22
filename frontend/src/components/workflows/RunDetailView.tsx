import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, ChevronRight, AlertTriangle,
  CheckCircle2, Clock, Circle, RefreshCw,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import Badge from '../common/Badge';
import PipelineMessageRenderer from './PipelineMessageRenderer';
import { stepBadgeVariant } from './workflowAgentUtils';
import { workflowsService } from '../../services/workflows';
import type { WorkflowRunDetail, WorkflowRunStep } from '../../lib/types-extended';

// ── Helpers ──────────────────────────────────────────────────────────────────

function stepStatusIcon(status: string) {
  switch (status) {
    case 'completed':
      return <CheckCircle2 className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--success)' }} />;
    case 'failed':
      return <AlertTriangle className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--danger)' }} />;
    default:
      return <Circle className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--text-muted)' }} />;
  }
}

function guessStepStatus(step: WorkflowRunStep): string {
  if (step.error) return 'failed';
  if (step.completed_at) return 'completed';
  return 'pending';
}

// ── Step card ────────────────────────────────────────────────────────────────

function RunStepCard({
  step,
  stepIdx,
  totalSteps,
}: {
  step: WorkflowRunStep;
  stepIdx: number;
  totalSteps: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const status = guessStepStatus(step);
  const borderColor = `color-mix(in srgb, ${
    status === 'completed' ? 'var(--success)'
    : status === 'failed' ? 'var(--danger)'
    : 'var(--text-muted)'
  } 25%, var(--border))`;

  return (
    <div className="rounded-xl overflow-hidden" style={{ border: `1px solid ${borderColor}` }}>
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-3 py-2.5 transition-colors hover:bg-[var(--surface-1)]"
      >
        <div className="flex items-center gap-2.5 min-w-0">
          {stepStatusIcon(status)}
          <span className="text-xs font-semibold truncate" style={{ color: 'var(--text)' }}>
            {step.agent_name}
          </span>
          <span className="text-[10px] font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
            Step {stepIdx + 1}/{totalSteps}
          </span>
          {step.duration_s != null && (
            <span className="flex items-center gap-1 text-[10px] font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
              <Clock className="w-3 h-3" />
              {step.duration_s.toFixed(1)}s
            </span>
          )}
          <Badge variant={stepBadgeVariant(status)} size="sm">{status}</Badge>
        </div>
        {expanded
          ? <ChevronDown className="w-4 h-4 shrink-0" style={{ color: 'var(--text-muted)' }} />
          : <ChevronRight className="w-4 h-4 shrink-0" style={{ color: 'var(--text-muted)' }} />
        }
      </button>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-2 max-h-96 overflow-y-auto">
              {step.messages.length > 0 ? (
                step.messages.map((msg) => (
                  <PipelineMessageRenderer key={msg.id} msg={msg} />
                ))
              ) : step.output_text ? (
                <div className="px-3 py-2 rounded-xl text-sm glass" style={{ color: 'var(--text)' }}>
                  <div
                    className="prose prose-sm max-w-none [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5 [&_pre]:my-1 [&_code]:text-[var(--accent)]"
                    style={{ color: 'var(--text)' }}
                  >
                    <ReactMarkdown>{step.output_text}</ReactMarkdown>
                  </div>
                </div>
              ) : (
                <p className="text-[10px] px-3 py-1" style={{ color: 'var(--text-muted)' }}>
                  No messages recorded for this step.
                </p>
              )}

              {step.error && (
                <div
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
                  style={{
                    background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
                    color: 'var(--danger)',
                  }}
                >
                  <AlertTriangle className="w-3 h-3 shrink-0" />
                  {step.error}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Collapsed output preview */}
      {!expanded && step.output_text && (
        <div className="px-3 pb-2.5">
          <p className="text-[10px] line-clamp-2" style={{ color: 'var(--text-muted)' }}>
            {step.output_text.slice(0, 200)}
          </p>
        </div>
      )}
    </div>
  );
}

// ── Main component ───────────────────────────────────────────────────────────

interface RunDetailViewProps {
  workflowId: string;
  runId: string;
}

export default function RunDetailView({ workflowId, runId }: RunDetailViewProps) {
  const [detail, setDetail] = useState<WorkflowRunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    workflowsService
      .getWorkflowRunDetail(workflowId, runId)
      .then(d => { if (!cancelled) setDetail(d); })
      .catch(e => { if (!cancelled) setError(e.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [workflowId, runId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-xs" style={{ color: 'var(--text-muted)' }}>
        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
        Loading run details...
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="flex items-center gap-2 py-4 text-xs" style={{ color: 'var(--danger)' }}>
        <AlertTriangle className="w-3.5 h-3.5" />
        {error || 'Run not found'}
      </div>
    );
  }

  const steps = detail.steps ?? [];

  return (
    <div className="pt-3 space-y-3">
      {/* Metadata row */}
      <div className="flex items-center gap-3 flex-wrap text-[10px] font-mono" style={{ color: 'var(--text-muted)' }}>
        <span>{steps.length} step{steps.length !== 1 ? 's' : ''}</span>
        {detail.total_duration_s != null && (
          <span className="flex items-center gap-1">
            <Clock className="w-2.5 h-2.5" />
            {detail.total_duration_s.toFixed(1)}s
          </span>
        )}
        {detail.total_cost_usd != null && detail.total_cost_usd > 0 && (
          <span>${detail.total_cost_usd.toFixed(4)}</span>
        )}
      </div>

      {/* Prompt preview */}
      {detail.initial_prompt && (
        <div className="rounded-lg bg-[var(--surface-1)] border border-[var(--border)] px-3 py-2">
          <p className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-0.5">
            Prompt
          </p>
          <p className="text-xs text-[var(--text)] line-clamp-2 leading-relaxed">
            {detail.initial_prompt}
          </p>
        </div>
      )}

      {/* Steps */}
      <div className="space-y-1.5">
        {steps.map((step, idx) => (
          <RunStepCard
            key={step.id}
            step={step}
            stepIdx={idx}
            totalSteps={steps.length}
          />
        ))}
      </div>
    </div>
  );
}
