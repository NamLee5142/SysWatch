import { render, screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { getLatestSnapshot, getSnapshotSeries, NetworkError } from '../api/client'
import type { Series, Snapshot } from '../api/types'
import { NetworkPage } from './NetworkPage'

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
  networkInfo: {
    interfaces: [
      { name: 'Wi-Fi', bytesSent: 1000, bytesRecv: 2000, bytesSentPerSec: 1024, bytesRecvPerSec: 2048 },
    ],
  },
}

const SERIES: Series = {
  metric: 'net_recv',
  bucket: 'hour',
  unit: 'bytes_per_sec',
  points: [
    { t: '2026-08-25T10:00:00Z', value: 1000 },
    { t: '2026-08-25T11:00:00Z', value: 2000 },
  ],
}

function neverSettles<T>(): Promise<T> {
  return new Promise<T>(() => {})
}

beforeAll(() => {
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

describe('NetworkPage', () => {
  it('shows loading states before the snapshot and series arrive', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<NetworkPage />)

    expect(screen.getByText('Loading network interfaces')).toBeInTheDocument()
    expect(screen.getByText('Loading Network throughput received over time')).toBeInTheDocument()
    expect(screen.getByText('Loading Network throughput sent over time')).toBeInTheDocument()
  })

  it('renders a card per interface with two formatted rates', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<NetworkPage />)

    await waitFor(() => expect(screen.getByText('Wi-Fi')).toBeInTheDocument())

    // A received and a sent rate, formatted by formatBytesPerSec (its exact
    // output is covered in format.test.ts).
    //
    // Restricted to <dd>, because the card is not the only thing on this page
    // formatting bytes per second: MetricChart passes formatBytesPerSec as its
    // axis tick formatter, so every rendered tick is text ending in KB/s too.
    // How many ticks a chart renders depends on the sizes it measures, which
    // jsdom does not decide identically everywhere - unrestricted, this
    // matched two here and five on a Linux runner.
    const rates = screen.getAllByText(
      (text, element) => element?.tagName === 'DD' && text.endsWith('KB/s'),
    )

    expect(rates).toHaveLength(2)
  })

  it('requests both the net_recv and net_sent metrics', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    render(<NetworkPage />)

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalledTimes(2))
    const metrics = vi.mocked(getSnapshotSeries).mock.calls.map((call) => call[0].metric)
    expect(new Set(metrics)).toEqual(new Set(['net_recv', 'net_sent']))
  })

  it('surfaces a backend failure rather than crashing', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new NetworkError(new Error('offline')))
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    render(<NetworkPage />)

    await waitFor(() =>
      expect(screen.getByText("Can't reach the backend. Check that it's running.")).toBeInTheDocument(),
    )
  })

  it('tells the user when the agent does not report network data', async () => {
    const { networkInfo: _omitted, ...withoutNetwork } = SNAPSHOT
    vi.mocked(getLatestSnapshot).mockResolvedValue(withoutNetwork)
    vi.mocked(getSnapshotSeries).mockResolvedValue({ ...SERIES, points: [] })

    render(<NetworkPage />)

    await waitFor(() =>
      expect(screen.getByText('This agent does not report network data.')).toBeInTheDocument(),
    )
  })
})
