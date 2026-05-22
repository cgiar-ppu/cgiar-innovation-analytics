import { memo, useRef, useState, useCallback, useEffect } from 'react'
import { Paperclip } from 'lucide-react'
import { SendButton } from './SendButton'
import { StopButton } from './StopButton'
import { VoiceButton } from './VoiceButton'
import { AttachmentChips } from './AttachmentChips'
import { SlashCommandMenu } from './SlashCommandMenu'
import { useTextareaAutoGrow } from '../../hooks/useTextareaAutoGrow'
import { useSkillsAutocomplete } from '../../hooks/useSkillsAutocomplete'
import { useChatStore } from '../../stores/chat'

interface Props {
  onSend: (text: string) => void
  onCancel: () => void
  onFileUpload: (file: File) => void
  isBusy: boolean
}

export const ChatInput = memo(function ChatInput({ onSend, onCancel, onFileUpload, isBusy }: Props) {
  const pendingAttachments = useChatStore((s) => s.pendingAttachments)
  const removeAttachment = useChatStore((s) => s.removeAttachment)
  const [text, setText] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const { textareaRef, adjustHeight } = useTextareaAutoGrow(200)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragCounter = useRef(0)

  const {
    suggestions,
    selectedIndex,
    isVisible: isAutocompleteVisible,
    selectSuggestion,
    handleKeyDown: handleAutocompleteKeyDown,
    updateText,
  } = useSkillsAutocomplete()

  useEffect(() => {
    adjustHeight()
  }, [text, adjustHeight])

  // Keep autocomplete in sync with text changes
  useEffect(() => {
    updateText(text)
  }, [text, updateText])

  const handleSend = () => {
    const trimmed = text.trim()
    if (!trimmed || isBusy) return
    onSend(trimmed)
    setText('')
    textareaRef.current?.focus()
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // Let autocomplete handle keys first when visible
    const result = handleAutocompleteKeyDown(e)
    if (result.consumed) {
      e.preventDefault()
      if (result.newText !== undefined) {
        setText(result.newText)
        textareaRef.current?.focus()
      }
      return
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files && files.length > 0) {
      Array.from(files).forEach((file) => onFileUpload(file))
      e.target.value = ''
    }
  }

  // Drag-and-drop file attachment handlers
  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current++
    if (e.dataTransfer.types.includes('Files')) {
      setIsDragging(true)
    }
  }

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    dragCounter.current--
    if (dragCounter.current === 0) {
      setIsDragging(false)
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setIsDragging(false)
    dragCounter.current = 0
    const files = e.dataTransfer.files
    if (files && files.length > 0) {
      Array.from(files).forEach((file) => onFileUpload(file))
    }
  }

  // Public method for welcome screen prompt injection
  const setAndFocus = useCallback((prompt: string) => {
    setText(prompt)
    textareaRef.current?.focus()
  }, [textareaRef])

  // Handle transcribed voice text — append to existing text (with space separator)
  const handleTranscription = useCallback((transcribed: string) => {
    setText(prev => {
      const separator = prev.trim() ? ' ' : ''
      return prev + separator + transcribed
    })
    textareaRef.current?.focus()
  }, [textareaRef])

  // Expose setAndFocus on the window for WelcomeScreen
  useEffect(() => {
    (window as unknown as Record<string, unknown>).__chatInputSetText = setAndFocus
    return () => { delete (window as unknown as Record<string, unknown>).__chatInputSetText }
  }, [setAndFocus])

  const handleAutocompleteSelect = useCallback((suggestion: { name: string; description: string; category: 'skill' | 'command' }) => {
    const newText = selectSuggestion(suggestion)
    setText(newText)
    textareaRef.current?.focus()
  }, [selectSuggestion, textareaRef])

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className={`relative glass-strong rounded-2xl px-4 py-3
      focus-within:border-accent focus-within:shadow-[0_0_0_1px_var(--accent),0_0_20px_var(--accent-glow)]
      transition-all ${isDragging ? 'border-accent shadow-[0_0_0_2px_var(--accent),0_0_24px_var(--accent-glow)]' : ''}`}>
      <SlashCommandMenu
        suggestions={suggestions}
        selectedIndex={selectedIndex}
        isVisible={isAutocompleteVisible}
        onSelect={handleAutocompleteSelect}
      />
      <AttachmentChips attachments={pendingAttachments} onRemove={removeAttachment} />
      <div className="flex items-end gap-2">
        <button
          onClick={() => fileInputRef.current?.click()}
          className="p-1.5 rounded-xl hover:bg-surface-2 transition-colors text-text-muted hover:text-text-primary flex-shrink-0 mb-0.5"
          aria-label="Upload file"
        >
          <Paperclip size={18} />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileChange}
        />

        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about CGIAR innovations, research results, or query the PRMS database..."
          rows={1}
          className="flex-1 resize-none bg-transparent text-text-primary placeholder:text-text-muted
            text-sm leading-relaxed outline-none py-1 max-h-[200px]"
        />

        <VoiceButton onTranscription={handleTranscription} disabled={isBusy} />

        {isBusy ? (
          <StopButton onClick={onCancel} />
        ) : (
          <SendButton disabled={!text.trim()} onClick={handleSend} />
        )}
      </div>
    </div>
  )
})
