/**
 * @file useTTS.ts
 * @module hooks
 *
 * Three-stage pipeline TTS engine for text-to-speech auto-read and manual
 * per-message playback. All playback state is module-level so that multiple
 * components calling `useTTS()` share the same AudioContext, queue, and
 * playback state — no overlapping voices.
 *
 * Architecture:
 *   Stage 1 (Sentence Buffer)  — accumulates streaming text, detects sentence
 *                                 boundaries, survives streamingText resets
 *   Stage 2 (TTS Fetcher)      — fetches TTS audio with up to 2 concurrent
 *                                 requests, delivers AudioBuffers in order
 *   Stage 3 (Audio Player)     — plays AudioBuffers sequentially, chains via
 *                                 source.onended
 *
 * Auto-read logic is in `useTTSAutoRead()` — call exactly once (in ChatArea).
 */

import { useCallback, useEffect, useRef } from 'react'
import { useTTSStore } from '../stores/tts'
import { useChatStore } from '../stores/chat'
import { api } from '../lib/api'
import { onTTSRequest, offTTSRequest } from '../lib/ttsEventBridge'

// ---------------------------------------------------------------------------
// Module-level singleton state
// ---------------------------------------------------------------------------

let audioCtx: AudioContext | null = null
let negotiatedFormat: 'opus' | 'mp3' | null = null

function getAudioContext(): AudioContext {
  if (!audioCtx) audioCtx = new AudioContext()
  return audioCtx
}

async function ensureResumed(): Promise<void> {
  const ctx = getAudioContext()
  if (ctx.state === 'suspended') await ctx.resume()
}

/**
 * Prepare the AudioContext from a user-gesture context (e.g. click).
 * Browsers require a user gesture to create/resume an AudioContext.
 */
export function warmAudioContext(): void {
  const ctx = getAudioContext()
  if (ctx.state === 'suspended') {
    ctx.resume().catch(() => {})
  }
}

// ---------------------------------------------------------------------------
// Content filtering — strip markdown that sounds bad when read aloud
// ---------------------------------------------------------------------------

function stripMarkdown(text: string): string {
  let out = text
  // Remove image links entirely: ![alt](url)
  out = out.replace(/!\[[^\]]*\]\([^)]*\)/g, '')
  // Convert links to just the text: [text](url)
  out = out.replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
  // Remove bold markers: **text** or __text__
  out = out.replace(/\*\*([^*]*)\*\*/g, '$1')
  out = out.replace(/__([^_]*)__/g, '$1')
  // Remove italic markers: *text* or _text_ (single)
  out = out.replace(/\*([^*]*)\*/g, '$1')
  out = out.replace(/(?<!\w)_([^_]*)_(?!\w)/g, '$1')
  // Remove inline code backticks
  out = out.replace(/`([^`]*)`/g, '$1')
  // Remove horizontal rules
  out = out.replace(/^-{3,}$/gm, '')
  // Strip header markers but keep text
  out = out.replace(/^#{1,6}\s+/gm, '')
  // Collapse multiple whitespace
  out = out.replace(/\n{3,}/g, '\n\n')
  return out.trim()
}

// ---------------------------------------------------------------------------
// Sentence boundary detection (NO colon — fragments too much)
// ---------------------------------------------------------------------------

const SENTENCE_RE = /[.!?]\s+/

function extractSentences(text: string): [string[], string] {
  const sentences: string[] = []
  let remaining = text
  let match: RegExpExecArray | null
  while ((match = SENTENCE_RE.exec(remaining)) !== null) {
    const end = match.index + match[0].length
    const sentence = remaining.slice(0, end).trim()
    if (sentence) sentences.push(sentence)
    remaining = remaining.slice(end)
  }
  return [sentences, remaining]
}

// ---------------------------------------------------------------------------
// Core audio fetch (opus with mp3 fallback)
// ---------------------------------------------------------------------------

async function fetchAudio(text: string, signal?: AbortSignal): Promise<AudioBuffer> {
  const { settings } = useTTSStore.getState()
  const format = negotiatedFormat ?? 'opus'

  const response = await fetch(api.ttsUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      voice: settings.voice,
      model: settings.model,
      instructions: settings.instructions,
      speed: settings.speed,
      response_format: format,
    }),
    signal,
  })

  if (!response.ok) throw new Error(`TTS request failed: ${response.status}`)

  const arrayBuffer = await response.arrayBuffer()
  const ctx = getAudioContext()

  try {
    const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0))
    if (!negotiatedFormat) negotiatedFormat = format
    return decoded
  } catch {
    if (format === 'opus') {
      negotiatedFormat = 'mp3'
      return fetchAudio(text, signal)
    }
    throw new Error('Failed to decode TTS audio in both opus and mp3 formats')
  }
}

// ---------------------------------------------------------------------------
// Stage 3: Audio Player (Consumer)
// ---------------------------------------------------------------------------

let playerQueue: AudioBuffer[] = []
let currentSource: AudioBufferSourceNode | null = null
let isPlayerActive = false
let sessionActive = false // true while a pipeline session is running

function playerPlayNext() {
  const buffer = playerQueue.shift()
  if (!buffer) {
    currentSource = null
    isPlayerActive = false
    // Reset manual playback flag when queue drains naturally
    if (manualPlaybackActive) {
      manualPlaybackActive = false
    }
    // Only set playing=false if session is done (no more buffers coming)
    if (!sessionActive) {
      useTTSStore.getState().setPlaying(false, null)
    }
    // Otherwise we are in "waiting" state — more buffers may arrive
    return
  }
  const ctx = getAudioContext()
  const source = ctx.createBufferSource()
  source.buffer = buffer
  source.connect(ctx.destination)
  currentSource = source
  isPlayerActive = true
  source.onended = () => {
    currentSource = null
    playerPlayNext()
  }
  source.start()
}

function playerEnqueue(buffer: AudioBuffer, messageId: string) {
  playerQueue.push(buffer)
  if (!isPlayerActive) {
    useTTSStore.getState().setPlaying(true, messageId)
    playerPlayNext()
  }
}

function playerStop() {
  try { currentSource?.stop() } catch { /* already stopped */ }
  currentSource = null
  playerQueue = []
  isPlayerActive = false
  useTTSStore.getState().setPlaying(false, null)
}

// ---------------------------------------------------------------------------
// Stage 2: TTS Fetcher (Producer) — up to 2 concurrent, ordered delivery
// ---------------------------------------------------------------------------

const MAX_CONCURRENT_FETCHES = 2

let sentenceQueue: string[] = []
let fetchSeqNext = 0        // next sequence number to assign
let fetchSeqExpected = 0    // next sequence number to deliver to Stage 3
let reorderBuffer: Map<number, AudioBuffer> = new Map()
let inFlightCount = 0
let sessionAbort: AbortController | null = null
let currentSessionId: string | null = null

function fetcherReset() {
  sessionAbort?.abort()
  sessionAbort = null
  sentenceQueue = []
  fetchSeqNext = 0
  fetchSeqExpected = 0
  reorderBuffer = new Map()
  inFlightCount = 0
}

function fetcherPushSentence(sentence: string) {
  sentenceQueue.push(sentence)
  fetcherDrain()
}

function fetcherDrain() {
  while (inFlightCount < MAX_CONCURRENT_FETCHES && sentenceQueue.length > 0) {
    const text = sentenceQueue.shift()!
    const seq = fetchSeqNext++
    const sid = currentSessionId!
    const signal = sessionAbort?.signal
    if (!sid) return

    inFlightCount++
    fetchAudio(text, signal)
      .then((buffer) => {
        inFlightCount--
        // Discard if session changed
        if (currentSessionId !== sid) return
        // Store in reorder buffer
        reorderBuffer.set(seq, buffer)
        // Deliver in-order buffers to Stage 3
        fetcherDeliverOrdered(sid)
        // Keep draining the sentence queue
        fetcherDrain()
      })
      .catch((err) => {
        inFlightCount--
        if (err instanceof DOMException && err.name === 'AbortError') return
        console.warn('[TTS] Fetch error for sentence seq', seq, err)
        // Skip this sentence — advance expected to unblock pipeline
        if (currentSessionId === sid) {
          // Mark as skipped by advancing expected past it
          if (fetchSeqExpected === seq) {
            fetchSeqExpected++
            fetcherDeliverOrdered(sid)
          }
          fetcherDrain()
        }
      })
  }
}

function fetcherDeliverOrdered(sid: string) {
  while (reorderBuffer.has(fetchSeqExpected)) {
    const buffer = reorderBuffer.get(fetchSeqExpected)!
    reorderBuffer.delete(fetchSeqExpected)
    fetchSeqExpected++
    if (currentSessionId === sid) {
      playerEnqueue(buffer, sid)
    }
  }
}

// ---------------------------------------------------------------------------
// Stage 1: Sentence Buffer (Accumulator)
// ---------------------------------------------------------------------------

let sentenceBuffer = ''

function stage1Reset() {
  sentenceBuffer = ''
}

function stage1Feed(delta: string) {
  // Apply markdown stripping to the delta
  sentenceBuffer += delta
  // Strip markdown from the accumulated buffer before extracting sentences
  const cleaned = stripMarkdown(sentenceBuffer)
  const [sentences, remaining] = extractSentences(cleaned)

  // We need to track how much of the original buffer was consumed.
  // Since stripMarkdown can change lengths, we re-derive remaining from
  // the cleaned text. Store the cleaned remaining as the new buffer.
  sentenceBuffer = remaining

  for (const sentence of sentences) {
    if (sentence.length < 3) continue // skip tiny fragments
    fetcherPushSentence(sentence)
  }
}

function stage1Flush() {
  const remaining = stripMarkdown(sentenceBuffer).trim()
  sentenceBuffer = ''
  if (remaining.length >= 3) {
    fetcherPushSentence(remaining)
  }
}

// ---------------------------------------------------------------------------
// Session lifecycle
// ---------------------------------------------------------------------------

function startNewSession(): string {
  // Kill any existing session
  stopPipeline()

  const sid = `auto-${Date.now()}`
  currentSessionId = sid
  sessionActive = true
  sessionAbort = new AbortController()

  stage1Reset()
  // Warm AudioContext
  ensureResumed().catch(() => {
    console.warn('[TTS] Could not resume AudioContext for auto-read')
  })

  return sid
}

function endSession() {
  // Flush remaining text but do NOT stop playback — let queue drain
  stage1Flush()
  sessionActive = false
  // If nothing is playing and queue is empty, clear playing state now
  if (!isPlayerActive && playerQueue.length === 0) {
    useTTSStore.getState().setPlaying(false, null)
  }
}

function stopPipeline() {
  sessionActive = false
  currentSessionId = null
  stage1Reset()
  fetcherReset()
  playerStop()
}

// ---------------------------------------------------------------------------
// Manual playback (speakTextSingleton) — for per-message TTS buttons
// ---------------------------------------------------------------------------

/** Whether a manual (per-message) playback is in progress. */
let manualPlaybackActive = false
let manualAbort: AbortController | null = null

async function speakTextSingleton(text: string, messageId: string) {
  if (!text.trim()) return

  // Stop any auto-read pipeline
  stopPipeline()

  // Stop any prior manual playback
  manualAbort?.abort()
  playerStop()

  manualPlaybackActive = true
  manualAbort = new AbortController()

  await ensureResumed()
  useTTSStore.getState().setPlaying(true, messageId)

  try {
    const buffer = await fetchAudio(text, manualAbort.signal)
    if (!manualPlaybackActive) return
    // Play directly through the player
    playerEnqueue(buffer, messageId)
    // Wait for playback to finish before potentially resuming auto-read
    // We detect this via a polling approach since onended chains internally
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') return
    console.error('[TTS] speakText error:', err)
    playerStop()
    manualPlaybackActive = false
  }
}

// ---------------------------------------------------------------------------
// useTTS — lightweight hook for per-message buttons
// ---------------------------------------------------------------------------

export function useTTS() {
  const speakText = useCallback(
    (text: string, messageId: string) => speakTextSingleton(text, messageId),
    [],
  )

  const speakMessage = useCallback(
    (messageId: string, text: string) => speakTextSingleton(text, messageId),
    [],
  )

  const stop = useCallback(() => {
    manualPlaybackActive = false
    manualAbort?.abort()
    manualAbort = null
    stopPipeline()
  }, [])

  const isPlaying = useTTSStore((s) => s.isPlaying)
  const playingMessageId = useTTSStore((s) => s.playingMessageId)

  return { speakText, speakMessage, stop, isPlaying, playingMessageId }
}

// ---------------------------------------------------------------------------
// useTTSAutoRead — call ONCE in ChatArea to enable streaming auto-read
// ---------------------------------------------------------------------------

export function useTTSAutoRead() {
  const subscribedRef = useRef(false)

  useEffect(() => {
    if (subscribedRef.current) return
    subscribedRef.current = true

    let prevStreamingText = useChatStore.getState().streamingText
    let prevIsBusy = useChatStore.getState().isBusy

    const unsub = useChatStore.subscribe((state) => {
      const { streamingText, isBusy, replayMode } = state
      const tts = useTTSStore.getState()

      // Skip if TTS is not enabled, manual playback is active, or we are
      // replaying buffered content from a WebSocket reconnection
      if (!tts.enabled || manualPlaybackActive || replayMode) {
        prevStreamingText = streamingText
        prevIsBusy = isBusy
        return
      }

      // -----------------------------------------------------------------
      // Detect session boundaries via isBusy transitions
      // -----------------------------------------------------------------

      // isBusy: false -> true = NEW SESSION (user sent a message)
      if (isBusy && !prevIsBusy) {
        startNewSession()
      }

      // -----------------------------------------------------------------
      // Stage 1: Delta computation — survives streamingText resets
      // -----------------------------------------------------------------

      if (streamingText !== prevStreamingText && currentSessionId) {
        if (streamingText.length > prevStreamingText.length &&
            streamingText.startsWith(prevStreamingText)) {
          // streamingText grew — take the new chars
          const delta = streamingText.slice(prevStreamingText.length)
          stage1Feed(delta)
        } else if (streamingText.length > 0 && prevStreamingText === '') {
          // streamingText went from empty to non-empty (after a finalization)
          // This is NEW content — the entire string is delta
          stage1Feed(streamingText)
        } else if (streamingText === '' && prevStreamingText !== '') {
          // streamingText reset to empty — finalization event
          // Do NOT clear the accumulator, do NOT stop anything
          // Just ignore this transition
        } else if (streamingText.length > 0 && prevStreamingText.length > 0 &&
                   !streamingText.startsWith(prevStreamingText)) {
          // streamingText changed but doesn't start with previous
          // This could be a reset-then-new-content in a single tick
          // Treat the entire new text as delta
          stage1Feed(streamingText)
        }
      }

      // -----------------------------------------------------------------
      // isBusy: true -> false = session ending — flush but don't stop
      // -----------------------------------------------------------------

      if (!isBusy && prevIsBusy && currentSessionId) {
        endSession()
      }

      prevStreamingText = streamingText
      prevIsBusy = isBusy
    })

    return () => {
      unsub()
      subscribedRef.current = false
    }
  }, [])

  // Register event bridge (singleton — safe since this hook runs once)
  useEffect(() => {
    onTTSRequest(speakTextSingleton)
    return () => { offTTSRequest() }
  }, [])

  // Cleanup on unmount
  useEffect(() => () => { stopPipeline() }, [])
}
