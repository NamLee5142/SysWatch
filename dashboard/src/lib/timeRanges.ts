import type { Bucket } from '../api/types'

export interface TimeRange {
  label: string
  // How far back from "now" this range looks, in milliseconds.
  rangeMs: number
  // The bucket that keeps this range's point count comfortably under the
  // backend's cap (MAX_POINTS in backend/app/api/snapshots.py, 5000) at the
  // agent's collection interval — a week of raw samples would blow well past
  // it, so the range and its bucket are chosen together, not independently.
  bucket: Bucket
}

const HOUR_MS = 60 * 60 * 1000
const DAY_MS = 24 * HOUR_MS

export const TIME_RANGES: readonly TimeRange[] = [
  { label: '1h', rangeMs: HOUR_MS, bucket: 'raw' },
  { label: '6h', rangeMs: 6 * HOUR_MS, bucket: 'minute' },
  { label: '24h', rangeMs: DAY_MS, bucket: 'hour' },
  { label: '7d', rangeMs: 7 * DAY_MS, bucket: 'hour' },
]

export const DEFAULT_TIME_RANGE: TimeRange = TIME_RANGES[2]
