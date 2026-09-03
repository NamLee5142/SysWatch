import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, NetworkError, login } from '../api/client'
import { LoginPage } from './LoginPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return { ...actual, login: vi.fn() }
})

const USER = { username: 'root', role: 'admin' } as const

function renderPage() {
  const onAuthenticated = vi.fn()
  render(<LoginPage onAuthenticated={onAuthenticated} />)
  return onAuthenticated
}

async function signIn(username = 'root', password = 'hunter2hunter2') {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Username'), username)
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

beforeEach(() => {
  vi.mocked(login).mockReset()
})

describe('LoginPage', () => {
  it('sends the credentials and reports the account back', async () => {
    vi.mocked(login).mockResolvedValue(USER)
    const onAuthenticated = renderPage()

    await signIn()

    expect(login).toHaveBeenCalledWith('root', 'hunter2hunter2')
    await waitFor(() => expect(onAuthenticated).toHaveBeenCalledWith(USER))
  })

  it('shows one message for any wrong credential', async () => {
    vi.mocked(login).mockRejectedValue(new ApiError(401, 'Invalid username or password'))
    const onAuthenticated = renderPage()

    await signIn()

    // The backend refuses to say whether the username exists; the page must
    // not invent a distinction either.
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid username or password.')
    expect(onAuthenticated).not.toHaveBeenCalled()
  })

  it('keeps the username but clears the password after a failure', async () => {
    vi.mocked(login).mockRejectedValue(new ApiError(401, 'nope'))
    renderPage()

    await signIn()

    await screen.findByRole('alert')
    expect(screen.getByLabelText('Username')).toHaveValue('root')
    expect(screen.getByLabelText('Password')).toHaveValue('')
  })

  it('counts down when the rate limit trips', async () => {
    vi.mocked(login).mockRejectedValue(new ApiError(429, 'Too many failed login attempts.', 42))
    renderPage()

    await signIn()

    expect(await screen.findByRole('alert')).toHaveTextContent('Try again in 42 seconds')
  })

  it('says the backend is unreachable rather than blaming the password', async () => {
    vi.mocked(login).mockRejectedValue(new NetworkError(new Error('offline')))
    renderPage()

    await signIn()

    expect(await screen.findByRole('alert')).toHaveTextContent("Can't reach the backend")
  })

  it('disables the button while the request is in flight', async () => {
    let release: (user: typeof USER) => void = () => {}
    vi.mocked(login).mockReturnValue(new Promise((resolve) => (release = resolve)))
    renderPage()

    await signIn()

    // Otherwise an impatient double-click spends two of the ten attempts the
    // rate limit allows.
    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled()

    release(USER)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled())
  })

  it('clears an earlier error when the next attempt starts', async () => {
    vi.mocked(login).mockRejectedValueOnce(new ApiError(401, 'nope'))
    renderPage()

    await signIn()
    await screen.findByRole('alert')

    vi.mocked(login).mockResolvedValue(USER)
    await signIn('root', 'the right one')

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('renders no navigation of its own', () => {
    renderPage()

    // It sits outside AppShell: a sidebar here would offer links to pages that
    // would only 401, and the shell's polling would fire requests guaranteed
    // to fail.
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })
})
