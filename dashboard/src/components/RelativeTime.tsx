import { useEffect, useState } from 'react'

import { formatRelativeTime } from '../lib/format'

const TICK_MS = 1000

interface RelativeTimeProps {
  iso: string
}

/**
 * Renders `iso` as "12s ago", counting up on its own second by second.
 *
 * This is what makes a stale dashboard visible: if the agent goes down, the
 * data hook stops getting fresher `collectedAt` values, but this must not
 * freeze alongside it — the whole point is to keep counting up between polls
 * so staleness is obvious without anyone needing to notice a missing update.
 */
export function RelativeTime({ iso }: RelativeTimeProps) {
  const [, forceTick] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => forceTick((tick) => tick + 1), TICK_MS)
    return () => window.clearInterval(id)
  }, [])

  return <time dateTime={iso}>{formatRelativeTime(iso)}</time>
}
