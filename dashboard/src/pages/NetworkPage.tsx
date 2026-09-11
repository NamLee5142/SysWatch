import { useState } from 'react'

import { getLatestSnapshot, getSnapshotSeries } from '../api/client'
import type { NetworkInfo } from '../api/types'
import { MetricChart } from '../components/MetricChart'
import { SnapshotErrorMessage } from '../components/SnapshotErrorMessage'
import { StatCardSkeleton } from '../components/StatCardSkeleton'
import { TimeRangePicker } from '../components/TimeRangePicker'
import { useSelectedHost } from '../hosts/SelectedHostContext'
import { usePolling } from '../hooks/usePolling'
import { useUpdateEffect } from '../hooks/useUpdateEffect'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { formatBytesPerSec } from '../lib/format'
import { DEFAULT_TIME_RANGE, type TimeRange } from '../lib/timeRanges'
import styles from './NetworkPage.module.css'

// An agent built before Sprint 7 sends a snapshot with no networkInfo block.
function NoNetworkData() {
  return <p className={styles.placeholder}>This agent does not report network data.</p>
}

function InterfaceCards({ networkInfo }: { networkInfo: NetworkInfo }) {
  if (networkInfo.interfaces.length === 0) {
    return <p className={styles.placeholder}>No active network interfaces.</p>
  }

  return (
    <div className={styles.cards}>
      {networkInfo.interfaces.map((nic) => (
        <div key={nic.name} className={styles.card}>
          <p className={styles.cardName}>{nic.name}</p>
          <dl className={styles.rates}>
            <div className={styles.rate}>
              <dt>Received</dt>
              <dd>{formatBytesPerSec(nic.bytesRecvPerSec)}</dd>
            </div>
            <div className={styles.rate}>
              <dt>Sent</dt>
              <dd>{formatBytesPerSec(nic.bytesSentPerSec)}</dd>
            </div>
          </dl>
        </div>
      ))}
    </div>
  )
}

export function NetworkPage() {
  const { hostName } = useSelectedHost()
  const [range, setRange] = useState<TimeRange>(DEFAULT_TIME_RANGE)

  const snapshot = usePolling((signal) => getLatestSnapshot(hostName ?? undefined, signal), POLL_INTERVAL_MS)

  const since = () => new Date(Date.now() - range.rangeMs).toISOString()
  const received = usePolling(
    (signal) => getSnapshotSeries(
        {
          metric: 'net_recv',
          host: hostName ?? undefined, since: since(), bucket: range.bucket }, signal),
    POLL_INTERVAL_MS,
  )
  const sent = usePolling(
    (signal) => getSnapshotSeries(
        {
          metric: 'net_sent',
          host: hostName ?? undefined, since: since(), bucket: range.bucket }, signal),
    POLL_INTERVAL_MS,
  )

  // A new range must take effect now, not on the next 5s tick — refetch both
  // series once on the change itself.
  useUpdateEffect(() => {
    received.refetch()
    sent.refetch()
  }, [range, received.refetch, sent.refetch])

  const networkInfo = snapshot.data?.networkInfo

  return (
    <div className={styles.page}>
      <h1>Network</h1>

      <div className={styles.summary}>
        {snapshot.data ? (
          networkInfo ? (
            <InterfaceCards networkInfo={networkInfo} />
          ) : (
            <NoNetworkData />
          )
        ) : snapshot.error ? (
          <SnapshotErrorMessage error={snapshot.error} className={styles.placeholder} />
        ) : (
          <div className={styles.cards} role="status">
            <span className="visually-hidden">Loading network interfaces</span>
            <StatCardSkeleton />
          </div>
        )}
      </div>

      <div className={styles.chartSection}>
        <div className={styles.chartHeader}>
          <h2>Throughput</h2>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>

        <h3 className={styles.chartLabel}>Received</h3>
        <MetricChart
          points={received.data?.points ?? []}
          unit={received.data?.unit ?? 'bytes_per_sec'}
          ariaLabel="Network throughput received over time"
          loading={!received.data && !received.error}
        />

        <h3 className={styles.chartLabel}>Sent</h3>
        <MetricChart
          points={sent.data?.points ?? []}
          unit={sent.data?.unit ?? 'bytes_per_sec'}
          ariaLabel="Network throughput sent over time"
          loading={!sent.data && !sent.error}
        />
      </div>
    </div>
  )
}
