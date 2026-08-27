import { useEffect, useRef } from 'react'

/**
 * Like useEffect, but skips the run that would otherwise fire on mount —
 * only fires on a genuine change to one of `deps` afterward.
 *
 * Built for triggering a refetch when a filter (a TimeRangePicker selection)
 * changes: `useApi` already fetches once on mount by itself, so a plain
 * `useEffect(() => refetch(), [range])` would fetch twice on the first
 * render — once from useApi's own mount effect, once from this one racing
 * it. Skipping the first run is what keeps that to a single fetch.
 */
export function useUpdateEffect(effect: () => void, deps: unknown[]): void {
  const hasMounted = useRef(false)

  useEffect(() => {
    if (!hasMounted.current) {
      hasMounted.current = true
      return
    }
    effect()
    // The linter cannot verify a dependency array it cannot see as a literal
    // at this call site — `deps` is whatever the caller passed in, which is
    // exactly the point of a generic wrapper like this one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
