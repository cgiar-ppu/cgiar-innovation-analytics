/**
 * @file useTextareaAutoGrow.ts
 * @module hooks
 *
 * Custom React hook that auto-grows a textarea element to fit its content up to
 * a configurable maximum height. The technique works by temporarily resetting
 * the element's height to `"auto"` so the browser recalculates `scrollHeight`,
 * then clamping that value to the maximum before re-applying it.
 *
 * This is a pure DOM-manipulation hook — it owns the ref and exposes an
 * `adjustHeight` callback so consumers can call it whenever the value changes.
 */

import { useRef, useCallback } from 'react'

/**
 * Return value of {@link useTextareaAutoGrow}.
 */
interface UseTextareaAutoGrowReturn {
  /**
   * Attach this ref to the `<textarea>` element you want to auto-grow.
   */
  textareaRef: React.RefObject<HTMLTextAreaElement | null>

  /**
   * Call this whenever the textarea value changes to recalculate and apply the
   * correct height. Typically invoked inside a `useEffect` that depends on the
   * controlled value state.
   */
  adjustHeight: () => void
}

/**
 * useTextareaAutoGrow
 *
 * Manages a textarea ref and provides an `adjustHeight` function that resizes
 * the element to fit its content up to `maxHeight` pixels.
 *
 * @param maxHeight - Maximum height in pixels before the textarea starts
 *   scrolling internally. Defaults to `200`.
 * @returns `{ textareaRef, adjustHeight }`
 *
 * @example
 * ```tsx
 * const { textareaRef, adjustHeight } = useTextareaAutoGrow()
 *
 * useEffect(() => {
 *   adjustHeight()
 * }, [value, adjustHeight])
 *
 * return <textarea ref={textareaRef} value={value} onChange={...} />
 * ```
 */
export function useTextareaAutoGrow(maxHeight = 200): UseTextareaAutoGrowReturn {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const adjustHeight = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    // Reset to auto first so shrinking the text reduces the element's height
    // (without this the element would only ever grow).
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  }, [maxHeight])

  return { textareaRef, adjustHeight }
}
