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
  AppConfig,
  ModelPolicy,
  GuardrailContactInfo,
  SelectableModel,
  HealthStatus,
  MessageRole,
  ChatMessage,
  PendingAttachment,
  TTSVoice,
  TTSSettings,
} from './types/index'
