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

export interface Snapshot {
  collectedAt: string
  cpuInfo: CPUInfo
  memoryInfo: MemoryInfo
  diskInfo: DiskInfo
  systemInfo: SystemInfo
}

export interface SnapshotPage {
  items: Snapshot[]
  count: number
}

export type Metric = 'cpu' | 'memory' | 'disk'
export type Bucket = 'raw' | 'minute' | 'hour' | 'day'

export interface SeriesPoint {
  t: string
  value: number
}

export interface Series {
  metric: Metric
  bucket: Bucket
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
