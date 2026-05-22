import { motion } from 'framer-motion';
import { ChevronUp, ChevronDown, X, Crown, Bot, Users } from 'lucide-react';
import StepConfigurator from '../StepConfigurator';
import type { AgentInfo, StepConfig } from '../../../lib/types-extended';
import { agentColor, agentShortDesc, isOrchestrator } from '../workflowAgentUtils';

export interface StepCardProps {
  agentId: string;
  index: number;
  total: number;
  agents: AgentInfo[];
  stepConfig: StepConfig;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  onConfigChange: (updated: StepConfig) => void;
}

export default function StepCard({
  agentId,
  index,
  total,
  agents,
  stepConfig,
  onMoveUp,
  onMoveDown,
  onRemove,
  onConfigChange,
}: StepCardProps) {
  const agent = agents.find(a => a.id === agentId);
  const isOrch = isOrchestrator(agentId);
  const color = agentColor(agentId);
  const shortDesc = agentShortDesc(agentId);

  return (
    <div className="flex flex-col items-stretch">
      <motion.div
        layout
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.94 }}
        className="rounded-xl border overflow-hidden"
        style={{
          borderColor: isOrch ? '#8b5cf6aa' : color + '55',
          background: isOrch
            ? 'linear-gradient(135deg, rgba(139,92,246,0.08) 0%, rgba(109,40,217,0.05) 100%)'
            : color + '0d',
        }}
      >
        {/* Step header */}
        <div className="flex items-center gap-3 px-3.5 py-2.5">
          <span
            className="flex-shrink-0 w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold text-white"
            style={{ backgroundColor: color }}
          >
            {index + 1}
          </span>

          <div className="flex items-center gap-2 flex-1 min-w-0">
            {isOrch ? (
              <Crown className="w-4 h-4 shrink-0" style={{ color }} />
            ) : (
              <Bot className="w-4 h-4 shrink-0" style={{ color }} />
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-sm font-semibold text-[var(--text)] truncate">
                  {agent?.name ?? agentId}
                </span>
                {isOrch && (
                  <span
                    className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wide"
                    style={{ backgroundColor: '#8b5cf620', color: '#8b5cf6' }}
                  >
                    <Users className="w-2.5 h-2.5" />
                    team
                  </span>
                )}
              </div>
              {shortDesc && (
                <p className="text-[10px] text-[var(--text-muted)] truncate mt-0.5">{shortDesc}</p>
              )}
            </div>
          </div>

          <div className="flex items-center gap-0.5 shrink-0">
            <button
              onClick={onMoveUp}
              disabled={index === 0}
              className="p-1 rounded hover:bg-[var(--surface-2)] text-[var(--text-muted)] disabled:opacity-25 transition-colors"
              title="Move up"
              aria-label="Move step up"
            >
              <ChevronUp className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onMoveDown}
              disabled={index === total - 1}
              className="p-1 rounded hover:bg-[var(--surface-2)] text-[var(--text-muted)] disabled:opacity-25 transition-colors"
              title="Move down"
              aria-label="Move step down"
            >
              <ChevronDown className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={onRemove}
              className="p-1 rounded hover:bg-[var(--danger)]/15 text-[var(--text-muted)] hover:text-[var(--danger)] transition-colors"
              title="Remove step"
              aria-label="Remove step"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <div className="px-3.5 pb-3 border-t border-[var(--border)]/40 pt-2">
          <StepConfigurator
            steps={[stepConfig]}
            onChange={updated => onConfigChange(updated[0]!)}
            availableAgents={[
              { id: 'orchestrator', name: 'Orchestrator' },
              ...agents.map(a => ({ id: a.id, name: a.name })),
            ]}
          />
        </div>
      </motion.div>

      {index < total - 1 && (
        <div className="flex justify-center py-1.5">
          <div className="flex flex-col items-center gap-0">
            <div className="w-px h-2.5 bg-[var(--border)]" />
            <div className="w-3.5 h-3.5 text-[var(--text-muted)] rotate-90 flex items-center justify-center">
              ›
            </div>
            <div className="w-px h-2.5 bg-[var(--border)]" />
          </div>
        </div>
      )}
    </div>
  );
}
