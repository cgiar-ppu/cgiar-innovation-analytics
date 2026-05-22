import { Settings2, Users, FileText, Hash, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';

export interface StepConfig {
  agent_id: string;
  sub_agents?: string[];
  extra_instructions?: string;
  max_turns?: number;
}

interface StepConfiguratorProps {
  steps: StepConfig[];
  onChange: (steps: StepConfig[]) => void;
  availableAgents: Array<{ id: string; name: string }>;
}

const ORCHESTRATOR_ID = 'orchestrator';

function StepConfigPanel({
  index,
  config,
  availableAgents,
  onUpdate,
}: {
  index: number;
  config: StepConfig;
  availableAgents: Array<{ id: string; name: string }>;
  onUpdate: (updated: StepConfig) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const isOrchestrator = config.agent_id === ORCHESTRATOR_ID;

  const subAgentOptions = availableAgents.filter(a => a.id !== ORCHESTRATOR_ID);

  const toggleSubAgent = (id: string) => {
    const current = config.sub_agents ?? [];
    const next = current.includes(id)
      ? current.filter(s => s !== id)
      : [...current, id];
    onUpdate({ ...config, sub_agents: next });
  };

  const hasConfig =
    (config.extra_instructions && config.extra_instructions.trim().length > 0) ||
    (isOrchestrator && (config.sub_agents ?? []).length > 0) ||
    (isOrchestrator && config.max_turns != null && config.max_turns !== 50);

  return (
    <div className="glass rounded-lg border border-[var(--border)] overflow-hidden">
      {/* Panel header — toggle expansion */}
      <button
        type="button"
        onClick={() => setExpanded(prev => !prev)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-[var(--surface-1)] transition-colors"
      >
        <Settings2 className="w-3.5 h-3.5 text-[var(--text-muted)] shrink-0" />
        <span className="text-xs font-medium text-[var(--text-muted)] flex-1">
          Step {index + 1} options
          {hasConfig && (
            <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-[var(--accent)] align-middle" />
          )}
        </span>
        {expanded
          ? <ChevronUp className="w-3.5 h-3.5 text-[var(--text-muted)]" />
          : <ChevronDown className="w-3.5 h-3.5 text-[var(--text-muted)]" />
        }
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 space-y-3 border-t border-[var(--border)]/60">

          {/* Orchestrator-only: sub-agent checkboxes */}
          {isOrchestrator && (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <Users className="w-3.5 h-3.5 text-[var(--accent)]" />
                <label className="text-xs font-medium text-[var(--text-muted)]">
                  Sub-agents (delegation targets)
                </label>
              </div>
              {subAgentOptions.length === 0 ? (
                <p className="text-xs text-[var(--text-muted)] italic">
                  No other agents available.
                </p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {subAgentOptions.map(a => {
                    const selected = (config.sub_agents ?? []).includes(a.id);
                    return (
                      <button
                        key={a.id}
                        type="button"
                        onClick={() => toggleSubAgent(a.id)}
                        className={`px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                          selected
                            ? 'border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--accent)]'
                            : 'border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--surface-2)]'
                        }`}
                      >
                        {a.name}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Extra instructions */}
          <div>
            <div className="flex items-center gap-1.5 mb-1.5">
              <FileText className="w-3.5 h-3.5 text-[var(--accent)]" />
              <label className="text-xs font-medium text-[var(--text-muted)]">
                Extra instructions{!isOrchestrator && ' (optional)'}
              </label>
            </div>
            <textarea
              value={config.extra_instructions ?? ''}
              onChange={e => onUpdate({ ...config, extra_instructions: e.target.value })}
              placeholder={
                isOrchestrator
                  ? 'Additional context for this orchestrator step…'
                  : 'Additional context for this agent step…'
              }
              rows={3}
              className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)] resize-none placeholder:text-[var(--text-muted)]"
            />
          </div>

          {/* Orchestrator-only: max turns */}
          {isOrchestrator && (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <Hash className="w-3.5 h-3.5 text-[var(--accent)]" />
                <label className="text-xs font-medium text-[var(--text-muted)]">Max turns</label>
              </div>
              <input
                type="number"
                min={1}
                max={200}
                value={config.max_turns ?? 50}
                onChange={e => {
                  const val = Math.min(200, Math.max(1, parseInt(e.target.value, 10) || 50));
                  onUpdate({ ...config, max_turns: val });
                }}
                className="w-28 bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
              />
              <p className="text-[10px] text-[var(--text-muted)] mt-1">Range: 1–200. Default: 50.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function StepConfigurator({
  steps,
  onChange,
  availableAgents,
}: StepConfiguratorProps) {
  if (steps.length === 0) return null;

  const updateStep = (index: number, updated: StepConfig) => {
    const next = steps.map((s, i) => (i === index ? updated : s));
    onChange(next);
  };

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-[var(--text-muted)]">
        Per-step configuration
      </label>
      {steps.map((config, index) => (
        <StepConfigPanel
          key={index}
          index={index}
          config={config}
          availableAgents={availableAgents}
          onUpdate={updated => updateStep(index, updated)}
        />
      ))}
    </div>
  );
}
