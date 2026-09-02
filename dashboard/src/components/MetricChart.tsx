import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { TooltipContentProps } from 'recharts'

import type { SeriesPoint, Unit } from '../api/types'
import { formatBytesPerSec } from '../lib/format'
import styles from './MetricChart.module.css'
import { Skeleton } from './Skeleton'

interface MetricChartProps {
  points: SeriesPoint[]
  // How points[].value is measured — see the Series.unit field the backend
  // sends. 'percent' keeps a fixed 0-100 axis so CPU, memory and disk read
  // identically; 'count' and 'bytes_per_sec' get an auto-scaled axis.
  unit?: Unit
  color?: string
  ariaLabel: string
  // True only before the series has ever resolved — see the caller-side note
  // on why this is not simply `points.length === 0`.
  loading?: boolean
}

interface AxisFormat {
  domain: [number | string, number | string]
  // Only 'percent' pins explicit ticks; the others let Recharts choose.
  ticks?: number[]
  interval?: number
  width: number
  formatTick: (value: number) => string
  formatValue: (value: number) => string
}

function axisFor(unit: Unit): AxisFormat {
  if (unit === 'bytes_per_sec') {
    return {
      domain: [0, 'auto'],
      width: 68,
      formatTick: formatBytesPerSec,
      formatValue: formatBytesPerSec,
    }
  }

  if (unit === 'count') {
    const asInteger = (value: number) => String(Math.round(value))
    return {
      domain: [0, 'auto'],
      width: 48,
      formatTick: asInteger,
      formatValue: asInteger,
    }
  }

  // percent
  return {
    domain: [0, 100],
    ticks: [0, 25, 50, 75, 100],
    interval: 0,
    width: 40,
    formatTick: (value) => `${value}%`,
    formatValue: (value) => `${value.toFixed(1)}%`,
  }
}

function formatTickLabel(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatTooltipLabel(iso: string): string {
  return new Date(iso).toLocaleString()
}

function ChartTooltip({
  active,
  payload,
  label,
  formatValue,
}: TooltipContentProps & { formatValue: (value: number) => string }) {
  if (!active || !payload || payload.length === 0 || typeof label !== 'string') {
    return null
  }

  const value = payload[0]?.value

  return (
    <div className={styles.tooltip}>
      <div>{formatTooltipLabel(label)}</div>
      <div>{typeof value === 'number' ? formatValue(value) : '—'}</div>
    </div>
  )
}

/** A value-over-time line shared by every trend chart. Percentage metrics
 *  (CPU, memory, disk) share one fixed 0-100 axis; process count and network
 *  throughput scale their own axis and format their own ticks. */
export function MetricChart({
  points,
  unit = 'percent',
  color = 'var(--accent)',
  ariaLabel,
  loading = false,
}: MetricChartProps) {
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

  const axis = axisFor(unit)

  return (
    <div className={styles.chart} role="img" aria-label={ariaLabel}>
      <ResponsiveContainer width="100%" height="100%" minHeight={220}>
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="t" tickFormatter={formatTickLabel} stroke="var(--text)" tick={{ fontSize: 12 }} />
          {/* For 'percent', explicit ticks rather than Recharts' auto count: at
              typical card heights its heuristic can collapse to a single "100%"
              tick, which is a worse axis than a fixed, always-consistent one.
              interval={0} is what actually forces all five to render. */}
          <YAxis
            domain={axis.domain}
            ticks={axis.ticks}
            interval={axis.interval}
            tickFormatter={axis.formatTick}
            stroke="var(--text)"
            tick={{ fontSize: 12 }}
            width={axis.width}
          />
          <Tooltip content={(props) => <ChartTooltip {...props} formatValue={axis.formatValue} />} />
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
