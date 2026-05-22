import { useEffect, useCallback, useRef } from 'react';
import { AnimatePresence } from 'framer-motion';
import { Plus, GitBranch, AlertTriangle, RefreshCw } from 'lucide-react';
import { useWorkflowState } from '../hooks/useWorkflowState';
import { useWorkflowRunConnection } from '../hooks/useWorkflowRunConnection';
import { useWorkflowRunsStore } from '../stores/workflowRuns';
import WorkflowCanvas from '../components/workflows/WorkflowCanvas';
import PipelineRunner from '../components/workflows/PipelineRunner';
import WorkflowList from '../components/workflows/WorkflowList';
import WorkflowDetail from '../components/workflows/WorkflowDetail';
import WorkflowRunDialog from '../components/workflows/WorkflowRunDialog';
import ActiveRunsBar from '../components/workflows/ActiveRunsBar';
import WorkflowRunPanel from '../components/workflows/WorkflowRunPanel';
import { CreateModal, WorkflowViewDialog } from '../components/workflows/WorkflowForm';
import Badge from '../components/common/Badge';
import { FILTER_TABS } from '../components/workflows/workflowAgentUtils';

export default function Workflows() {
  const {
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
    handlePipelineClose,
  } = useWorkflowState();

  const activeRunId = useWorkflowRunsStore(s => s.activeRunId);
  const activeRun = useWorkflowRunsStore(s => activeRunId ? s.runs[activeRunId] : undefined);
  const addRun = useWorkflowRunsStore(s => s.addRun);
  const setActiveRun = useWorkflowRunsStore(s => s.setActiveRun);

  // Track the workflow ID for the connection (use selected workflow or active run's workflow)
  const connectionWorkflowId = activeRun?.workflowId ?? selectedId;

  const { startRun, cancelRun, isConnected } = useWorkflowRunConnection({
    workflowId: connectionWorkflowId,
    // Only connect once we have live data from the API — prevents spurious
    // WebSocket attempts to mock workflow IDs (e.g. wf-demo-1) that don't
    // exist in the database, which previously caused "WebSocket is closed
    // before the connection is established" console errors.
    enabled: isLive,
  });

  // Ref to hold the pending run prompt (set when user confirms in the dialog)
  const pendingRunRef = useRef<{ workflow: typeof selectedWorkflow; prompt: string; stepPrompts: string[]; tempRunId?: string } | null>(null);

  // Fetch active runs from the server on mount to populate the store
  useEffect(() => {
    async function fetchActiveRuns() {
      try {
        const res = await fetch('/api/workflows/runs/active');
        if (res.ok) {
          const data = await res.json();
          const runs = data.runs as Array<{
            run_id: string;
            workflow_id: string;
            workflow_name: string;
            status: string;
            started_at: number;
          }>;
          // Add any server-reported running runs that we don't have locally
          const store = useWorkflowRunsStore.getState();
          for (const run of runs) {
            if (!store.runs[run.run_id] && run.status === 'running') {
              // We can't fully reconstruct the run without agent_sequence,
              // but we register it so the bar shows it
              store.addRun(run.run_id, run.workflow_id, run.workflow_name, []);
            }
          }
        }
      } catch {
        // Non-critical: active runs bar simply won't show server-side runs
      }
    }
    fetchActiveRuns();
  }, []);

  // When the connection is established and we have a pending run, send it
  useEffect(() => {
    if (isConnected && pendingRunRef.current) {
      const { workflow, prompt, stepPrompts, tempRunId } = pendingRunRef.current;
      if (workflow) {
        const tid = tempRunId || ('pending-' + Date.now());
        addRun(tid, workflow.id, workflow.name, workflow.agent_sequence);
        startRun(prompt, stepPrompts, tid);
      }
      pendingRunRef.current = null;
    }
  }, [isConnected, addRun, startRun]);

  // Handle run confirmation from the dialog -- start via WebSocket + store
  const handleNewRunConfirm = useCallback((prompt: string) => {
    if (!runDialogWorkflow) return;

    // Add run to the store immediately (with a temporary ID that will be
    // replaced once the server responds with run_started)
    const tempRunId = 'pending-' + Date.now();
    addRun(tempRunId, runDialogWorkflow.id, runDialogWorkflow.name, runDialogWorkflow.agent_sequence);

    // Close the dialog
    setRunDialogWorkflow(null);

    // Send the run command, passing the temp ID so the hook can replace it
    if (isConnected) {
      startRun(prompt, [], tempRunId);
    } else {
      // If not yet connected, store the pending run
      pendingRunRef.current = { workflow: runDialogWorkflow, prompt, stepPrompts: [], tempRunId };
    }
  }, [runDialogWorkflow, addRun, setRunDialogWorkflow, isConnected, startRun]);

  const handleCancelRun = useCallback((runId: string) => {
    cancelRun(runId);
  }, [cancelRun]);

  const handleClosePanel = useCallback(() => {
    setActiveRun(null);
    // Refetch workflows so run_count and status update in the list,
    // and RunHistoryPanel will re-mount with fresh data.
    refetch();
  }, [setActiveRun, refetch]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Page header */}
      <div className="shrink-0 px-6 pt-6 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[var(--border)]">
        <div>
          <h1 className="text-xl font-bold text-[var(--text)]">Workflows</h1>
          <p className="text-sm text-[var(--text-muted)] mt-0.5">
            Chain agents into multi-step pipelines
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Live badge */}
          <Badge variant={isLive ? 'success' : 'warning'}>{isLive ? 'Live' : 'Cached'}</Badge>

          {/* Status filters */}
          <div className="flex items-center gap-1 bg-[var(--surface-1)] border border-[var(--border)] rounded-lg p-0.5">
            {FILTER_TABS.map(s => (
              <button
                key={s}
                onClick={() => setFilterStatus(s)}
                className="px-3 py-1 text-xs rounded-md capitalize transition-all"
                style={
                  filterStatus === s
                    ? { background: 'var(--accent)', color: '#fff', fontWeight: 600 }
                    : { color: 'var(--text-muted)' }
                }
              >
                {s}
              </button>
            ))}
          </div>

          {/* New workflow button */}
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-[var(--accent)] to-[var(--purple)] text-white rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <Plus className="w-4 h-4" />
            New Workflow
          </button>
        </div>
      </div>

      {/* Active runs bar */}
      <ActiveRunsBar />

      {/* Error banner */}
      {error && (
        <div className="shrink-0 mx-6 mt-3 flex items-center gap-3 bg-[var(--danger)]/10 border border-[var(--danger)]/20 text-[var(--danger)] rounded-xl px-4 py-3">
          <AlertTriangle className="w-4 h-4 shrink-0" />
          <span className="text-xs flex-1">{error}</span>
          <button
            onClick={refetch}
            className="flex items-center gap-1 text-xs font-medium hover:underline"
          >
            <RefreshCw className="w-3 h-3" />
            Retry
          </button>
        </div>
      )}

      {/* Split layout */}
      <div className="flex-1 overflow-hidden grid grid-cols-1 lg:grid-cols-5 gap-0">

        {/* Left panel: workflow list (2/5) */}
        <div className="lg:col-span-2 border-r border-[var(--border)] flex flex-col overflow-hidden">
          <WorkflowList
            workflows={filteredWorkflows}
            agents={agents}
            selectedId={selectedId}
            filterStatus={filterStatus}
            onSelect={id => setSelectedId(id)}
            onRun={(wf, e) => { e.stopPropagation(); openRunDialog(wf); }}
            onDelete={(wf, e) => { e.stopPropagation(); handleDelete(wf.id); }}
            onEdit={(wf, e) => { e.stopPropagation(); openEditDialog(wf); }}
            onCreateFirst={() => setShowCreate(true)}
          />
        </div>

        {/* Right panel: canvas + detail + run panel (3/5) */}
        <div className="lg:col-span-3 flex flex-col overflow-hidden">
          {/* Inline WorkflowRunPanel when a run is active */}
          {activeRunId && activeRun ? (
            <div className="flex-1 overflow-hidden p-4">
              <AnimatePresence mode="wait">
                <WorkflowRunPanel
                  key={activeRunId}
                  onClose={handleClosePanel}
                  onCancel={handleCancelRun}
                />
              </AnimatePresence>
            </div>
          ) : selectedWorkflow ? (
            <>
              {/* ReactFlow canvas */}
              <div className="flex-1 overflow-hidden">
                <WorkflowCanvas workflow={selectedWorkflow} />
              </div>

              {/* Detail strip */}
              <div className="shrink-0 p-4 border-t border-[var(--border)]">
                <WorkflowDetail
                  workflow={selectedWorkflow}
                  agents={agents}
                  onRun={() => openRunDialog(selectedWorkflow)}
                  onEdit={() => openEditDialog(selectedWorkflow)}
                />
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center p-6">
              <div className="text-center opacity-50">
                <GitBranch className="w-12 h-12 text-[var(--text-muted)] mx-auto mb-3" />
                <p className="text-sm text-[var(--text-muted)]">Select a workflow to preview</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Create modal */}
      <AnimatePresence>
        {showCreate && (
          <CreateModal
            agents={agents}
            onClose={() => setShowCreate(false)}
            onCreated={refetch}
          />
        )}
      </AnimatePresence>

      {/* Run dialog -- uses new concurrency path */}
      <AnimatePresence>
        {runDialogWorkflow && (
          <WorkflowRunDialog
            workflow={runDialogWorkflow}
            agents={agents}
            onConfirm={handleNewRunConfirm}
            onClose={() => setRunDialogWorkflow(null)}
          />
        )}
      </AnimatePresence>

      {/* View / Edit dialog */}
      <AnimatePresence>
        {editDialogWorkflow && (
          <WorkflowViewDialog
            workflow={editDialogWorkflow}
            agents={agents}
            onClose={() => setEditDialogWorkflow(null)}
            onSaved={refetch}
          />
        )}
      </AnimatePresence>

      {/* Pipeline runner overlay (FALLBACK -- kept for backward compat) */}
      <AnimatePresence>
        {pipelineWorkflow && (
          <PipelineRunner
            workflow={pipelineWorkflow}
            onClose={handlePipelineClose}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
