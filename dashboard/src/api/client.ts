import type { Bucket, HostList, Metric, Series, Snapshot, SnapshotPage, Status } from './types'

// In development the Vite proxy (vite.config.ts) serves '/api' from the same
// origin as the page, so no origin needs naming here. A production build has
// no such proxy and must set VITE_API_BASE_URL to the backend's own origin.
const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api'

/**
 * The backend answered, just not with success — a 404, a 422, a 503 relaying
 * that the agent is unreachable. Distinct from NetworkError so a caller can
 * render "no data yet" instead of "backend unreachable"; those need different
 * UI and this is what lets them tell the two apart.
 */
export class ApiError extends Error {
  readonly status: number
  readonly detail: unknown

  constructor(status: number, detail: unknown) {
    super(formatDetail(status, detail))
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

/** The request never reached the backend at all: connection refused, DNS
 *  failure, offline. There is no status code to report because no response
 *  arrived. */
export class NetworkError extends Error {
  constructor(cause: unknown) {
    super('Unable to reach the backend')
    this.name = 'NetworkError'
    this.cause = cause
  }
}

// The backend's error body takes two shapes depending on who raised it: a
// hand-written HTTPException carries a plain string detail (see
// _validate_window in app/api/snapshots.py), while FastAPI's own query
// validation carries a list of {msg, loc, ...} objects, one per invalid
// field. Both are folded into one readable message here so callers get a
// string either way instead of having to branch on which kind of 422 it was.
function formatDetail(status: number, detail: unknown): string {
  if (typeof detail === 'string') {
    return detail
  }

  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry && typeof entry === 'object' && 'msg' in entry ? String(entry.msg) : null))
      .filter((message): message is string => message !== null)

    if (messages.length > 0) {
      return messages.join('; ')
    }
  }

  return `Request failed with status ${status}`
}

async function parseErrorBody(response: Response): Promise<unknown> {
  try {
    const body: unknown = await response.json()
    return body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : undefined
  } catch {
    // Not every error response is JSON (a proxy's own 502 page, for one).
    return undefined
  }
}

function buildUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams()

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        query.set(key, String(value))
      }
    }
  }

  const queryString = query.toString()
  return queryString ? `${BASE_URL}${path}?${queryString}` : `${BASE_URL}${path}`
}

async function request<T>(
  path: string,
  params?: Record<string, string | number | undefined>,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response

  try {
    response = await fetch(buildUrl(path, params), { signal })
  } catch (cause) {
    // An abort is the caller's own doing (see the polling hook in a later
    // commit), not a connectivity failure, so it is left to propagate as-is
    // rather than being reported as one.
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw cause
    }
    throw new NetworkError(cause)
  }

  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorBody(response))
  }

  return (await response.json()) as T
}

// The index signature is what lets this be passed straight to request(),
// which builds a query string from an arbitrary string/number bag; the named
// properties are what give callers autocomplete and typo-checking.
export interface ListSnapshotsParams {
  host?: string
  since?: string
  until?: string
  limit?: number
  offset?: number
  [key: string]: string | number | undefined
}

export function listSnapshots(params: ListSnapshotsParams = {}, signal?: AbortSignal): Promise<SnapshotPage> {
  return request<SnapshotPage>('/snapshots', params, signal)
}

export interface SnapshotSeriesParams {
  metric: Metric
  host?: string
  since?: string
  until?: string
  bucket?: Bucket
  [key: string]: string | number | undefined
}

export function getSnapshotSeries(params: SnapshotSeriesParams, signal?: AbortSignal): Promise<Series> {
  return request<Series>('/snapshots/series', params, signal)
}

export function getLatestSnapshot(host?: string, signal?: AbortSignal): Promise<Snapshot> {
  return request<Snapshot>('/snapshots/latest', { host }, signal)
}

// Reads the agent directly rather than storage, so it 503s while the agent is
// down. The dashboard reads getLatestSnapshot() instead for exactly that
// reason; this is exposed for completeness and any future non-dashboard use.
export function getSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  return request<Snapshot>('/snapshot', undefined, signal)
}

export function getStatus(signal?: AbortSignal): Promise<Status> {
  return request<Status>('/status', undefined, signal)
}

export function getHosts(signal?: AbortSignal): Promise<HostList> {
  return request<HostList>('/hosts', undefined, signal)
}
