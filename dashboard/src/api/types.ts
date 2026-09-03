// Mirrors the backend's Pydantic response models field-for-field, including
// their camelCase names, so the shape here is never the thing to debug when
// a response looks wrong. See backend/app/models/{snapshot,status,host}.py.
//
// Every timestamp crosses the wire as the ISO-8601 string FastAPI serializes
// it to (e.g. "2026-08-12T11:15:27Z"); this layer does not parse it into a
// Date; callers that need one construct it with `new Date(value)`.

export interface CPUInfo {
  coreCount: number
  usagePercent: number
}

export interface MemoryInfo {
  totalMB: number
  usedMB: number
}

export interface DiskInfo {
  totalGB: number
  freeGB: number
}

export interface SystemInfo {
  name: string
  version: string
  hostName: string
}

export interface ProcessEntry {
  pid: number
  name: string
  memoryMB: number
}

export interface ProcessInfo {
  // Total running processes — not top.length, which is only the heaviest few.
  count: number
  top: ProcessEntry[]
}

export interface NetworkInterface {
  name: string
  bytesSent: number
  bytesRecv: number
  bytesSentPerSec: number
  bytesRecvPerSec: number
}

export interface NetworkInfo {
  interfaces: NetworkInterface[]
}

export interface Snapshot {
  collectedAt: string
  cpuInfo: CPUInfo
  memoryInfo: MemoryInfo
  diskInfo: DiskInfo
  systemInfo: SystemInfo
  // Absent from a snapshot collected by an agent built before Sprint 7, and
  // omitted from the response rather than sent as null (the backend uses
  // response_model_exclude_none).
  processInfo?: ProcessInfo
  networkInfo?: NetworkInfo
}

export interface SnapshotPage {
  items: Snapshot[]
  count: number
}

export type Metric = 'cpu' | 'memory' | 'disk' | 'processes' | 'net_sent' | 'net_recv'
export type Bucket = 'raw' | 'minute' | 'hour' | 'day'

// What a series' values are measured in. cpu/memory/disk are 'percent' on a
// 0-100 axis; the process and network metrics are not, so the chart reads the
// axis from here rather than assuming a percentage.
export type Unit = 'percent' | 'count' | 'bytes_per_sec'

export interface SeriesPoint {
  t: string
  value: number
}

export interface Series {
  metric: Metric
  bucket: Bucket
  unit: Unit
  points: SeriesPoint[]
}

// "unknown" is the honest answer before the poller has ticked, or when
// polling is switched off — not a failure state, so it renders differently
// from "down".
export type AgentState = 'up' | 'down' | 'unknown'

export interface Status {
  backend: 'ok'
  agent: AgentState
  pollerRunning: boolean
  lastPollAt: string | null
  lastSuccessAt: string | null
  lastPollError: string | null
}

export interface Host {
  hostName: string
  lastCollectedAt: string
  snapshotCount: number
}

export interface HostList {
  items: Host[]
}

// See backend/app/models/alert.py. The order info < warning < critical is only
// for sorting; nothing branches on it.
export type Severity = 'info' | 'warning' | 'critical'
export type AlertState = 'ok' | 'firing'
export type Operator = 'gt' | 'gte' | 'lt' | 'lte'

export interface AlertRule {
  id: number
  name: string
  metric: Metric
  operator: Operator
  threshold: number
  severity: Severity
  enabled: boolean
  createdAt: string
  updatedAt: string
}

export interface AlertRuleList {
  items: AlertRule[]
}

export interface Alert {
  id: number
  // null once the rule is deleted; the copied fields below still describe what
  // fired.
  ruleId: number | null
  ruleName: string
  metric: Metric
  operator: Operator
  threshold: number
  severity: Severity
  hostName: string
  state: AlertState
  value: number
  triggeredAt: string
  resolvedAt: string | null
  lastSeenAt: string
}

export interface AlertPage {
  items: Alert[]
  count: number
}

export interface AlertList {
  items: Alert[]
}
