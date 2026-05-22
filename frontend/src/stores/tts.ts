/**
 * @file tts.ts
 * @module stores
 *
 * Zustand store for text-to-speech state: whether auto-read is enabled,
 * playback status, available voices, current settings, and an internal
 * audio queue for sentence-level streaming.
 *
 * Voice, instructions, and speed settings are persisted to localStorage under
 * `synapsis-tts`. The `enabled` flag is NOT persisted — it defaults to false
 * on every page load/tab, preventing TTS from auto-playing on reconnection.
 */

import { create } from 'zustand'
import { api } from '../lib/api'
import type { TTSVoice, TTSSettings } from '../lib/types'

const STORAGE_KEY = 'synapsis-tts'

/** Default settings used before the backend is contacted. */
const DEFAULT_SETTINGS: TTSSettings = {
  voice: 'alloy',
  model: 'tts-1',
  instructions: '',
  speed: 1,
}

/** Shape of the data persisted to localStorage (enabled is NOT persisted). */
interface PersistedTTS {
  voice: string
  instructions: string
  speed: number
}

/**
 * Reads persisted TTS preferences from localStorage, returning `null` if
 * nothing is stored or the data is malformed.
 */
function loadPersisted(): PersistedTTS | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as PersistedTTS
  } catch {
    return null
  }
}

/** Writes the persistable subset of TTS state to localStorage. */
function savePersisted(state: PersistedTTS): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  } catch {
    // Storage full or unavailable — silently ignore.
  }
}

/** Flushes the current settings (not enabled) to localStorage. */
function persistSettings(settings: TTSSettings): void {
  savePersisted({
    voice: settings.voice,
    instructions: settings.instructions,
    speed: settings.speed,
  })
}

// ---------------------------------------------------------------------------
// Store shape
// ---------------------------------------------------------------------------

interface TTSState {
  /** Whether auto-read is enabled (reads all new assistant messages aloud). */
  enabled: boolean
  /** Whether audio is currently playing. */
  isPlaying: boolean
  /** ID of the message currently being read aloud (null if none). */
  playingMessageId: string | null
  /** Available voices from the backend. */
  voices: TTSVoice[]
  /** Current TTS settings. */
  settings: TTSSettings
  /** Whether the settings panel is open. */
  settingsPanelOpen: boolean
  /** Queue of text chunks waiting to be spoken. */
  _audioQueue: Array<{ text: string; messageId: string }>

  // Actions
  setEnabled: (enabled: boolean) => void
  toggleEnabled: () => void
  setPlaying: (playing: boolean, messageId?: string | null) => void
  setSettingsPanelOpen: (open: boolean) => void
  toggleSettingsPanel: () => void
  loadVoices: () => Promise<void>
  updateSettings: (settings: Partial<TTSSettings>) => Promise<void>
  enqueueText: (text: string, messageId: string) => void
  clearQueue: () => void
  setVoices: (voices: TTSVoice[]) => void
  setSettings: (settings: TTSSettings) => void
}

// Merge localStorage overrides into default settings.
const persisted = loadPersisted()
// TTS is always off by default — must be explicitly enabled per session
const initialEnabled = false
const initialSettings: TTSSettings = {
  ...DEFAULT_SETTINGS,
  ...(persisted && {
    voice: persisted.voice,
    instructions: persisted.instructions,
    speed: persisted.speed,
  }),
}

/** @internal Zustand store instance. Use the exported {@link useTTSStore} hook. */
export const useTTSStore = create<TTSState>((set, get) => ({
  enabled: initialEnabled,
  isPlaying: false,
  playingMessageId: null,
  voices: [],
  settings: initialSettings,
  settingsPanelOpen: false,
  _audioQueue: [],

  setEnabled: (enabled) => {
    set({ enabled })
  },

  toggleEnabled: () => {
    set((s) => ({ enabled: !s.enabled }))
  },

  setPlaying: (playing, messageId) =>
    set({
      isPlaying: playing,
      playingMessageId: messageId ?? null,
    }),

  setSettingsPanelOpen: (open) => set({ settingsPanelOpen: open }),
  toggleSettingsPanel: () => set((s) => ({ settingsPanelOpen: !s.settingsPanelOpen })),

  loadVoices: async () => {
    try {
      const data = await api.getTTSVoices()
      const { voices, current } = data
      if (!voices || !Array.isArray(voices)) {
        console.warn('[TTS] loadVoices: unexpected response shape', data)
        return
      }
      const merged: TTSSettings = {
        ...current,
        // Preserve any locally-persisted overrides for voice/instructions/speed.
        ...(persisted && {
          voice: persisted.voice,
          instructions: persisted.instructions,
          speed: persisted.speed,
        }),
      }
      set({ voices, settings: merged })
    } catch (err) {
      console.warn('[TTS] loadVoices failed:', err)
      // Backend may not have TTS routes yet — leave defaults.
    }
  },

  updateSettings: async (partial) => {
    // Optimistically apply locally.
    const prev = get().settings
    const next = { ...prev, ...partial }
    set({ settings: next })
    persistSettings(next)

    try {
      const { settings: confirmed } = await api.updateTTSSettings(partial)
      set({ settings: confirmed })
      persistSettings(confirmed)
    } catch {
      // Revert on failure.
      set({ settings: prev })
      persistSettings(prev)
    }
  },

  enqueueText: (text, messageId) =>
    set((s) => ({
      _audioQueue: [...s._audioQueue, { text, messageId }],
    })),

  clearQueue: () => set({ _audioQueue: [] }),

  setVoices: (voices) => set({ voices }),
  setSettings: (settings) => {
    set({ settings })
    persistSettings(settings)
  },
}))

export type { TTSState, TTSVoice, TTSSettings }
