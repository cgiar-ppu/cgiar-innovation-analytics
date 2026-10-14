import type { ChatMessage } from './types'

/** Subtype of a chat message that must always be visible (never collapsed). */
export const NOTICE_SUBTYPE = 'notice'

/** True when a chat message is a notice that the compact view must show in full. */
export function isNotice(msg: ChatMessage): boolean {
  return msg.role === 'system' && msg.subtype === NOTICE_SUBTYPE
}
