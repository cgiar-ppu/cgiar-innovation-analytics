import { useState, useEffect } from 'react';
import { X, Bot } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

const AVAILABLE_TOOLS = ['Read', 'Write', 'Edit', 'Bash', 'Glob', 'Grep', 'WebSearch', 'WebFetch'];
const MODELS = [
  { value: 'sonnet', label: 'Sonnet (Fast)' },
  { value: 'opus', label: 'Opus (Powerful)' },
];
const COLORS = ['#6366f1', '#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6'];

interface AgentCreateModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (data: {
    name: string;
    description: string;
    system_prompt: string;
    tools: string[];
    model: string;
    color: string;
  }) => void;
  initialData?: {
    name?: string;
    description?: string;
    system_prompt?: string;
    tools?: string[];
    model?: string;
    color?: string;
  };
  title?: string;
}

export default function AgentCreateModal({ open, onClose, onSave, initialData, title = 'Create Agent' }: AgentCreateModalProps) {
  const [name, setName] = useState(initialData?.name || '');
  const [description, setDescription] = useState(initialData?.description || '');
  const [systemPrompt, setSystemPrompt] = useState(initialData?.system_prompt || '');
  const [selectedTools, setSelectedTools] = useState<string[]>(initialData?.tools || [...AVAILABLE_TOOLS]);
  const [model, setModel] = useState(initialData?.model || 'sonnet');
  const [color, setColor] = useState(initialData?.color || '#6366f1');

  // Sync state when initialData changes (e.g. switching between edit targets)
  useEffect(() => {
    setName(initialData?.name || '');
    setDescription(initialData?.description || '');
    setSystemPrompt(initialData?.system_prompt || '');
    setSelectedTools(initialData?.tools || [...AVAILABLE_TOOLS]);
    setModel(initialData?.model || 'sonnet');
    setColor(initialData?.color || '#6366f1');
  }, [initialData]);

  const toggleTool = (tool: string) => {
    setSelectedTools(prev =>
      prev.includes(tool) ? prev.filter(t => t !== tool) : [...prev, tool]
    );
  };

  const handleSave = () => {
    if (!name.trim() || !description.trim() || !systemPrompt.trim()) return;
    onSave({ name, description, system_prompt: systemPrompt, tools: selectedTools, model, color });
    setName('');
    setDescription('');
    setSystemPrompt('');
    setSelectedTools([...AVAILABLE_TOOLS]);
    setModel('sonnet');
    setColor('#6366f1');
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          onClick={onClose}
        >
          <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
          <motion.div
            initial={{ scale: 0.95 }}
            animate={{ scale: 1 }}
            exit={{ scale: 0.95 }}
            className="relative glass-strong rounded-2xl border border-[var(--border)] shadow-2xl w-full max-w-lg max-h-[85vh] flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between p-5 border-b border-[var(--border)] shrink-0">
              <div className="flex items-center gap-2">
                <Bot className="w-5 h-5 text-[var(--accent)]" />
                <h2 className="text-lg font-semibold text-[var(--text)]">{title}</h2>
              </div>
              <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-[var(--surface-1)] text-[var(--text-muted)]">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Body */}
            <div className="p-5 space-y-4 overflow-y-auto flex-1">
              <div>
                <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Name *</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Financial Analyst"
                  className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Description *</label>
                <input
                  value={description}
                  onChange={e => setDescription(e.target.value)}
                  placeholder="Specializes in SEC filings, GAAP standards, and financial analysis"
                  className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">System Prompt *</label>
                <textarea
                  value={systemPrompt}
                  onChange={e => setSystemPrompt(e.target.value)}
                  placeholder="You are a Financial Analysis Specialist..."
                  rows={6}
                  className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)] resize-none font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-[var(--text-muted)] mb-2">Tools</label>
                <div className="flex flex-wrap gap-2">
                  {AVAILABLE_TOOLS.map(tool => (
                    <button
                      key={tool}
                      onClick={() => toggleTool(tool)}
                      className={`px-2.5 py-1 rounded-md text-xs font-medium border transition-colors ${
                        selectedTools.includes(tool)
                          ? 'border-[var(--accent)] bg-[var(--accent)]/15 text-[var(--accent)]'
                          : 'border-[var(--border)] text-[var(--text-muted)] hover:bg-[var(--surface-1)]'
                      }`}
                    >
                      {tool}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Model</label>
                  <select
                    value={model}
                    onChange={e => setModel(e.target.value)}
                    className="w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
                  >
                    {MODELS.map(m => (
                      <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-[var(--text-muted)] mb-1">Color</label>
                  <div className="flex gap-1.5">
                    {COLORS.map(c => (
                      <button
                        key={c}
                        onClick={() => setColor(c)}
                        className={`w-7 h-7 rounded-lg border-2 transition-all ${
                          color === c ? 'border-white scale-110' : 'border-transparent'
                        }`}
                        style={{ backgroundColor: c }}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex justify-end gap-2 p-4 border-t border-[var(--border)] shrink-0">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm rounded-lg bg-[var(--surface-1)] text-[var(--text)] hover:bg-[var(--surface-2)]"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={!name.trim() || !description.trim() || !systemPrompt.trim()}
                className="px-4 py-2 text-sm rounded-lg bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white font-medium hover:opacity-90 disabled:opacity-50"
              >
                Save Agent
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
