/**
 * @file useCopyToClipboard.ts
 * @module hooks
 *
 * Custom React hook that wraps the Clipboard API and maintains a short-lived
 * "Copied!" confirmation state. The confirmation automatically resets after a
 * configurable delay so the UI can give visual feedback without permanent state
 * changes.
 *
 * Clipboard errors (e.g. permission denied in insecure contexts) are silently
 * swallowed — the same behaviour used in AssistantMessage before extraction.
 */

import { useState, useRef, useEffect, useCallback } from 'react'

/**
 * Return value of {@link useCopyToClipboard}.
 */
interface UseCopyToClipboardReturn {
  /**
   * `true` for `resetMs` milliseconds after a successful copy, then `false`.
   * Use this to toggle between a "Copy" and "Copied!" label / icon.
   */
  copied: boolean

  /**
   * Writes `text` to the system clipboard. Sets `copied` to `true` on
   * success and resets it after the configured delay.
   *
   * @param text - The plain-text string to place on the clipboard.
   */
  copyToClipboard: (text: string) => Promise<void>
}

/**
 * useCopyToClipboard
 *
 * Handles clipboard writes with an automatic "Copied!" timer.
 *
 * @param resetMs - How long (in milliseconds) to keep `copied` set to `true`
 *   before resetting to `false`. Defaults to `2000` (2 seconds).
 * @returns `{ copied, copyToClipboard }`
 *
 * @example
 * ```tsx
 * const { copied, copyToClipboard } = useCopyToClipboard()
 *
 * return (
 *   <button onClick={() => copyToClipboard(someText)}>
 *     {copied ? 'Copied!' : 'Copy'}
 *   </button>
 * )
 * ```
 */
export function useCopyToClipboard(resetMs = 2000): UseCopyToClipboardReturn {
  const [copied, setCopied] = useState(false)

  // Keep a ref to the pending reset timer so we can cancel it on re-click or
  // on unmount, preventing a setState call on an unmounted component.
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  // Cancel any pending timer when the component that owns this hook unmounts.
  useEffect(() => {
    return () => { clearTimeout(timerRef.current) }
  }, [])

  const copyToClipboard = useCallback(async (text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      // Cancel any previously scheduled reset before starting a new one,
      // so that a rapid double-click restarts the timer cleanly.
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setCopied(false), resetMs)
    } catch {
      // Clipboard API may throw if the page is not focused or the user has
      // denied the clipboard-write permission. Fail silently.
    }
  }, [resetMs])

  return { copied, copyToClipboard }
}
