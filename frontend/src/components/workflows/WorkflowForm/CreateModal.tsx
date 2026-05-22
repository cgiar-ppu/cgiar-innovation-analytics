import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { GitBranch, X } from 'lucide-react';
import { workflowsService } from '../../../services/workflows';
import type { AgentInfo, StepConfig } from '../../../lib/types-extended';
import { useModalA11y } from '../../common/useModalA11y';
import DetailsForm from './DetailsForm';
import SequenceEditor from './SequenceEditor';

export interface CreateModalProps {
  agents: AgentInfo[];
  onClose: () => void;
  onCreated: () => void;
}

export function CreateModal({ agents, onClose, onCreated }: CreateModalProps) {
  const { modalRef, modalProps } = useModalA11y(true, onClose);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newPrompt, setNewPrompt] = useState('');
  const [selectedAgents, setSelectedAgents] = useState<string[]>([]);
  const [stepConfigs, setStepConfigs] = useState<StepConfig[]>([]);

  useEffect(() => {
    setStepConfigs(prev =>
      selectedAgents.map((agentId, i) => {
        const existing = prev[i];
        if (existing && existing.agent_id === agentId) return existing;
        return { agent_id: agentId };
      })
    );
  }, [selectedAgents]);

  const addAgent = (id: string) => setSelectedAgents(prev => [...prev, id]);

  const removeAgentAt = (index: number) =>
    setSelectedAgents(prev => prev.filter((_, i) => i !== index));

  const moveAgent = (index: number, direction: 'up' | 'down') => {
    setSelectedAgents(prev => {
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

  const handleCreate = useCallback(async () => {
    if (!newName.trim() || selectedAgents.length < 2) return;
    try {
      await workflowsService.createWorkflow({
        name: newName,
        description: newDesc,
        agent_sequence: selectedAgents,
        initial_prompt: newPrompt,
        step_configs: stepConfigs,
      });
      onCreated();
      onClose();
    } catch (err) {
      console.error('Failed to create workflow:', err);
    }
  }, [newName, newDesc, newPrompt, selectedAgents, stepConfigs, onCreated, onClose]);

  const canCreate = newName.trim().length > 0 && selectedAgents.length >= 2;

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
        aria-label="Create workflow"
        initial={{ scale: 0.96, y: 8 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.96, y: 8 }}
        transition={{ type: 'spring', stiffness: 320, damping: 28 }}
        className="relative glass-strong rounded-2xl border border-[var(--border)] shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Modal header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center">
              <GitBranch className="w-4 h-4 text-white" />
            </div>
            <h2 className="text-base font-semibold text-[var(--text)]">Create Workflow</h2>
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
              name={newName}
              onNameChange={setNewName}
              description={newDesc}
              onDescriptionChange={setNewDesc}
              initialPrompt={newPrompt}
              onInitialPromptChange={setNewPrompt}
            />

            <div className="h-px bg-[var(--border)]" />

            <SequenceEditor
              sequence={selectedAgents}
              agents={agents}
              stepConfigs={stepConfigs}
              onMoveAgent={moveAgent}
              onRemoveAgent={removeAgentAt}
              onUpdateStepConfig={updateStepConfig}
              onAddAgent={addAgent}
              agentSectionTitle="Available Agents"
            />

          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-3 px-6 py-4 border-t border-[var(--border)] shrink-0">
          <p className="text-xs text-[var(--text-muted)]">
            {canCreate
              ? 'Ready to create'
              : !newName.trim()
              ? 'Enter a workflow name'
              : 'Add at least 2 steps'}
          </p>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm rounded-lg bg-[var(--surface-1)] text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleCreate}
              disabled={!canCreate}
              className="px-5 py-2 text-sm rounded-lg bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
            >
              Create Workflow
            </button>
          </div>
        </div>
      </motion.div>
    </motion.div>
  );
}
