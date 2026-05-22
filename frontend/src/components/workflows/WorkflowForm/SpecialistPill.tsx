import { Bot, Plus } from 'lucide-react';
import type { AgentInfo } from '../../../lib/types-extended';
import { agentColor, agentShortDesc } from '../workflowAgentUtils';

export interface SpecialistPillProps {
  agent: AgentInfo;
  onAdd: () => void;
}

export default function SpecialistPill({ agent, onAdd }: SpecialistPillProps) {
  const color = agentColor(agent.id);
  return (
    <button
      onClick={onAdd}
      className="flex items-center gap-2 px-3 py-2 rounded-lg border transition-all hover:scale-[1.02] active:scale-[0.98] text-left"
      style={{ borderColor: color + '44', backgroundColor: color + '0e' }}
    >
      <Bot className="w-3.5 h-3.5 shrink-0" style={{ color }} />
      <div className="min-w-0">
        <p className="text-xs font-medium text-[var(--text)] truncate">{agent.name}</p>
        <p className="text-[10px] text-[var(--text-muted)] truncate">{agentShortDesc(agent.id)}</p>
      </div>
      <Plus className="w-3 h-3 shrink-0 text-[var(--text-muted)] ml-auto" />
    </button>
  );
}
