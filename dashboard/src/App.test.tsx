import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getMe } from './api/client'
import App from './App'

// The real App mounts AuthProvider, which asks the backend who is calling
// before it renders anything. Every page under the shell then polls; none of
// that needs to resolve for these assertions.
vi.mock('./api/client', () => ({
  ApiError: class extends Error {},
  NetworkError: class extends Error {},
  getMe: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  setUnauthorizedHandler: vi.fn(),
  getLatestSnapshot: vi.fn(() => new Promise(() => {})),
  getStatus: vi.fn(() => new Promise(() => {})),
  getActiveAlerts: vi.fn(() => new Promise(() => {})),
  getHosts: vi.fn(() => new Promise(() => {})),
}))

beforeEach(() => {
  vi.mocked(getMe).mockReset()
})

describe('App', () => {
  it('renders the shell with the overview page at the root path', async () => {
    vi.mocked(getMe).mockResolvedValue({ username: 'root', role: 'admin' })

    render(<App />)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'CPU' })).toBeInTheDocument()
  })

  it('shows the login form to a visitor with no session', async () => {
    vi.mocked(getMe).mockRejectedValue(new Error('401'))

    render(<App />)

    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument())
    // Not the shell behind it: nothing in there would load anyway.
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})
