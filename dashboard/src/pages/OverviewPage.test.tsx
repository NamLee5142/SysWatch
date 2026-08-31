import { act, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getLatestSnapshot, getStatus } from '../api/client'
import type { Snapshot, Status } from '../api/types'
import { OverviewPage } from './OverviewPage'

vi.mock('../api/client', () => ({
  getLatestSnapshot: vi.fn(),
  getStatus: vi.fn(),
}))

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

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

beforeEach(() => {
  vi.mocked(getLatestSnapshot).mockReset()
  vi.mocked(getStatus).mockReset()
})

describe('OverviewPage', () => {
  it('shows a loading skeleton before the first snapshot arrives', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    render(<OverviewPage />)

    expect(screen.getByText('Loading Overview')).toBeInTheDocument()
  })

  it('shows an error message when the snapshot fetch fails, instead of crashing', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new Error('boom'))
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    render(<OverviewPage />)

    await waitFor(() => expect(screen.getByText('Unable to load the latest snapshot.')).toBeInTheDocument())
  })

  it('renders CPU usage and core count', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)

    render(<OverviewPage />)

    await waitFor(() => expect(screen.getByText('43%')).toBeInTheDocument())
    expect(screen.getByText('8 cores')).toBeInTheDocument()
  })

  it('renders memory as used / total, formatted in GB', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)

    render(<OverviewPage />)

    await waitFor(() => expect(screen.getByText('4.0 GB / 16.0 GB')).toBeInTheDocument())
  })

  it('renders disk as used, derived from total minus free', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)

    render(<OverviewPage />)

    // The agent reports total and free, not used — the page has to subtract.
    await waitFor(() => expect(screen.getByText('400 GB used')).toBeInTheDocument())
    expect(screen.getByText('112 GB free')).toBeInTheDocument()
  })

  it('renders hostname and OS', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)

    render(<OverviewPage />)

    await waitFor(() => expect(screen.getByText('devbox')).toBeInTheDocument())
    expect(screen.getByText('Windows 11')).toBeInTheDocument()
  })

  it('renders the connection state from /status, not from whether the snapshot loaded', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue({ ...STATUS_UP, agent: 'down', lastPollError: 'connection refused' })

    render(<OverviewPage />)

    // The snapshot itself loaded fine (it is storage-backed and survives an
    // agent outage) — connection state has to come from a different signal.
    await waitFor(() => expect(screen.getByText('Agent unreachable')).toBeInTheDocument())
  })

  it('falls back to Unknown when the status fetch has not resolved yet', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    render(<OverviewPage />)

    await waitFor(() => expect(screen.getByText('devbox')).toBeInTheDocument())
    expect(screen.getByText('Unknown')).toBeInTheDocument()
  })

  it('keeps polling on an interval rather than fetching only once', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockResolvedValue(STATUS_UP)

    render(<OverviewPage />)
    await vi.waitFor(() => expect(getLatestSnapshot).toHaveBeenCalledTimes(1))

    // Wrapped in act(): the interval's refetch triggers a state update
    // outside any event handler, which needs an act() boundary to flush and
    // be observable here — a bare advance can under-report the call count.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000)
    })

    expect(getLatestSnapshot).toHaveBeenCalledTimes(2)
    expect(getStatus).toHaveBeenCalledTimes(2)
    vi.useRealTimers()
  })
})
