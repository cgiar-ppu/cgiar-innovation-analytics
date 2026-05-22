/**
 * @file pipeline.ts
 * @module lib/types
 *
 * Types shared across pipeline execution consumers, including the
 * Zustand workflowRuns store and the usePipelineExecution hook.
 */

/**
 * Canonical message type for pipeline step messages. Used by both the
 * Zustand workflowRuns store and the usePipelineExecution hook.
 *
 * Replaces the formerly-duplicated `StepMessage` (usePipelineExecution)
 * and `RunStepMessage` (workflowRuns) interfaces.
 */
export interface PipelineStepMessage {
  id: string;
  type: 'text' | 'thinking' | 'tool_use' | 'tool_result' | 'system' | 'agent_activity' | 'result' | 'error';
  content: string;
  tool?: string;
  toolInput?: Record<string, unknown>;
  toolUseId?: string;
  isError?: boolean;
  estimatedCost?: number;
  turns?: number;
  durationMs?: number;
}

/**
 * State for a single step within a pipeline execution.
 * Shared across the workflowRuns store and usePipelineExecution hook.
 */
export interface PipelineStepState {
  agent_id: string;
  agent_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  messages: PipelineStepMessage[];
  durationS?: number;
  outputPreview?: string;
}
