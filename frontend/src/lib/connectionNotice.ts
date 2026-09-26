/**
 * @file connectionNotice.ts
 * @module lib
 *
 * L4-10: sending, stopping, starting a chat or switching model while the chat
 * socket is down used to throw an uncaught error and silently do nothing.
 * Callers now catch it and tell the user.
 */
import { toast } from 'sonner'

export const DISCONNECTED_MESSAGE = 'Connection lost - reconnecting. Please try again in a moment.'

/**
 * Run a socket action; on failure show a toast and return false.
 * The WebSocket `send` throws when the socket is not open.
 */
export function runWhileConnected(action: () => void, message: string = DISCONNECTED_MESSAGE): boolean {
  try {
    action()
    return true
  } catch {
    toast.error(message, { id: 'ia-disconnected' })
    return false
  }
}
