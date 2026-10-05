"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError } from "./api";

interface ResourceState<T> {
  data: T | null;
  error: string | null;
}

/**
 * Load async data for a component. `fetcher` must be memoised (useCallback); it re-runs
 * when it changes or when `reload()` is called. Stale responses are ignored.
 */
export function useResource<T>(fetcher: () => Promise<T>, errorMessage = "Failed to load data") {
  const [state, setState] = useState<ResourceState<T>>({ data: null, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetcher().then(
      (data) => !cancelled && setState({ data, error: null }),
      (err: unknown) =>
        !cancelled &&
        setState((s) => ({
          data: s.data,
          error: err instanceof ApiError && err.status === 404 ? err.message : errorMessage,
        })),
    );
    return () => {
      cancelled = true;
    };
  }, [fetcher, version, errorMessage]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  const mutate = useCallback(
    (update: (current: T | null) => T | null) => setState((s) => ({ ...s, data: update(s.data) })),
    [],
  );
  return { data: state.data, error: state.error, reload, mutate };
}
