/**
 * @file useWorkflowRunConnection.ts
 * @module hooks
 *
 * Custom React hook that manages a WebSocket connection to the workflow
 * pipeline endpoint. Supports starting new runs, attaching to existing
 * runs, and routing all events into the workflowRuns Zustand store.
 *
 * Disconnecting does NOT cancel the pipeline -- it continues on the server.
 * Reconnection uses exponential backoff (borrowed from useWebSocket.ts).
 */

import { useRef, useState, useCallback, useEffect } from 'react';
import { useWorkflowRunsStore } from '../stores/workflowRuns';

/** Maximum delay (ms) between reconnection attempts. */
const MAX_BACKOFF = 30_000;

/** Starting delay (ms) for the first reconnection attempt. */
const INITIAL_BACKOFF = 1_000;

interface UseWorkflowRunConnectionOptions {
  /** The workflow ID to connect to (determines the WebSocket URL path). */
  workflowId: string | null;
  /** If true, the connection is established on mount. */
  enabled?: boolean;
}

interface UseWorkflowRunConnectionReturn {
  /** Start a new pipeline run. Pass the temporary store run ID so it can be replaced
   *  with the real server-assigned ID when run_started arrives. */
  startRun: (prompt: string, stepPrompts?: string[], tempRunId?: string) => void;
  /** Attach to an existing pipeline run by ID. */
  attachToRun: (runId: string) => void;
  /** Cancel a running pipeline. If no runId, cancels the current run. */
  cancelRun: (runId?: string) => void;
  /** True when the WebSocket is open. */
  isConnected: boolean;
  /** Current connection status. */
  connectionStatus: 'disconnected' | 'connecting' | 'connected' | 'error';
  /** Manually trigger a reconnect. */
  reconnect: () => void;
  /** Disconnect the WebSocket (pipeline continues on server). */
  disconnect: () => void;
}

export function useWorkflowRunConnection({
  workflowId,
  enabled = true,
}: UseWorkflowRunConnectionOptions): UseWorkflowRunConnectionReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const backoffRef = useRef(INITIAL_BACKOFF);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const keepAliveRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'disconnected' | 'connecting' | 'connected' | 'error'>('disconnected');

  // Track the current run_id so we know which run incoming events belong to
  const currentRunIdRef = useRef<string | null>(null);
  // Track the pending (temporary) run ID so we can replace it on run_started
  const pendingTempRunIdRef = useRef<string | null>(null);
  // Track intentional disconnects to suppress auto-reconnect
  const intentionalDisconnectRef = useRef(false);

  const store = useWorkflowRunsStore;

  // Use a ref for scheduleReconnect to break the circular dependency
  // between connect -> scheduleReconnect -> connect
  const scheduleReconnectRef = useRef<() => void>(() => {});

  const connect = useCallback(() => {
    if (!workflowId || !enabled) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${proto}//${window.location.host}/ws/workflow/${workflowId}`;

    setConnectionStatus('connecting');
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      setConnectionStatus('connected');
      backoffRef.current = INITIAL_BACKOFF;

      // Auto-reattach: if we have an active run for this workflow (from a
      // previous connection that dropped), re-attach so the server replays
      // buffered events and resumes live forwarding. This handles the case
      // where the user navigates away and back, or the WS drops mid-run.
      const reattachId = currentRunIdRef.current || (() => {
        const state = store.getState();
        if (!state.activeRunId) return null;
        const run = state.runs[state.activeRunId];
        if (run && run.workflowId === workflowId && run.status === 'running') {
          return state.activeRunId;
        }
        return null;
      })();
      if (reattachId && ws.readyState === WebSocket.OPEN) {
        currentRunIdRef.current = reattachId;
        ws.send(JSON.stringify({ type: 'attach', run_id: reattachId }));
      }

      // Keepalive pings every 25s
      if (keepAliveRef.current) clearInterval(keepAliveRef.current);
      keepAliveRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 25_000);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);

        // Handle run_started: the server assigned a run_id — replace temp ID
        if (msg.type === 'run_started') {
          const tempId = pendingTempRunIdRef.current;
          currentRunIdRef.current = msg.run_id;
          if (tempId) {
            store.getState().replaceRunId(tempId, msg.run_id);
            pendingTempRunIdRef.current = null;
          }
          return;
        }

        // Handle attached: we successfully attached to an existing run
        if (msg.type === 'attached') {
          currentRunIdRef.current = msg.run_id;
          return;
        }

        // Handle pong (keepalive response)
        if (msg.type === 'pong') return;

        // Route all other events to the store
        const runId = msg.run_id || currentRunIdRef.current;
        if (runId) {
          store.getState().handleEvent(runId, msg);
        }
      } catch {
        // Ignore unparseable frames
      }
    };

    ws.onerror = () => {
      setConnectionStatus('error');
    };

    ws.onclose = () => {
      setIsConnected(false);
      setConnectionStatus('disconnected');
      wsRef.current = null;
      if (keepAliveRef.current) {
        clearInterval(keepAliveRef.current);
        keepAliveRef.current = undefined;
      }
      // Auto-reconnect with backoff only if still enabled, has a workflow,
      // and this was not an intentional disconnect
      if (enabled && workflowId && !intentionalDisconnectRef.current) {
        scheduleReconnectRef.current();
      }
      intentionalDisconnectRef.current = false;
    };
  }, [workflowId, enabled, store]);

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    setConnectionStatus('connecting');
    const delay = backoffRef.current;
    backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF);
    reconnectTimerRef.current = setTimeout(() => {
      connect();
    }, delay);
  }, [connect]);

  // Keep the ref in sync so the onclose handler always calls the latest version
  scheduleReconnectRef.current = scheduleReconnect;

  const disconnect = useCallback(() => {
    intentionalDisconnectRef.current = true;
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
    if (keepAliveRef.current) clearInterval(keepAliveRef.current);
    if (wsRef.current) {
      wsRef.current.close(1000);
      wsRef.current = null;
    }
    setIsConnected(false);
    setConnectionStatus('disconnected');
  }, []);

  const startRun = useCallback((prompt: string, stepPrompts?: string[], tempRunId?: string) => {
    if (tempRunId) {
      pendingTempRunIdRef.current = tempRunId;
    }
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      return;
    }
    wsRef.current.send(JSON.stringify({
      type: 'run',
      prompt,
      step_prompts: stepPrompts || [],
    }));
  }, []);

  const attachToRun = useCallback((runId: string) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({
      type: 'attach',
      run_id: runId,
    }));
  }, []);

  const cancelRun = useCallback((runId?: string) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({
      type: 'cancel',
      run_id: runId || currentRunIdRef.current,
    }));
  }, []);

  // Connect on mount when enabled
  useEffect(() => {
    if (enabled && workflowId) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [workflowId, enabled, connect, disconnect]);

  return {
    startRun,
    attachToRun,
    cancelRun,
    isConnected,
    connectionStatus,
    reconnect: connect,
    disconnect,
  };
}
