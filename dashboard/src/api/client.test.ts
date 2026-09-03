import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  ApiError,
  NetworkError,
  createAlertRule,
  deleteAlertRule,
  getActiveAlerts,
  getAlerts,
  getHosts,
  getLatestSnapshot,
  getSnapshot,
  getSnapshotSeries,
  getMe,
  getStatus,
  listAlertRules,
  login,
  logout,
  setUnauthorizedHandler,
  listSnapshots,
  updateAlertRule,
} from './client'

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('returns the parsed body on success', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], count: 0 }))

    const page = await listSnapshots()

    expect(page).toEqual({ items: [], count: 0 })
  })

  it('builds the request URL under the /api prefix with no query string when empty', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], count: 0 }))

    await listSnapshots()

    expect(fetch).toHaveBeenCalledWith('/api/snapshots', expect.anything())
  })

  it('encodes provided parameters into the query string, dropping unset ones', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], count: 0 }))

    await listSnapshots({ host: 'devbox', limit: 10 })

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/snapshots?host=devbox&limit=10')
  })

  it('throws ApiError with the status and a string detail on a 404', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'No snapshot stored yet' }, 404))

    await expect(getLatestSnapshot()).rejects.toMatchObject({
      name: 'ApiError',
      status: 404,
      message: 'No snapshot stored yet',
    })
  })

  it('folds FastAPI validation errors into one readable message', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        {
          detail: [
            { loc: ['query', 'metric'], msg: 'Input should be cpu, memory or disk', type: 'literal_error' },
          ],
        },
        422,
      ),
    )

    await expect(getSnapshotSeries({ metric: 'cpu' })).rejects.toMatchObject({
      status: 422,
      message: 'Input should be cpu, memory or disk',
    })
  })

  it('falls back to a generic message when the detail array has no usable msg field', async () => {
    // Array.isArray(detail) is true here, unlike the not-JSON case below —
    // this exercises the filter finding nothing, not the outer type check.
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: [{ loc: ['query', 'metric'], type: 'literal_error' }] }, 422))

    await expect(getSnapshotSeries({ metric: 'cpu' })).rejects.toMatchObject({
      status: 422,
      message: 'Request failed with status 422',
    })
  })

  it('falls back to a generic message when an error response is not JSON', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response('<html>Bad Gateway</html>', { status: 502 }))

    await expect(getStatus()).rejects.toMatchObject({
      status: 502,
      message: 'Request failed with status 502',
    })
  })

  it('throws NetworkError, not ApiError, when the backend cannot be reached', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(getHosts()).rejects.toBeInstanceOf(NetworkError)
  })

  it('keeps ApiError and NetworkError distinguishable at runtime', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'gone' }, 404))
    await expect(getHosts()).rejects.not.toBeInstanceOf(NetworkError)

    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(getHosts()).rejects.not.toBeInstanceOf(ApiError)
  })

  it('lets an abort propagate as-is instead of becoming a NetworkError', async () => {
    const controller = new AbortController()
    vi.mocked(fetch).mockRejectedValue(new DOMException('The operation was aborted.', 'AbortError'))

    await expect(getHosts(controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('hits /snapshot, not /snapshots/latest, for the direct-from-agent read', async () => {
    // getSnapshot() reads through the agent, unlike getLatestSnapshot()'s
    // storage-backed /snapshots/latest — an easy pair to mix up since they
    // return the same shape, which is exactly why this checks the URL.
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ collectedAt: '2026-08-25T10:00:00Z' }))

    await getSnapshot()

    expect(fetch).toHaveBeenCalledWith('/api/snapshot', expect.anything())
  })

  it('passes the abort signal through to fetch', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [] }))
    const controller = new AbortController()

    await getHosts(controller.signal)

    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect(init).toMatchObject({ signal: controller.signal })
  })

  it('encodes alert filters, including a non-default state', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [], count: 0 }))

    await getAlerts({ state: 'firing', rule_id: 3, limit: 20 })

    const [url] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/alerts?state=firing&rule_id=3&limit=20')
  })

  it('reads active alerts from /alerts/active', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [] }))

    await getActiveAlerts()

    expect(fetch).toHaveBeenCalledWith('/api/alerts/active', expect.anything())
  })

  it('POSTs a new rule as a JSON body', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: 1 }, 201))

    await createAlertRule({ name: 'CPU', metric: 'cpu', operator: 'gt', threshold: 90 })

    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/alert-rules')
    expect(init).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ name: 'CPU', metric: 'cpu', operator: 'gt', threshold: 90 }),
      headers: { 'Content-Type': 'application/json' },
    })
  })

  it('PUTs only the changed fields', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ id: 7, enabled: false }))

    await updateAlertRule(7, { enabled: false })

    const [url, init] = vi.mocked(fetch).mock.calls[0]
    expect(url).toBe('/api/alert-rules/7')
    expect(init).toMatchObject({ method: 'PUT', body: JSON.stringify({ enabled: false }) })
  })

  it('resolves a 204 DELETE without trying to parse a body', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }))

    await expect(deleteAlertRule(7)).resolves.toBeUndefined()
    expect(fetch).toHaveBeenCalledWith('/api/alert-rules/7', expect.objectContaining({ method: 'DELETE' }))
  })

  it('surfaces a 422 from rule creation as an ApiError with the message', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ detail: [{ loc: ['body', 'threshold'], msg: 'Input should be a finite number' }] }, 422),
    )

    await expect(
      createAlertRule({ name: 'x', metric: 'cpu', operator: 'gt', threshold: Infinity }),
    ).rejects.toMatchObject({ name: 'ApiError', status: 422, message: 'Input should be a finite number' })
  })

  it('sends credentials on every request so the session cookie travels', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [] }))

    await getHosts()

    const [, init] = vi.mocked(fetch).mock.calls[0]
    // Same-origin would send it anyway; a production build pointed at
    // VITE_API_BASE_URL on another origin would not.
    expect(init).toMatchObject({ credentials: 'include' })
  })

  it('notifies the unauthorized handler when a session stops working', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'Not authenticated' }, 401))

    await expect(getHosts()).rejects.toBeInstanceOf(ApiError)

    expect(handler).toHaveBeenCalledOnce()
    setUnauthorizedHandler(null)
  })

  it('does not notify it for a rejected login', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'Invalid username or password' }, 401))

    await expect(login('root', 'wrong')).rejects.toBeInstanceOf(ApiError)

    // A wrong password is not an ended session; treating it as one would ask
    // the app to redirect to the login page it is already showing.
    expect(handler).not.toHaveBeenCalled()
    setUnauthorizedHandler(null)
  })

  it('does not notify it for a first-load /auth/me', async () => {
    const handler = vi.fn()
    setUnauthorizedHandler(handler)
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'Not authenticated' }, 401))

    await expect(getMe()).rejects.toBeInstanceOf(ApiError)

    // "Never logged in" is the normal first visit, not a session ending.
    expect(handler).not.toHaveBeenCalled()
    setUnauthorizedHandler(null)
  })

  it('reads Retry-After off a 429', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Too many failed login attempts.' }), {
        status: 429,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '42' },
      }),
    )

    await expect(login('root', 'wrong')).rejects.toMatchObject({ status: 429, retryAfter: 42 })
  })

  it('leaves retryAfter undefined when the header is absent or nonsense', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ detail: 'nope' }, 429))
    await expect(login('root', 'wrong')).rejects.toMatchObject({ retryAfter: undefined })

    vi.mocked(fetch).mockResolvedValue(
      new Response('{}', { status: 429, headers: { 'Retry-After': 'Wed, 21 Oct 2026 07:28:00 GMT' } }),
    )
    // The date form of Retry-After is valid HTTP but not a number of seconds;
    // better undefined than NaN in a message.
    await expect(login('root', 'wrong')).rejects.toMatchObject({ retryAfter: undefined })
  })

  it('logs out with a POST that tolerates a 204', async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(null, { status: 204 }))

    await expect(logout()).resolves.toBeUndefined()
    expect(fetch).toHaveBeenCalledWith('/api/auth/logout', expect.objectContaining({ method: 'POST' }))
  })

  it('does not attach a JSON body or header to a GET', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({ items: [] }))

    await listAlertRules()

    const [, init] = vi.mocked(fetch).mock.calls[0]
    expect((init as RequestInit).body).toBeUndefined()
    expect((init as RequestInit).headers).toBeUndefined()
  })
})
