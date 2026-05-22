/**
 * @file common.ts
 * @module lib/types
 *
 * Shared/generic domain types used across the application: file info,
 * memory, application configuration, and health status.
 */

/**
 * Metadata for a file stored in the agent's workspace, as returned by
 * `/api/files`.
 */
export interface FileInfo {
  /** Filename (without path). */
  name: string
  /** Size in bytes. */
  size: number
  /** ISO 8601 last-modified timestamp. */
  modified: string
}

/**
 * A persistent memory entry stored in the agent's memory store.
 */
export interface Memory {
  /** Auto-increment primary key. */
  id: number
  /** Category label (e.g. `"preference"`, `"fact"`). */
  category: string
  /** The memory text. */
  content: string
  /** Importance score (1-10). */
  importance: number
  /** Session ID where this memory was created. */
  source_session: string
  /** Unix timestamp of creation. */
  created_at: number
  /** Unix timestamp of last update. */
  updated_at: number
  /** Number of times this memory has been retrieved. */
  access_count: number
  /** Comma-separated tag string. */
  tags: string
  /** `1` if active, `0` if soft-deleted. */
  active: number
}

/**
 * Payload for creating a new {@link Memory} entry via `POST /api/memories`.
 */
export interface NewMemory {
  /** Category label. */
  category: string
  /** The memory text. */
  content: string
  /** Importance score (1-10). */
  importance: number
  /** Comma-separated tags. */
  tags: string
}

/**
 * Application configuration returned by `GET /api/config`.
 * Drives feature flags and UI labels throughout the app.
 */
export interface AppConfig {
  /** Primary model identifier. */
  model: string
  /** Fallback model used when the primary is unavailable. */
  fallback_model: string
  /** Maximum number of agentic turns per run. */
  max_turns: number
  /** Billing / authentication method in use. */
  auth_method: 'subscription' | 'api_key' | 'none'
  /** Backend version string. */
  version: string
  /** Agent personality / type identifier. */
  agent_type: string
  /** Available persona names. */
  personas: string[]
  /** Available confidence level labels. */
  confidence_levels: string[]
  /** Available memory category labels. */
  memory_categories: string[]
  /** Whether a VNC server is available for the desktop panel. */
  vnc_available: boolean
  /** Port the VNC WebSocket proxy listens on. */
  vnc_port: number
  /** Host platform identifier (optional). */
  platform?: string
}

/**
 * Health-check response from `GET /api/health`.
 */
export interface HealthStatus {
  /** `"ok"` when the backend is healthy. */
  status: string
  /** Model currently loaded. */
  model: string
  /** Absolute path to the agent's workspace directory. */
  workspace: string
  /** Authentication method in use. */
  auth_method: string
  /** Backend version string. */
  version: string
}

/**
 * A voice option available for text-to-speech playback, as returned by
 * `GET /api/tts/voices`.
 */
export interface TTSVoice {
  /** Unique voice identifier (e.g. `"alloy"`, `"nova"`). */
  id: string
  /** Human-readable display name. */
  name: string
  /** Short description of the voice's character. */
  description: string
}

/**
 * Current TTS configuration, persisted both locally and on the backend.
 */
export interface TTSSettings {
  /** Active voice identifier. */
  voice: string
  /** TTS model identifier (e.g. `"tts-1"`, `"tts-1-hd"`). */
  model: string
  /** System-level instructions / prompt for the TTS engine. */
  instructions: string
  /** Playback speed multiplier (0.25–4.0). */
  speed: number
}
