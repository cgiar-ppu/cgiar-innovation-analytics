import { useState } from 'react';
import { motion } from 'framer-motion';
import { Play, X, ArrowRight } from 'lucide-react';
import type { Workflow, AgentInfo } from '../../lib/types-extended';
import { agentColor } from './workflowAgentUtils';

export interface WorkflowRunDialogProps {
  workflow: Workflow;
  agents: AgentInfo[];
  onConfirm: (prompt: string) => void;
  onClose: () => void;
}

export default function WorkflowRunDialog({
  workflow: wf,
  agents,
  onConfirm,
  onClose,
}: WorkflowRunDialogProps) {
  const [prompt, setPrompt] = useState(wf.initial_prompt ?? '');

  const handleStart = () => {
    if (!prompt.trim()) return;
    onConfirm(prompt.trim());
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      <motion.div
        initial={{ scale: 0.96, y: 8 }}
        animate={{ scale: 1, y: 0 }}
        exit={{ scale: 0.96, y: 8 }}
        transition={{ type: 'spring', stiffness: 320, damping: 28 }}
        className="relative glass-strong rounded-2xl border border-[var(--border)] shadow-2xl w-full max-w-md"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center"
              style={{ background: 'linear-gradient(135deg, var(--accent), var(--purple))' }}
            >
              <Play className="w-4 h-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-[var(--text)]">Run Pipeline</h2>
              <p className="text-[10px] text-[var(--text-muted)]">{wf.name}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-[var(--surface-2)] text-[var(--text-muted)] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-4">
          {/* Prompt input */}
          <div>
            <label className="block text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">
              Initial Prompt
            </label>
            <textarea
              value={prompt}
              onChange={e => setPrompt(e.target.value)}
              placeholder="Describe what you want the pipeline to do..."
              rows={4}
              autoFocus
              className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2.5 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] transition-colors resize-none placeholder:text-[var(--text-muted)]"
            />
          </div>

          {/* Agent chain preview */}
          <div>
            <p className="text-xs font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-2">
              Pipeline
            </p>
            <div className="flex items-center gap-1 flex-wrap">
              {(wf.agent_sequence ?? []).map((id, i) => {
                const agent = agents.find(a => a.id === id);
                const color = agentColor(id);
                return (
                  <span key={id + i} className="flex items-center gap-1">
                    {i > 0 && (
                      <ArrowRight className="w-3 h-3 text-[var(--text-muted)] shrink-0" />
                    )}
                    <span
                      className="text-[10px] font-medium px-2 py-0.5 rounded-full border"
                      style={{
                        borderColor: color + '55',
                        backgroundColor: color + '15',
                        color,
                      }}
                    >
                      {agent?.name ?? id}
                    </span>
                  </span>
                );
              })}
            </div>
          </div>

          <p className="text-[10px] text-[var(--text-muted)] leading-relaxed">
            Pipeline will run with the workflow's configured step settings.
          </p>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-[var(--border)]">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm rounded-lg bg-[var(--surface-1)] text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleStart}
            disabled={!prompt.trim()}
            className="flex items-center gap-2 px-5 py-2 text-sm rounded-lg bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white font-medium hover:opacity-90 disabled:opacity-40 transition-opacity"
          >
            <Play className="w-3.5 h-3.5" />
            Start Pipeline
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
