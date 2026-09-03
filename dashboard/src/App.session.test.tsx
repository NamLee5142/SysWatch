import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

/**
 * The session lifecycle through the real stack.
 *
 * Only `fetch` is stubbed here, so the actual API client, AuthProvider,
 * ProtectedRoute and pages all run. Everything else in the suite mocks the
 * client module, which means this is the only place the wiring between them —
 * a 401 anywhere reaching setUnauthorizedHandler and ending up at the login
 * form — is proved rather than assumed.
 */

const ADMIN = { username: 'root', role: 'admin' }

let sessionValid = true

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function route(url: string): Response {
  if (url.startsWith('/api/auth/me')) {
    return sessionValid ? json(ADMIN) : json({ detail: 'Not authenticated' }, 401)
  }

  if (url.startsWith('/api/auth/login')) {
    sessionValid = true
    return json(ADMIN)
  }

  if (url.startsWith('/api/auth/logout')) {
    sessionValid = false
    return new Response(null, { status: 204 })
  }

  if (!sessionValid) {
    return json({ detail: 'Not authenticated' }, 401)
  }

  // A fresh backend that has not collected anything yet: the pages have a
  // handled state for this, so they render rather than crashing on a shape
  // that only looked close enough.
  if (url.startsWith('/api/snapshots/latest')) {
    return json({ detail: 'No snapshot stored yet' }, 404)
  }
  if (url.startsWith('/api/snapshots/series')) {
    return json({ metric: 'cpu', bucket: 'hour', unit: 'percent', points: [] })
  }
  if (url.startsWith('/api/status')) {
    return json({
      backend: 'ok',
      agent: 'unknown',
      pollerRunning: true,
      lastPollAt: null,
      lastSuccessAt: null,
      lastPollError: null,
    })
  }

  // /snapshots, /hosts, /alerts, /alerts/active, /alert-rules.
  return json({ items: [], count: 0 })
}

beforeEach(() => {
  sessionValid = true
  // App mounts a real BrowserRouter, which reads window.location — and jsdom
  // keeps one history for the whole file. Without this reset a test starts
  // wherever the previous one was redirected to, including the `from` state a
  // ProtectedRoute left behind.
  window.history.replaceState(null, '', '/')
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => Promise.resolve(route(String(input)))),
  )
})

afterEach(async () => {
  // Testing Library has already unmounted the app by now, which clears the
  // unauthorized handler. This lets any request still in flight from the test
  // land against that null handler — otherwise a 401 left over from one test
  // arrives after the next test has mounted its own provider and signs it
  // straight back out.
  await new Promise((resolve) => setTimeout(resolve, 0))
  vi.unstubAllGlobals()
})

describe('session lifecycle', () => {
  it('lands on the dashboard when the session is good', async () => {
    render(<App />)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument())
    expect(screen.getByText('root')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('shows the login form when there is no session', async () => {
    sessionValid = false

    render(<App />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument())
  })

  it('signs in and reaches the dashboard', async () => {
    sessionValid = false
    render(<App />)
    await screen.findByRole('button', { name: 'Sign in' })

    await userEvent.type(screen.getByLabelText('Username'), 'root')
    await userEvent.type(screen.getByLabelText('Password'), 'hunter2hunter2')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument())
  })

  it('reports a rejected password without leaving the form', async () => {
    sessionValid = false
    vi.mocked(fetch).mockImplementation((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.startsWith('/api/auth/login')) {
        return Promise.resolve(json({ detail: 'Invalid username or password' }, 401))
      }
      return Promise.resolve(route(url))
    })

    render(<App />)
    await screen.findByRole('button', { name: 'Sign in' })
    await userEvent.type(screen.getByLabelText('Username'), 'root')
    await userEvent.type(screen.getByLabelText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    // A wrong password must not be mistaken for an ended session and bounce
    // the page somewhere; the form is already where it should be.
    expect(screen.getByLabelText('Username')).toBeInTheDocument()
  })

  it('falls back to the login form when a session ends mid-visit', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: 'Overview' })

    // The cookie is still in the browser; the server has stopped honouring it.
    sessionValid = false

    // Navigating remounts a page, which fetches, which is how the app finds
    // out — the same way a background poll would.
    await userEvent.click(screen.getByRole('link', { name: 'CPU' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument())
  })

  it('signs out on request', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: 'Overview' })

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument())
  })

  it('sends the session cookie on every request it makes', async () => {
    render(<App />)
    await screen.findByRole('heading', { name: 'Overview' })

    // Nothing works without this: the cookie is HttpOnly, so credentials:
    // 'include' is the only thing carrying it on a cross-origin build.
    for (const [, init] of vi.mocked(fetch).mock.calls) {
      expect(init).toMatchObject({ credentials: 'include' })
    }
  })
})
