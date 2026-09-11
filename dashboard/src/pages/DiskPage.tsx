import { useState } from 'react'

import { getLatestSnapshot, getSnapshotSeries } from '../api/client'
import type { DiskInfo } from '../api/types'
import { GaugeCard } from '../components/GaugeCard'
import { GaugeCardSkeleton } from '../components/GaugeCardSkeleton'
import { MetricChart } from '../components/MetricChart'
import { SnapshotErrorMessage } from '../components/SnapshotErrorMessage'
import { TimeRangePicker } from '../components/TimeRangePicker'
import { useSelectedHost } from '../hosts/SelectedHostContext'
import { usePolling } from '../hooks/usePolling'
import { useUpdateEffect } from '../hooks/useUpdateEffect'
import { POLL_INTERVAL_MS } from '../lib/constants'
import { formatGB, percentOf } from '../lib/format'
import { DEFAULT_TIME_RANGE, type TimeRange } from '../lib/timeRanges'
import styles from './MetricPage.module.css'

// The agent reports total and free, not used — derived the same way every
// page that shows disk usage does (see also OverviewPage).
function DiskGauge({ diskInfo }: { diskInfo: DiskInfo }) {
  const usedGB = diskInfo.totalGB - diskInfo.freeGB
  return (
    <GaugeCard
      value={percentOf(usedGB, diskInfo.totalGB)}
      hint={`${formatGB(usedGB)} used / ${formatGB(diskInfo.freeGB)} free`}
      size={160}
    />
  )
}

export function DiskPage() {
  const { hostName } = useSelectedHost()
  const [range, setRange] = useState<TimeRange>(DEFAULT_TIME_RANGE)

  const snapshot = usePolling((signal) => getLatestSnapshot(hostName ?? undefined, signal), POLL_INTERVAL_MS)
  const series = usePolling(
    (signal) =>
      getSnapshotSeries(
        {
          metric: 'disk',
          host: hostName ?? undefined,
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

  return (
    <div className={styles.page}>
      <h1>Disk</h1>

      {/* Its own section, not gated behind the snapshot — see CpuPage for
          why: the chart has a different data source and no reason to stay
          hidden, TimeRangePicker included, while the gauge is still loading. */}
      <div className={styles.summary}>
        {snapshot.data ? (
          <DiskGauge diskInfo={snapshot.data.diskInfo} />
        ) : snapshot.error ? (
          <SnapshotErrorMessage error={snapshot.error} className={styles.placeholder} />
        ) : (
          <div role="status">
            <span className="visually-hidden">Loading Disk</span>
            <GaugeCardSkeleton size={160} />
          </div>
        )}
      </div>

      <div className={styles.chartSection}>
        <div className={styles.chartHeader}>
          <h2>Trend</h2>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>
        {/* loading only while genuinely unresolved — falls back to the
            chart's own empty state once series.error is set, unchanged from
            before this commit. */}
        <MetricChart
          points={series.data?.points ?? []}
          ariaLabel="Disk usage over time"
          loading={!series.data && !series.error}
        />
      </div>
    </div>
  )
}
