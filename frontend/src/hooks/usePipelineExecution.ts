import { useState, useEffect, useRef, useCallback } from 'react';
import type { Workflow, PipelineEvent } from '../lib/types-extended';
import type { PipelineStepMessage, PipelineStepState } from '../lib/types';
import { applyPipelineEvent } from '../lib/pipelineEventReducer';
import { agentDisplayName } from '../components/workflows/workflowAgentUtils';

// Re-export shared types under their legacy names for backward compatibility.
// Consumers that imported StepMessage or StepState from this module
// will continue to work without changes.
export type { PipelineStepMessage as StepMessage };
export type { PipelineStepState as StepState };

export type PipelineStatus = 'connecting' | 'running' | 'completed' | 'cancelled' | 'error';

// ─── Hook ─────────────────────────────────────────────────────────────────────

interface UsePipelineExecutionOptions {
  workflow: Workflow | null;
  prompt: string;
  stepPrompts: string[];
}

interface UsePipelineExecutionResult {
  pipelineStatus: PipelineStatus;
  steps: PipelineStepState[];
  expandedSteps: Record<number, boolean>;
  showThinking: Record<string, boolean>;
  totalDurationS: number | null;
  connectionError: string | null;
  runLogId: string | null;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  handleCancel: () => void;
  toggleStep: (idx: number) => void;
  toggleThinking: (id: string) => void;
  setExpandedSteps: React.Dispatch<React.SetStateAction<Record<number, boolean>>>;
}

export function usePipelineExecution({
  workflow,
  prompt,
  stepPrompts,
}: UsePipelineExecutionOptions): UsePipelineExecutionResult {
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>('connecting');
  const [steps, setSteps] = useState<PipelineStepState[]>(() =>
    (workflow?.agent_sequence ?? []).map(id => ({
      agent_id: id,
      agent_name: agentDisplayName(id),
      status: 'pending',
      messages: [] as PipelineStepMessage[],
    }))
  );
  const [expandedSteps, setExpandedSteps] = useState<Record<number, boolean>>({});
  const [showThinking, setShowThinking] = useState<Record<string, boolean>>({});
  const [totalDurationS, setTotalDurationS] = useState<number | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [runLogId, setRunLogId] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Track pipeline status in a ref so ws.onclose can read it without stale closures
  const pipelineStatusRef = useRef<PipelineStatus>('connecting');

  // Refs for streaming buffers (not rendered directly, only used by reducer)
  const streamingTextRef = useRef('');
  const streamingThinkingRef = useRef('');
  const currentStepRef = useRef(-1);

  // Keep ref in sync with state
  useEffect(() => {
    pipelineStatusRef.current = pipelineStatus;
  }, [pipelineStatus]);

  // Auto-scroll to bottom of message area
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [steps]);

  // ─── Message handler (stable ref so ws.onmessage closure never re-registers) ─

  const handleMessage = useCallback((msg: PipelineEvent) => {
    // We need to apply the reducer with the actual current steps,
    // so we use setSteps with a functional updater
    setSteps(prevSteps => {
      const applied = applyPipelineEvent(
        prevSteps,
        msg as PipelineEvent & Record<string, unknown>,
        currentStepRef.current,
        streamingTextRef.current,
        streamingThinkingRef.current,
      );

      // Update refs with new streaming state
      streamingTextRef.current = applied.streamingText;
      streamingThinkingRef.current = applied.streamingThinking;
      currentStepRef.current = applied.currentStep;

      // Apply expanded-step changes (Record-based in this hook)
      if (applied.expandedStepChanges) {
        setExpandedSteps(prev => {
          const next = { ...prev };
          for (const change of applied.expandedStepChanges!) {
            next[change.index] = change.expanded;
          }
          return next;
        });
      }

      // Apply pipeline-level status changes
      if (applied.pipelineStatus === 'completed') {
        setPipelineStatus('completed');
        setTotalDurationS(applied.totalDurationS);
        if (applied.runLogId) setRunLogId(applied.runLogId);
      } else if (applied.pipelineStatus === 'cancelled') {
        setPipelineStatus('cancelled');
      } else if (applied.pipelineStatus === 'failed') {
        setConnectionError(applied.connectionError);
        setPipelineStatus('error');
      }

      return applied.steps;
    });
  }, []);

  // ─── WebSocket: open on mount, send run immediately ───────────────────────

  useEffect(() => {
    if (!workflow) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${protocol}//${window.location.host}/ws/workflow/${workflow.id}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    // Keepalive pings every 25 s
    const keepAlive = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      } else {
        clearInterval(keepAlive);
      }
    }, 25_000);
    ws.addEventListener('close', () => clearInterval(keepAlive));

    ws.onopen = () => {
      setPipelineStatus('running');
      ws.send(JSON.stringify({
        type: 'run',
        prompt,
        step_prompts: stepPrompts,
      }));
    };

    ws.onmessage = (e) => {
      try {
        const msg: PipelineEvent = JSON.parse(e.data);
        handleMessage(msg);
      } catch {
        // ignore unparseable frames
      }
    };

    ws.onerror = () => {
      setConnectionError('WebSocket connection error');
      setPipelineStatus('error');
    };

    ws.onclose = (e) => {
      clearInterval(keepAlive);
      if (e.code !== 1000 && pipelineStatusRef.current === 'running') {
        setConnectionError(`Disconnected (${e.reason || 'code ' + e.code})`);
        setPipelineStatus('error');
      }
    };

    return () => {
      clearInterval(keepAlive);
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close(1000);
      }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workflow?.id]);

  // ─── Actions ──────────────────────────────────────────────────────────────

  const handleCancel = () => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'cancel' }));
    }
    setPipelineStatus('cancelled');
  };

  const toggleStep = (idx: number) => {
    setExpandedSteps(prev => ({ ...prev, [idx]: !prev[idx] }));
  };

  const toggleThinking = (id: string) => {
    setShowThinking(prev => ({ ...prev, [id]: !prev[id] }));
  };

  return {
    pipelineStatus,
    steps,
    expandedSteps,
    showThinking,
    totalDurationS,
    connectionError,
    runLogId,
    messagesEndRef,
    handleCancel,
    toggleStep,
    toggleThinking,
    setExpandedSteps,
  };
}
