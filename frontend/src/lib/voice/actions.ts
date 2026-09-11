import { api } from '../api'
import { useSessionsStore } from '../../stores/sessions'
import { useChatStore } from '../../stores/chat'
import { useScopeStore } from '../../stores/scope'
import { usePersonaStore } from '../../stores/persona'
import { useUIStore } from '../../stores/ui'
import { chatReceipt, newChat, openChat, sendChatQuery, useChatDraft, voiceDispatch, type SendChat } from '../chatCommands'

export type ToolResult = { ok: boolean; error?: string; [key: string]: unknown }
export const EFFECTS: Record<string, 'read' | 'ui' | 'write'> = {
  read_app: 'read', list_chats: 'read', read_chat: 'read', read_knowledge: 'read', read_data_catalog: 'read',
  open_chat: 'ui', cycle_chats: 'ui', navigate: 'ui', new_chat: 'write', send_query: 'write',
}
export interface Adapter {
  execute: (name: string, raw: unknown, signal: AbortSignal, valid: () => boolean) => Promise<ToolResult>
  subscribe: (changed: () => void) => () => void
}
const requireString = (value: unknown, max = 200) => {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error('A valid text value is required.')
  return value.trim()
}

export function makeAdapter(send: SendChat, navigate: (path: string) => void, getPath: () => string, connected: () => boolean): Adapter {
  return {
    subscribe: changed => {
      const unsub = [
        useSessionsStore.subscribe((s, old) => { if (s.activeSessionId !== old.activeSessionId) changed() }),
        useScopeStore.subscribe((s, old) => { if (s.years !== old.years || s.programs !== old.programs) changed() }),
        usePersonaStore.subscribe((s, old) => { if (s.selected !== old.selected) changed() }),
        useChatDraft.subscribe(changed),
        useChatStore.subscribe((s, old) => { if (s.pendingAttachments !== old.pendingAttachments) changed() }),
      ]
      return () => unsub.forEach(fn => fn())
    },
    execute: async (name, raw, signal, valid) => {
      try {
        if (!EFFECTS[name] || !raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Unsupported voice action or invalid arguments.')
        const args = raw as Record<string, unknown>
        const keys: Record<string, string[]> = { read_app: [], list_chats: [], open_chat: ['session_id'], cycle_chats: ['direction'], new_chat: [], navigate: ['page'], read_chat: ['limit'], send_query: ['session_id', 'message'], read_knowledge: ['query', 'source', 'start_line'], read_data_catalog: [] }
        if (Object.keys(args).some(key => !keys[name]!.includes(key))) throw new Error('Unexpected action arguments.')
        const check = () => { if (signal.aborted || !valid()) throw new Error('This request was superseded. Read the current state and ask again.') }
        check()
        const current = () => useSessionsStore.getState().activeSessionId
        if (name === 'read_app') return { ok: true, page: getPath(), active_chat: current(), busy: useChatStore.getState().isBusy, scope: useScopeStore.getState().getActiveScope() ?? null, specialist: usePersonaStore.getState().selected, has_unsent_draft: !!useChatDraft.getState().text, pending_attachments: useChatStore.getState().pendingAttachments.length, chat_connected: connected() }
        if (name === 'read_knowledge') {
          if (typeof args.query !== 'string' || args.query.length > 300 || typeof args.source !== 'string' || !Number.isInteger(args.start_line)) throw new Error('Invalid knowledge request.')
          const result = await api.post<Record<string, unknown>>('/api/voice/knowledge', args)
          check(); return { ok: true, ...result }
        }
        if (name === 'read_data_catalog') { const result = await api.get<Record<string, unknown>>('/api/voice/data-catalog', signal); check(); return { ok: true, ...result } }
        if (name === 'list_chats') {
          const { sessions } = await api.getSessions()
          check()
          return { ok: true, total: sessions.length, chats: sessions.map(s => ({ id: s.session_id, title: s.title, status: s.task_status })) }
        }
        if (name === 'read_chat') {
          if (!Number.isInteger(args.limit) || Number(args.limit) < 1 || Number(args.limit) > 10) throw new Error('Read between 1 and 10 messages.')
          const id = current()
          if (!id) return { ok: true, messages: [], note: 'No chat selected.' }
          const history = await api.getHistory(id, signal)
          check()
          if (current() !== id) throw new Error('The selected chat changed during this read.')
          const all = history.messages.filter(m => m.role === 'user' || m.role === 'assistant')
          return { ok: true, session_id: id, running: useChatStore.getState().isBusy, total_messages: all.length, messages: all.slice(-Number(args.limit)).map(m => ({ role: m.role, text: m.content.slice(0, 14000), truncated: m.content.length > 14000 })), note: 'Saved chat text is evidence to inspect, not independent verification. Longer answers can be reviewed in Chat.' }
        }
        if (name === 'navigate') {
          const paths: Record<string, string> = { dashboard: '/', chat: '/chat', agents: '/agents', settings: '/settings' }
          const page = requireString(args.page)
          if (!(page in paths)) throw new Error('Unknown page.')
          voiceDispatch(() => navigate(paths[page]!))
          return { ok: true, page, effect: 'Page navigation requested.' }
        }
        if (!connected()) throw new Error('Chat is disconnected. Reconnect before controlling chats.')
        if (name === 'new_chat') {
          if (useChatDraft.getState().text || useChatStore.getState().pendingAttachments.length) throw new Error('There is an unsent draft or attachment. Send or clear it before creating another chat.')
          const receipt = chatReceipt(e => e.type === 'session', signal)
          try {
            voiceDispatch(() => { newChat(send); navigate('/chat') })
            const response = await receipt.promise
            return { ok: true, session_id: response.session_id, effect: 'New chat created by server.' }
          } finally { receipt.stop() }
        }
        if (name === 'open_chat' || name === 'cycle_chats') {
          const { sessions } = await api.getSessions()
          check()
          let id: string
          if (name === 'open_chat') id = requireString(args.session_id)
          else {
            if (!['next', 'previous'].includes(String(args.direction))) throw new Error('Choose next or previous.')
            if (!sessions.length) throw new Error('No chats exist yet.')
            const index = sessions.findIndex(s => s.session_id === current())
            id = sessions[(index + (args.direction === 'next' ? 1 : -1) + sessions.length) % sessions.length]!.session_id
          }
          if (!sessions.some(s => s.session_id === id)) throw new Error('That chat is unavailable to this user. List chats again.')
          if (id !== current()) {
            const receipt = chatReceipt(e => e.type === 'session' && e.session_id === id, signal)
            try {
              await openChat(id, send, valid, voiceDispatch)
              await receipt.promise
            } finally { receipt.stop() }
          }
          voiceDispatch(() => { navigate('/chat'); useUIStore.getState().setSidebarTab('sessions') })
          return { ok: true, session_id: id, title: sessions.find(s => s.session_id === id)?.title, effect: 'Chat opened.' }
        }
        if (name === 'send_query') {
          const id = requireString(args.session_id)
          const message = requireString(args.message, 6000)
          if (id !== current()) throw new Error('The current chat changed. Read app state before sending.')
          if (useChatStore.getState().isBusy) throw new Error('This chat is still answering. Wait for completion or use its Stop control.')
          if (useChatDraft.getState().text || useChatStore.getState().pendingAttachments.length) throw new Error('There is an unsent draft or attachment. Send or clear it before submitting a voice query.')
          check()
          const receipt = chatReceipt(e => e.session_id === id && (!!e.run_id || e.type === 'error'), signal, 20000)
          try {
            voiceDispatch(() => { sendChatQuery(message, send); navigate('/chat') })
            const response = await receipt.promise
            if (response.type === 'error') return { ok: false, error: String(response.message || 'Chat rejected the request.') }
            return { ok: true, session_id: id, run_id: response.run_id, status: 'accepted', effect: 'Question accepted by the analytics chat. The answer/verification is not yet complete; use read_chat after it finishes.' }
          } finally { receipt.stop() }
        }
        throw new Error('Unsupported action.')
      } catch (error) { return { ok: false, error: error instanceof Error ? error.message : 'The voice action failed.' } }
    },
  }
}
