import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, ChevronRight, AlertTriangle,
  CheckCircle2, Clock, Loader2, Circle,
} from 'lucide-react';
import Badge from '../common/Badge';
import PipelineMessageRenderer from './PipelineMessageRenderer';
import { stepStatusColor, stepBadgeVariant } from './workflowAgentUtils';
import type { StepState } from '../../hooks/usePipelineExecution';

// ─── Props ────────────────────────────────────────────────────────────────────

interface PipelineStepCardProps {
  step: StepState;
  stepIdx: number;
  agentCount: number;
  isExpanded: boolean;
  showThinking: Record<string, boolean>;
  onToggleExpand: (idx: number) => void;
  onToggleThinking: (id: string) => void;
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function PipelineStepCard({
  step,
  stepIdx,
  agentCount,
  isExpanded,
  showThinking,
  onToggleExpand,
  onToggleThinking,
}: PipelineStepCardProps) {
  const borderColor = `color-mix(in srgb, ${stepStatusColor(step.status)} 25%, var(--border))`;

  return (
    <motion.div
      key={`step-output-${stepIdx}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl overflow-hidden"
      style={{ border: `1px solid ${borderColor}` }}
    >
      {/* Step output header */}
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

      {/* Expanded messages */}
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
