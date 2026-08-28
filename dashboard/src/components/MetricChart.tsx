import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { TooltipContentProps } from 'recharts'

import type { SeriesPoint } from '../api/types'
import styles from './MetricChart.module.css'
import { Skeleton } from './Skeleton'

interface MetricChartProps {
  points: SeriesPoint[]
  // Every metric this backend serves is a percentage (see the metric_expression
  // note in backend/app/repositories/snapshot_store.py), which is what lets a
  // single 0-100 axis serve CPU, memory and disk without a per-page variant.
  color?: string
  ariaLabel: string
  // True only before the series has ever resolved — see the caller-side note
  // on why this is not simply `points.length === 0`.
  loading?: boolean
}

function formatTick(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatTooltipLabel(iso: string): string {
  return new Date(iso).toLocaleString()
}

function ChartTooltip({ active, payload, label }: TooltipContentProps) {
  if (!active || !payload || payload.length === 0 || typeof label !== 'string') {
    return null
  }

  const value = payload[0]?.value

  return (
    <div className={styles.tooltip}>
      <div>{formatTooltipLabel(label)}</div>
      <div>{typeof value === 'number' ? `${value.toFixed(1)}%` : '—'}</div>
    </div>
  )
}

/** A percentage-over-time line, shared by the CPU, Memory and Disk trend
 *  charts so their axes, tooltip and empty state read identically. */
export function MetricChart({ points, color = 'var(--accent)', ariaLabel, loading = false }: MetricChartProps) {
  // Distinct from the empty state below: a first load and a genuinely empty
  // query used to render the same "No data for this range." message, which
  // is misleading while a fetch is still in flight — that is not yet a
  // settled answer. role="status" here (a live region) rather than role="img"
  // (a static graphic with a name) reflects that this is a transient phase,
  // not a final one.
  if (loading) {
    return (
      <div className={styles.chart} role="status">
        <span className="visually-hidden">{`Loading ${ariaLabel}`}</span>
        <Skeleton width="100%" height={220} />
      </div>
    )
  }

  if (points.length === 0) {
    return (
      <div className={styles.chart} role="img" aria-label={ariaLabel}>
        <p className={styles.empty}>No data for this range.</p>
      </div>
    )
  }

  return (
    <div className={styles.chart} role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%" minHeight={220}>
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="t" tickFormatter={formatTick} stroke="var(--text)" tick={{ fontSize: 12 }} />
          {/* Explicit ticks rather than Recharts' auto count: at typical card
              heights its heuristic can collapse to a single "100%" tick,
              which is a worse axis than a fixed, always-consistent one. */}
          <YAxis
            domain={[0, 100]}
            ticks={[0, 25, 50, 75, 100]}
            // Recharts' default overlap-avoidance ("preserveEnd") can still
            // collapse an explicit `ticks` list down to just the last one at
            // typical card heights; interval={0} is what actually forces all
            // five to render.
            interval={0}
            tickFormatter={(tick: number) => `${tick}%`}
            stroke="var(--text)"
            tick={{ fontSize: 12 }}
            width={40}
          />
          <Tooltip content={ChartTooltip} />
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
