/** Shared commands used by mouse/keyboard controls and the voice adapter. */
import { create } from 'zustand'
import { api } from './api'
import type { ClientMessage } from './types'
import { useChatStore } from '../stores/chat'
import { useSessionsStore } from '../stores/sessions'
import { useScopeStore } from '../stores/scope'
import { usePersonaStore } from '../stores/persona'

export const useChatDraft = create<{ text: string; setText: (text: string | ((previous: string) => string)) => void }>((set) => ({ text: '', setText: (text) => set(state => ({ text: typeof text === "function" ? text(state.text) : text })) }))
export type SendChat = (message: ClientMessage) => void
let selection = 0
let ownDispatch = false
export const isVoiceDispatch = () => ownDispatch
export function voiceDispatch<T>(fn: () => T): T {
  ownDispatch = true
  try { return fn() } finally { ownDispatch = false }
}

export function sendChatQuery(text: string, send: SendChat) {
  const { pendingAttachments, clearAttachments } = useChatStore.getState()
  const enriched = pendingAttachments.length ? ['[Attached files]', ...pendingAttachments.map(a => `  ${a.fileName} -> ${a.filePath}`), '[End attached files]', '', text].join('\n') : text
  const scope = useScopeStore.getState().getActiveScope()
  const agent = usePersonaStore.getState().getActivePersona()
  // send throws if disconnected: preserve the user's draft/attachments in that case.
  send({ message: enriched, ...(scope ? { scope } : {}), ...(agent ? { agent } : {}) })
  if (pendingAttachments.length) clearAttachments()
  useChatStore.getState().addUserMessage(enriched)
  const id = useSessionsStore.getState().activeSessionId
  if (id) useSessionsStore.getState().markSessionBusy(id)
}

export function newChat(send: SendChat) {
  selection++
  const current = useSessionsStore.getState().activeSessionId
  if (current) useChatStore.getState().cacheCurrentSession(current)
  send({ type: 'new_session' })
  useChatStore.getState().clearMessages()
  useSessionsStore.getState().setActiveSession(null)
}

export async function openChat(id: string, send: SendChat, guard = () => true, dispatch: <T>(fn: () => T) => T = fn => fn()) {
  if (id === useSessionsStore.getState().activeSessionId) return
  const revision = ++selection
  const previous = useSessionsStore.getState().activeSessionId
  // Verify authorization and load before mutating; later manual navigation wins.
  const history = await api.getHistory(id)
  if (revision !== selection || previous !== useSessionsStore.getState().activeSessionId || !guard()) throw new Error('Chat selection changed. Ask again from the current chat.')
  dispatch(() => {
    if (previous) useChatStore.getState().cacheCurrentSession(previous)
    send({ type: 'switch_session', session_id: id })
    useSessionsStore.getState().setActiveSession(id)
    useChatStore.getState().clearMessages()
    useChatStore.setState({ messages: history.messages })
    if (useSessionsStore.getState().busySessions.has(id)) useChatStore.getState().setBusy(true)
  })
}

// Server receipts are independent of optimistic UI updates.
type Event = { type: string; session_id?: string; run_id?: string; [key: string]: unknown }
const listeners = new Set<(event: Event) => void>()
export const observeChatEvent = (event: Event) => listeners.forEach(fn => fn(event))
export function chatReceipt(matches: (event: Event) => boolean, signal: AbortSignal, ms = 15000) {
  let stop: () => void = () => {}
  const promise = new Promise<Event>((resolve, reject) => {
    const cleanup = () => { clearTimeout(timer); listeners.delete(listener); signal.removeEventListener('abort', cancelled) }
    const listener = (event: Event) => { if (matches(event)) { cleanup(); resolve(event) } }
    const cancelled = () => { cleanup(); reject(new Error('Voice action cancelled; a submitted chat query may still run.')) }
    const timer = setTimeout(() => { cleanup(); reject(new Error('Server acceptance is unconfirmed. Check this chat before retrying; the request may still run.')) }, ms)
    stop = cleanup
    listeners.add(listener)
    signal.addEventListener('abort', cancelled, { once: true })
    if (signal.aborted) cancelled()
  })
  void promise.catch(() => {}) // Caller may still be awaiting a preceding read.
  return { promise, stop }
}
