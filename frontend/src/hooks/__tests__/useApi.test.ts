/**
 * Tests for the useApi hook (hooks/useApi.ts).
 *
 * Uses renderHook from @testing-library/react and vi.fn() for the fetcher.
 * act() wraps state updates so React flushes effects before assertions.
 */
import { describe, it, expect, vi } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { useApi } from '../useApi'

describe('useApi hook', () => {
  // -----------------------------------------------------------------------
  // test_returns_fallback_when_api_fails
  // -----------------------------------------------------------------------
  it('test_returns_fallback_when_api_fails', async () => {
    const fallback = [{ id: 1, name: 'mock' }]
    const fetcher = vi.fn().mockRejectedValue(new Error('network error'))

    const { result } = renderHook(() => useApi(fetcher, fallback))

    // Wait for loading to settle
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toEqual(fallback)
    expect(result.current.isLive).toBe(false)
    expect(result.current.error).toBe('network error')
  })

  // -----------------------------------------------------------------------
  // test_returns_live_data_on_success
  // -----------------------------------------------------------------------
  it('test_returns_live_data_on_success', async () => {
    const fallback = ['fallback']
    const liveData = ['live', 'data']
    const fetcher = vi.fn().mockResolvedValue(liveData)

    const { result } = renderHook(() => useApi(fetcher, fallback))

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toEqual(liveData)
  })

  // -----------------------------------------------------------------------
  // test_isLive_flag_false_on_fallback
  // -----------------------------------------------------------------------
  it('test_isLive_flag_false_on_fallback', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('fail'))

    const { result } = renderHook(() => useApi(fetcher, null))

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.isLive).toBe(false)
  })

  // -----------------------------------------------------------------------
  // test_isLive_flag_true_on_success
  // -----------------------------------------------------------------------
  it('test_isLive_flag_true_on_success', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true })

    const { result } = renderHook(() => useApi(fetcher, null))

    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.isLive).toBe(true)
  })

  // -----------------------------------------------------------------------
  // test_loading_state
  // -----------------------------------------------------------------------
  it('test_loading_state', async () => {
    // Use a fetcher that never resolves so we can observe the loading=true phase
    let resolve!: (v: string) => void
    const fetcher = vi.fn(() => new Promise<string>(r => { resolve = r }))

    const { result } = renderHook(() => useApi(fetcher, 'fallback'))

    // Initially loading should be true (autoFetch=true is the default)
    expect(result.current.loading).toBe(true)

    // Resolve the promise and wait for loading to go false
    resolve('done')
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.data).toBe('done')
  })

  // -----------------------------------------------------------------------
  // test_no_auto_fetch_when_disabled
  // -----------------------------------------------------------------------
  it('test_no_auto_fetch_when_disabled', () => {
    const fetcher = vi.fn().mockResolvedValue('data')

    const { result } = renderHook(() =>
      useApi(fetcher, 'fallback', { autoFetch: false })
    )

    // Should start with loading=false when autoFetch is disabled
    expect(result.current.loading).toBe(false)
    expect(fetcher).not.toHaveBeenCalled()
  })

  // -----------------------------------------------------------------------
  // test_refetch_re-invokes_fetcher
  // -----------------------------------------------------------------------
  it('test_refetch_reinvokes_fetcher', async () => {
    const fetcher = vi.fn().mockResolvedValue('first')

    const { result } = renderHook(() => useApi(fetcher, 'fallback'))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(fetcher).toHaveBeenCalledTimes(1)

    fetcher.mockResolvedValue('second')
    await act(async () => {
      result.current.refetch()
    })

    await waitFor(() => expect(result.current.data).toBe('second'))
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
})
