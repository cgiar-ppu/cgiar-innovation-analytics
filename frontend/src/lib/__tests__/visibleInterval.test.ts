import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { visibleInterval } from '../visibleInterval'

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  document.dispatchEvent(new Event('visibilitychange'))
}

describe('visibleInterval (env-power: no polling from hidden tabs)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setVisibility('visible')
  })
  afterEach(() => {
    vi.useRealTimers()
    setVisibility('visible')
  })

  it('ticks while the tab is visible', () => {
    const fn = vi.fn()
    const stop = visibleInterval(fn, 120_000)
    vi.advanceTimersByTime(360_000)
    expect(fn).toHaveBeenCalledTimes(3)
    stop()
  })

  it('sends nothing while hidden, however long', () => {
    const fn = vi.fn()
    const stop = visibleInterval(fn, 120_000)
    setVisibility('hidden')
    vi.advanceTimersByTime(8 * 60 * 60_000) // a forgotten tab overnight
    expect(fn).not.toHaveBeenCalled()
    stop()
  })

  it('catches up once when the tab becomes visible after a skipped tick', () => {
    const fn = vi.fn()
    const stop = visibleInterval(fn, 120_000)
    setVisibility('hidden')
    vi.advanceTimersByTime(600_000)
    setVisibility('visible')
    expect(fn).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(120_000)
    expect(fn).toHaveBeenCalledTimes(2)
    stop()
  })

  it('does not fire on a visibility flip when no tick was skipped', () => {
    const fn = vi.fn()
    const stop = visibleInterval(fn, 120_000)
    setVisibility('hidden')
    setVisibility('visible')
    expect(fn).not.toHaveBeenCalled()
    stop()
  })

  it('stop() clears the timer and the listener', () => {
    const fn = vi.fn()
    const stop = visibleInterval(fn, 1_000)
    setVisibility('hidden')
    vi.advanceTimersByTime(5_000)
    stop()
    setVisibility('visible')
    vi.advanceTimersByTime(5_000)
    expect(fn).not.toHaveBeenCalled()
  })
})
