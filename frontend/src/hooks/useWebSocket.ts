/**
 * @file useWebSocket.ts
 * @module hooks
 *
 * Custom React hook that manages a persistent WebSocket connection to the
 * backend `/ws/chat` endpoint. Handles:
 *
 * - Initial connection and automatic reconnection with exponential back-off
 *   (capped at {@link MAX_BACKOFF} ms).
 * - Delegating incoming message routing to {@link routeWebSocketMessage}.
 * - Providing a {@link send} helper that serialises {@link ClientMessage}
 *   objects and guards against sending on a closed socket.
 * - Exposing connection status for display in the UI.
 */

import { useRef, useState, useCallback, useEffect } from 'react'
import type { ClientMessage } from '../lib/types'
import { useChatStore } from '../stores/chat'
import { useSessionsStore } from '../stores/sessions'
import { routeWebSocketMessage, type RouterContext } from './wsMessageRouter'
import { getAuthToken } from '../stores/auth'

/** Maximum delay (ms) between reconnection attempts. */
const MAX_BACKOFF = 30_000

/** Starting delay (ms) for the first reconnection attempt. */
const INITIAL_BACKOFF = 1000

/**
 * Return value of {@link useWebSocket}.
 */
interface UseWebSocketReturn {
  /**
   * Serialises a {@link ClientMessage} as JSON and sends it over the socket.
   * No-ops silently if the socket is not currently open.
   */
  send: (msg: ClientMessage) => void

  /** `true` when the WebSocket `readyState` is `OPEN`. */
  isConnected: boolean

  /** Finer-grained connection lifecycle state for status indicators. */
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error'

  /**
   * Manually triggers a connection attempt. Called automatically on mount;
   * consumers can call it to force a reconnect after the user explicitly
   * dismisses an error state.
   */
  connect: () => void

  /**
   * Clears any pending reconnect timer and closes the socket.
   * Called automatically on unmount.
   */
  disconnect: () => void
}

/**
 * useWebSocket
 *
 * Opens a WebSocket connection on mount, keeps it alive with exponential
 * back-off reconnection, and wires incoming messages into the chat and
 * sessions Zustand stores via {@link routeWebSocketMessage}.
 *
 * @returns `{ send, isConnected, connectionStatus, connect, disconnect }`
 */
export function useWebSocket(): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const backoffRef = useRef(INITIAL_BACKOFF)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // Dedup guard for session_complete, exposed to the router via RouterContext.
  const lastSessionCompleteRef = useRef<{ sessionId: string; timestamp: number } | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected' as const)

  // Build the router context that bridges React refs to the pure router function.
  const routerCtxRef = useRef<RouterContext>({
    getLastSessionComplete: () => lastSessionCompleteRef.current,
    setLastSessionComplete: (record) => { lastSessionCompleteRef.current = record },
  })

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    // When deployed on Amplify (static CDN), the WebSocket must connect
    // directly to the backend host rather than window.location.host.
    const backendUrl = import.meta.env.VITE_BACKEND_URL as string | undefined
    let url: string
    if (backendUrl) {
      const parsed = new URL(backendUrl)
      const wsProto = parsed.protocol === 'https:' ? 'wss:' : 'ws:'
      url = `${wsProto}//${parsed.host}/ws/chat`
    } else {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      url = `${proto}//${window.location.host}/ws/chat`
    }

    // Attach the JWT so the backend can resolve the per-user identity that
    // scopes chat sessions (Step 3/4). Omitted in dev-bypass mode (no token).
    const token = getAuthToken()
    if (token) {
      url += `${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
    }

    setConnectionStatus('connecting')
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setIsConnected(true)
      setConnectionStatus('connected')
      backoffRef.current = INITIAL_BACKOFF

      // Clear stale streaming buffers AND replay mode from the dead connection,
      // but preserve isBusy — the backend will tell us the true busy state when
      // we send switch_session and it replies with {type: "session", is_busy}.
      const chatState = useChatStore.getState()
      if (chatState.streamingText || chatState.streamingThinking || chatState.replayMode) {
        useChatStore.setState({ streamingText: '', streamingThinking: '', activeAgent: null, replayMode: false })
      }

      // Resume active session on reconnect
      const activeSession = useSessionsStore.getState().activeSessionId
      if (activeSession) {
        ws.send(JSON.stringify({ type: 'switch_session', session_id: activeSession }))
        // Force a history reload to catch messages that arrived while disconnected.
        setTimeout(() => {
          const stillActive = useSessionsStore.getState().activeSessionId
          const cs = useChatStore.getState()
          if (stillActive === activeSession && !cs.isBusy) {
            cs.loadHistory(activeSession)
          }
        }, 500)
      }
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        routeWebSocketMessage(msg, routerCtxRef.current)
      } catch (err) {
        console.error('[WebSocket] Error handling message:', err)
      }
    }

    ws.onclose = () => {
      setIsConnected(false)
      setConnectionStatus('disconnected')
      wsRef.current = null
      scheduleReconnect()
    }

    ws.onerror = () => {
      setConnectionStatus('error')
    }
  }, [])

  /**
   * Schedules the next reconnection attempt using exponential back-off.
   * The delay doubles on each failure up to {@link MAX_BACKOFF}.
   */
  const scheduleReconnect = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    setConnectionStatus('connecting')
    const delay = backoffRef.current
    backoffRef.current = Math.min(backoffRef.current * 2, MAX_BACKOFF)
    reconnectTimerRef.current = setTimeout(() => {
      connect()
    }, delay)
  }, [connect])

  const send = useCallback((msg: ClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg))
    }
  }, [])

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    wsRef.current?.close()
    wsRef.current = null
  }, [])

  useEffect(() => {
    connect()

    // When the tab regains focus after being hidden, reload history for the
    // active session to catch messages that arrived while the JS event loop
    // was throttled or the WebSocket silently dropped.
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        const activeSession = useSessionsStore.getState().activeSessionId
        if (activeSession) {
          setTimeout(() => {
            const chatState = useChatStore.getState()
            if (!chatState.isBusy && !chatState.replayMode) {
              chatState.loadHistory(activeSession)
            }
          }, 300)
        }
      }
    }
    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
      disconnect()
    }
  }, [connect, disconnect])

  return { send, isConnected, connectionStatus, connect, disconnect }
}
