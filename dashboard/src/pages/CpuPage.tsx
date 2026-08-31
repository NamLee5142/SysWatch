import { useState } from 'react'

import { getLatestSnapshot, getSnapshotSeries } from '../api/client'
import { GaugeCard } from '../components/GaugeCard'
import { GaugeCardSkeleton } from '../components/GaugeCardSkeleton'
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

  return (
    <div className={styles.page}>
      <h1>CPU</h1>

      {/* Its own section, not gated behind the snapshot: the chart has a
          different data source (series, not snapshot) and no reason to stay
          hidden — including the TimeRangePicker itself, which needs no
          fetched data at all — just because the gauge is still loading. */}
      <div className={styles.summary}>
        {snapshot.data ? (
          <GaugeCard
            value={snapshot.data.cpuInfo.usagePercent}
            hint={`${snapshot.data.cpuInfo.coreCount} cores`}
            size={160}
          />
        ) : snapshot.error ? (
          <p className={styles.placeholder}>Unable to load the latest snapshot.</p>
        ) : (
          <div role="status">
            <span className="visually-hidden">Loading CPU</span>
            <GaugeCardSkeleton size={160} />
          </div>
        )}
      </div>

      <div className={styles.chartSection}>
        <div className={styles.chartHeader}>
          <h2>Trend</h2>
          <TimeRangePicker value={range} onChange={setRange} />
        </div>
        {/* loading only while genuinely unresolved: once series.error is set,
            this must fall back to the chart's own empty state rather than
            loading forever — that fallback is unchanged from before this
            commit, only the "hasn't tried yet" case is new. */}
        <MetricChart
          points={series.data?.points ?? []}
          ariaLabel="CPU usage over time"
          loading={!series.data && !series.error}
        />
      </div>
    </div>
  )
}
