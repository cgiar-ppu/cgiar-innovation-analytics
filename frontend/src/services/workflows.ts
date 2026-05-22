import { api } from '../lib/api';
import type {
  Workflow,
  StepConfig,
  WorkflowRunSummary,
  WorkflowRunDetail,
} from '../lib/types-extended';

export const workflowsService = {
  async getWorkflows(): Promise<Workflow[]> {
    const data = await api.get<{ workflows: Workflow[] } | Workflow[]>('/api/workflows');
    return (data as { workflows?: Workflow[] }).workflows ?? (data as Workflow[]);
  },

  getWorkflow(id: string): Promise<Workflow> {
    return api.get<Workflow>(`/api/workflows/${id}`);
  },

  createWorkflow(data: {
    name: string;
    description: string;
    agent_sequence: string[];
    initial_prompt: string;
    step_configs?: StepConfig[];
  }): Promise<Workflow> {
    return api.post<Workflow>('/api/workflows', data);
  },

  async deleteWorkflow(id: string): Promise<void> {
    await api.del<unknown>(`/api/workflows/${id}`);
  },

  updateWorkflow(
    id: string,
    data: {
      name?: string;
      description?: string;
      agent_sequence?: string[];
      initial_prompt?: string;
      step_configs?: StepConfig[];
    }
  ): Promise<Workflow> {
    return api.patch<Workflow>(`/api/workflows/${id}`, data);
  },

  async runWorkflow(id: string): Promise<void> {
    await api.post<unknown>(`/api/workflows/${id}/run`, {});
  },

  getRunLogs(workflowId: string): Promise<{
    logs: Array<{
      filename: string;
      run_id: string;
      timestamp: string;
      status: string;
      duration_s: number;
    }>;
  }> {
    return api.get(`/api/workflows/${workflowId}/logs`);
  },

  // downloadRunLog streams a binary blob for client-side download. The api
  // helper always calls .json(), so raw fetch is kept here for this one method.
  async downloadRunLog(workflowId: string, filename: string): Promise<void> {
    const res = await fetch(`/api/workflows/${workflowId}/logs/${filename}`);
    if (!res.ok) throw new Error(`GET /api/workflows/${workflowId}/logs/${filename}: ${res.status}`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },

  // ── Run history (DB-backed) ─────────────────────────────────────────────

  getWorkflowRuns(workflowId: string): Promise<{ runs: WorkflowRunSummary[]; total: number }> {
    return api.get(`/api/workflows/${workflowId}/runs`);
  },

  getWorkflowRunDetail(workflowId: string, runId: string): Promise<WorkflowRunDetail> {
    return api.get(`/api/workflows/${workflowId}/runs/${runId}`);
  },

  async downloadWorkflowRun(workflowId: string, runId: string, format: string = 'json'): Promise<void> {
    const res = await fetch(`/api/workflows/${workflowId}/runs/${runId}/download?format=${format}`);
    if (!res.ok) throw new Error('Failed to download run');
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    const contentDisposition = res.headers.get('Content-Disposition');
    const filename = contentDisposition?.match(/filename="(.+)"/)?.[1] || `run_${runId}.${format}`;
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  },

  continueFromRun(workflowId: string, runId: string): Promise<{ session_id: string; title: string }> {
    return api.post(`/api/workflows/${workflowId}/runs/${runId}/continue`, {});
  },
};
