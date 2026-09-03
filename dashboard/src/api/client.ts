import type {
  Alert,
  AlertList,
  AlertPage,
  AlertRule,
  AlertRuleList,
  AlertState,
  Bucket,
  CurrentUser,
  HostList,
  Metric,
  Operator,
  Series,
  Severity,
  Snapshot,
  SnapshotPage,
  Status,
} from './types'

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
  /** Seconds from a 429's Retry-After header, when the backend sent one. The
   *  backend adds Retry-After to expose_headers precisely so this is readable
   *  cross-origin; without it a rate-limited login could only say "later". */
  readonly retryAfter?: number

  constructor(status: number, detail: unknown, retryAfter?: number) {
    super(formatDetail(status, detail))
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.retryAfter = retryAfter
  }
}

function parseRetryAfter(response: Response): number | undefined {
  const header = response.headers.get('Retry-After')
  if (header === null) {
    return undefined
  }

  const seconds = Number(header)
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined
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

interface RequestOptions {
  params?: Record<string, string | number | undefined>
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  // Serialised to a JSON request body. Only meaningful for POST and PUT.
  body?: unknown
  signal?: AbortSignal
  // Set on the login call. A 401 there means "those credentials are wrong",
  // which the form shows inline — it must not be mistaken for "the session
  // you were using has ended" and bounce the page to a login it is already on.
  expectsUnauthorized?: boolean
}

type UnauthorizedHandler = () => void

let onUnauthorized: UnauthorizedHandler | null = null

/**
 * Register what happens when the backend says a session is no longer good.
 *
 * Any of the ~5 polls a page has running can be the one that discovers a
 * session expired, and each of them handling it would mean five redirects and
 * five chances to get it wrong. They all funnel here instead; AuthContext is
 * what registers a handler.
 */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  onUnauthorized = handler
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { params, method = 'GET', body, signal, expectsUnauthorized = false } = options

  // The session is an HttpOnly cookie the browser holds. Same-origin requests
  // would send it anyway, but a production build talking to VITE_API_BASE_URL
  // on another origin would not without this.
  const init: RequestInit = { method, signal, credentials: 'include' }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }

  let response: Response

  try {
    response = await fetch(buildUrl(path, params), init)
  } catch (cause) {
    // An abort is the caller's own doing (see the polling hook), not a
    // connectivity failure, so it is left to propagate as-is rather than being
    // reported as one.
    if (cause instanceof DOMException && cause.name === 'AbortError') {
      throw cause
    }
    throw new NetworkError(cause)
  }

  if (!response.ok) {
    if (response.status === 401 && !expectsUnauthorized) {
      onUnauthorized?.()
    }
    throw new ApiError(response.status, await parseErrorBody(response), parseRetryAfter(response))
  }

  // DELETE answers 204 with no body; parsing it as JSON would throw.
  if (response.status === 204) {
    return undefined as T
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
  return request<SnapshotPage>('/snapshots', { params, signal })
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
  return request<Series>('/snapshots/series', { params, signal })
}

export function getLatestSnapshot(host?: string, signal?: AbortSignal): Promise<Snapshot> {
  return request<Snapshot>('/snapshots/latest', { params: { host }, signal })
}

// Reads the agent directly rather than storage, so it 503s while the agent is
// down. The dashboard reads getLatestSnapshot() instead for exactly that
// reason; this is exposed for completeness and any future non-dashboard use.
export function getSnapshot(signal?: AbortSignal): Promise<Snapshot> {
  return request<Snapshot>('/snapshot', { signal })
}

export function getStatus(signal?: AbortSignal): Promise<Status> {
  return request<Status>('/status', { signal })
}

export function getHosts(signal?: AbortSignal): Promise<HostList> {
  return request<HostList>('/hosts', { signal })
}

export interface ListAlertsParams {
  host?: string
  state?: AlertState
  rule_id?: number
  since?: string
  until?: string
  limit?: number
  offset?: number
  [key: string]: string | number | undefined
}

export function getAlerts(params: ListAlertsParams = {}, signal?: AbortSignal): Promise<AlertPage> {
  return request<AlertPage>('/alerts', { params, signal })
}

export function getActiveAlerts(host?: string, signal?: AbortSignal): Promise<AlertList> {
  return request<AlertList>('/alerts/active', { params: { host }, signal })
}

export function getAlert(id: number, signal?: AbortSignal): Promise<Alert> {
  return request<Alert>(`/alerts/${id}`, { signal })
}

export function listAlertRules(signal?: AbortSignal): Promise<AlertRuleList> {
  return request<AlertRuleList>('/alert-rules', { signal })
}

export interface AlertRuleInput {
  name: string
  metric: Metric
  operator: Operator
  threshold: number
  severity?: Severity
  enabled?: boolean
}

export function createAlertRule(rule: AlertRuleInput, signal?: AbortSignal): Promise<AlertRule> {
  return request<AlertRule>('/alert-rules', { method: 'POST', body: rule, signal })
}

export function updateAlertRule(
  id: number,
  changes: Partial<AlertRuleInput>,
  signal?: AbortSignal,
): Promise<AlertRule> {
  return request<AlertRule>(`/alert-rules/${id}`, { method: 'PUT', body: changes, signal })
}

export function deleteAlertRule(id: number, signal?: AbortSignal): Promise<void> {
  return request<void>(`/alert-rules/${id}`, { method: 'DELETE', signal })
}


export function login(username: string, password: string, signal?: AbortSignal): Promise<CurrentUser> {
  return request<CurrentUser>('/auth/login', {
    method: 'POST',
    body: { username, password },
    signal,
    // A 401 here is a wrong password, not an ended session.
    expectsUnauthorized: true,
  })
}

export function logout(signal?: AbortSignal): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST', signal })
}

export function getMe(signal?: AbortSignal): Promise<CurrentUser> {
  // Also 401s for a caller who has simply never logged in, which is how the
  // app tells "no session" from "backend unreachable" on first load.
  return request<CurrentUser>('/auth/me', { signal, expectsUnauthorized: true })
}
