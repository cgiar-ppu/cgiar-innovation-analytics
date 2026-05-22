/**
 * @file pipelineEventReducer.ts
 * @module lib
 *
 * Pure function that applies a single pipeline event to step state.
 * Used by both the Zustand workflowRuns store and the usePipelineExecution hook
 * to eliminate duplicate event-handling logic.
 *
 * The reducer is intentionally framework-agnostic: it takes immutable state in
 * and returns new immutable state out, with no side effects.
 */

import type { PipelineStepMessage, PipelineStepState } from './types';
import type { PipelineEvent } from './types-extended';

// ---------------------------------------------------------------------------
// Result shape returned by applyPipelineEvent
// ---------------------------------------------------------------------------

export interface PipelineEventResult {
  /** Updated step array (always a new reference if anything changed). */
  steps: PipelineStepState[];
  /** Updated streaming text buffer (reset on structural events). */
  streamingText: string;
  /** Updated streaming thinking buffer (reset on structural events). */
  streamingThinking: string;
  /** Updated current step index (-1 means no step active). */
  currentStep: number;
  /** Set of step indices that should be expanded in the UI. `null` = no change. */
  expandedStepChanges: { index: number; expanded: boolean }[] | null;
  /** Pipeline-level status change, if any. */
  pipelineStatus: 'completed' | 'cancelled' | 'failed' | null;
  /** Total duration in seconds, if pipeline_complete event. */
  totalDurationS: number | null;
  /** Run log ID, if pipeline_complete event. */
  runLogId: string | null;
  /** Pipeline-level error message, if any. */
  connectionError: string | null;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Replaces streaming IDs with finalized IDs for a given step index.
 */
function finalizeStreamingIds(msgs: PipelineStepMessage[], stepIdx: number, suffix?: string): PipelineStepMessage[] {
  const textFinal = suffix ? `text-${suffix}-${stepIdx}` : `text-${Date.now()}`;
  const thinkFinal = suffix ? `thinking-${suffix}-${stepIdx}` : `thinking-${Date.now()}`;
  return msgs.map(m => {
    if (m.id === `streaming-text-${stepIdx}`) return { ...m, id: textFinal };
    if (m.id === `streaming-thinking-${stepIdx}`) return { ...m, id: thinkFinal };
    return m;
  });
}

/**
 * Appends text/thinking content to the streaming message for a step,
 * creating one if it does not yet exist.
 */
function appendStreamingContent(
  msgs: PipelineStepMessage[],
  stepIdx: number,
  msgType: 'text' | 'thinking',
  content: string,
): PipelineStepMessage[] {
  const result = [...msgs];
  const streamId = `streaming-${msgType}-${stepIdx}`;
  const last = result[result.length - 1];
  if (last && last.type === msgType && last.id === streamId) {
    result[result.length - 1] = { ...last, content: last.content + content };
  } else {
    result.push({ id: streamId, type: msgType, content });
  }
  return result;
}

/**
 * Immutably updates a single step in the steps array.
 */
function updateStep(
  steps: PipelineStepState[],
  idx: number,
  updater: (step: PipelineStepState) => PipelineStepState,
): PipelineStepState[] {
  return steps.map((s, i) => (i === idx ? updater(s) : s));
}

// ---------------------------------------------------------------------------
// Main reducer
// ---------------------------------------------------------------------------

/**
 * Applies a single pipeline event to the current step/streaming state and
 * returns a new state object. This is a pure function with no side effects.
 *
 * @param steps           Current step states
 * @param event           The incoming pipeline event
 * @param currentStep     Index of the currently-active step (-1 if none)
 * @param streamingText   Current streaming text buffer
 * @param streamingThinking Current streaming thinking buffer
 * @param runId           Run identifier (used for generating unique message IDs)
 */
export function applyPipelineEvent(
  steps: PipelineStepState[],
  event: PipelineEvent & Record<string, unknown>,
  currentStep: number,
  streamingText: string,
  streamingThinking: string,
  runId: string = '',
): PipelineEventResult {
  const result: PipelineEventResult = {
    steps,
    streamingText,
    streamingThinking,
    currentStep,
    expandedStepChanges: null,
    pipelineStatus: null,
    totalDurationS: null,
    runLogId: null,
    connectionError: null,
  };

  const type = event.type;
  const stepIdx = typeof event.step === 'number' ? event.step : currentStep;

  switch (type) {
    case 'step_start': {
      const idx = event.step as number;
      if (idx == null || idx < 0) break;
      result.currentStep = idx;
      result.steps = updateStep(steps, idx, s => ({
        ...s,
        status: 'running',
        agent_name: (event.agent_name as string) || s.agent_name,
      }));
      result.expandedStepChanges = [{ index: idx, expanded: true }];
      break;
    }

    case 'text': {
      const content = (event.content as string) ?? '';
      result.streamingText = streamingText + content;
      if (stepIdx >= 0 && steps[stepIdx]) {
        result.steps = updateStep(steps, stepIdx, s => ({
          ...s,
          messages: appendStreamingContent(s.messages, stepIdx, 'text', content),
        }));
      }
      break;
    }

    case 'thinking': {
      const content = (event.content as string) ?? '';
      result.streamingThinking = streamingThinking + content;
      if (stepIdx >= 0 && steps[stepIdx]) {
        result.steps = updateStep(steps, stepIdx, s => ({
          ...s,
          messages: appendStreamingContent(s.messages, stepIdx, 'thinking', content),
        }));
      }
      break;
    }

    case 'tool_use': {
      result.streamingText = '';
      result.streamingThinking = '';
      if (stepIdx >= 0 && steps[stepIdx]) {
        result.steps = updateStep(steps, stepIdx, s => {
          const msgs = finalizeStreamingIds(s.messages, stepIdx);
          msgs.push({
            id: runId ? `${runId}-${stepIdx}-tool-${Date.now()}` : `tool-${event.tool_use_id ?? Date.now()}`,
            type: 'tool_use',
            content: '',
            tool: event.tool,
            toolInput: event.input as Record<string, unknown>,
            toolUseId: event.tool_use_id,
          });
          return { ...s, messages: msgs };
        });
      }
      break;
    }

    case 'tool_result': {
      if (stepIdx >= 0 && steps[stepIdx]) {
        const content = typeof event.content === 'string'
          ? event.content
          : JSON.stringify(event.content);
        result.steps = updateStep(steps, stepIdx, s => ({
          ...s,
          messages: [...s.messages, {
            id: runId ? `${runId}-${stepIdx}-result-${Date.now()}` : `result-${event.tool_use_id ?? Date.now()}`,
            type: 'tool_result' as const,
            content: content ?? '',
            toolUseId: event.tool_use_id,
            isError: event.is_error,
          }],
        }));
      }
      break;
    }

    case 'result': {
      if (stepIdx >= 0 && steps[stepIdx]) {
        result.steps = updateStep(steps, stepIdx, s => ({
          ...s,
          messages: finalizeStreamingIds(s.messages, stepIdx),
        }));
      }
      break;
    }

    case 'step_complete': {
      const idx = event.step as number;
      if (idx == null || idx < 0) break;
      result.streamingText = '';
      result.streamingThinking = '';
      result.steps = updateStep(steps, idx, s => ({
        ...s,
        status: 'completed',
        messages: finalizeStreamingIds(s.messages, idx, 'final'),
        durationS: event.duration_s,
        outputPreview: event.output_preview,
      }));
      // Collapse completed step, expand next
      const changes: { index: number; expanded: boolean }[] = [
        { index: idx, expanded: false },
      ];
      if (idx + 1 < steps.length) {
        changes.push({ index: idx + 1, expanded: true });
      }
      result.expandedStepChanges = changes;
      break;
    }

    case 'pipeline_complete': {
      result.pipelineStatus = 'completed';
      result.totalDurationS = (event.total_duration_s as number) ?? null;
      result.runLogId = (event.run_log_id as string) ?? null;
      break;
    }

    case 'pipeline_cancelled':
    case 'cancelled': {
      result.pipelineStatus = 'cancelled';
      break;
    }

    case 'error': {
      if (stepIdx >= 0 && steps[stepIdx]) {
        result.steps = updateStep(steps, stepIdx, s => ({
          ...s,
          status: 'failed',
          messages: [...s.messages, {
            id: `error-${Date.now()}`,
            type: 'error' as const,
            content: (event.message as string) ?? 'Unknown error',
          }],
        }));
      }
      if (stepIdx < 0) {
        result.pipelineStatus = 'failed';
        result.connectionError = (event.message as string) ?? 'Pipeline error';
      }
      break;
    }
  }

  return result;
}
