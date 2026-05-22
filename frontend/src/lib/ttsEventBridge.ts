/**
 * @file ttsEventBridge.ts
 * @module lib
 *
 * Lightweight pub/sub bridge that allows non-React code (e.g. the WebSocket
 * message router) to request TTS playback without importing React hooks.
 */

type TTSEventHandler = (text: string, messageId: string) => void

let _handler: TTSEventHandler | null = null

/** Register the TTS handler (called by useTTS on mount). */
export function onTTSRequest(fn: TTSEventHandler) { _handler = fn }

/** Unregister the TTS handler (called by useTTS on unmount). */
export function offTTSRequest() { _handler = null }

/** Emit a TTS request. No-ops silently if no handler is registered. */
export function emitTTSRequest(text: string, messageId: string) {
  _handler?.(text, messageId)
}
