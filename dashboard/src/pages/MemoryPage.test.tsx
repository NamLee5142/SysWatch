import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { getLatestSnapshot, getSnapshotSeries, NetworkError } from '../api/client'
import type { Series, Snapshot } from '../api/types'
import { MemoryPage } from './MemoryPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getLatestSnapshot: vi.fn(),
    getSnapshotSeries: vi.fn(),
  }
})

const SNAPSHOT: Snapshot = {
  collectedAt: new Date().toISOString(),
  cpuInfo: { coreCount: 8, usagePercent: 42.5 },
  memoryInfo: { totalMB: 16384, usedMB: 4096 },
  diskInfo: { totalGB: 512, freeGB: 112 },
  systemInfo: { name: 'Windows', version: '11', hostName: 'devbox' },
}

const SERIES: Series = {
  metric: 'memory',
  bucket: 'hour',
  unit: 'percent',
  points: [
    { t: '2026-08-25T10:00:00Z', value: 20 },
    { t: '2026-08-25T11:00:00Z', value: 30 },
  ],
}

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

beforeAll(() => {
  // Same jsdom limitation MetricChart.test.tsx documents: ResponsiveContainer
  // needs a real size to render anything under it.
  Object.defineProperty(HTMLElement.prototype, 'getBoundingClientRect', {
    configurable: true,
    value: () => ({ width: 600, height: 220, top: 0, left: 0, right: 600, bottom: 220, x: 0, y: 0, toJSON() {} }),
  })
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub
})

beforeEach(() => {
  vi.mocked(getLatestSnapshot).mockReset()
  vi.mocked(getSnapshotSeries).mockReset()
})

describe('MemoryPage', () => {
  it('shows loading skeletons before the first snapshot and series arrive', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<MemoryPage />)

    // Two independent sections, each announcing its own loading state.
    expect(screen.getByText('Loading Memory')).toBeInTheDocument()
    expect(screen.getByText('Loading Memory usage over time')).toBeInTheDocument()
  })

  it('shows an error message when the snapshot fetch fails, instead of crashing', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new Error('boom'))
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<MemoryPage />)

    await waitFor(() => expect(screen.getByText('Unable to load the latest snapshot.')).toBeInTheDocument())
  })

  it('shows the network-specific message when the backend is unreachable, not the generic one', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new NetworkError(new Error('offline')))
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<MemoryPage />)

    await waitFor(() =>
      expect(screen.getByText("Can't reach the backend. Check that it's running.")).toBeInTheDocument(),
    )
  })

  it('renders the used percentage as the gauge reading', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<MemoryPage />)

    // 4096 / 16384 = 25%.
    await waitFor(() => expect(screen.getByText('25%')).toBeInTheDocument())
  })

  it('renders used vs total, formatted in GB', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<MemoryPage />)

    await waitFor(() => expect(screen.getByText('4.0 GB / 16.0 GB')).toBeInTheDocument())
  })

  it('requests the memory metric, defaulting to the 24h range', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<MemoryPage />)

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(1))
    const [params] = vi.mocked(getSnapshotSeries).mock.calls[0]
    expect(params.metric).toBe('memory')
    expect(params.bucket).toBe('hour')

    const sinceMs = new Date(String(params.since)).getTime()
    const expectedMs = Date.now() - 24 * 60 * 60 * 1000
    expect(Math.abs(sinceMs - expectedMs)).toBeLessThan(5000)
  })

  it('refetches the series immediately when a new range is picked, not on the next poll tick', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)
    const user = userEvent.setup()

    render(<MemoryPage />)
    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('radio', { name: '1h' }))

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(2))
    const [, secondParams] = vi.mocked(getSnapshotSeries).mock.calls
    expect(secondParams[0].bucket).toBe('raw')
  })

  it('does not fetch the series twice on mount', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<MemoryPage />)

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(1))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(getSnapshotSeries).toHaveBeenCalledTimes(1)
  })

  it('renders the chart line once series data arrives', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<MemoryPage />)

    await waitFor(() => expect(document.querySelector('.recharts-line-curve')).toBeInTheDocument())
  })

  it('shows the chart empty state when the series has no points', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue({ ...SERIES, points: [] })

    render(<MemoryPage />)

    await waitFor(() => expect(screen.getByText('No data for this range.')).toBeInTheDocument())
  })

  it('shows the chart loading skeleton, not the empty state, while the series is still unresolved', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<MemoryPage />)

    await waitFor(() => expect(screen.getByText('25%')).toBeInTheDocument())
    expect(screen.getByText('Loading Memory usage over time')).toBeInTheDocument()
    expect(screen.queryByText('No data for this range.')).not.toBeInTheDocument()
  })

  it('falls back to the empty state, not a permanent loading skeleton, when the series fetch fails', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockRejectedValue(new Error('boom'))

    render(<MemoryPage />)

    await waitFor(() => expect(screen.getByText('No data for this range.')).toBeInTheDocument())
    expect(screen.queryByText('Loading Memory usage over time')).not.toBeInTheDocument()
  })

  it('renders the gauge without crashing when the series resolves before the snapshot does', async () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<MemoryPage />)

    await waitFor(() => expect(document.querySelector('.recharts-line-curve')).toBeInTheDocument())
    expect(screen.getByText('Loading Memory')).toBeInTheDocument()
  })

  it('renders 0% rather than crashing when totalMB is zero', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue({
      ...SNAPSHOT,
      memoryInfo: { totalMB: 0, usedMB: 0 },
    })
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<MemoryPage />)

    await waitFor(() => expect(screen.getByText('0%')).toBeInTheDocument())
  })
})
