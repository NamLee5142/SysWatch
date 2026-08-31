import type { AgentState } from '../api/types'
import styles from './StalenessBanner.module.css'

interface StalenessBannerProps {
  agentState: AgentState
}

/**
 * A visible warning when the agent is unreachable, shown above whatever page
 * content is already rendered — not instead of it. `/snapshots/latest` is
 * storage-backed and keeps answering while the agent is down, so the numbers
 * on screen are real, just possibly stale; this makes that explicit instead
 * of leaving it to the small header dot alone.
 *
 * Takes agentState as a prop rather than fetching /status itself: AppShell
 * already polls it for the header, and every page already accepts a second
 * independent poll of the same endpoint as the cost of no shared request
 * cache — a third one here would not be paying for anything new.
 */
export function StalenessBanner({ agentState }: StalenessBannerProps) {
  if (agentState !== 'down') {
    return null
  }

  return (
    <div className={styles.banner} role="status">
      Agent unreachable — showing the last data received.
    </div>
  )
}
