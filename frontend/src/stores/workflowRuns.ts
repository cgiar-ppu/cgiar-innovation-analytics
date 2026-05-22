/**
 * @file workflowRuns.ts
 * @module stores
 *
 * Zustand store for concurrent workflow run state. Each run is tracked
 * independently with its own step list, streaming buffers, and event history.
 * The run manager on the backend owns execution lifecycle; this store is
 * purely a UI-side projection of live events.
 *
 * Event-to-state logic is delegated to the shared {@link applyPipelineEvent}
 * reducer in `lib/pipelineEventReducer.ts`.
 */

import { create } from 'zustand';
import type { PipelineStepMessage, PipelineStepState } from '../lib/types';
import { applyPipelineEvent } from '../lib/pipelineEventReducer';
import { agentDisplayName } from '../components/workflows/workflowAgentUtils';

export type RunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

// Re-export shared types under their legacy names for backward compatibility.
// Consumers that imported RunStepMessage or RunStepState from this module
// will continue to work without changes.
export type { PipelineStepMessage as RunStepMessage };
export type { PipelineStepState as RunStepState };

export interface WorkflowRun {
  runId: string;
  workflowId: string;
  workflowName: string;
  status: RunStatus;
  steps: PipelineStepState[];
  agentSequence: string[];
  startedAt: number;
  totalDurationS: number | null;
  expandedSteps: Set<number>;
  streamingText: string;
  streamingThinking: string;
  currentStep: number;
}

interface WorkflowRunsState {
  runs: Record<string, WorkflowRun>;
  activeRunId: string | null;

  // Actions
  addRun: (runId: string, workflowId: string, workflowName: string, agentSequence: string[]) => void;
  removeRun: (runId: string) => void;
  /** Replace a temporary run ID with the real server-assigned ID. */
  replaceRunId: (oldRunId: string, newRunId: string) => void;
  setActiveRun: (runId: string | null) => void;
  handleEvent: (runId: string, event: Record<string, unknown>) => void;
  toggleStep: (runId: string, stepIndex: number) => void;
  hydrateFromEvents: (runId: string, events: Record<string, unknown>[]) => void;
}

export const useWorkflowRunsStore = create<WorkflowRunsState>((set, get) => ({
  runs: {},
  activeRunId: null,

  addRun: (runId, workflowId, workflowName, agentSequence) => {
    set(state => ({
      runs: {
        ...state.runs,
        [runId]: {
          runId,
          workflowId,
          workflowName,
          status: 'running',
          steps: agentSequence.map(agentId => ({
            agent_id: agentId,
            agent_name: agentDisplayName(agentId),
            status: 'pending' as const,
            messages: [] as PipelineStepMessage[],
          })),
          agentSequence,
          startedAt: Date.now(),
          totalDurationS: null,
          expandedSteps: new Set<number>(),
          streamingText: '',
          streamingThinking: '',
          currentStep: -1,
        },
      },
      activeRunId: runId,
    }));
  },

  removeRun: (runId) => {
    set(state => {
      const { [runId]: _, ...rest } = state.runs;
      return {
        runs: rest,
        activeRunId: state.activeRunId === runId ? null : state.activeRunId,
      };
    });
  },

  replaceRunId: (oldRunId, newRunId) => {
    set(state => {
      const oldRun = state.runs[oldRunId];
      if (!oldRun) return state;
      const { [oldRunId]: _, ...rest } = state.runs;
      const updatedRun = { ...oldRun, runId: newRunId };
      return {
        runs: { ...rest, [newRunId]: updatedRun },
        activeRunId: state.activeRunId === oldRunId ? newRunId : state.activeRunId,
      };
    });
  },

  setActiveRun: (runId) => set({ activeRunId: runId }),

  toggleStep: (runId, stepIndex) => {
    set(state => {
      const run = state.runs[runId];
      if (!run) return state;
      const newExpanded = new Set(run.expandedSteps);
      if (newExpanded.has(stepIndex)) {
        newExpanded.delete(stepIndex);
      } else {
        newExpanded.add(stepIndex);
      }
      return {
        runs: {
          ...state.runs,
          [runId]: { ...run, expandedSteps: newExpanded },
        },
      };
    });
  },

  handleEvent: (runId, event) => {
    set(state => {
      const run = state.runs[runId];
      if (!run) return state;

      // Delegate to the shared pure reducer
      const result = applyPipelineEvent(
        run.steps,
        event as Parameters<typeof applyPipelineEvent>[1],
        run.currentStep,
        run.streamingText,
        run.streamingThinking,
        runId,
      );

      const updated: WorkflowRun = {
        ...run,
        steps: result.steps,
        streamingText: result.streamingText,
        streamingThinking: result.streamingThinking,
        currentStep: result.currentStep,
      };

      // Apply expanded-step changes (Set-based in this store)
      if (result.expandedStepChanges) {
        const newExpanded = new Set(updated.expandedSteps);
        for (const change of result.expandedStepChanges) {
          if (change.expanded) {
            newExpanded.add(change.index);
          } else {
            newExpanded.delete(change.index);
          }
        }
        updated.expandedSteps = newExpanded;
      }

      // Apply pipeline-level status changes
      if (result.pipelineStatus === 'completed') {
        updated.status = 'completed';
        updated.totalDurationS = result.totalDurationS;
      } else if (result.pipelineStatus === 'cancelled') {
        updated.status = 'cancelled';
      } else if (result.pipelineStatus === 'failed') {
        updated.status = 'failed';
      }

      // Handle pipeline_status event (pass-through for status updates)
      if ((event as Record<string, unknown>).type === 'pipeline_status') {
        updated.status = (event as Record<string, unknown>).status as RunStatus;
      }

      // Handle agent_activity event (not in shared reducer since only store uses it)
      if ((event as Record<string, unknown>).type === 'agent_activity') {
        const stepIdx = typeof event.step === 'number' ? (event.step as number) : updated.currentStep;
        const targetStep = stepIdx >= 0 ? updated.steps[stepIdx] : undefined;
        if (targetStep) {
          const newSteps = [...updated.steps];
          newSteps[stepIdx] = {
            ...targetStep,
            messages: [...targetStep.messages, {
              id: `${runId}-${stepIdx}-agent-${Date.now()}`,
              type: 'agent_activity',
              content: `Delegating to ${(event as Record<string, unknown>).agent}`,
              tool: (event as Record<string, unknown>).agent as string,
            }],
          };
          updated.steps = newSteps;
        }
      }

      return {
        runs: { ...state.runs, [runId]: updated },
      };
    });
  },

  hydrateFromEvents: (runId, events) => {
    for (const event of events) {
      get().handleEvent(runId, event);
    }
  },
}));
