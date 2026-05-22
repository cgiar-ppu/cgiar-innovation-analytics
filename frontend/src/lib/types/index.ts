/**
 * @file index.ts
 * @module lib/types
 *
 * Barrel re-export of all domain type files. Importing from `lib/types`
 * continues to work unchanged — all types are re-exported here.
 */

export type { ServerMessage, ClientMessage } from './websocket'
export type { Session } from './session'
export type { ChatMessage, MessageRole, PendingAttachment, SearchResult } from './chat'
export type { PipelineStepMessage, PipelineStepState } from './pipeline'
export type { FileInfo, Memory, NewMemory, AppConfig, HealthStatus, TTSVoice, TTSSettings } from './common'
export type {
  GitFileStatus,
  GitStatus,
  GitDiffResponse,
  GitLogCommit,
  GitLogResponse,
  GitShowResponse,
} from './git'
