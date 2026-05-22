/**
 * @file PipelineMessageRenderer.tsx
 * @module components/workflows
 *
 * Shared message renderer for pipeline/workflow step messages. Wraps the
 * existing MessageItem component and provides adapters for the two message
 * shapes used across the codebase:
 *
 *   - PipelineStepMessage (shared type for live pipeline execution)
 *   - WorkflowRunMessage  (server-persisted, used by RunDetailView)
 *
 * Usage:
 *   <PipelineMessageRenderer msg={msg} />
 *   <PipelineMessageRenderer msg={msg} isThinkingExpanded={...} onToggleThinking={...} />
 */

import MessageItem from './MessageItem';
import { adaptWorkflowRunMessage } from './MessageItem';
import type { PipelineStepMessage } from '../../lib/types';
import type { WorkflowRunMessage } from '../../lib/types-extended';

// ---------------------------------------------------------------------------
// Union type covering both message shapes (PipelineStepMessage is now the
// single canonical type used by both the store and the hook)
// ---------------------------------------------------------------------------

export type PipelineMessage = PipelineStepMessage | WorkflowRunMessage;

// ---------------------------------------------------------------------------
// Type guards
// ---------------------------------------------------------------------------

function isWorkflowRunMessage(msg: PipelineMessage): msg is WorkflowRunMessage {
  // WorkflowRunMessage has numeric `id` and a `data` field
  return typeof (msg as WorkflowRunMessage).data !== 'undefined';
}

function isStepOrRunStepMessage(msg: PipelineMessage): msg is PipelineStepMessage {
  return !isWorkflowRunMessage(msg);
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface PipelineMessageRendererProps {
  msg: PipelineMessage;
  /** Controlled thinking expand state. If omitted, MessageItem manages its own. */
  isThinkingExpanded?: boolean;
  /** Controlled thinking toggle callback. */
  onToggleThinking?: (id: string) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function PipelineMessageRenderer({
  msg,
  isThinkingExpanded,
  onToggleThinking,
}: PipelineMessageRendererProps) {
  // Wrap the string-only callback to match MessageItem's (string | number) signature
  const wrappedToggle: ((id: string | number) => void) | undefined = onToggleThinking
    ? (id: string | number) => onToggleThinking(String(id))
    : undefined;

  // Adapt WorkflowRunMessage (server-persisted shape) to flat props
  if (isWorkflowRunMessage(msg)) {
    const adapted = adaptWorkflowRunMessage(msg);
    return (
      <MessageItem
        {...adapted}
        isThinkingExpanded={isThinkingExpanded}
        onToggleThinking={wrappedToggle}
      />
    );
  }

  // PipelineStepMessage (used by both live execution and the Zustand store)
  if (isStepOrRunStepMessage(msg)) {
    return (
      <MessageItem
        id={msg.id}
        type={msg.type}
        content={msg.content}
        tool={msg.tool}
        toolInput={msg.toolInput}
        isError={msg.isError}
        isThinkingExpanded={isThinkingExpanded}
        onToggleThinking={wrappedToggle}
      />
    );
  }

  return null;
}
