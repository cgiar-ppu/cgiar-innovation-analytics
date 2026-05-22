import { api } from '../lib/api';
import type { AgentInfo } from '../lib/types-extended';

export interface AgentCreatePayload {
  name: string;
  description: string;
  system_prompt: string;
  tools: string[];
  model: string;
  color: string;
}

export interface AgentUpdatePayload {
  name?: string;
  description?: string;
  system_prompt?: string;
  tools?: string[];
  model?: string;
  color?: string;
}

// The api helper does not expose a PUT method; use a local helper for the one
// endpoint that requires it.
async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`PUT ${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

export const agentsService = {
  async getAgents(): Promise<AgentInfo[]> {
    const data = await api.get<{ agents: AgentInfo[] } | AgentInfo[]>('/api/agents');
    return (data as { agents?: AgentInfo[] }).agents ?? (data as AgentInfo[]);
  },

  getAgent(id: string): Promise<AgentInfo> {
    return api.get<AgentInfo>(`/api/agents/${id}`);
  },

  createAgent(payload: AgentCreatePayload): Promise<AgentInfo> {
    return api.post<AgentInfo>('/api/agents', payload);
  },

  updateAgent(id: string, payload: AgentUpdatePayload): Promise<AgentInfo> {
    return put<AgentInfo>(`/api/agents/${id}`, payload);
  },

  async deleteAgent(id: string): Promise<void> {
    await api.del<unknown>(`/api/agents/${id}`);
  },

  cloneAgent(id: string): Promise<AgentInfo> {
    return api.post<AgentInfo>(`/api/agents/${id}/clone`, {});
  },

  testAgent(id: string): Promise<{ status: string; message: string }> {
    return api.post<{ status: string; message: string }>(`/api/agents/${id}/test`, {});
  },
};
