import type { Metric, Operator, Severity, Unit } from '../api/types'
import { formatBytesPerSec } from './format'

// Mirrors METRIC_UNIT in backend/app/models/snapshot.py. The Alert payload
// carries `metric` but not its unit, so the value and threshold columns look it
// up here.
export const METRIC_UNIT: Record<Metric, Unit> = {
  cpu: 'percent',
  memory: 'percent',
  disk: 'percent',
  processes: 'count',
  net_sent: 'bytes_per_sec',
  net_recv: 'bytes_per_sec',
}

export const METRIC_LABEL: Record<Metric, string> = {
  cpu: 'CPU usage',
  memory: 'Memory usage',
  disk: 'Disk usage',
  processes: 'Process count',
  net_sent: 'Network send rate',
  net_recv: 'Network receive rate',
}

export const OPERATOR_SYMBOL: Record<Operator, string> = {
  gt: '>',
  gte: '≥',
  lt: '<',
  lte: '≤',
}

export const SEVERITY_LABEL: Record<Severity, string> = {
  info: 'Info',
  warning: 'Warning',
  critical: 'Critical',
}

/** A metric value in its own unit: percent for cpu/memory/disk, a bare count for
 *  processes, a rate for the network metrics. */
export function formatMetricValue(metric: Metric, value: number): string {
  switch (METRIC_UNIT[metric]) {
    case 'percent':
      return `${value.toFixed(1)}%`
    case 'count':
      return String(Math.round(value))
    case 'bytes_per_sec':
      return formatBytesPerSec(value)
  }
}

/** "> 90%", "< 10%", "> 500" — the rule condition, one string. */
export function formatCondition(metric: Metric, operator: Operator, threshold: number): string {
  return `${OPERATOR_SYMBOL[operator]} ${formatMetricValue(metric, threshold)}`
}
