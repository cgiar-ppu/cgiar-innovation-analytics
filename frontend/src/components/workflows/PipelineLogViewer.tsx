import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle2, Square, Download } from 'lucide-react';
import type { StepState, PipelineStatus } from '../../hooks/usePipelineExecution';
import type { Workflow } from '../../lib/types-extended';
import { workflowsService } from '../../services/workflows';
import PipelineStepCard from './PipelineStepCard';

// ─── Props ────────────────────────────────────────────────────────────────────

interface PipelineLogViewerProps {
  workflow: Workflow;
  steps: StepState[];
  expandedSteps: Record<number, boolean>;
  showThinking: Record<string, boolean>;
  pipelineStatus: PipelineStatus;
  totalDurationS: number | null;
  runLogId: string | null;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  onToggleStep: (idx: number) => void;
  onToggleThinking: (id: string) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PipelineLogViewer({
  workflow,
  steps,
  expandedSteps,
  showThinking,
  pipelineStatus,
  totalDurationS,
  runLogId,
  messagesEndRef,
  onToggleStep,
  onToggleThinking,
}: PipelineLogViewerProps) {
  const agentCount = workflow.agent_sequence.length;

  return (
    <div className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
      <AnimatePresence initial={false}>
        {workflow.agent_sequence.map((_agentId, idx) => {
          const step = steps[idx];
          if (!step) return null;
          const isExpanded = expandedSteps[idx] ?? (step.status === 'running');
          const hasMessages = step.messages.length > 0;

          // Don't render steps that haven't started yet
          if (step.status === 'pending' && !hasMessages) return null;

          return (
            <PipelineStepCard
              key={`step-output-${idx}`}
              step={step}
              stepIdx={idx}
              agentCount={agentCount}
              isExpanded={isExpanded}
              showThinking={showThinking}
              onToggleExpand={onToggleStep}
              onToggleThinking={onToggleThinking}
            />
          );
        })}
      </AnimatePresence>

      {/* Completion summary */}
      {pipelineStatus === 'completed' && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="glass rounded-xl p-4"
          style={{
            border: '1px solid color-mix(in srgb, var(--success) 25%, transparent)',
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="w-4 h-4" style={{ color: 'var(--success)' }} />
            <span className="text-sm font-semibold" style={{ color: 'var(--success)' }}>
              Pipeline Complete
            </span>
          </div>
          <div
            className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]"
            style={{ color: 'var(--text-muted)' }}
          >
            <span>{agentCount} agent{agentCount !== 1 ? 's' : ''} executed</span>
            {totalDurationS != null && (
              <span>Total: {totalDurationS.toFixed(1)}s</span>
            )}
            {steps.map((s, i) =>
              s.durationS != null ? (
                <span key={i}>
                  {s.agent_name}: {s.durationS.toFixed(1)}s
                </span>
              ) : null
            )}
          </div>
          {runLogId && (
            <button
              onClick={async () => {
                try {
                  const { logs } = await workflowsService.getRunLogs(workflow.id);
                  const log = logs.find(l => l.run_id === runLogId) ?? logs[0];
                  if (log) {
                    await workflowsService.downloadRunLog(workflow.id, log.filename);
                  }
                } catch (err) {
                  console.error('Failed to download log:', err);
                }
              }}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--surface-1)] text-xs font-medium text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
            >
              <Download className="w-3.5 h-3.5" />
              Download Run Log
            </button>
          )}
        </motion.div>
      )}

      {/* Cancelled notice */}
      {pipelineStatus === 'cancelled' && (
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-2 px-4 py-3 rounded-xl text-sm"
          style={{
            border: '1px solid color-mix(in srgb, var(--warning) 25%, transparent)',
            background: 'color-mix(in srgb, var(--warning) 6%, transparent)',
            color: 'var(--warning)',
          }}
        >
          <Square className="w-4 h-4 shrink-0" />
          Pipeline was cancelled
        </motion.div>
      )}

      <div ref={messagesEndRef} />
    </div>
  );
}
