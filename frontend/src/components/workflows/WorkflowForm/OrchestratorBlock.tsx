import { Crown, Users, Plus } from 'lucide-react';

export interface OrchestratorBlockProps {
  onAdd: () => void;
  variant?: 'synapsis' | 'generic';
}

export default function OrchestratorBlock({ onAdd, variant = 'synapsis' }: OrchestratorBlockProps) {
  const isGeneric = variant === 'generic';
  const gradientFrom = isGeneric ? '#6366f1aa' : '#8b5cf6aa';
  const gradientTo = isGeneric ? '#4f46e5aa' : '#6d28d9aa';
  const iconFrom = isGeneric ? '#6366f1' : '#8b5cf6';
  const iconTo = isGeneric ? '#4f46e5' : '#6d28d9';
  const badgeBg = isGeneric ? '#6366f120' : '#8b5cf620';
  const badgeColor = isGeneric ? '#6366f1' : '#8b5cf6';
  const plusBg = isGeneric ? '#6366f130' : '#8b5cf630';

  return (
    <button
      onClick={onAdd}
      className="w-full text-left rounded-xl border-2 p-4 transition-all group hover:scale-[1.01] active:scale-[0.99]"
      style={{
        border: '2px solid transparent',
        background: `linear-gradient(var(--surface-1), var(--surface-1)) padding-box, linear-gradient(135deg, ${gradientFrom}, ${gradientTo}) border-box`,
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
          style={{ background: `linear-gradient(135deg, ${iconFrom}, ${iconTo})` }}
        >
          {isGeneric
            ? <Users className="w-5 h-5 text-white" />
            : <Crown className="w-5 h-5 text-white" />
          }
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold text-[var(--text)]">
              {isGeneric ? 'Generic Orchestrator' : 'Innovation Analytics Team'}
            </span>
            <span
              className="px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider"
              style={{ background: badgeBg, color: badgeColor }}
            >
              {isGeneric ? 'General Purpose' : 'Same as Chat tab'}
            </span>
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 leading-relaxed">
            {isGeneric
              ? 'General-purpose orchestrator — delegates tasks to specialist agents without domain bias.'
              : 'Data analysis, visualization, research methodology & automation specialist team.'
            }
          </p>
        </div>

        <div
          className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 mt-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
          style={{ background: plusBg }}
        >
          <Plus className="w-3.5 h-3.5" style={{ color: badgeColor }} />
        </div>
      </div>
    </button>
  );
}
