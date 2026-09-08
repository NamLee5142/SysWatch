import { screen, waitFor } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getActiveAlerts, getLatestSnapshot, getStatus } from '../api/client'
import type { Status } from '../api/types'
import { renderWithAuth } from '../test/renderWithAuth'
import { AppShell } from './AppShell'

vi.mock('../api/client', () => ({
  getLatestSnapshot: vi.fn(),
  getStatus: vi.fn(),
  getActiveAlerts: vi.fn(),
}))


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

function renderShell(options = {}) {
  return renderWithAuth(
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<p>page content</p>} />
      </Route>
    </Routes>,
    options,
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
  it('names the selected host', () => {
    // Read from /hosts now, not from the latest snapshot. With two machines
    // reporting, "whichever row is newest" showed one of them, alternating,
    // with nothing on screen to say so.
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    renderShell()

    expect(screen.getByText('devbox')).toBeInTheDocument()
  })

  it('shows a dash when no host has reported yet', () => {
    vi.mocked(getStatus).mockReturnValue(neverSettles())

    renderShell({ hosts: [], hostName: null })

    expect(screen.getByText('—')).toBeInTheDocument()
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
