import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState, type ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { login } from '../api/client'
import type { CurrentUser } from '../api/types'
import { AppRoutes } from '../routes'
import { renderWithAuth, TEST_ADMIN } from '../test/renderWithAuth'
import { AuthContext, type AuthValue } from './AuthContext'

// Every page under the shell polls something. None of it needs to resolve for
// these tests, which are about which screen appears.
vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  NetworkError: class extends Error {},
  login: vi.fn(),
  logout: vi.fn(),
  getMe: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
  getLatestSnapshot: vi.fn(() => new Promise(() => {})),
  getStatus: vi.fn(() => new Promise(() => {})),
  getHosts: vi.fn(() => new Promise(() => {})),
  getSnapshotSeries: vi.fn(() => new Promise(() => {})),
  listSnapshots: vi.fn(() => new Promise(() => {})),
  getAlerts: vi.fn(() => new Promise(() => {})),
  getActiveAlerts: vi.fn(() => new Promise(() => {})),
  listAlertRules: vi.fn(() => new Promise(() => {})),
}))

/** An auth context that can actually change, for the sign-in journey. */
function StatefulAuth({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)

  const value: AuthValue = {
    status: user === null ? 'anonymous' : 'authenticated',
    user,
    isAdmin: user?.role === 'admin',
    signIn: setUser,
    signOut: async () => setUser(null),
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

beforeEach(() => {
  vi.mocked(login).mockReset()
})

describe('ProtectedRoute', () => {
  it('sends an anonymous visitor to the login form', () => {
    renderWithAuth(<AppRoutes />, { user: null, path: '/' })

    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
  })

  it.each(['/cpu', '/alerts', '/history'])('guards %s too', (path) => {
    renderWithAuth(<AppRoutes />, { user: null, path })

    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('lets an authenticated visitor through', () => {
    renderWithAuth(<AppRoutes />, { user: TEST_ADMIN, path: '/cpu' })

    expect(screen.getByRole('heading', { name: 'CPU' })).toBeInTheDocument()
  })

  it('does not keep an authenticated visitor on the login page', () => {
    renderWithAuth(<AppRoutes />, { user: TEST_ADMIN, path: '/login' })

    // Arriving at /login with a live session should land on the dashboard, not
    // offer a form that would immediately redirect anyway.
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })

  it('resumes the page the visitor was headed for', async () => {
    vi.mocked(login).mockResolvedValue(TEST_ADMIN)

    render(
      <MemoryRouter initialEntries={['/alerts']}>
        <StatefulAuth>
          <AppRoutes />
        </StatefulAuth>
      </MemoryRouter>,
    )

    await userEvent.type(screen.getByLabelText('Username'), 'root')
    await userEvent.type(screen.getByLabelText('Password'), 'hunter2hunter2')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    // Not Overview: being dumped somewhere else and having to navigate again
    // is the thing the `from` state exists to avoid.
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Alerts' })).toBeInTheDocument())
  })

  it('lands on the dashboard when there was no intended page', async () => {
    vi.mocked(login).mockResolvedValue(TEST_ADMIN)

    render(
      <MemoryRouter initialEntries={['/login']}>
        <StatefulAuth>
          <AppRoutes />
        </StatefulAuth>
      </MemoryRouter>,
    )

    await userEvent.type(screen.getByLabelText('Username'), 'root')
    await userEvent.type(screen.getByLabelText('Password'), 'hunter2hunter2')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument())
  })

  it('shows the login form again when the session ends mid-session', async () => {
    render(
      <MemoryRouter initialEntries={['/alerts']}>
        <StatefulAuth>
          <AppRoutes />
        </StatefulAuth>
      </MemoryRouter>,
    )
    vi.mocked(login).mockResolvedValue(TEST_ADMIN)
    await userEvent.type(screen.getByLabelText('Username'), 'root')
    await userEvent.type(screen.getByLabelText('Password'), 'hunter2hunter2')
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))
    await screen.findByRole('heading', { name: 'Alerts' })

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument())
  })
})

describe('AppShell account', () => {
  it('shows who is signed in and their role', () => {
    renderWithAuth(<AppRoutes />, { user: { username: 'viv', role: 'viewer' }, path: '/' })

    // The role explains why the alert-rule controls are or are not there.
    expect(screen.getByText('viv')).toBeInTheDocument()
    expect(screen.getByText('· viewer')).toBeInTheDocument()
  })

  it('signs out through the context', async () => {
    const signOut = vi.fn()
    renderWithAuth(<AppRoutes />, { user: TEST_ADMIN, path: '/', signOut })

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(signOut).toHaveBeenCalledOnce()
  })
})
