import { Link } from 'react-router-dom'

import { getActiveAlerts } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import { POLL_INTERVAL_MS } from '../lib/constants'
import styles from './AlertIndicator.module.css'

/**
 * The bell in the app-shell header. Polls the active-alert count on the shared
 * interval and links to /alerts, so nobody has to keep the page open to notice
 * something started firing. Polling is enough for a first cut — no WebSocket.
 */
export function AlertIndicator() {
  const active = usePolling((signal) => getActiveAlerts(undefined, signal), POLL_INTERVAL_MS)

  // Treat a failed or not-yet-loaded poll as zero rather than flashing an error
  // in the chrome; the Alerts page itself surfaces the failure.
  const count = active.data?.items.length ?? 0
  // "across all hosts" because the header next to it names one machine, and a
  // bare count beside a host name reads as that host's count. It is not: this
  // is every host, which is the point of it.
  const label =
    count === 0
      ? 'No active alerts'
      : `${count} active alert${count === 1 ? '' : 's'} across all hosts`

  return (
    <Link
      to="/alerts"
      className={`${styles.indicator} ${count > 0 ? styles.active : styles.quiet}`}
      aria-label={label}
      title={label}
    >
      <span aria-hidden="true">🔔</span>
      <span className={styles.count}>{count}</span>
    </Link>
  )
}
