import { getHosts, getLatestSnapshot, getStatus } from '../api/client'
import { RelativeTime } from '../components/RelativeTime'
import { StatCard } from '../components/StatCard'
import { StatusDot } from '../components/StatusDot'
import { usePolling } from '../hooks/usePolling'
import { AGENT_STATE_LABEL } from '../lib/agentState'
import { POLL_INTERVAL_MS } from '../lib/constants'
import styles from './SystemPage.module.css'

// Three independent sources, none blocking the others: the host list has no
// reason to wait on the snapshot fetch, and vice versa. This is why System
// does not use the single-early-return loading gate every other page does —
// those pages have exactly one thing to wait on, this one has three.
export function SystemPage() {
  const snapshot = usePolling((signal) => getLatestSnapshot(undefined, signal), POLL_INTERVAL_MS)
  const status = usePolling(getStatus, POLL_INTERVAL_MS)
  const hosts = usePolling(getHosts, POLL_INTERVAL_MS)

  const agentState = status.data?.agent ?? 'unknown'

  return (
    <div className={styles.page}>
      <h1>System</h1>

      {snapshot.data ? (
        <div className={styles.grid}>
          <StatCard label="Hostname" value={snapshot.data.systemInfo.hostName} />
          <StatCard label="OS" value={`${snapshot.data.systemInfo.name} ${snapshot.data.systemInfo.version}`} />
        </div>
      ) : (
        <p className={styles.placeholder}>
          {snapshot.error ? 'Unable to load the latest snapshot.' : 'Loading…'}
        </p>
      )}

      <section className={styles.section}>
        <h2>Connection</h2>
        {status.data ? (
          <dl className={styles.statusList}>
            <div className={styles.statusRow}>
              <dt>Agent</dt>
              <dd className={styles.connectionValue}>
                <StatusDot state={agentState} />
                {AGENT_STATE_LABEL[agentState]}
              </dd>
            </div>
            <div className={styles.statusRow}>
              <dt>Backend poller</dt>
              <dd>{status.data.pollerRunning ? 'Running' : 'Stopped'}</dd>
            </div>
            <div className={styles.statusRow}>
              <dt>Last successful collection</dt>
              <dd>{status.data.lastSuccessAt ? <RelativeTime iso={status.data.lastSuccessAt} /> : 'Never'}</dd>
            </div>
            {status.data.lastPollError && (
              <div className={styles.statusRow}>
                <dt>Last error</dt>
                <dd className={styles.errorValue}>{status.data.lastPollError}</dd>
              </div>
            )}
          </dl>
        ) : (
          <p className={styles.placeholder}>{status.error ? 'Unable to load status.' : 'Loading…'}</p>
        )}
      </section>

      <section className={styles.section}>
        <h2>Hosts</h2>
        {hosts.data ? (
          hosts.data.items.length === 0 ? (
            <p className={styles.placeholder}>No hosts have reported yet.</p>
          ) : (
            <div className={styles.tableWrapper}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">Host</th>
                    <th scope="col">Last seen</th>
                    <th scope="col">Snapshots</th>
                  </tr>
                </thead>
                <tbody>
                  {hosts.data.items.map((host) => (
                    <tr key={host.hostName}>
                      <td>{host.hostName}</td>
                      <td>
                        <RelativeTime iso={host.lastCollectedAt} />
                      </td>
                      <td>{host.snapshotCount}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <p className={styles.placeholder}>{hosts.error ? 'Unable to load hosts.' : 'Loading…'}</p>
        )}
      </section>
    </div>
  )
}
