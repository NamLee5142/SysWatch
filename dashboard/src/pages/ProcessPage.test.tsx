import { screen, waitFor } from '@testing-library/react'
import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { renderWithHost } from '../test/renderWithHost'
import { getLatestSnapshot, getSnapshotSeries, NetworkError } from '../api/client'
import type { Series, Snapshot } from '../api/types'
import { ProcessPage } from './ProcessPage'

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
  processInfo: {
    count: 240,
    top: [
      { pid: 1234, name: 'chrome.exe', memoryMB: 512 },
      { pid: 9, name: 'System', memoryMB: 3 },
    ],
  },
}

const SERIES: Series = {
  metric: 'processes',
  bucket: 'hour',
  unit: 'count',
  points: [
    { t: '2026-08-25T10:00:00Z', value: 220 },
    { t: '2026-08-25T11:00:00Z', value: 240 },
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

describe('ProcessPage', () => {
  it('shows loading states before the snapshot and series arrive', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    renderWithHost(<ProcessPage />)

    expect(screen.getByText('Loading processes')).toBeInTheDocument()
    expect(screen.getByText('Loading Process count over time')).toBeInTheDocument()
  })

  it('surfaces a network failure with the backend-specific message', async () => {
    vi.mocked(getLatestSnapshot).mockRejectedValue(new NetworkError(new Error('offline')))
    vi.mocked(getSnapshotSeries).mockReturnValue(neverSettles())

    renderWithHost(<ProcessPage />)

    // Both the count and the table section fall back to the same message.
    await waitFor(() =>
      expect(screen.getAllByText("Can't reach the backend. Check that it's running.").length).toBeGreaterThan(0),
    )
  })

  it('renders the process count and the top-by-memory table', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    renderWithHost(<ProcessPage />)

    await waitFor(() => expect(screen.getByText('240')).toBeInTheDocument())
    expect(screen.getByText('chrome.exe')).toBeInTheDocument()
    expect(screen.getByText('1234')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Memory' })).toBeInTheDocument()
  })

  it('requests the processes metric', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getSnapshotSeries).mockResolvedValue(SERIES)

    renderWithHost(<ProcessPage />)

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalled())
    expect(vi.mocked(getSnapshotSeries).mock.calls[0][0].metric).toBe('processes')
  })

  it('tells the user when the agent does not report process data', async () => {
    const { processInfo: _omitted, ...withoutProcess } = SNAPSHOT
    vi.mocked(getLatestSnapshot).mockResolvedValue(withoutProcess)
    vi.mocked(getSnapshotSeries).mockResolvedValue({ ...SERIES, points: [] })

    renderWithHost(<ProcessPage />)

    await waitFor(() =>
      expect(screen.getAllByText('This agent does not report process data.').length).toBeGreaterThan(0),
    )
  })
})
