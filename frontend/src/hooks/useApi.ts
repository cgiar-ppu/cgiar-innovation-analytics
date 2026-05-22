import { useState, useEffect, useCallback, useRef } from 'react';

interface UseApiResult<T> {
  data: T;
  loading: boolean;
  error: string | null;
  isLive: boolean;
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
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetcherRef.current();
      setData(result);
      setIsLive(true);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch';
      setError(msg);
      setIsLive(false);
      // Keep fallback data visible
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

  return { data, loading, error, isLive, refetch };
}
