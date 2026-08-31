import { useEffect, useRef } from 'react'

import { useApi, type ApiState, type Fetcher } from './useApi'

/**
 * useApi(), refetching automatically every intervalMs.
 *
 * Skips a tick while the tab is hidden — a background tab gets no benefit
 * from data nobody is looking at, and polling anyway is exactly the traffic
 * pattern that makes "poll every N seconds" expensive at scale — then
 * refetches once as soon as the tab becomes visible again, so switching back
 * doesn't leave the page showing whatever was last fetched before it was
 * hidden until the next scheduled tick.
 */
export function usePolling<T>(fetcher: Fetcher<T>, intervalMs: number): ApiState<T> {
  const api = useApi(fetcher)

  // Same reasoning as the ref in useApi: api.refetch is a stable useCallback,
  // but reading it fresh each render costs nothing and avoids relying on
  // that stability as an invariant these effects depend on.
  const refetchRef = useRef(api.refetch)
  useEffect(() => {
    refetchRef.current = api.refetch
  })

  useEffect(() => {
    const id = window.setInterval(() => {
      if (!document.hidden) {
        refetchRef.current()
      }
    }, intervalMs)

    return () => window.clearInterval(id)
  }, [intervalMs])

  useEffect(() => {
    function handleVisibilityChange() {
      if (!document.hidden) {
        refetchRef.current()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  return api
}
