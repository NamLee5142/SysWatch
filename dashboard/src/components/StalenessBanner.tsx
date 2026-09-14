import type { AgentState } from '../api/types'
import { useNow } from '../hooks/useNow'
import { RelativeTime } from './RelativeTime'
import styles from './StalenessBanner.module.css'

/**
 * How long without a snapshot before a host counts as stale.
 *
 * Three minutes. The dashboard cannot know a given agent's collection
 * interval - it is configured on the monitored machine, not here - so this has
 * to be a number generous enough not to accuse a slow but healthy agent, and
 * short enough to notice within the time somebody would care. Three minutes is
 * six missed collections at the ten-second interval a deployment actually
 * uses, and three at the slowest interval anyone is likely to configure.
 */
export const STALE_AFTER_MS = 3 * 60 * 1000

/** How often to re-check. A minute is fine for a three-minute threshold, and
 *  it means the banner appears within a minute of the host going quiet rather
 *  than whenever something else happens to re-render. */
const CHECK_INTERVAL_MS = 60 * 1000

interface StalenessBannerProps {
  agentState: AgentState
  /** Which host `agentState` describes, from /status. */
  agentHost: string | null
  /** The host being looked at. */
  hostName: string | null
  /** When that host's most recent snapshot was collected. */
  lastCollectedAt: string | null
}

/**
 * A visible warning when what is on screen is not current, above the page
 * content rather than instead of it. The numbers are real, just possibly old,
 * and this makes that explicit rather than leaving it to the header dot.
 *
 * Two different questions, and they are not interchangeable:
 *
 * - **Is the polled agent reachable?** /status answers this, immediately and
 *   for exactly one machine. It says nothing about a host that pushes, so it
 *   is only consulted while looking at the host it is about - otherwise the
 *   banner would report the local agent's outage against a remote machine's
 *   name, which is worse than saying nothing.
 * - **Has this host reported recently?** Answered by its last snapshot, and
 *   works for every host however its data arrives. Slower to notice - it takes
 *   STALE_AFTER_MS - but it is the only signal a pushed host has.
 */
export function StalenessBanner({
  agentState,
  agentHost,
  hostName,
  lastCollectedAt,
}: StalenessBannerProps) {
  const now = useNow(CHECK_INTERVAL_MS)
  const watchingThePolledAgent = hostName !== null && hostName === agentHost

  if (watchingThePolledAgent && agentState === 'down') {
    return (
      <div className={styles.banner} role="status">
        Agent unreachable — showing the last data received.
      </div>
    )
  }

  if (lastCollectedAt !== null && now - Date.parse(lastCollectedAt) > STALE_AFTER_MS) {
    return (
      <div className={styles.banner} role="status">
        {/* The time counts up on its own, so a page left open keeps saying
            how long it has been rather than freezing at the moment it went
            stale. */}
        No new data from {hostName} since <RelativeTime iso={lastCollectedAt} /> — showing
        the last snapshot received.
      </div>
    )
  }

  return null
}
