import { act, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getHosts, getLatestSnapshot, getStatus, NetworkError } from '../api/client'
import { renderWithHost } from '../test/renderWithHost'
import type { HostList, Snapshot, Status } from '../api/types'
import { SystemPage } from './SystemPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getLatestSnapshot: vi.fn(),
    getStatus: vi.fn(),
    getHosts: vi.fn(),
  }
})

const SNAPSHOT: Snapshot = {
  collectedAt: new Date().toISOString(),
  cpuInfo: { coreCount: 8, usagePercent: 42.5 },
  memoryInfo: { totalMB: 16384, usedMB: 4096 },
  diskInfo: { totalGB: 512, freeGB: 112 },
  systemInfo: { name: 'Windows', version: '11', hostName: 'devbox' },
}

const STATUS_UP: Status = {
  backend: 'ok',
  agent: 'up',
  pollerRunning: true,
  lastPollAt: new Date().toISOString(),
  lastSuccessAt: new Date().toISOString(),
  lastPollError: null,
}

// Deliberately distinct from SNAPSHOT's hostName ("devbox"): reusing it here
// would make the identity StatCard and a table cell both render the text
// "devbox", and getByText('devbox') throws on finding more than one match.
const HOSTS: HostList = {
  items: [
    { hostName: 'buildbox', lastCollectedAt: new Date().toISOString(), snapshotCount: 42 },
    { hostName: 'testbox', lastCollectedAt: new Date().toISOString(), snapshotCount: 7 },
  ],
}

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

function resolveAll() {
  vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
  vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
  vi.mocked(getHosts).mockResolvedValue(HOSTS)
}

beforeEach(() => {
  vi.mocked(getLatestSnapshot).mockReset()
  vi.mocked(getStatus).mockReset()
  vi.mocked(getHosts).mockReset()
})

describe('SystemPage', () => {
  it('renders hostname and OS once the snapshot loads', async () => {
    resolveAll()

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('devbox')).toBeInTheDocument())
    expect(screen.getByText('Windows 11')).toBeInTheDocument()
  })

  it('shows a loading skeleton for the identity section before the snapshot arrives', async () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    // Let the other two sections actually resolve first — right after the
    // initial render all three legitimately show a loading state for a
    // moment, which is not what this test is checking.
    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())

    expect(screen.getByText('Loading identity')).toBeInTheDocument()
  })

  it('shows an error message for the identity section when the snapshot fetch fails', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new Error('boom'))
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('Unable to load the latest snapshot.')).toBeInTheDocument())
  })

  it('shows the network-specific message for the identity section when the backend is unreachable', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new NetworkError(new Error('offline')))
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() =>
      expect(screen.getByText("Can't reach the backend. Check that it's running.")).toBeInTheDocument(),
    )
  })

  it('shows an error message for the connection section when the status fetch fails, not a permanent skeleton', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockRejectedValue(new Error('boom'))
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('Unable to load status.')).toBeInTheDocument())
    expect(screen.queryByText('Loading connection status')).not.toBeInTheDocument()
  })

  it('shows a loading skeleton for the connection section before status arrives', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockReturnValue(neverSettles())
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('devbox')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())

    expect(screen.getByText('Loading connection status')).toBeInTheDocument()
  })

  it('shows a loading skeleton for the hosts section before the host list arrives', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
    vi.mocked(getHosts).mockReturnValue(neverSettles())

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('devbox')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument())

    // The real column headers stay visible while the rows are still loading.
    expect(screen.getByRole('columnheader', { name: 'Host' })).toBeInTheDocument()
    expect(screen.getByText('Loading hosts')).toBeInTheDocument()
  })

  it('renders the connection detail independently of the snapshot section', async () => {
    // The snapshot never resolves; the status and host sections must not
    // wait on it — that independence is the whole point of this page's
    // per-section loading, unlike every other page's single early return.
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument())
    expect(screen.getByText('Running')).toBeInTheDocument()
  })

  it('shows "Stopped" when the poller is not running', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue({ ...STATUS_UP, pollerRunning: false })
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('Stopped')).toBeInTheDocument())
  })

  it('shows "Never" for the last successful collection when nothing has succeeded yet', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue({ ...STATUS_UP, lastSuccessAt: null })
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('Never')).toBeInTheDocument())
  })

  it('shows the last poll error only when one exists', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue({ ...STATUS_UP, agent: 'down', lastPollError: 'connection refused' })
    vi.mocked(getHosts).mockResolvedValue(HOSTS)

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('connection refused')).toBeInTheDocument())
  })

  it('omits the error row entirely when there is no error', async () => {
    resolveAll()

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument())
    expect(screen.queryByText('Last error')).not.toBeInTheDocument()
  })

  it('renders every reporting host with its snapshot count', async () => {
    resolveAll()

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByRole('table')).toBeInTheDocument())
    expect(screen.getByRole('cell', { name: 'buildbox' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: 'testbox' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '42' })).toBeInTheDocument()
    expect(screen.getByRole('cell', { name: '7' })).toBeInTheDocument()
  })

  it('shows a specific empty message rather than a blank table when no hosts have reported', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
    vi.mocked(getHosts).mockResolvedValue({ items: [] })

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('No hosts have reported yet.')).toBeInTheDocument())
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('shows an error message for the hosts section when that fetch fails, independent of the others', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)
    vi.mocked(getHosts).mockRejectedValue(new Error('boom'))

    renderWithHost(<SystemPage />)

    await waitFor(() => expect(screen.getByText('Unable to load hosts.')).toBeInTheDocument())
    // The other two sections are unaffected by the hosts failure.
    expect(screen.getByText('devbox')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
  })

  it('polls all three sources on an interval', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    resolveAll()

    renderWithHost(<SystemPage />)
    await vi.waitFor(() => expect(getLatestSnapshot).toHaveBeenCalledTimes(1))

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    expect(getLatestSnapshot).toHaveBeenCalledTimes(2)
    expect(getStatus).toHaveBeenCalledTimes(2)
    expect(getHosts).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })
})
