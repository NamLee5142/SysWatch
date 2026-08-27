import { useState } from 'react'

import { getLatestSnapshot, getSnapshotSeries } from '../api/client'
import { GaugeCard } from '../components/GaugeCard'
import { MetricChart } from '../components/MetricChart'
import { TimeRangePicker } from '../components/TimeRangePicker'
import { usePolling } from '../hooks/usePolling'
import { useUpdateEffect } from '../hooks/useUpdateEffect'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { formatMemoryMB, percentOf } from '../lib/format'
import { DEFAULT_TIME_RANGE, type TimeRange } from '../lib/timeRanges'
import styles from './MetricPage.module.css'

export function MemoryPage() {
  const [range, setRange] = useState<TimeRange>(DEFAULT_TIME_RANGE)

  const snapshot = usePolling((signal) => getLatestSnapshot(undefined, signal), POLL_INTERVAL_MS)
  const series = usePolling(
    (signal) =>
      getSnapshotSeries(
        {
          metric: 'memory',
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

  if (!snapshot.data) {
    return (
      <div className={styles.page}>
        <h1>Memory</h1>
        <p className={styles.placeholder}>{snapshot.error ? 'Unable to load the latest snapshot.' : 'Loading…'}</p>
      </div>
    )
  }

  const { memoryInfo } = snapshot.data
  const usedPercent = percentOf(memoryInfo.usedMB, memoryInfo.totalMB)

  return (
    <div className={styles.page}>
      <h1>Memory</h1>
      <div className={styles.summary}>
        <GaugeCard
          value={usedPercent}
          hint={`${formatMemoryMB(memoryInfo.usedMB)} / ${formatMemoryMB(memoryInfo.totalMB)}`}
          size={160}
        />
      </div>
      <div className={styles.chartSection}>
        <div className={styles.chartHeader}>
          <h2>Trend</h2>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>
        <MetricChart points={series.data?.points ?? []} ariaLabel="Memory usage over time" />
      </div>
    </div>
  )
}
