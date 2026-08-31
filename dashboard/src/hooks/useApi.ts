import { useCallback, useEffect, useRef, useState } from 'react'

export type Fetcher<T> = (signal: AbortSignal) => Promise<T>

export interface ApiState<T> {
  data: T | undefined
  error: unknown
  loading: boolean
  refetch: () => void
}

/**
 * Runs `fetcher` once on mount and again whenever refetch() is called.
 *
 * `data` is never cleared by a refetch, only replaced once the new fetch
 * succeeds: a page checking `loading && data === undefined` shows a spinner
 * on first load only, and keeps rendering the last known value through every
 * refresh after that instead of blanking on each one.
 */
export function useApi<T>(fetcher: Fetcher<T>): ApiState<T> {
  // Read through a ref rather than depending on `fetcher` directly: callers
  // typically pass an inline arrow function, a new reference every render,
  // and depending on that here would refetch on every render. The effect
  // below is driven only by `attempt`, bumped explicitly by refetch().
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })

  const [data, setData] = useState<T>()
  const [error, setError] = useState<unknown>()
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    // The guard that actually matters: whatever this fetch settles with — a
    // real value, a real error, or an AbortError from the abort() below — is
    // stale the moment cleanup has run, whether that is unmount or a newer
    // refetch superseding it. Checking `cancelled` first makes a
    // rejection-reason check on AbortError redundant, since nothing outside
    // this closure's own cleanup can ever abort this controller.
    let cancelled = false

    fetcherRef.current(controller.signal).then(
      (result) => {
        if (cancelled) return
        setData(result)
        setError(undefined)
        setLoading(false)
      },
      (reason: unknown) => {
        if (cancelled) return
        setError(reason)
        setLoading(false)
      },
    )

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [attempt])

  const refetch = useCallback(() => {
    // Batched into the same event with the attempt bump below, so this and
    // the mount effect's re-run land in one render — not a separate one
    // triggered by setting loading synchronously inside the effect itself.
    setLoading(true)
    setAttempt((value) => value + 1)
  }, [])

  return { data, error, loading, refetch }
}
