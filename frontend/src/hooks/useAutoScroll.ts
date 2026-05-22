/**
 * @file useAutoScroll.ts
 * @module hooks
 *
 * Custom React hook that keeps a scrollable container pinned to its bottom
 * edge as new content is appended — unless the user has manually scrolled up,
 * in which case auto-scroll is suppressed so they can read earlier messages.
 *
 * Uses a ResizeObserver on the content wrapper to detect height changes,
 * replacing the previous deps-based useEffect that fired on every text delta.
 *
 * The "user has scrolled up" heuristic is a simple threshold: if the scroll
 * position is within {@link BOTTOM_THRESHOLD} pixels of the bottom the
 * container is considered "at bottom" and auto-scroll remains active.
 */

import { useRef, useEffect, useCallback, useState } from 'react'

/** Pixel distance from the true bottom within which we consider the container "at bottom". */
const BOTTOM_THRESHOLD = 100

/**
 * Return value of {@link useAutoScroll}.
 */
interface UseAutoScrollReturn {
  /**
   * Attach this ref to the scrollable container `<div>`.
   * The hook reads and sets `scrollTop` / `scrollHeight` on this element.
   */
  containerRef: React.RefObject<HTMLDivElement | null>

  /**
   * `true` when the container's scroll position is within
   * {@link BOTTOM_THRESHOLD} pixels of the bottom.
   */
  isAtBottom: boolean

  /**
   * Imperatively scrolls the container to the very bottom and resets the
   * "user scrolled up" flag. Useful for a "scroll to bottom" button.
   */
  scrollToBottom: () => void
}

/**
 * useAutoScroll
 *
 * Attaches a scroll listener and a ResizeObserver to the container ref.
 * Auto-scrolls to the bottom when content grows — but only when the user
 * has not manually scrolled up.
 *
 * @returns `{ containerRef, isAtBottom, scrollToBottom }`
 *
 * @example
 * ```tsx
 * const { containerRef, isAtBottom, scrollToBottom } = useAutoScroll()
 *
 * return (
 *   <div ref={containerRef} className="overflow-y-auto">
 *     {messages.map(...)}
 *   </div>
 * )
 * ```
 */
export function useAutoScroll(): UseAutoScrollReturn {
  const containerRef = useRef<HTMLDivElement>(null)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const userScrolledUp = useRef(false)

  const scrollToBottom = useCallback(() => {
    const el = containerRef.current
    if (el) {
      el.scrollTop = el.scrollHeight
      setIsAtBottom(true)
      userScrolledUp.current = false
    }
  }, [])

  // Listen for manual scroll events to detect when the user scrolls up.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const handleScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < BOTTOM_THRESHOLD
      setIsAtBottom(atBottom)
      userScrolledUp.current = !atBottom
    }

    el.addEventListener('scroll', handleScroll, { passive: true })
    return () => el.removeEventListener('scroll', handleScroll)
  }, [])

  // Use ResizeObserver to detect content growth and auto-scroll
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const observer = new ResizeObserver(() => {
      if (!userScrolledUp.current) {
        queueMicrotask(() => scrollToBottom())
      }
    })

    const target = el.firstElementChild || el
    observer.observe(target)

    return () => observer.disconnect()
  }, [scrollToBottom])

  return { containerRef, isAtBottom, scrollToBottom }
}
