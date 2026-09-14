import { useEffect, useState } from 'react'

/**
 * The current time, re-rendering on its own every `intervalMs`.
 *
 * Reading Date.now() during render is impure, and here it is also wrong: a
 * dashboard left open would only notice a host had gone quiet when something
 * else happened to re-render it. Anything that decides "is this too old" needs
 * its own clock, the same way RelativeTime keeps counting up between polls.
 */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])

  return now
}
