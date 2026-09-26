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
 * Application configuration returned by `GET /api/config`.
 * Drives feature flags and UI labels throughout the app.
 */
/**
 * A model option exposed in the chat model-selector pill.
 */
export interface SelectableModel {
  /** Model ID passed to the backend as the per-session override. */
  id: string
  /** Short human-readable label shown in the pill/dropdown. */
  label: string
}

/** `model_policy` block of `GET /api/config` (see Lane D contract). */
export interface ModelPolicy {
  /** Caller role as resolved by the server: `anonymous`, `researcher`, `admin`, ... */
  role: string
  default_model: string
  allowed_models: string[]
  max_budget_usd_per_turn: number | null
  daily_budget_usd: number | null
  max_turns: number
  /** True only for administrators: show per-answer cost. */
  show_cost: boolean
}

/** One in-app contact served by `GET /api/config` (`contacts`). */
export interface GuardrailContactInfo {
  name: string
  email: string
  /** What to ask this person about, e.g. `technical`. */
  remit: string
}

export interface AppConfig {
  invited_login_enabled?: boolean;
  /** Primary model identifier. */
  model: string
  /** Fallback model used when the primary is unavailable. */
  fallback_model: string
  /** Models the user can pick from in the chat model-selector pill. */
  selectable_models?: SelectableModel[]
  /**
   * Allow-list of model IDs this deployment exposes, driven by the
   * SYNAPSIS_AVAILABLE_MODELS env var. `selectable_models` is already
   * filtered to this list server-side; exposed for diagnostics/visibility.
   */
  available_models?: string[]
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
  /**
   * The caller's model/cost policy (role-aware, Lane D 2026-09-26). The UI
   * hides the cost pill unless `show_cost` is true (administrators only).
   */
  model_policy?: ModelPolicy
  /** "Reach out if in doubt" contacts for the disclaimer modal and footer. */
  contacts?: GuardrailContactInfo[]
  /** SSO / invitation / password login flags (read by the login screen). */
  sso_enabled?: boolean
  password_login_enabled?: boolean
  signup_allowed_domains?: string[]
  /** Host platform identifier (optional). */
  platform?: string
  /**
   * Whether the backend has interim self-signup enabled (IA_SELF_SIGNUP).
   * Gates whether LoginScreen shows the "Create account" option. Optional /
   * defaults to falsy so older backends without the field behave as before.
   */
  self_signup?: boolean
}

/**
 * Health-check response from `GET /api/health`. `workspace`, `auth_method`
 * and `available_models` are only returned to administrators.
 */
export interface HealthStatus {
  /** `"ok"` when the backend is healthy. */
  status: string
  /** Deployed commit. */
  git_sha?: string
  /** Default model. */
  model: string
  /** Backend version string. */
  version: string
  workspace?: string
  auth_method?: string
  available_models?: string[]
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
