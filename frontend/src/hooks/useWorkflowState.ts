import { useState, useEffect, useMemo, useCallback } from 'react';
import { useApi } from './useApi';
import { workflowsService } from '../services/workflows';
import { agentsService } from '../services/agents';
import { mockWorkflows, mockAgents } from '../lib/mockData';
import type { Workflow, AgentInfo } from '../lib/types-extended';
import type { FilterStatus } from '../components/workflows/workflowAgentUtils';

export interface UseWorkflowStateReturn {
  // Data
  workflows: Workflow[];
  agents: AgentInfo[];
  isLive: boolean;
  error: string | null;
  refetch: () => void;

  // Selection / filter
  filterStatus: FilterStatus;
  setFilterStatus: (s: FilterStatus) => void;
  selectedId: string | null;
  setSelectedId: (id: string | null) => void;
  filteredWorkflows: Workflow[];
  selectedWorkflow: Workflow | null;

  // Modal visibility
  showCreate: boolean;
  setShowCreate: (v: boolean) => void;
  runDialogWorkflow: Workflow | null;
  setRunDialogWorkflow: (wf: Workflow | null) => void;
  editDialogWorkflow: Workflow | null;
  setEditDialogWorkflow: (wf: Workflow | null) => void;
  pipelineWorkflow: Workflow | null;

  // Actions
  handleDelete: (id: string) => Promise<void>;
  openRunDialog: (wf: Workflow) => void;
  openEditDialog: (wf: Workflow) => void;
  handleRunConfirm: (prompt: string) => void;
  handlePipelineClose: () => void;
}

export function useWorkflowState(): UseWorkflowStateReturn {
  const { data: workflows, isLive, refetch, error } = useApi<Workflow[]>(
    () => workflowsService.getWorkflows(),
    mockWorkflows
  );
  const { data: agents } = useApi<AgentInfo[]>(
    () => agentsService.getAgents(),
    mockAgents
  );

  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [runDialogWorkflow, setRunDialogWorkflow] = useState<Workflow | null>(null);
  const [editDialogWorkflow, setEditDialogWorkflow] = useState<Workflow | null>(null);
  const [pipelineWorkflow, setPipelineWorkflow] = useState<Workflow | null>(null);

  // Auto-select the first workflow only once we have live API data.
  // Gating on isLive prevents selecting a mock workflow ID (e.g. wf-demo-1)
  // which would cause useWorkflowRunConnection to open a spurious WebSocket
  // to a non-existent workflow, producing "closed before established" errors.
  useEffect(() => {
    if (isLive && workflows.length > 0 && (selectedId === null || !workflows.find(w => w.id === selectedId))) {
      setSelectedId(workflows[0]!.id);
    }
  }, [workflows, isLive]);

  const filteredWorkflows = useMemo(
    () =>
      filterStatus === 'all'
        ? workflows
        : workflows.filter(w => w.status === filterStatus),
    [workflows, filterStatus]
  );

  const selectedWorkflow = useMemo(
    () => workflows.find(w => w.id === selectedId) ?? null,
    [workflows, selectedId]
  );

  const handleDelete = useCallback(
    async (id: string) => {
      if (!confirm('Delete this workflow?')) return;
      try {
        await workflowsService.deleteWorkflow(id);
        refetch();
      } catch (err) {
        console.error('Failed to delete:', err);
      }
    },
    [refetch]
  );

  const openRunDialog = useCallback((wf: Workflow) => {
    setSelectedId(wf.id);
    setRunDialogWorkflow(wf);
  }, []);

  const openEditDialog = useCallback((wf: Workflow) => {
    setSelectedId(wf.id);
    setEditDialogWorkflow(wf);
  }, []);

  const handleRunConfirm = useCallback(
    (prompt: string) => {
      if (!runDialogWorkflow) return;
      setPipelineWorkflow({ ...runDialogWorkflow, initial_prompt: prompt });
      setRunDialogWorkflow(null);
    },
    [runDialogWorkflow]
  );

  const handlePipelineClose = useCallback(() => {
    setPipelineWorkflow(null);
    refetch();
  }, [refetch]);

  return {
    workflows,
    agents,
    isLive,
    error,
    refetch,
    filterStatus,
    setFilterStatus,
    selectedId,
    setSelectedId,
    filteredWorkflows,
    selectedWorkflow,
    showCreate,
    setShowCreate,
    runDialogWorkflow,
    setRunDialogWorkflow,
    editDialogWorkflow,
    setEditDialogWorkflow,
    pipelineWorkflow,
    handleDelete,
    openRunDialog,
    openEditDialog,
    handleRunConfirm,
    handlePipelineClose,
  };
}
