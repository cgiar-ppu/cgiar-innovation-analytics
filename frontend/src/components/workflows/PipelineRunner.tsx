import { motion } from 'framer-motion';
import { X, Square, AlertTriangle, Play } from 'lucide-react';
import type { Workflow } from '../../lib/types-extended';
import { usePipelineExecution } from '../../hooks/usePipelineExecution';
import PipelineStatusBar from './PipelineStatusBar';
import PipelineLogViewer from './PipelineLogViewer';

// ─── Props ────────────────────────────────────────────────────────────────────

interface PipelineRunnerProps {
  workflow: Workflow | null;
  onClose: () => void;
  stepPrompts?: string[];
  initialPrompt?: string;
}

// ─── Status label map ─────────────────────────────────────────────────────────

function buildStatusLabel(
  pipelineStatus: 'connecting' | 'running' | 'completed' | 'cancelled' | 'error',
  agentCount: number,
  totalDurationS: number | null,
): string {
  switch (pipelineStatus) {
    case 'connecting': return 'Connecting...';
    case 'running':    return `Running pipeline (${agentCount} agents)`;
    case 'completed':  return `Completed in ${totalDurationS?.toFixed(1) ?? '?'}s`;
    case 'cancelled':  return 'Pipeline cancelled';
    case 'error':      return 'Pipeline error';
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PipelineRunner({
  workflow,
  onClose,
  stepPrompts: stepPromptsProp,
  initialPrompt: initialPromptProp,
}: PipelineRunnerProps) {
  const prompt = initialPromptProp ?? workflow?.initial_prompt ?? '';
  const stepPrompts = stepPromptsProp ?? [];

  const {
    pipelineStatus,
    steps,
    expandedSteps,
    showThinking,
    totalDurationS,
    connectionError,
    runLogId,
    messagesEndRef,
    handleCancel,
    toggleStep,
    toggleThinking,
  } = usePipelineExecution({ workflow, prompt, stepPrompts });

  if (!workflow) return null;

  const agentCount = workflow.agent_sequence.length;
  const completedCount = steps.filter(s => s.status === 'completed').length;
  const progressPct = agentCount > 0 ? (completedCount / agentCount) * 100 : 0;

  const handleClose = () => onClose();

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)' }}
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      onClick={handleClose}
    >
      <motion.div
        className="glass-strong relative flex flex-col w-full max-w-3xl max-h-[92vh] rounded-2xl overflow-hidden shadow-2xl"
        style={{ border: '1px solid var(--border)' }}
        initial={{ scale: 0.96, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.2 }}
        onClick={e => e.stopPropagation()}
      >
        {/* ── Header ────────────────────────────────────────────────────────── */}
        <div
          className="flex items-center justify-between px-5 py-4"
          style={{ borderBottom: '1px solid var(--border)' }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <Play className="w-4 h-4 shrink-0" style={{ color: 'var(--accent)' }} />
            <div className="min-w-0">
              <h2 className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>
                {workflow.name}
              </h2>
              <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                {buildStatusLabel(pipelineStatus, agentCount, totalDurationS)}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {pipelineStatus === 'running' && (
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
              onClick={handleClose}
              className="p-1.5 rounded-lg transition-colors hover:bg-[var(--surface-1)]"
              style={{ color: 'var(--text-muted)' }}
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* ── Connection error banner ────────────────────────────────────── */}
        {connectionError && (
          <div
            className="flex items-center gap-2 px-5 py-2 text-xs"
            style={{
              background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
              borderBottom: '1px solid color-mix(in srgb, var(--danger) 20%, transparent)',
              color: 'var(--danger)',
            }}
          >
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            {connectionError}
          </div>
        )}

        {/* ── Step progress bar ──────────────────────────────────────────── */}
        <PipelineStatusBar
          agentSequence={workflow.agent_sequence}
          steps={steps}
          expandedSteps={expandedSteps}
          progressPct={progressPct}
          onToggleStep={toggleStep}
        />

        {/* ── Streaming output area ──────────────────────────────────────── */}
        <PipelineLogViewer
          workflow={workflow}
          steps={steps}
          expandedSteps={expandedSteps}
          showThinking={showThinking}
          pipelineStatus={pipelineStatus}
          totalDurationS={totalDurationS}
          runLogId={runLogId}
          messagesEndRef={messagesEndRef}
          onToggleStep={toggleStep}
          onToggleThinking={toggleThinking}
        />
      </motion.div>
    </motion.div>
  );
}
