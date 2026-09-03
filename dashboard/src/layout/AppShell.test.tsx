import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getActiveAlerts, getLatestSnapshot, getStatus } from '../api/client'
import type { Snapshot, Status } from '../api/types'
import { AppShell } from './AppShell'

vi.mock('../api/client', () => ({
  getLatestSnapshot: vi.fn(),
  getStatus: vi.fn(),
  getActiveAlerts: vi.fn(),
}))

const SNAPSHOT: Snapshot = {
  collectedAt: new Date().toISOString(),
  cpuInfo: { coreCount: 8, usagePercent: 10 },
  memoryInfo: { totalMB: 16384, usedMB: 4096 },
  diskInfo: { totalGB: 512, freeGB: 112 },
  systemInfo: { name: 'Windows', version: '11', hostName: 'devbox' },
}

const STATUS: Status = {
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

function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/']}>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<p>page content</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.mocked(getLatestSnapshot).mockReset()
  vi.mocked(getStatus).mockReset()
  vi.mocked(getActiveAlerts).mockReset()
  // The header's alert indicator polls this; individual tests that care about
  // it override the resolved value.
  vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
})

describe('AppShell header', () => {
  it('shows a dash for the hostname before the first snapshot arrives', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    renderShell()

    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows the real hostname once the snapshot loads', async () => {
    vi.mocked(getLatestSnapshot).mockResolvedValue(SNAPSHOT)
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    renderShell()

    await waitFor(() => expect(screen.getByText('devbox')).toBeInTheDocument())
  })

  it('shows Unknown before the status poll resolves', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    renderShell()

    expect(screen.getByText('Unknown')).toBeInTheDocument()
  })

  it('reflects the agent being down', async () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockResolvedValue({ ...STATUS, agent: 'down' })

    renderShell()

    await waitFor(() => expect(screen.getByText('Agent unreachable')).toBeInTheDocument())
  })

  it('shows the staleness banner above the page content when the agent is down', async () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockResolvedValue({ ...STATUS, agent: 'down' })

    renderShell()

    // The banner reuses AppShell's own /status poll (see StalenessBanner's
    // own doc comment) rather than fetching independently — this is what
    // proves that wiring, not just the component in isolation, works.
    await waitFor(() =>
      expect(screen.getByText('Agent unreachable — showing the last data received.')).toBeInTheDocument(),
    )
  })

  it('does not show the staleness banner while the agent is up', async () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockResolvedValue(STATUS)

    renderShell()

    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument())
    expect(screen.queryByText('Agent unreachable — showing the last data received.')).not.toBeInTheDocument()
  })

  it('reflects the agent being up', async () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockResolvedValue(STATUS)

    renderShell()

    await waitFor(() => expect(screen.getByText('Connected')).toBeInTheDocument())
  })

  it('still renders the routed page content alongside the header', () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    renderShell()

    expect(screen.getByText('page content')).toBeInTheDocument()
  })

  it('shows the alert indicator, linking to the Alerts page', async () => {
    vi.mocked(getLatestSnapshot).mockReturnValue(neverSettles())
    vi.mocked(getStatus).mockReturnValue(neverSettles())
    // The indicator only reads items.length.
    vi.mocked(getActiveAlerts).mockResolvedValue({ items: [{}, {}] } as never)

    renderShell()

    const link = await screen.findByRole('link', { name: '2 active alerts' })
    expect(link).toHaveAttribute('href', '/alerts')
  })
})
