import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AudioLines, Mic, MicOff, Pause, Play, Square, X, ChevronDown, BookOpen } from 'lucide-react'
import { useWebSocketContext } from '../../contexts/WebSocketContext'
import { api } from '../../lib/api'
import { makeAdapter } from '../../lib/voice/actions'
import { LiveClient, type Caption, type VoiceStatus } from '../../lib/voice/liveClient'
import { useTTSStore } from '../../stores/tts'
import { useSessionsStore } from '../../stores/sessions'

type Source = { file: string; start_line: number; end_line: number; text: string }
const examples = ['What is this app for?', 'What data can I explore?', 'Open my next chat', 'How are innovations counted?']

/** Mounted above routes: changing chats/pages keeps the opt-in voice call alive. */
export default function VoiceGuide() {
  const { send, isConnected } = useWebSocketContext()
  const navigate = useNavigate()
  const location = useLocation()
  const current = useRef({ path: location.pathname, connected: isConnected })
  current.current = { path: location.pathname, connected: isConnected }
  const client = useRef<LiveClient | null>(null)
  const [available, setAvailable] = useState(false)
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<VoiceStatus>('idle')
  const [message, setMessage] = useState('Your guide to the app, data and chats')
  const [muted, setMuted] = useState(false)
  const [paused, setPaused] = useState(false)
  const [blocked, setBlocked] = useState(false)
  const [captions, setCaptions] = useState<Caption[]>([])
  const [activity, setActivity] = useState<string[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [typed, setTyped] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const activeId = useSessionsStore(s => s.activeSessionId)
  const title = useSessionsStore(s => s.sessions.find(chat => chat.session_id === activeId)?.title)
  const running = status === 'connected' || status === 'connecting' || status === 'closing'
  const isLive = status === 'connected'

  useEffect(() => {
    let mounted = true
    api.get<{ enabled: boolean; configured: boolean }>('/api/voice/status').then(s => { if (mounted) setAvailable(s.enabled) }).catch(() => {})
    const adapter = makeAdapter(send, navigate, () => current.current.path, () => current.current.connected)
    const instance = new LiveClient({
      status: (state, text) => { if (mounted) { setStatus(state); setMessage(text); if (state === 'connected') setStartedAt(Date.now()); if (state === 'idle' || state === 'error') setStartedAt(null) } },
      caption: caption => { if (mounted) setCaptions(rows => [...rows, caption].slice(-500)) },
      task: text => { if (mounted) setActivity(rows => [...rows, text].slice(-8)) },
      playbackBlocked: value => { if (mounted) setBlocked(value) },
      usage: () => {},
      evidence: result => { if (mounted && Array.isArray(result.excerpts)) setSources(result.excerpts as Source[]) },
    }, adapter)
    client.current = instance
    const unload = () => instance.dispose()
    window.addEventListener('pagehide', unload)
    return () => { mounted = false; window.removeEventListener('pagehide', unload); instance.dispose(); client.current = null }
  }, [send, navigate])
  useEffect(() => { client.current?.contextChanged() }, [location.pathname])
  useEffect(() => {
    if (!startedAt) return
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [startedAt])

  if (!available) return null
  const start = () => {
    useTTSStore.getState().setEnabled(false)
    setMuted(false); setPaused(false); setCaptions([]); setActivity([]); setSources([]); setElapsed(0)
    void client.current?.start()
  }
  const ask = (text: string) => { client.current?.typeMessage(text); setActivity(rows => [...rows, `You: ${text}`].slice(-8)); setTyped('') }
  // Display grouping only: protocol execution never depends on caption timing.
  const grouped: Array<{ id: string; speaker: string; text: string; end: number }> = []
  for (const caption of captions) {
    const last = [...grouped].reverse().find(row => row.speaker === caption.speaker)
    if (last && caption.start - last.end < 1800) { last.text += caption.delta; last.end = caption.end }
    else grouped.push({ id: caption.id, speaker: caption.speaker, text: caption.delta, end: caption.end })
  }
  return <>
    {!open && <button onClick={() => setOpen(true)} className="fixed bottom-12 right-5 z-40 flex items-center gap-2 rounded-full bg-accent px-4 py-3 text-white shadow-lg hover:brightness-110 focus-visible:outline focus-visible:outline-2" aria-label="Open voice guide">
      <AudioLines size={19} /> {running ? 'Voice is on' : 'Voice guide'}
    </button>}
    {open && <section role="region" aria-label="Voice guide" className="fixed z-40 bottom-10 right-3 sm:right-5 w-[calc(100%-1.5rem)] sm:w-[390px] max-h-[calc(100dvh-6rem)] flex flex-col rounded-2xl border border-border bg-surface-1 text-text-primary shadow-2xl overflow-hidden" style={{ background: 'var(--bg)' }}>
      <header className="flex items-center gap-3 p-4 border-b border-border">
        <span className="rounded-xl bg-accent/15 p-2 text-accent"><AudioLines size={20} /></span>
        <div className="flex-1"><h2 className="font-semibold text-sm">Innovation Analytics guide</h2><p className="text-xs text-text-muted">{running ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')} · ${muted ? 'Microphone muted' : isLive ? 'Listening' : status}` : 'Talk through your work'}</p></div>
        <button className="p-2 rounded-lg hover:bg-surface-2" onClick={() => setOpen(false)} aria-label={running ? 'Minimize voice guide (call continues)' : 'Close voice guide panel'}>{running ? <ChevronDown size={18} /> : <X size={18} />}</button>
      </header>
      <div className="p-4 space-y-3 overflow-y-auto min-h-0">
        <p className="text-sm" role="status">{message}</p>
        {!running && <>
          <p className="text-sm text-text-muted">Ask how the app works, explore data definitions, move between chats, or send an analysis question.</p>
          <div className="grid grid-cols-2 gap-2">{examples.map(text => <div key={text} className="rounded-xl border border-border p-2 text-xs text-text-muted">“{text}”</div>)}</div>
          <p className="text-xs text-text-muted leading-relaxed">Starting voice shares your audio and relevant chat or methodology excerpts with OpenAI. Voice recording is off. Questions sent to Chat are saved there as usual. Calls end after 10 minutes.</p>
          <button onClick={start} className="w-full rounded-xl bg-accent py-3 text-sm font-medium text-white flex gap-2 justify-center"><Mic size={17} />{status === 'error' ? 'Retry voice' : 'Start voice conversation'}</button>
        </>}
        {running && <>
          <div className="rounded-xl bg-accent/10 px-3 py-2 text-xs"><span className="text-text-muted">Current chat</span><p className="font-medium truncate">{title || (activeId ? 'Untitled chat' : 'No chat selected')}</p></div>
          <div className="flex flex-wrap gap-2">
            <button disabled={!isLive} onClick={() => { client.current?.mute(!muted); setMuted(!muted) }} className="rounded-lg border border-border px-3 py-2 text-xs flex items-center gap-1.5 disabled:opacity-50">{muted ? <Mic size={15} /> : <MicOff size={15} />}{muted ? 'Unmute' : 'Mute'}</button>
            <button disabled={!isLive} onClick={() => { client.current?.pauseActions(!paused); setPaused(!paused) }} className="rounded-lg border border-border px-3 py-2 text-xs flex items-center gap-1.5 disabled:opacity-50">{paused ? <Play size={15} /> : <Pause size={15} />}{paused ? 'Resume actions' : 'Pause actions'}</button>
            <button onClick={() => client.current?.end()} disabled={status === 'closing'} className="rounded-lg bg-red-500/10 text-red-600 px-3 py-2 text-xs flex items-center gap-1.5"><Square size={14} />End voice</button>
          </div>
          {muted && <p className="text-xs text-text-muted">Mute keeps the paid connection open. End voice to disconnect.</p>}
          {blocked && <button onClick={() => void client.current?.resumePlayback()} className="rounded-lg bg-accent px-3 py-2 text-white text-xs">Enable audio playback</button>}
          <div className="rounded-xl border border-border p-3 max-h-52 overflow-y-auto" aria-label="Voice captions" tabIndex={0}>
            {!grouped.length && <p className="text-xs text-text-muted">Live captions will appear here.</p>}
            {grouped.map(row => <div key={row.id} className="mb-2 text-sm"><span className="block text-[10px] font-semibold uppercase text-text-muted">{row.speaker === 'user' ? 'You' : 'Guide'}</span>{row.text}</div>)}
          </div>
          <form onSubmit={e => { e.preventDefault(); if (typed.trim()) ask(typed.trim()) }} className="flex gap-2">
            <input aria-label="Type to voice guide" value={typed} onChange={e => setTyped(e.target.value)} maxLength={2000} placeholder="Or type to the guide…" disabled={!isLive} className="min-w-0 flex-1 rounded-lg border border-border bg-transparent px-3 py-2 text-sm" />
            <button disabled={!isLive || !typed.trim()} className="rounded-lg px-3 py-2 bg-accent text-white text-sm disabled:opacity-50">Ask</button>
          </form>
        </>}
        {!!activity.length && <details open><summary className="text-xs font-medium cursor-pointer">Activity</summary><ul className="text-xs text-text-muted space-y-1 mt-2">{activity.map((text, i) => <li key={i}>{text}</li>)}</ul></details>}
        {!!sources.length && <details><summary className="text-xs font-medium cursor-pointer"><BookOpen size={13} className="inline mr-1" />Sources consulted</summary>{sources.map((source, i) => <details key={i} className="mt-2 text-xs"><summary className="cursor-pointer break-all">{source.file}:{source.start_line}–{source.end_line}</summary><pre className="whitespace-pre-wrap break-words text-[11px] mt-2 max-h-48 overflow-auto">{source.text}</pre></details>)}</details>}
        <p className="text-[10px] text-text-muted">AI guidance requires human checks. Ending voice does not stop an analytics query already sent to Chat.</p>
      </div>
    </section>}
  </>
}
