import { useState } from 'react'

import { getLatestSnapshot, getSnapshotSeries } from '../api/client'
import { GaugeCard } from '../components/GaugeCard'
import { MetricChart } from '../components/MetricChart'
import { TimeRangePicker } from '../components/TimeRangePicker'
import { usePolling } from '../hooks/usePolling'
import { useUpdateEffect } from '../hooks/useUpdateEffect'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { formatGB, percentOf } from '../lib/format'
import { DEFAULT_TIME_RANGE, type TimeRange } from '../lib/timeRanges'
import styles from './MetricPage.module.css'

export function DiskPage() {
  const [range, setRange] = useState<TimeRange>(DEFAULT_TIME_RANGE)

  const snapshot = usePolling((signal) => getLatestSnapshot(undefined, signal), POLL_INTERVAL_MS)
  const series = usePolling(
    (signal) =>
      getSnapshotSeries(
        {
          metric: 'disk',
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
        <h1>Disk</h1>
        <p className={styles.placeholder}>{snapshot.error ? 'Unable to load the latest snapshot.' : 'Loading…'}</p>
      </div>
    )
  }

  const { diskInfo } = snapshot.data
  // The agent reports total and free, not used — every page that shows disk
  // usage has to derive it the same way (see also OverviewPage).
  const usedGB = diskInfo.totalGB - diskInfo.freeGB
  const usedPercent = percentOf(usedGB, diskInfo.totalGB)

  return (
    <div className={styles.page}>
      <h1>Disk</h1>
      <div className={styles.summary}>
        <GaugeCard
          value={usedPercent}
          hint={`${formatGB(usedGB)} used / ${formatGB(diskInfo.freeGB)} free`}
          size={160}
        />
      </div>
      <div className={styles.chartSection}>
        <div className={styles.chartHeader}>
          <h2>Trend</h2>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>
        <MetricChart points={series.data?.points ?? []} ariaLabel="Disk usage over time" />
      </div>
    </div>
  )
}
