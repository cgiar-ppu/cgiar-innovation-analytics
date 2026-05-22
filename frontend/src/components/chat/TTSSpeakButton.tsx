import { Volume2, Square } from 'lucide-react'
import { useTTS } from '../../hooks/useTTS'

interface Props {
  messageId: string
  text: string
}

export function TTSSpeakButton({ messageId, text }: Props) {
  const { speakMessage, stop, playingMessageId } = useTTS()
  const isPlayingThis = playingMessageId === messageId

  const handleClick = () => {
    if (isPlayingThis) {
      stop()
    } else {
      speakMessage(messageId, text)
    }
  }

  return (
    <button
      onClick={handleClick}
      className={`p-1.5 rounded-lg glass transition-all text-text-muted hover:text-text-primary ${
        isPlayingThis ? 'text-accent animate-pulse' : ''
      }`}
      aria-label={isPlayingThis ? 'Stop reading' : 'Read aloud'}
      title={isPlayingThis ? 'Stop' : 'Read aloud'}
    >
      {isPlayingThis ? <Square size={14} /> : <Volume2 size={14} />}
    </button>
  )
}
