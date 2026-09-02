import { useState } from 'react'

import { getLatestSnapshot, getSnapshotSeries } from '../api/client'
import type { ProcessInfo } from '../api/types'
import { MetricChart } from '../components/MetricChart'
import { SnapshotErrorMessage } from '../components/SnapshotErrorMessage'
import { StatCard } from '../components/StatCard'
import { StatCardSkeleton } from '../components/StatCardSkeleton'
import { TableSkeletonRows } from '../components/TableSkeletonRows'
import { TimeRangePicker } from '../components/TimeRangePicker'
import { usePolling } from '../hooks/usePolling'
import { useUpdateEffect } from '../hooks/useUpdateEffect'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { formatMemoryMB } from '../lib/format'
import { DEFAULT_TIME_RANGE, type TimeRange } from '../lib/timeRanges'
import styles from './ProcessPage.module.css'

// Not every agent reports processes: one built before Sprint 7 sends a
// snapshot with no processInfo block at all.
function NoProcessData() {
  return <p className={styles.placeholder}>This agent does not report process data.</p>
}

function TopProcessTable({ processInfo }: { processInfo: ProcessInfo }) {
  if (processInfo.top.length === 0) {
    return <p className={styles.placeholder}>No process detail in the latest snapshot.</p>
  }

  return (
    <div className={styles.tableWrapper}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Process</th>
            <th scope="col">PID</th>
            <th scope="col">Memory</th>
          </tr>
        </thead>
        <tbody>
          {processInfo.top.map((process) => (
            <tr key={process.pid}>
              <td>{process.name}</td>
              <td>{process.pid}</td>
              <td>{formatMemoryMB(process.memoryMB)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function ProcessPage() {
  const [range, setRange] = useState<TimeRange>(DEFAULT_TIME_RANGE)

  const snapshot = usePolling((signal) => getLatestSnapshot(undefined, signal), POLL_INTERVAL_MS)
  const series = usePolling(
    (signal) =>
      getSnapshotSeries(
        {
          metric: 'processes',
          since: new Date(Date.now() - range.rangeMs).toISOString(),
          bucket: range.bucket,
        },
        signal,
      ),
    POLL_INTERVAL_MS,
  )

  useUpdateEffect(() => {
    series.refetch()
  }, [range, series.refetch])

  const processInfo = snapshot.data?.processInfo

  return (
    <div className={styles.page}>
      <h1>Processes</h1>

      {/* Its own section, not gated behind the snapshot — see CpuPage for
          why: the chart has a different data source and TimeRangePicker needs
          no fetched data at all. */}
      <div className={styles.summary}>
        {snapshot.data ? (
          processInfo ? (
            <StatCard label="Running processes" value={processInfo.count} />
          ) : (
            <NoProcessData />
          )
        ) : snapshot.error ? (
          <SnapshotErrorMessage error={snapshot.error} className={styles.placeholder} />
        ) : (
          <div role="status">
            <span className="visually-hidden">Loading processes</span>
            <StatCardSkeleton />
          </div>
        )}
      </div>

      <section className={styles.section}>
        <h2>Top by memory</h2>
        {snapshot.data ? (
          processInfo ? (
            <TopProcessTable processInfo={processInfo} />
          ) : (
            <NoProcessData />
          )
        ) : snapshot.error ? (
          <SnapshotErrorMessage error={snapshot.error} className={styles.placeholder} />
        ) : (
          <div className={styles.tableWrapper} role="status">
            <span className="visually-hidden">Loading top processes</span>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Process</th>
                  <th scope="col">PID</th>
                  <th scope="col">Memory</th>
                </tr>
              </thead>
              <tbody>
                <TableSkeletonRows columns={3} />
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className={styles.chartSection}>
        <div className={styles.chartHeader}>
          <h2>Trend</h2>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>
        <MetricChart
          points={series.data?.points ?? []}
          unit={series.data?.unit ?? 'count'}
          ariaLabel="Process count over time"
          loading={!series.data && !series.error}
        />
      </div>
    </div>
  )
}
