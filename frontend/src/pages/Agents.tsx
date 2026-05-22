import { useState, useMemo, useCallback } from 'react';
import { Search, Plus, Edit2, Trash2, Copy, Bot } from 'lucide-react';
import { useApi } from '../hooks/useApi';
import { agentsService } from '../services/agents';
import { mockAgents } from '../lib/mockData';
import AgentCard from '../components/agents/AgentCard';
import AgentDetailModal from '../components/agents/AgentDetailModal';
import AgentCreateModal from '../components/agents/AgentCreateModal';
import Badge from '../components/common/Badge';
import GlassCard from '../components/common/GlassCard';
import type { AgentInfo } from '../lib/types-extended';

export default function Agents() {
  const { data: agents, isLive, refetch } = useApi<AgentInfo[]>(
    () => agentsService.getAgents(),
    mockAgents
  );
  const [search, setSearch] = useState('');
  const [selectedAgent, setSelectedAgent] = useState<AgentInfo | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editingAgent, setEditingAgent] = useState<AgentInfo | null>(null);

  const filtered = useMemo(
    () => agents.filter(a =>
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.description.toLowerCase().includes(search.toLowerCase()) ||
      a.id.toLowerCase().includes(search.toLowerCase())
    ),
    [agents, search]
  );

  const builtinAgents = useMemo(() => filtered.filter(a => a.type === 'builtin'), [filtered]);
  const customAgents = useMemo(() => filtered.filter(a => a.type === 'custom'), [filtered]);

  const handleCreate = useCallback(async (data: {
    name: string; description: string; system_prompt: string;
    tools: string[]; model: string; color: string;
  }) => {
    try {
      await agentsService.createAgent(data);
      setShowCreate(false);
      refetch();
    } catch (err) {
      console.error('Failed to create agent:', err);
    }
  }, [refetch]);

  const handleEdit = useCallback(async (data: {
    name: string; description: string; system_prompt: string;
    tools: string[]; model: string; color: string;
  }) => {
    if (!editingAgent) return;
    try {
      await agentsService.updateAgent(editingAgent.id, data);
      setEditingAgent(null);
      refetch();
    } catch (err) {
      console.error('Failed to update agent:', err);
    }
  }, [editingAgent, refetch]);

  const handleDelete = useCallback(async (id: string) => {
    if (!confirm('Delete this custom agent?')) return;
    try {
      await agentsService.deleteAgent(id);
      refetch();
    } catch (err) {
      console.error('Failed to delete:', err);
    }
  }, [refetch]);

  const handleClone = useCallback(async (id: string) => {
    try {
      await agentsService.cloneAgent(id);
      refetch();
    } catch (err) {
      console.error('Failed to clone:', err);
    }
  }, [refetch]);

  return (
    <div className="max-w-screen-xl mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--text)]">Agents</h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            {agents.length} specialist agents available
          </p>
        </div>
        <div className="flex gap-2">
          <Badge variant={isLive ? 'success' : 'warning'}>{isLive ? 'Live' : 'Cached'}</Badge>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <Plus className="w-4 h-4" />
            Create Agent
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[var(--text-muted)]" />
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search agents..."
          className="w-full pl-10 pr-4 py-2.5 bg-[var(--surface-1)] border border-[var(--border)] rounded-lg text-sm text-[var(--text)] placeholder:text-[var(--text-muted)] outline-none focus:border-[var(--accent)] transition-colors"
        />
      </div>

      {/* Builtin Agents */}
      {builtinAgents.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">Builtin Agents</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {builtinAgents.map((agent, i) => (
              <div key={agent.id} className="relative group">
                <AgentCard
                  agent={agent}
                  index={i}
                  onClick={() => setSelectedAgent(agent)}
                />
                {/* Clone button for builtins */}
                <button
                  onClick={(e) => { e.stopPropagation(); handleClone(agent.id); }}
                  className="absolute top-3 right-3 p-1.5 rounded-lg bg-[var(--surface-1)]/80 backdrop-blur opacity-0 group-hover:opacity-100 transition-opacity text-[var(--text-muted)] hover:text-[var(--accent)]"
                  title="Clone agent"
                >
                  <Copy className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Custom Agents Empty State */}
      {customAgents.length === 0 && !search && (
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">Custom Agents</h2>
          <GlassCard className="flex flex-col items-center justify-center py-12">
            <div className="w-12 h-12 rounded-xl bg-[var(--accent)]/10 flex items-center justify-center mb-4">
              <Bot className="w-6 h-6 text-[var(--accent)]" />
            </div>
            <h3 className="text-base font-semibold text-[var(--text)] mb-1">No custom agents yet</h3>
            <p className="text-sm text-[var(--text-muted)] mb-4">Create specialized agents tailored to your needs</p>
            <button
              onClick={() => setShowCreate(true)}
              className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
            >
              <Plus className="w-4 h-4" />
              Create Agent
            </button>
          </GlassCard>
        </div>
      )}

      {/* Custom Agents */}
      {customAgents.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-3">Custom Agents</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {customAgents.map((agent, i) => (
              <div key={agent.id} className="relative group">
                <AgentCard
                  agent={agent}
                  index={i}
                  onClick={() => setSelectedAgent(agent)}
                />
                {/* Custom badge */}
                <Badge variant="accent" size="sm" className="absolute top-3 left-3">Custom</Badge>
                {/* Action buttons */}
                <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => { e.stopPropagation(); setEditingAgent(agent); }}
                    className="p-1.5 rounded-lg bg-[var(--surface-1)]/80 backdrop-blur text-[var(--text-muted)] hover:text-[var(--accent)]"
                    title="Edit"
                  >
                    <Edit2 className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleClone(agent.id); }}
                    className="p-1.5 rounded-lg bg-[var(--surface-1)]/80 backdrop-blur text-[var(--text-muted)] hover:text-[var(--accent)]"
                    title="Clone"
                  >
                    <Copy className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDelete(agent.id); }}
                    className="p-1.5 rounded-lg bg-[var(--surface-1)]/80 backdrop-blur text-[var(--text-muted)] hover:text-[var(--danger)]"
                    title="Delete"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {filtered.length === 0 && (
        <div className="text-center py-12 text-[var(--text-muted)]">
          No agents match "{search}"
        </div>
      )}

      {/* Detail Modal */}
      <AgentDetailModal agent={selectedAgent} onClose={() => setSelectedAgent(null)} />

      {/* Create Modal */}
      <AgentCreateModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onSave={handleCreate}
      />

      {/* Edit Modal */}
      <AgentCreateModal
        open={!!editingAgent}
        onClose={() => setEditingAgent(null)}
        onSave={handleEdit}
        initialData={editingAgent ? {
          name: editingAgent.name,
          description: editingAgent.description,
          system_prompt: editingAgent.system_prompt,
          tools: editingAgent.tools,
          model: editingAgent.model,
          color: editingAgent.color,
        } : undefined}
        title="Edit Agent"
      />
    </div>
  );
}
