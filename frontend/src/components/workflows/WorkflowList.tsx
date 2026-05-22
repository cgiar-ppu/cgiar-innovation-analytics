import { motion } from 'framer-motion';
import { GitBranch, Play, Trash2, Pencil, Clock, Zap, Plus } from 'lucide-react';
import Badge from '../common/Badge';
import GlassCard from '../common/GlassCard';
import type { Workflow, AgentInfo } from '../../lib/types-extended';
import { agentColor, statusVariant, FILTER_TABS, type FilterStatus } from './workflowAgentUtils';

// ─── Avatar strip (overlapping colored circles for the list cards) ────────────

interface AvatarStripProps {
  sequence: string[];
  agents: AgentInfo[];
}

function AvatarStrip({ sequence, agents }: AvatarStripProps) {
  if (!sequence || sequence.length === 0) return null;
  return (
    <div className="flex items-center">
      {sequence.map((id, i) => {
        const agent = agents.find(a => a.id === id);
        const color = agentColor(id);
        const initials = (agent?.name ?? id)
          .split(/[\s_]/)
          .map(w => w[0])
          .join('')
          .slice(0, 3)
          .toUpperCase();
        return (
          <div
            key={i}
            className="w-7 h-7 rounded-full flex items-center justify-center text-[9px] font-bold text-white border-2 border-[var(--surface-1)] shrink-0"
            style={{
              background: `linear-gradient(135deg, ${color}, ${color}cc)`,
              marginLeft: i > 0 ? '-6px' : '0',
              zIndex: sequence.length - i,
            }}
            title={agent?.name ?? id}
          >
            {initials}
          </div>
        );
      })}
      {sequence.length > 1 && (
        <>
          <div className="w-4 mx-1.5 h-px bg-[var(--border)]" />
          <span className="text-[10px] font-mono text-[var(--text-muted)]">
            {sequence.length} steps
          </span>
        </>
      )}
    </div>
  );
}

// ─── Single workflow list card ────────────────────────────────────────────────

export interface WorkflowListCardProps {
  workflow: Workflow;
  agents: AgentInfo[];
  isSelected: boolean;
  onSelect: () => void;
  onRun: (e: React.MouseEvent) => void;
  onDelete: (e: React.MouseEvent) => void;
  onEdit: (e: React.MouseEvent) => void;
}

export function WorkflowListCard({
  workflow: wf,
  agents,
  isSelected,
  onSelect,
  onRun,
  onDelete,
  onEdit,
}: WorkflowListCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      onClick={onSelect}
      className="glass rounded-xl border cursor-pointer overflow-hidden transition-all"
      style={{
        borderColor: isSelected ? 'var(--accent)' : 'var(--border)',
        borderLeftWidth: isSelected ? '3px' : '1px',
        background: isSelected
          ? 'color-mix(in srgb, var(--accent) 5%, var(--surface-1))'
          : undefined,
      }}
    >
      <div className="p-4">
        {/* Name + status row */}
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <div className="flex items-center gap-2 min-w-0">
            <GitBranch className="w-3.5 h-3.5 text-[var(--accent)] shrink-0" />
            <span className="text-sm font-semibold text-[var(--text)] truncate">{wf.name}</span>
          </div>
          <Badge variant={statusVariant(wf.status)}>{wf.status}</Badge>
        </div>

        {wf.description && (
          <p className="text-[11px] text-[var(--text-muted)] line-clamp-2 mb-3">
            {wf.description}
          </p>
        )}

        {/* Avatar strip */}
        <div className="mb-3">
          <AvatarStrip sequence={wf.agent_sequence ?? []} agents={agents} />
        </div>

        {/* Progress bar */}
        <div className="w-full h-0.5 bg-[var(--border)] rounded-full overflow-hidden mb-3">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${wf.progress ?? 0}%`,
              background: 'var(--accent)',
            }}
          />
        </div>

        {/* Meta + action row */}
        <div className="flex items-center justify-between text-[10px] font-mono text-[var(--text-muted)]">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {wf.last_run ? new Date(wf.last_run).toLocaleDateString() : 'Never'}
            </span>
            <span className="flex items-center gap-1">
              <Play className="w-3 h-3" />
              {wf.run_count ?? 0} runs
            </span>
            <span className="flex items-center gap-1">
              <Zap className="w-3 h-3" />
              {wf.steps ?? wf.agent_sequence?.length ?? 0} steps
            </span>
          </div>

          <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
            <button
              onClick={onRun}
              className="flex items-center gap-1 px-2 py-0.5 rounded hover:bg-[var(--accent)]/15 text-[var(--accent)] transition-colors"
              title="Run workflow"
            >
              <Play className="w-3 h-3" />
              Run
            </button>
            <button
              onClick={onEdit}
              className="p-0.5 rounded hover:bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
              title="View / Edit workflow"
            >
              <Pencil className="w-3 h-3" />
            </button>
            <button
              onClick={onDelete}
              className="p-0.5 rounded hover:bg-[var(--danger)]/15 hover:text-[var(--danger)] transition-colors"
              title="Delete workflow"
            >
              <Trash2 className="w-3 h-3" />
            </button>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Left panel: full workflow list with empty state ──────────────────────────

export interface WorkflowListProps {
  workflows: Workflow[];
  agents: AgentInfo[];
  selectedId: string | null;
  filterStatus: FilterStatus;
  onSelect: (id: string) => void;
  onRun: (wf: Workflow, e: React.MouseEvent) => void;
  onDelete: (wf: Workflow, e: React.MouseEvent) => void;
  onEdit: (wf: Workflow, e: React.MouseEvent) => void;
  onCreateFirst: () => void;
}

export default function WorkflowList({
  workflows,
  agents,
  selectedId,
  filterStatus,
  onSelect,
  onRun,
  onDelete,
  onEdit,
  onCreateFirst,
}: WorkflowListProps) {
  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-3">
      {workflows.length === 0 && (
        <GlassCard className="text-center py-12">
          <GitBranch className="w-9 h-9 text-[var(--text-muted)] mx-auto mb-3 opacity-40" />
          <p className="text-sm text-[var(--text-muted)] font-medium">
            {filterStatus === 'all' ? 'No workflows yet' : `No ${filterStatus} workflows`}
          </p>
          {filterStatus === 'all' && (
            <button
              onClick={onCreateFirst}
              className="mt-4 inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white text-sm font-medium hover:opacity-90 transition-opacity"
            >
              <Plus className="w-4 h-4" />
              Create First Workflow
            </button>
          )}
        </GlassCard>
      )}

      {workflows.map(wf => (
        <WorkflowListCard
          key={wf.id}
          workflow={wf}
          agents={agents}
          isSelected={selectedId === wf.id}
          onSelect={() => onSelect(wf.id)}
          onRun={e => onRun(wf, e)}
          onDelete={e => onDelete(wf, e)}
          onEdit={e => onEdit(wf, e)}
        />
      ))}
    </div>
  );
}

export { FILTER_TABS };
