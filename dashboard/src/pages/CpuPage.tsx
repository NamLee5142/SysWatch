import { useState } from 'react'

import { getLatestSnapshot, getSnapshotSeries } from '../api/client'
import { GaugeCard } from '../components/GaugeCard'
import { MetricChart } from '../components/MetricChart'
import { TimeRangePicker } from '../components/TimeRangePicker'
import { usePolling } from '../hooks/usePolling'
import { useUpdateEffect } from '../hooks/useUpdateEffect'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { DEFAULT_TIME_RANGE, type TimeRange } from '../lib/timeRanges'
import styles from './MetricPage.module.css'

export function CpuPage() {
  const [range, setRange] = useState<TimeRange>(DEFAULT_TIME_RANGE)

  const snapshot = usePolling((signal) => getLatestSnapshot(undefined, signal), POLL_INTERVAL_MS)
  const series = usePolling(
    (signal) =>
      getSnapshotSeries(
        {
          metric: 'cpu',
          since: new Date(Date.now() - range.rangeMs).toISOString(),
          bucket: range.bucket,
        },
        signal,
      ),
    POLL_INTERVAL_MS,
  )

  // Picking a new range must not wait for the next 5s poll tick to take
  // visible effect — refetch immediately, once, on the change itself.
  useUpdateEffect(() => {
    series.refetch()
  }, [range, series.refetch])

  // Same minimal-on-purpose stance as Overview: real loading/error polish is
  // Phase E's job (commits 20-21).
  if (!snapshot.data) {
    return (
      <div className={styles.page}>
        <h1>CPU</h1>
        <p className={styles.placeholder}>{snapshot.error ? 'Unable to load the latest snapshot.' : 'Loading…'}</p>
      </div>
    )
  }

  const { cpuInfo } = snapshot.data

  return (
    <div className={styles.page}>
      <h1>CPU</h1>
      <div className={styles.summary}>
        <GaugeCard value={cpuInfo.usagePercent} hint={`${cpuInfo.coreCount} cores`} size={160} />
      </div>
      <div className={styles.chartSection}>
        <div className={styles.chartHeader}>
          <h2>Trend</h2>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>
        <MetricChart points={series.data?.points ?? []} ariaLabel="CPU usage over time" />
      </div>
    </div>
  )
}
