/**
 * @file index.ts
 * @module lib/types
 *
 * Barrel re-export of all domain type files. Importing from `lib/types`
 * continues to work unchanged — all types are re-exported here.
 */

export type { ServerMessage, ClientMessage, MessageScope } from './websocket'
export type { Session } from './session'
export type { ChatMessage, MessageRole, PendingAttachment, SearchResult } from './chat'
export type { FileInfo, AppConfig, ModelPolicy, GuardrailContactInfo, SelectableModel, HealthStatus, TTSVoice, TTSSettings } from './common'
