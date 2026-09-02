import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { getLatestSnapshot, getSnapshotSeries, NetworkError } from '../api/client'
import type { Series, Snapshot } from '../api/types'
import { CpuPage } from './CpuPage'

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
  metric: 'cpu',
  bucket: 'hour',
  unit: 'percent',
  points: [
    { t: '2026-08-25T10:00:00Z', value: 20 },
    { t: '2026-08-25T11:00:00Z', value: 70 },
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

describe('CpuPage', () => {
  it('shows loading skeletons before the first snapshot and series arrive', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<CpuPage />)

    // Two independent sections, each announcing its own loading state — the
    // summary (gauge) and the chart do not share one gate.
    expect(screen.getByText('Loading CPU')).toBeInTheDocument()
    expect(screen.getByText('Loading CPU usage over time')).toBeInTheDocument()
  })

  it('shows an error message when the snapshot fetch fails, instead of crashing', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new Error('boom'))
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<CpuPage />)

    await waitFor(() => expect(screen.getByText('Unable to load the latest snapshot.')).toBeInTheDocument())
  })

  it('shows the network-specific message when the backend is unreachable, not the generic one', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new NetworkError(new Error('offline')))
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<CpuPage />)

    // Distinct from the previous test's generic-Error case: proves the
    // summary section renders SnapshotErrorMessage's real output rather than
    // a hardcoded string that happens to match one particular cause.
    await waitFor(() =>
      expect(screen.getByText("Can't reach the backend. Check that it's running.")).toBeInTheDocument(),
    )
  })

  it('renders CPU usage and core count', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<CpuPage />)

    await waitFor(() => expect(screen.getByText('43%')).toBeInTheDocument())
    expect(screen.getByText('8 cores')).toBeInTheDocument()
  })

  it('requests the cpu metric, defaulting to the 24h range', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<CpuPage />)

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(1))
    const [params] = vi.mocked(getSnapshotSeries).mock.calls[0]
    expect(params.metric).toBe('cpu')
    expect(params.bucket).toBe('hour')

    // Requesting the whole table and trusting the backend's 5000-point cap
    // to reject it is not the same as actually windowing the request — a
    // missing `since` would still resolve fine against a small test fixture
    // and only fail against a real, months-old database.
    const sinceMs = new Date(String(params.since)).getTime()
    const expectedMs = Date.now() - 24 * 60 * 60 * 1000
    expect(Math.abs(sinceMs - expectedMs)).toBeLessThan(5000)
  })

  it('refetches the series immediately when a new range is picked, not on the next poll tick', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)
    const user = userEvent.setup()

    render(<CpuPage />)
    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(1))

    await user.click(screen.getByRole('radio', { name: '1h' }))

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(2))
    const [, secondParams] = vi.mocked(getSnapshotSeries).mock.calls
    expect(secondParams[0].bucket).toBe('raw')
  })

  it('does not fetch the series twice on mount', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<CpuPage />)

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(1))
    // Give any accidental second fetch a chance to have fired before asserting.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
    expect(getSnapshotSeries).toHaveBeenCalledTimes(1)
  })

  it('renders the chart line once series data arrives', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<CpuPage />)

    await waitFor(() => expect(document.querySelector('.recharts-line-curve')).toBeInTheDocument())
  })

  it('shows the chart empty state when the series has no points', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue({ ...SERIES, points: [] })

    render(<CpuPage />)

    await waitFor(() => expect(screen.getByText('No data for this range.')).toBeInTheDocument())
  })

  it('shows the chart loading skeleton, not the empty state, while the series is still unresolved', async () => {
    // The snapshot is a trivial single-row read and the series is a heavier
    // aggregation query; nothing guarantees they settle in the same order.
    // The chart section is independent of the gauge's data source, so it
    // must show its own loading state rather than "No data for this range."
    // — which would misrepresent a fetch still in flight as a completed,
    // empty one.
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<CpuPage />)

    await waitFor(() => expect(screen.getByText('43%')).toBeInTheDocument())
    expect(screen.getByText('Loading CPU usage over time')).toBeInTheDocument()
    expect(screen.queryByText('No data for this range.')).not.toBeInTheDocument()
  })

  it('falls back to the empty state, not a permanent loading skeleton, when the series fetch fails', async () => {
    // Once series.error is set the fetch is never going to resolve on its
    // own — loading has to turn off here, or a genuinely failed request
    // looks identical to one still in flight forever.
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockRejectedValue(new Error('boom'))

    render(<CpuPage />)

    await waitFor(() => expect(screen.getByText('No data for this range.')).toBeInTheDocument())
    expect(screen.queryByText('Loading CPU usage over time')).not.toBeInTheDocument()
  })

  it('renders the gauge without crashing when the series resolves before the snapshot does', async () => {
    // The reverse ordering from the test above: the chart's own data source
    // is independent, so it must not be held back by (or hold back) the
    // gauge section either way.
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<CpuPage />)

    await waitFor(() => expect(document.querySelector('.recharts-line-curve')).toBeInTheDocument())
    expect(screen.getByText('Loading CPU')).toBeInTheDocument()
  })

  it('renders the gauge without a redundant "CPU" label, unlike the Overview tile', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<CpuPage />)

    // The page's own <h1>CPU</h1> already says so once.
    await waitFor(() => expect(screen.getByText('43%')).toBeInTheDocument())
    expect(screen.getAllByText('CPU')).toHaveLength(1)
  })
})
