/**
 * @file useFleetConnection.ts
 * @module hooks
 *
 * Custom React hook that manages a WebSocket connection to the fleet
 * real-time endpoint at `/ws/fleet/{fleetId}`. Handles:
 *
 * - Connecting and reconnecting with exponential backoff (1s -> 30s cap).
 * - Routing incoming messages (agent status, batch progress, health updates)
 *   into the fleet Zustand store.
 * - Providing a typed `send` helper for outgoing commands.
 *
 * Disconnecting does NOT stop agents -- they continue on the server.
 */

import { useRef, useState, useCallback, useEffect } from 'react'
import { useFleetStore } from '../stores/fleet'
import type { FleetAgent } from '../stores/fleet'

/** Maximum delay (ms) between reconnection attempts. */
const MAX_BACKOFF = 30_000

/** Starting delay (ms) for the first reconnection attempt. */
const INITIAL_BACKOFF = 1_000

interface UseFleetConnectionOptions {
  /** The fleet ID to subscribe to. Null means no connection. */
  fleetId: string | null
  /** If false, the connection will not be established. Defaults to true. */
  enabled?: boolean
}

interface UseFleetConnectionReturn {
  /** Whether the WebSocket is currently open. */
  connected: boolean
  /** Finer-grained connection lifecycle status. */
  connectionStatus: 'disconnected' | 'connecting' | 'connected' | 'error'
  /** Sends a JSON-serialisable message over the socket. No-ops if closed. */
  send: (msg: Record<string, unknown>) => void
  /** Manually closes the socket (fleet continues on server). */
  disconnect: () => void
  /** Manually triggers a reconnection attempt. */
  reconnect: () => void
}

export function useFleetConnection({
  fleetId,
  enabled = true,
}: UseFleetConnectionOptions): UseFleetConnectionReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(INITIAL_BACKOFF)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const keepAliveRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined)
  const intentionalDisconnectRef = useRef(false)

  const [connected, setConnected] = useState(false)
  const [connectionStatus, setConnectionStatus] = useState<
    'disconnected' | 'connecting' | 'connected' | 'error'
  >('disconnected')

  const store = useFleetStore

  // Ref for scheduleReconnect to avoid circular dep with connect
  const scheduleReconnectRef = useRef<() => void>(() => {})

  // -------------------------------------------------------------------------
  // Message router
  // -------------------------------------------------------------------------

  const routeMessage = useCallback(
    (msg: Record<string, unknown>) => {
      const state = store.getState()

      switch (msg.type) {
        case 'fleet_state': {
          // Full state snapshot on connection
          if (Array.isArray(msg.agents)) {
            state.setAgents(msg.agents as FleetAgent[])
          }
          if (msg.health && typeof msg.health === 'object') {
            state.setHealth(msg.health as Parameters<typeof state.setHealth>[0])
          }
          break
        }

        case 'agent_status': {
          // Single agent status change
          const agentId = msg.agent_id as string | undefined
          if (agentId) {
            const updates: Partial<FleetAgent> = {}
            if (msg.status) updates.status = msg.status as FleetAgent['status']
            if (msg.turn_count !== undefined) updates.turn_count = msg.turn_count as number
            if (msg.last_active !== undefined) updates.last_active = msg.last_active as number | null
            if (msg.context_summary !== undefined) updates.context_summary = msg.context_summary as string
            if (msg.result !== undefined) updates.result = msg.result as string
            if (msg.error_message !== undefined) updates.error_message = msg.error_message as string
            state.updateAgent(agentId, updates)
          }
          break
        }

        case 'agent_complete': {
          const agentId = msg.agent_id as string | undefined
          if (agentId) {
            state.updateAgent(agentId, {
              status: (msg.status as FleetAgent['status']) || 'completed',
              result: (msg.result as string) || '',
              turn_count: (msg.turn_count as number) ?? 0,
            })
          }
          break
        }

        case 'batch_progress': {
          const runId = msg.run_id as string | undefined
          if (runId) {
            state.updateRun(runId, {
              progress_current: (msg.progress_current as number) ?? 0,
              progress_total: (msg.progress_total as number) ?? 0,
              status: (msg.status as string) || 'running',
            })
          }
          break
        }

        case 'batch_complete': {
          const runId = msg.run_id as string | undefined
          if (runId) {
            state.updateRun(runId, {
              status: 'completed',
              result_summary: (msg.result_summary as string) || '',
              completed_at: Date.now() / 1000,
              progress_current: (msg.progress_total as number) ?? 0,
            })
          }
          break
        }

        case 'health_update': {
          if (msg.health && typeof msg.health === 'object') {
            state.setHealth(msg.health as Parameters<typeof state.setHealth>[0])
          }
          break
        }

        case 'agents_spawned': {
          // New agents added to the fleet
          if (Array.isArray(msg.agents)) {
            const current = store.getState().agents
            state.setAgents([...current, ...(msg.agents as FleetAgent[])])
          }
          state.setSpawning(false)
          break
        }

        case 'error': {
          console.error('[FleetWS] Server error:', msg.message)
          break
        }

        case 'pong':
          // Keepalive response -- ignore
          break

        default:
          break
      }
    },
    [store],
  )

  // -------------------------------------------------------------------------
  // Connect / disconnect
  // -------------------------------------------------------------------------

  const connect = useCallback(() => {
    if (!fleetId || !enabled) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${proto}//${window.location.host}/ws/fleet/${fleetId}`

    setConnectionStatus('connecting')
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setConnectionStatus('connected')
      backoffRef.current = INITIAL_BACKOFF

      // Keepalive pings every 25s
      if (keepAliveRef.current) clearInterval(keepAliveRef.current)
      keepAliveRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }))
        }
      }, 25_000)
    }

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        routeMessage(msg)
      } catch {
        // Ignore unparseable frames
      }
    }

    ws.onerror = () => {
      setConnectionStatus('error')
    }

    ws.onclose = () => {
      setConnected(false)
      setConnectionStatus('disconnected')
      wsRef.current = null
      if (keepAliveRef.current) {
        clearInterval(keepAliveRef.current)
        keepAliveRef.current = undefined
      }
      if (enabled && fleetId && !intentionalDisconnectRef.current) {
        scheduleReconnectRef.current()
      }
      intentionalDisconnectRef.current = false
    }
  }, [fleetId, enabled, routeMessage])

  const scheduleReconnect = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    setConnectionStatus('connecting')
    const delay = backoffRef.current
    backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF)
    reconnectTimerRef.current = setTimeout(() => {
      connect()
    }, delay)
  }, [connect])

  scheduleReconnectRef.current = scheduleReconnect

  const disconnect = useCallback(() => {
    intentionalDisconnectRef.current = true
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    if (keepAliveRef.current) clearInterval(keepAliveRef.current)
    if (wsRef.current) {
      wsRef.current.close(1000)
      wsRef.current = null
    }
    setConnected(false)
    setConnectionStatus('disconnected')
  }, [])

  const send = useCallback((msg: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  // Connect on mount, disconnect on unmount or fleetId change
  useEffect(() => {
    if (enabled && fleetId) {
      connect()
    }
    return () => {
      disconnect()
    }
  }, [fleetId, enabled, connect, disconnect])

  return { connected, connectionStatus, send, disconnect, reconnect: connect }
}
