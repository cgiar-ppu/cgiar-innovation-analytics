import { X, Bot, Wrench, Cpu, FileText } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import type { AgentInfo } from '../../lib/types-extended';
import { colorWithAlpha } from '../../lib/color';
import Badge from '../common/Badge';
import StatusDot from '../common/StatusDot';

interface AgentDetailModalProps {
  agent: AgentInfo | null;
  onClose: () => void;
}

export default function AgentDetailModal({ agent, onClose }: AgentDetailModalProps) {
  return (
    <AnimatePresence>
      {agent && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          onClick={onClose}
        >
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="relative glass-strong rounded-2xl border border-[var(--border)] shadow-2xl w-full max-w-lg overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center gap-3 p-5 border-b border-[var(--border)]">
              <div
                className="w-12 h-12 rounded-xl flex items-center justify-center"
                style={{ backgroundColor: colorWithAlpha(agent.color, 0.125) }}
              >
                <Bot className="w-6 h-6" style={{ color: agent.color || 'var(--accent)' }} />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-semibold text-[var(--text)]">{agent.name}</h2>
                  <StatusDot status={agent.status === 'active' ? 'active' : 'inactive'} pulse />
                </div>
                <p className="text-xs text-[var(--text-muted)]">{agent.id} &middot; {agent.type}</p>
              </div>
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[var(--surface-1)] text-[var(--text-muted)]">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="p-5 space-y-4">
              <div>
                <h4 className="text-xs font-medium text-[var(--text-muted)] uppercase mb-1">Description</h4>
                <p className="text-sm text-[var(--text)]">{agent.description}</p>
              </div>

              <div>
                <h4 className="text-xs font-medium text-[var(--text-muted)] uppercase mb-2 flex items-center gap-1">
                  <Cpu className="w-3 h-3" /> Model
                </h4>
                <Badge variant="accent">{agent.model}</Badge>
              </div>

              <div>
                <h4 className="text-xs font-medium text-[var(--text-muted)] uppercase mb-2 flex items-center gap-1">
                  <Wrench className="w-3 h-3" /> Tools ({agent.tools.length})
                </h4>
                <div className="flex flex-wrap gap-1.5">
                  {agent.tools.map(t => (
                    <Badge key={t} variant="muted">{t}</Badge>
                  ))}
                </div>
              </div>

              {agent.system_prompt && (
                <div>
                  <h4 className="text-xs font-medium text-[var(--text-muted)] uppercase mb-2 flex items-center gap-1">
                    <FileText className="w-3 h-3" /> System Prompt
                  </h4>
                  <p className="text-sm text-[var(--text)] whitespace-pre-wrap bg-[var(--surface-1)] rounded-lg p-3 max-h-40 overflow-y-auto">
                    {agent.system_prompt}
                  </p>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="flex justify-end p-4 border-t border-[var(--border)]">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm rounded-lg bg-[var(--surface-1)] text-[var(--text)] hover:bg-[var(--surface-2)] transition-colors"
              >
                Close
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
