/**
 * @file types.ts
 * @module lib
 *
 * Re-export hub — all types now live in focused domain files under
 * `lib/types/`. This file preserves backward compatibility so that
 * every existing `import { ... } from '../lib/types'` continues to
 * resolve without changes.
 */
export type {
  ServerMessage,
  ClientMessage,
  Session,
  SearchResult,
  FileInfo,
  Memory,
  NewMemory,
  AppConfig,
  HealthStatus,
  MessageRole,
  ChatMessage,
  PipelineStepMessage,
  PipelineStepState,
  PendingAttachment,
  GitFileStatus,
  GitStatus,
  GitDiffResponse,
  GitLogCommit,
  GitLogResponse,
  GitShowResponse,
  TTSVoice,
  TTSSettings,
} from './types/index'
