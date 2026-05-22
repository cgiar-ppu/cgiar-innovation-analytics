/**
 * @file MessageItem.tsx
 * @module components/workflows
 *
 * Unified message renderer used by WorkflowRunPanel, PipelineStepCard, and
 * RunDetailView. Supports both controlled thinking state (parent manages
 * isThinkingExpanded / onToggleThinking) and uncontrolled (self-managed via
 * internal useState when those props are omitted).
 */

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, ChevronRight, Wrench, AlertTriangle,
  CheckCircle2, Sparkles, Loader2,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import type { WorkflowRunMessage } from '../../lib/types-extended';

// ---------------------------------------------------------------------------
// Public props
// ---------------------------------------------------------------------------

export interface MessageItemProps {
  id: string | number;
  type: string; // 'text' | 'thinking' | 'tool_use' | 'tool_result' | 'error' | 'agent_activity' | 'system'
  content: string;
  tool?: string;
  toolInput?: unknown;
  isError?: boolean;
  /** Controlled thinking state — if omitted the component manages its own. */
  isThinkingExpanded?: boolean;
  /** Controlled thinking toggle callback. */
  onToggleThinking?: (id: string | number) => void;
}

// ---------------------------------------------------------------------------
// Adapter for RunDetailView's WorkflowRunMessage type
// ---------------------------------------------------------------------------

export function adaptWorkflowRunMessage(msg: WorkflowRunMessage): MessageItemProps {
  const data = (typeof msg.data === 'object' && msg.data !== null)
    ? msg.data as Record<string, unknown>
    : {} as Record<string, unknown>;

  return {
    id: msg.id,
    type: msg.type,
    content: (data.content as string) ?? '',
    tool: (data.tool as string) ?? undefined,
    toolInput: data.input ?? undefined,
    isError: Boolean(msg.is_error),
  };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function MessageItem({
  id,
  type,
  content,
  tool,
  toolInput,
  isError,
  isThinkingExpanded: controlledExpanded,
  onToggleThinking,
}: MessageItemProps) {
  // Uncontrolled thinking state (used when parent does not provide props)
  const [selfExpanded, setSelfExpanded] = useState(false);
  const thinkingOpen = controlledExpanded ?? selfExpanded;
  const toggleThinking = () => {
    if (onToggleThinking) {
      onToggleThinking(id);
    } else {
      setSelfExpanded(prev => !prev);
    }
  };

  // --- thinking ---
  if (type === 'thinking') {
    if (!content) return null;
    return (
      <div>
        <button
          onClick={toggleThinking}
          className="flex items-center gap-1.5 text-xs hover:opacity-80 transition-opacity mb-1"
          style={{ color: 'var(--text-muted)' }}
        >
          {thinkingOpen
            ? <ChevronDown className="w-3 h-3" />
            : <ChevronRight className="w-3 h-3" />
          }
          <Sparkles className="w-3 h-3" />
          Thinking...
        </button>
        <AnimatePresence>
          {thinkingOpen && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden"
            >
              <div
                className="px-3 py-2 rounded-lg text-xs italic max-h-48 overflow-y-auto"
                style={{
                  background: 'color-mix(in srgb, var(--accent) 6%, transparent)',
                  border: '1px solid color-mix(in srgb, var(--accent) 15%, transparent)',
                  color: 'var(--text-muted)',
                }}
              >
                {content}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }

  // --- tool_use ---
  if (type === 'tool_use') {
    return (
      <div
        className="rounded-lg px-3 py-2"
        style={{
          background: 'color-mix(in srgb, var(--warning) 6%, transparent)',
          border: '1px solid color-mix(in srgb, var(--warning) 20%, transparent)',
        }}
      >
        <div className="flex items-center gap-1.5 text-xs font-semibold mb-1" style={{ color: 'var(--warning)' }}>
          <Wrench className="w-3 h-3" />
          {tool ?? 'unknown'}
        </div>
        {toolInput != null && (
          <pre
            className="text-[10px] overflow-x-auto max-h-24 overflow-y-auto"
            style={{ color: 'var(--text-muted)' }}
          >
            {typeof toolInput === 'object' ? JSON.stringify(toolInput, null, 2) : String(toolInput)}
          </pre>
        )}
      </div>
    );
  }

  // --- tool_result ---
  if (type === 'tool_result') {
    const borderColor = isError
      ? 'color-mix(in srgb, var(--danger) 25%, transparent)'
      : 'color-mix(in srgb, var(--success) 25%, transparent)';
    const bgColor = isError
      ? 'color-mix(in srgb, var(--danger) 6%, transparent)'
      : 'color-mix(in srgb, var(--success) 6%, transparent)';
    const labelColor = isError ? 'var(--danger)' : 'var(--success)';

    return (
      <div
        className="rounded-lg px-3 py-2"
        style={{ background: bgColor, border: `1px solid ${borderColor}` }}
      >
        <div className="flex items-center gap-1.5 text-xs font-semibold mb-1" style={{ color: labelColor }}>
          {isError
            ? <AlertTriangle className="w-3 h-3" />
            : <CheckCircle2 className="w-3 h-3" />
          }
          Tool Result
        </div>
        <pre
          className="text-[10px] overflow-x-auto max-h-32 overflow-y-auto whitespace-pre-wrap"
          style={{ color: 'var(--text-muted)' }}
        >
          {content?.slice(0, 2000)}
        </pre>
      </div>
    );
  }

  // --- error ---
  if (type === 'error') {
    return (
      <div
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
        style={{
          background: 'color-mix(in srgb, var(--danger) 10%, transparent)',
          color: 'var(--danger)',
        }}
      >
        <AlertTriangle className="w-3 h-3 shrink-0" />
        {content}
      </div>
    );
  }

  // --- agent_activity ---
  if (type === 'agent_activity') {
    return (
      <div
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
        style={{
          background: 'color-mix(in srgb, var(--accent) 8%, transparent)',
          border: '1px solid color-mix(in srgb, var(--accent) 15%, transparent)',
          color: 'var(--accent)',
        }}
      >
        <Loader2 className="w-3 h-3 animate-spin" />
        {content}
      </div>
    );
  }

  // --- system ---
  if (type === 'system') {
    return (
      <div
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs"
        style={{
          background: 'color-mix(in srgb, var(--text-muted) 8%, transparent)',
          color: 'var(--text-muted)',
        }}
      >
        {content}
      </div>
    );
  }

  // --- text (default) — rendered with ReactMarkdown ---
  if (!content) return null;
  return (
    <div
      className="px-3 py-2 rounded-xl text-sm glass"
      style={{ color: 'var(--text)' }}
    >
      <div
        className="prose prose-sm max-w-none [&_p]:my-1 [&_ul]:my-1 [&_ol]:my-1 [&_li]:my-0.5 [&_pre]:my-1 [&_code]:text-[var(--accent)]"
        style={{ color: 'var(--text)' }}
      >
        <ReactMarkdown>{content}</ReactMarkdown>
      </div>
    </div>
  );
}
