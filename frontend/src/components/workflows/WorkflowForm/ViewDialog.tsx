import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import { Pencil, X, Save } from 'lucide-react';
import { workflowsService } from '../../../services/workflows';
import type { Workflow, AgentInfo, StepConfig } from '../../../lib/types-extended';
import { useModalA11y } from '../../common/useModalA11y';
import DetailsForm from './DetailsForm';
import SequenceEditor from './SequenceEditor';

export interface WorkflowViewDialogProps {
  workflow: Workflow;
  agents: AgentInfo[];
  onClose: () => void;
  onSaved: () => void;
}

export function WorkflowViewDialog({ workflow: wf, agents, onClose, onSaved }: WorkflowViewDialogProps) {
  const { modalRef, modalProps } = useModalA11y(true, onClose);
  const [name, setName] = useState(wf.name ?? '');
  const [description, setDescription] = useState(wf.description ?? '');
  const [initialPrompt, setInitialPrompt] = useState(wf.initial_prompt ?? '');
  const [sequence, setSequence] = useState<string[]>(wf.agent_sequence ?? []);
  const [stepConfigs, setStepConfigs] = useState<StepConfig[]>(
    () => (wf.step_configs ?? wf.agent_sequence ?? []).map((item, i) => {
      if (typeof item === 'object' && item !== null && 'agent_id' in item) return item as StepConfig;
      const agentId = (wf.agent_sequence ?? [])[i] ?? '';
      return { agent_id: agentId };
    })
  );
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // Keep stepConfigs in sync when sequence changes (add/remove/reorder)
  useEffect(() => {
    setStepConfigs(prev =>
      sequence.map((agentId, i) => {
        const existing = prev[i];
        if (existing && existing.agent_id === agentId) return existing;
        return { agent_id: agentId };
      })
    );
  }, [sequence]);

  const addAgent = (id: string) => setSequence(prev => [...prev, id]);

  const removeAgentAt = (index: number) =>
    setSequence(prev => prev.filter((_, i) => i !== index));

  const moveAgent = (index: number, direction: 'up' | 'down') => {
    setSequence(prev => {
      const next = [...prev];
      const target = direction === 'up' ? index - 1 : index + 1;
      if (target < 0 || target >= next.length) return prev;
      const tmp = next[index]!;
      next[index] = next[target]!;
      next[target] = tmp;
      return next;
    });
  };

  const updateStepConfig = (index: number, updated: StepConfig) =>
    setStepConfigs(prev => prev.map((s, i) => (i === index ? updated : s)));

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      await workflowsService.updateWorkflow(wf.id, {
        name: name.trim(),
        description: description.trim(),
        initial_prompt: initialPrompt.trim(),
        agent_sequence: sequence,
        step_configs: stepConfigs,
      });
      onSaved();
      onClose();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/55 backdrop-blur-sm" />

      <motion.div
        ref={modalRef}
        {...modalProps}
        aria-label={`Edit workflow: ${wf.name}`}
        initial={{ scale: 0.96, y: 8 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.96, y: 8 }}
        transition={{ type: 'spring', stiffness: 320, damping: 28 }}
        className="relative glass-strong rounded-2xl border border-[var(--border)] shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center">
              <Pencil className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-[var(--text)]">View / Edit Workflow</h2>
              <p className="text-[10px] text-[var(--text-muted)]">{wf.name}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--surface-2)] text-[var(--text-muted)] transition-colors"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-6">

            <DetailsForm
              name={name}
              onNameChange={setName}
              description={description}
              onDescriptionChange={setDescription}
              initialPrompt={initialPrompt}
              onInitialPromptChange={setInitialPrompt}
            />

            <div className="h-px bg-[var(--border)]" />

            <SequenceEditor
              sequence={sequence}
              agents={agents}
              stepConfigs={stepConfigs}
              onMoveAgent={moveAgent}
              onRemoveAgent={removeAgentAt}
              onUpdateStepConfig={updateStepConfig}
              onAddAgent={addAgent}
              agentSectionTitle="Add Agents"
            />

          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-[var(--border)] shrink-0">
          <div className="flex-1 min-w-0">
            {saveError && (
              <p className="text-xs text-[var(--danger)] truncate">{saveError}</p>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg bg-[var(--surface-1)] text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
            >
              Close
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !name.trim()}
              className="flex items-center gap-2 px-5 py-2 text-sm rounded-lg bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
            >
              <Save className="w-3.5 h-3.5" />
              {saving ? 'Saving...' : 'Save Changes'}
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
