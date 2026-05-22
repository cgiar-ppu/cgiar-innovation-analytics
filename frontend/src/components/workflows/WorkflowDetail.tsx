import { ChevronRight, Crown, Bot, Pencil, Play } from 'lucide-react';
import Badge from '../common/Badge';
import RunHistoryPanel from './RunHistoryPanel';
import type { Workflow, AgentInfo } from '../../lib/types-extended';
import { agentColor, isOrchestrator, statusVariant } from './workflowAgentUtils';

// ─── Mini pipeline strip (pill row used in detail panel) ──────────────────────

interface MiniPipelineProps {
  sequence: string[];
  agents: AgentInfo[];
}

function MiniPipeline({ sequence, agents }: MiniPipelineProps) {
  if (!sequence || sequence.length === 0) return null;
  return (
    <div className="flex items-center gap-1 flex-wrap">
      {sequence.map((id, idx) => {
        const agent = agents.find(a => a.id === id);
        const isOrch = isOrchestrator(id);
        const color = agentColor(id);
        return (
          <div key={idx} className="flex items-center gap-1">
            <div
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border text-[10px] font-medium"
              style={{
                borderColor: color + '55',
                backgroundColor: color + '18',
                color,
              }}
            >
              {isOrch ? (
                <Crown className="w-2.5 h-2.5 shrink-0" />
              ) : (
                <Bot className="w-2.5 h-2.5 shrink-0" />
              )}
              <span className="truncate max-w-[90px]">{agent?.name ?? id}</span>
            </div>
            {idx < sequence.length - 1 && (
              <ChevronRight className="w-3 h-3 text-[var(--text-muted)] shrink-0" />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Right panel: selected workflow detail strip ───────────────────────────────

export interface WorkflowDetailProps {
  workflow: Workflow;
  agents: AgentInfo[];
  onRun: () => void;
  onEdit: () => void;
}

export default function WorkflowDetail({ workflow: wf, agents, onRun, onEdit }: WorkflowDetailProps) {
  return (
    <div className="glass rounded-xl border border-[var(--border)] p-4 space-y-3">
      {/* Title row */}
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-semibold text-[var(--text)] truncate">{wf.name}</h3>
            <Badge variant={statusVariant(wf.status)}>{wf.status}</Badge>
          </div>
          {wf.description && (
            <p className="text-[11px] text-[var(--text-muted)] mt-0.5 line-clamp-2">
              {wf.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={onEdit}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium bg-[var(--surface-2)] text-[var(--text)] hover:bg-[var(--surface-1)] border border-[var(--border)] transition-colors"
          >
            <Pencil className="w-3.5 h-3.5" />
            Edit
          </button>
          <button
            onClick={onRun}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white hover:opacity-90 transition-opacity"
          >
            <Play className="w-3.5 h-3.5" />
            Run Pipeline
          </button>
        </div>
      </div>

      {/* Initial prompt preview */}
      {wf.initial_prompt && (
        <div className="rounded-lg bg-[var(--surface-1)] border border-[var(--border)] px-3 py-2">
          <p className="text-[10px] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1">
            Initial Prompt
          </p>
          <p className="text-xs text-[var(--text)] line-clamp-2 leading-relaxed">
            {wf.initial_prompt}
          </p>
        </div>
      )}

      {/* Meta chips */}
      <div className="flex items-center gap-4 text-[10px] font-mono text-[var(--text-muted)]">
        <span>{wf.agent_sequence?.length ?? 0} agents in chain</span>
        <span>{wf.run_count ?? 0} total runs</span>
        {wf.last_run && <span>Last run {new Date(wf.last_run).toLocaleDateString()}</span>}
      </div>

      {/* Agent chain as pills */}
      {(wf.agent_sequence ?? []).length > 0 && (
        <MiniPipeline sequence={wf.agent_sequence} agents={agents} />
      )}

      {/* Run history -- always render; the panel handles the empty state gracefully.
         The run_count field on the workflow may be stale (WebSocket-based runs
         don't always increment it), so we let RunHistoryPanel query the DB directly. */}
      <RunHistoryPanel key={`${wf.id}-${wf.run_count ?? 0}`} workflowId={wf.id} />
    </div>
  );
}
