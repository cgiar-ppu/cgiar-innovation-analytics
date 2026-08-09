import { useEffect, useCallback } from 'react'
import { Maximize2, Minimize2, Wrench, Loader2 } from 'lucide-react'
import { useChatStore } from '../../stores/chat'
import { usePersonaStore } from '../../stores/persona'
import { useScopeStore } from '../../stores/scope'
import { useSessionsStore } from '../../stores/sessions'
import { useUIStore } from '../../stores/ui'
import { useTTSStore } from '../../stores/tts'
import { useAutoScroll } from '../../hooks/useAutoScroll'
import { useTTSAutoRead } from '../../hooks/useTTS'
import { MessageList } from './MessageList'
import { StreamingMessage } from './StreamingMessage'
import { TypingIndicator } from './TypingIndicator'
import { ScrollToBottom } from './ScrollToBottom'
import { AgentActivityBanner } from './AgentActivityBanner'
import { WelcomeScreen } from '../welcome/WelcomeScreen'
import { ChatInput } from '../input/ChatInput'
import { ExportMenu } from './ExportMenu'
import { TTSSettingsPanel } from './TTSSettingsPanel'
import { PersonaPicker } from './PersonaPicker'
import { InfoPopover } from '../common/InfoPopover'
import { INFO_TOPICS } from '../common/infoCopy'
import { ScopeFilterBar } from './ScopeFilterBar'
import type { ClientMessage } from '../../lib/types'

interface Props {
  send: (msg: ClientMessage) => void
  onFileUpload: (file: File) => void
}

export function ChatArea({ send, onFileUpload }: Props) {
  // Granular selectors — only re-render when the specific slice changes
  const messages = useChatStore((s) => s.messages)
  const streamingText = useChatStore((s) => s.streamingText)
  const streamingThinking = useChatStore((s) => s.streamingThinking)
  const isBusy = useChatStore((s) => s.isBusy)
  const activeAgent = useChatStore((s) => s.activeAgent)
  const toolActivity = useChatStore((s) => s.toolActivity)

  const { containerRef, isAtBottom, scrollToBottom } = useAutoScroll()
  const expandedView = useUIStore((s) => s.expandedView)
  const toggleExpandedView = useUIStore((s) => s.toggleExpandedView)
  const hasMessages = messages.length > 0 || !!streamingText

  // TTS: load voices on mount + activate the singleton auto-read subscription
  useTTSAutoRead()
  useEffect(() => {
    useTTSStore.getState().loadVoices()
  }, [])

  const handleSend = useCallback((text: string) => {
    const { pendingAttachments, clearAttachments } = useChatStore.getState()

    let enrichedText = text

    if (pendingAttachments.length > 0) {
      const attachmentBlock = [
        '[Attached files]',
        ...pendingAttachments.map(
          (a) => `  ${a.fileName} -> ${a.filePath}`
        ),
        '[End attached files]',
        '',
      ].join('\n')

      enrichedText = attachmentBlock + text
      clearAttachments()
    }

    useChatStore.getState().addUserMessage(enrichedText)
    const activeId = useSessionsStore.getState().activeSessionId
    if (activeId) useSessionsStore.getState().markSessionBusy(activeId)

    // Attach the active data scope (year / programme filters) so the backend
    // can constrain the agent for this turn, and the selected specialist so it
    // can route the turn. Both are `undefined` when nothing is selected — the
    // frame is then byte-identical to the pre-filter/pre-picker one.
    const scope = useScopeStore.getState().getActiveScope()
    const agent = usePersonaStore.getState().getActivePersona()
    send({
      message: enrichedText,
      ...(scope ? { scope } : {}),
      ...(agent ? { agent } : {}),
    })
  }, [send])

  const handleCancel = useCallback(() => {
    send({ type: 'cancel' })
  }, [send])

  return (
    <div className="flex-1 flex flex-col relative min-h-0 overflow-x-hidden">
      <div className="flex items-center justify-between gap-2 px-4 py-2 border-b border-[var(--border)] flex-shrink-0 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          {/* F15 — what the chat surface is and how to read its answers. */}
          <InfoPopover topic={INFO_TOPICS.chat} />
          <PersonaPicker />
          <ScopeFilterBar />
        </div>
        <div className="flex items-center gap-1">
        <button
          onClick={toggleExpandedView}
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-medium transition-all ${
            expandedView
              ? 'bg-accent/15 text-accent border border-accent/30'
              : 'hover:bg-surface-2 text-text-muted hover:text-text-primary'
          }`}
          title={expandedView ? 'Switch to compact view' : 'Switch to expanded view'}
        >
          {expandedView ? <Maximize2 size={14} /> : <Minimize2 size={14} />}
          <span className="hidden sm:inline">{expandedView ? 'Expanded' : 'Compact'}</span>
        </button>
        <TTSSettingsPanel />
        <ExportMenu />
        </div>
      </div>
      <div ref={containerRef} className="chat-messages-area flex-1 overflow-y-auto overflow-x-hidden" style={{ overflowAnchor: 'auto' }}>
        <div className="max-w-chat mx-auto px-4 py-6 space-y-5 min-w-0">
          {!hasMessages && (
            <WelcomeScreen onPromptClick={handleSend} />
          )}
          {activeAgent && (
            <AgentActivityBanner agentName={activeAgent.name} status={activeAgent.status} />
          )}
          <MessageList messages={messages} expandedView={expandedView} />
          <StreamingMessage text={streamingText} thinking={streamingThinking} expandedView={expandedView} />
          {toolActivity && isBusy && !streamingText && (
            <div className="animate-fade-in-up flex items-center gap-3">
              <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] flex items-center justify-center flex-shrink-0 shadow-sm">
                <Wrench size={14} className="text-white" />
              </div>
              <div className="flex items-center gap-2 px-4 py-3 rounded-2xl glass text-sm text-text-muted">
                <Loader2 size={14} className="animate-spin text-accent" />
                <span>
                  {toolActivity.phase === 'preparing' ? 'Preparing' : 'Running'}{' '}
                  <span className="font-medium text-text-primary">{toolActivity.tool}</span>…
                </span>
              </div>
            </div>
          )}
          {isBusy && !streamingText && !streamingThinking && !toolActivity && (
            <TypingIndicator />
          )}
        </div>
      </div>

      <ScrollToBottom visible={!isAtBottom} onClick={scrollToBottom} />

      <div className="flex-shrink-0 pb-5 px-4 pb-safe">
        <div className="max-w-chat mx-auto">
          <ChatInput
            onSend={handleSend}
            onCancel={handleCancel}
            onFileUpload={onFileUpload}
            isBusy={isBusy}
          />
        </div>
      </div>
    </div>
  )
}
