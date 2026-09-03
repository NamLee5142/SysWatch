import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, NetworkError, getMe, logout, setUnauthorizedHandler } from '../api/client'
import { useAuth } from './AuthContext'
import { AuthProvider } from './AuthProvider'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getMe: vi.fn(),
    logout: vi.fn(),
    setUnauthorizedHandler: vi.fn(),
  }
})

const ADMIN = { username: 'root', role: 'admin' } as const
const VIEWER = { username: 'viv', role: 'viewer' } as const

function Probe() {
  const { status, user, isAdmin, signOut } = useAuth()
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="user">{user?.username ?? 'none'}</span>
      <span data-testid="admin">{String(isAdmin)}</span>
      <button onClick={() => void signOut()}>Sign out</button>
    </div>
  )
}

function renderProvider() {
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  )
}

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

beforeEach(() => {
  vi.mocked(getMe).mockReset()
  vi.mocked(logout).mockReset().mockResolvedValue(undefined)
  vi.mocked(setUnauthorizedHandler).mockReset()
})

describe('AuthProvider', () => {
  it('shows nothing decisive while the session check is in flight', () => {
    vi.mocked(getMe).mockReturnValue(neverSettles())

    renderProvider()

    // Not the login page: a refresh with a good session would otherwise flash
    // a login form and replace it, which reads as having been logged out.
    expect(screen.getByRole('status')).toBeInTheDocument()
    expect(screen.queryByTestId('status')).not.toBeInTheDocument()
  })

  it('adopts the account the backend reports', async () => {
    vi.mocked(getMe).mockResolvedValue(ADMIN)

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))
    expect(screen.getByTestId('user')).toHaveTextContent('root')
    expect(screen.getByTestId('admin')).toHaveTextContent('true')
  })

  it('marks a viewer as not an admin', async () => {
    vi.mocked(getMe).mockResolvedValue(VIEWER)

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('admin')).toHaveTextContent('false'))
  })

  it('settles as anonymous when there is no session', async () => {
    vi.mocked(getMe).mockRejectedValue(new ApiError(401, 'Not authenticated'))

    renderProvider()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
    expect(screen.getByTestId('user')).toHaveTextContent('none')
  })

  it('settles as anonymous when the backend cannot be reached', async () => {
    vi.mocked(getMe).mockRejectedValue(new NetworkError(new Error('offline')))

    renderProvider()

    // Better than a dashboard claiming you are logged in to something that is
    // not answering; the login page then reports the real reason.
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
  })

  it('signs out through the backend and clears locally', async () => {
    vi.mocked(getMe).mockResolvedValue(ADMIN)
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    expect(logout).toHaveBeenCalledOnce()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
  })

  it('clears locally even when the logout request fails', async () => {
    vi.mocked(getMe).mockResolvedValue(ADMIN)
    vi.mocked(logout).mockRejectedValue(new NetworkError(new Error('offline')))
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    await userEvent.click(screen.getByRole('button', { name: 'Sign out' }))

    // Staying "logged in" because the backend did not answer leaves someone
    // looking at a dashboard they have asked to leave.
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
  })

  it('drops the user when any request reports the session gone', async () => {
    vi.mocked(getMe).mockResolvedValue(ADMIN)
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    // Whatever the client handed setUnauthorizedHandler is what a 401 from any
    // of the page's polls will call.
    const handler = vi.mocked(setUnauthorizedHandler).mock.calls.at(0)?.[0]
    expect(handler).toBeTypeOf('function')
    handler?.()

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('anonymous'))
  })

  it('unregisters the handler on unmount', async () => {
    vi.mocked(getMe).mockResolvedValue(ADMIN)
    const { unmount } = renderProvider()
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'))

    unmount()

    expect(vi.mocked(setUnauthorizedHandler)).toHaveBeenLastCalledWith(null)
  })
})

describe('useAuth', () => {
  it('refuses to be used outside a provider', () => {
    // Without this a component would silently behave as if nobody were logged
    // in, which looks like a login bug rather than the wiring mistake it is.
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(() => render(<Probe />)).toThrow('useAuth must be used inside an AuthProvider')

    quiet.mockRestore()
  })
})
