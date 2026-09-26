import { useState, useEffect, useCallback, useRef } from 'react';

interface UseApiResult<T> {
  /**
   * The last successfully fetched value, or `fallback` until the first fetch
   * succeeds. A failed refetch never replaces real data with the fallback.
   * Pass `null` as the fallback for anything that shows figures, so a page can
   * render a skeleton / "unavailable" state instead of invented numbers.
   */
  data: T;
  loading: boolean;
  error: string | null;
  /** True when the most recent fetch succeeded. */
  isLive: boolean;
  /** When `data` was last fetched successfully (null = never). */
  lastSuccessAt: Date | null;
  refetch: () => void;
}

export function useApi<T>(
  fetcher: () => Promise<T>,
  fallback: T,
  options?: { autoFetch?: boolean; interval?: number }
): UseApiResult<T> {
  const { autoFetch = true, interval } = options ?? {};
  const [data, setData] = useState<T>(fallback);
  const [loading, setLoading] = useState(autoFetch);
  const [error, setError] = useState<string | null>(null);
  const [isLive, setIsLive] = useState(false);
  const [lastSuccessAt, setLastSuccessAt] = useState<Date | null>(null);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      setData(result);
      setIsLive(true);
      setLastSuccessAt(new Date());
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch';
      setError(msg);
      setIsLive(false);
      // Keep whatever we had: the last real data, or the fallback if nothing
      // has ever loaded. Never swap real data for the fallback.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (autoFetch) refetch();
  }, [autoFetch, refetch]);

  useEffect(() => {
    if (!interval) return;
    const id = setInterval(refetch, interval);
    return () => clearInterval(id);
  }, [interval, refetch]);

  return { data, loading, error, isLive, lastSuccessAt, refetch };
}
