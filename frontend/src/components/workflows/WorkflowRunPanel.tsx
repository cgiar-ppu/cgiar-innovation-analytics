/**
 * @file WorkflowRunPanel.tsx
 * @module components/workflows
 *
 * Inline panel (not a modal) that renders one workflow run's live output.
 * Reads from the workflowRuns Zustand store via the activeRunId. Displays
 * step cards with streaming content, a status bar, and cancel/close actions.
 */

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X, Square, Play, Clock, Loader2,
  CheckCircle2, AlertTriangle, ChevronDown, ChevronRight,
  Circle, Ban,
} from 'lucide-react';
import Badge from '../common/Badge';
import PipelineMessageRenderer from './PipelineMessageRenderer';
import { stepStatusColor, stepBadgeVariant } from './workflowAgentUtils';
import { useWorkflowRunsStore, type RunStepState, type RunStatus } from '../../stores/workflowRuns';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildStatusLabel(
  status: RunStatus,
  agentCount: number,
  totalDurationS: number | null,
): string {
  switch (status) {
    case 'pending':   return 'Starting...';
    case 'running':   return `Running pipeline (${agentCount} agents)`;
    case 'completed': return `Completed in ${totalDurationS?.toFixed(1) ?? '?'}s`;
    case 'cancelled': return 'Pipeline cancelled';
    case 'failed':    return 'Pipeline error';
  }
}

// ---------------------------------------------------------------------------
// Step card
// ---------------------------------------------------------------------------

function RunStepCard({
  step,
  stepIdx,
  agentCount,
  isExpanded,
  showThinking,
  onToggleExpand,
  onToggleThinking,
}: {
  step: RunStepState;
  stepIdx: number;
  agentCount: number;
  isExpanded: boolean;
  showThinking: Record<string, boolean>;
  onToggleExpand: (idx: number) => void;
  onToggleThinking: (id: string) => void;
}) {
  const borderColor = `color-mix(in srgb, ${stepStatusColor(step.status)} 25%, var(--border))`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl overflow-hidden"
      style={{ border: `1px solid ${borderColor}` }}
    >
      <button
        onClick={() => onToggleExpand(stepIdx)}
        className="w-full flex items-center justify-between px-4 py-3 transition-colors hover:bg-[var(--surface-1)]"
      >
        <div className="flex items-center gap-3 min-w-0">
          {step.status === 'running' ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" style={{ color: 'var(--accent)' }} />
          ) : step.status === 'completed' ? (
            <CheckCircle2 className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--success)' }} />
          ) : step.status === 'failed' ? (
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--danger)' }} />
          ) : (
            <Circle className="w-3.5 h-3.5 shrink-0" style={{ color: 'var(--text-muted)' }} />
          )}

          <span className="text-xs font-semibold truncate" style={{ color: 'var(--text)' }}>
            {step.agent_name}
          </span>
          <span className="text-[10px] font-mono shrink-0" style={{ color: 'var(--text-muted)' }}>
            Step {stepIdx + 1}/{agentCount}
          </span>
          {step.durationS != null && (
            <span
              className="flex items-center gap-1 text-[10px] font-mono shrink-0"
              style={{ color: 'var(--text-muted)' }}
            >
              <Clock className="w-3 h-3" />
              {step.durationS.toFixed(1)}s
            </span>
          )}
          <Badge variant={stepBadgeVariant(step.status)} size="sm">
            {step.status}
          </Badge>
        </div>

        {isExpanded
          ? <ChevronDown className="w-4 h-4 shrink-0" style={{ color: 'var(--text-muted)' }} />
          : <ChevronRight className="w-4 h-4 shrink-0" style={{ color: 'var(--text-muted)' }} />
        }
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0 }}
            animate={{ height: 'auto' }}
            exit={{ height: 0 }}
            className="overflow-hidden"
          >
            <div className="px-4 pb-4 space-y-2 max-h-96 overflow-y-auto">
              {step.messages.map(msg => (
                <PipelineMessageRenderer
                  key={msg.id}
                  msg={msg}
                  isThinkingExpanded={showThinking[msg.id] ?? false}
                  onToggleThinking={onToggleThinking}
                />
              ))}

              {/* Typing indicator while running */}
              {step.status === 'running' && (
                <div className="flex items-center gap-1 px-2 py-1.5">
                  {[0, 100, 200].map(delay => (
                    <div
                      key={delay}
                      className="w-1.5 h-1.5 rounded-full animate-bounce"
                      style={{
                        background: 'var(--accent)',
                        animationDelay: `${delay}ms`,
                      }}
                    />
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Collapsed output preview */}
      {!isExpanded && step.outputPreview && (
        <div className="px-4 pb-3">
          <p className="text-[11px] line-clamp-2" style={{ color: 'var(--text-muted)' }}>
            {step.outputPreview}
          </p>
        </div>
      )}
    </motion.div>
  );
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface WorkflowRunPanelProps {
  onClose: () => void;
  onCancel?: (runId: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function WorkflowRunPanel({ onClose, onCancel }: WorkflowRunPanelProps) {
  const activeRunId = useWorkflowRunsStore(s => s.activeRunId);
  const run = useWorkflowRunsStore(s => activeRunId ? s.runs[activeRunId] : undefined);
  const toggleStep = useWorkflowRunsStore(s => s.toggleStep);

  const [showThinking, setShowThinking] = useState<Record<string, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [run?.steps]);

  if (!run || !activeRunId) return null;

  const agentCount = run.agentSequence.length;
  const completedCount = run.steps.filter(s => s.status === 'completed').length;
  const progressPct = agentCount > 0 ? (completedCount / agentCount) * 100 : 0;

  const handleToggleStep = (idx: number) => {
    toggleStep(activeRunId, idx);
  };

  const handleToggleThinking = (id: string) => {
    setShowThinking(prev => ({ ...prev, [id]: !prev[id] }));
  };

  const handleCancel = () => {
    if (onCancel) onCancel(activeRunId);
  };

  return (
    <motion.div
      className="flex flex-col rounded-2xl overflow-hidden shadow-xl"
      style={{
        border: '1px solid var(--border)',
        background: 'var(--surface)',
        maxHeight: '70vh',
      }}
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 12 }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-5 py-3 shrink-0"
        style={{ borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-center gap-3 min-w-0">
          <Play className="w-4 h-4 shrink-0" style={{ color: 'var(--accent)' }} />
          <div className="min-w-0">
            <h2 className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>
              {run.workflowName || 'Workflow Run'}
            </h2>
            <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              {buildStatusLabel(run.status, agentCount, run.totalDurationS)}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {run.status === 'running' && onCancel && (
            <button
              onClick={handleCancel}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-opacity hover:opacity-80"
              style={{ background: 'var(--danger)', color: '#fff' }}
            >
              <Square className="w-3 h-3" />
              Cancel
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg transition-colors hover:bg-[var(--surface-1)]"
            style={{ color: 'var(--text-muted)' }}
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Progress bar */}
      <div className="shrink-0 px-5 py-2" style={{ borderBottom: '1px solid var(--border)' }}>
        <div
          className="w-full h-1 rounded-full overflow-hidden"
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

      {/* Step cards */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {run.steps.map((step, idx) => (
          <RunStepCard
            key={`${activeRunId}-step-${idx}`}
            step={step}
            stepIdx={idx}
            agentCount={agentCount}
            isExpanded={run.expandedSteps.has(idx)}
            showThinking={showThinking}
            onToggleExpand={handleToggleStep}
            onToggleThinking={handleToggleThinking}
          />
        ))}

        {/* Completion summary */}
        {run.status === 'completed' && run.totalDurationS !== null && (
          <div
            className="flex items-center gap-2 px-4 py-3 rounded-xl text-xs"
            style={{
              background: 'color-mix(in srgb, var(--success) 8%, transparent)',
              border: '1px solid color-mix(in srgb, var(--success) 20%, transparent)',
              color: 'var(--success)',
            }}
          >
            <CheckCircle2 className="w-4 h-4 shrink-0" />
            Pipeline completed in {run.totalDurationS.toFixed(1)}s
          </div>
        )}

        {run.status === 'cancelled' && (
          <div
            className="flex items-center gap-2 px-4 py-3 rounded-xl text-xs"
            style={{
              background: 'color-mix(in srgb, var(--warning) 8%, transparent)',
              border: '1px solid color-mix(in srgb, var(--warning) 20%, transparent)',
              color: 'var(--warning)',
            }}
          >
            <Ban className="w-4 h-4 shrink-0" />
            Pipeline cancelled
          </div>
        )}

        {run.status === 'failed' && (
          <div
            className="flex items-center gap-2 px-4 py-3 rounded-xl text-xs"
            style={{
              background: 'color-mix(in srgb, var(--danger) 8%, transparent)',
              border: '1px solid color-mix(in srgb, var(--danger) 20%, transparent)',
              color: 'var(--danger)',
            }}
          >
            <AlertTriangle className="w-4 h-4 shrink-0" />
            Pipeline failed
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </motion.div>
  );
}
