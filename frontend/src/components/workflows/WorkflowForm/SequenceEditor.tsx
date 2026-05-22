import { AnimatePresence } from 'framer-motion';
import { GitBranch } from 'lucide-react';
import type { AgentInfo, StepConfig } from '../../../lib/types-extended';
import { isOrchestrator, ORCHESTRATOR_ID, GENERIC_ORCHESTRATOR_ID } from '../workflowAgentUtils';
import OrchestratorBlock from './OrchestratorBlock';
import SpecialistPill from './SpecialistPill';
import StepCard from './StepCard';

export interface SequenceEditorProps {
  sequence: string[];
  agents: AgentInfo[];
  stepConfigs: StepConfig[];
  onMoveAgent: (index: number, direction: 'up' | 'down') => void;
  onRemoveAgent: (index: number) => void;
  onUpdateStepConfig: (index: number, updated: StepConfig) => void;
  onAddAgent: (id: string) => void;
  /** Label shown in the "Available Agents" section header */
  agentSectionTitle?: string;
}

export default function SequenceEditor({
  sequence,
  agents,
  stepConfigs,
  onMoveAgent,
  onRemoveAgent,
  onUpdateStepConfig,
  onAddAgent,
  agentSectionTitle = 'Available Agents',
}: SequenceEditorProps) {
  const specialistAgents = agents.filter(a => !isOrchestrator(a.id));

  return (
    <>
      {/* Agent picker */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest">
          {agentSectionTitle}
        </h3>

        <div className="space-y-2">
          <p className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider">
            Orchestrator Teams
          </p>
          <OrchestratorBlock onAdd={() => onAddAgent(ORCHESTRATOR_ID)} />
          <OrchestratorBlock variant="generic" onAdd={() => onAddAgent(GENERIC_ORCHESTRATOR_ID)} />
        </div>

        <div>
          <p className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-2">
            Specialist Agents
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {specialistAgents.map(agent => (
              <SpecialistPill
                key={agent.id}
                agent={agent}
                onAdd={() => onAddAgent(agent.id)}
              />
            ))}
          </div>
        </div>
      </section>

      <div className="h-px bg-[var(--border)]" />

      {/* Pipeline sequence */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-widest">
            Pipeline Sequence
          </h3>
          {sequence.length > 0 && (
            <span className="text-[10px] text-[var(--text-muted)]">
              {sequence.length} step{sequence.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        {sequence.length === 0 ? (
          <div className="border-2 border-dashed border-[var(--border)] rounded-xl p-8 text-center">
            <GitBranch className="w-8 h-8 text-[var(--text-muted)] mx-auto mb-2 opacity-50" />
            <p className="text-sm text-[var(--text-muted)]">
              Click an agent above to add your first step
            </p>
            <p className="text-xs text-[var(--text-muted)] mt-1 opacity-70">
              You need at least 2 steps to create a pipeline
            </p>
          </div>
        ) : (
          <AnimatePresence mode="popLayout">
            <div className="space-y-0">
              {sequence.map((agentId, index) => (
                <StepCard
                  key={`${agentId}-${index}`}
                  agentId={agentId}
                  index={index}
                  total={sequence.length}
                  agents={agents}
                  stepConfig={stepConfigs[index] ?? { agent_id: agentId }}
                  onMoveUp={() => onMoveAgent(index, 'up')}
                  onMoveDown={() => onMoveAgent(index, 'down')}
                  onRemove={() => onRemoveAgent(index)}
                  onConfigChange={updated => onUpdateStepConfig(index, updated)}
                />
              ))}
            </div>
          </AnimatePresence>
        )}
      </section>
    </>
  );
}
