import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { useState } from 'react'

import {
  getActiveAlerts,
  getHosts,
  getLatestSnapshot,
  getSnapshotSeries,
  getStatus,
  listSnapshots,
} from '../api/client'
import type { Snapshot } from '../api/types'
import { AppShell } from '../layout/AppShell'
import { CpuPage } from '../pages/CpuPage'
import { AuthContext } from '../auth/AuthContext'
import { SelectedHostContext, type SelectedHostValue } from './SelectedHostContext'
import { TEST_ADMIN, testHost } from '../test/renderWithAuth'
import { renderWithHost } from '../test/renderWithHost'
import { DiskPage } from '../pages/DiskPage'
import { HistoryPage } from '../pages/HistoryPage'
import { MemoryPage } from '../pages/MemoryPage'
import { NetworkPage } from '../pages/NetworkPage'
import { OverviewPage } from '../pages/OverviewPage'
import { ProcessPage } from '../pages/ProcessPage'
import { SystemPage } from '../pages/SystemPage'

vi.mock('../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/client')>()
  return {
    ...actual,
    getLatestSnapshot: vi.fn(),
    getSnapshotSeries: vi.fn(),
    getStatus: vi.fn(),
    getHosts: vi.fn(),
    getActiveAlerts: vi.fn(),
    listSnapshots: vi.fn(),
  }
})

function snapshot(hostName: string, cpu: number): Snapshot {
  return {
    collectedAt: '2026-09-08T10:00:00Z',
    cpuInfo: { coreCount: 8, usagePercent: cpu },
    memoryInfo: { totalMB: 16384, usedMB: 4096 },
    diskInfo: { totalGB: 512, freeGB: 112 },
    systemInfo: { name: 'Windows', version: '11', hostName },
    processInfo: { count: 100, top: [] },
    networkInfo: { interfaces: [] },
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getLatestSnapshot).mockResolvedValue(snapshot('devbox', 42.5))
  vi.mocked(getSnapshotSeries).mockResolvedValue({
    metric: 'cpu',
    bucket: 'hour',
    unit: 'percent',
    points: [],
  })
  vi.mocked(getStatus).mockResolvedValue({
    backend: 'ok',
    agent: 'up',
    pollerRunning: true,
    lastPollAt: '2026-09-08T10:00:00Z',
    lastSuccessAt: '2026-09-08T10:00:00Z',
    lastPollError: null,
  })
  vi.mocked(getHosts).mockResolvedValue({ items: [testHost('devbox'), testHost('buildbox')] })
  vi.mocked(getActiveAlerts).mockResolvedValue({ items: [] })
  vi.mocked(listSnapshots).mockResolvedValue({ items: [], count: 0 })
})

// Every page that shows one machine's numbers. Alerts is deliberately absent:
// its rows belong to whichever host raised them.
const PAGES = [
  ['Overview', <OverviewPage key="o" />],
  ['CPU', <CpuPage key="c" />],
  ['Memory', <MemoryPage key="m" />],
  ['Disk', <DiskPage key="d" />],
  ['Network', <NetworkPage key="n" />],
  ['Processes', <ProcessPage key="p" />],
  ['System', <SystemPage key="s" />],
] as const

describe('every page asks for the selected host', () => {
  it.each(PAGES)('%s scopes its snapshot', async (_name, page) => {
    renderWithHost(page, { hostName: 'buildbox' })

    await waitFor(() => expect(getLatestSnapshot).toHaveBeenCalled())
    for (const [host] of vi.mocked(getLatestSnapshot).mock.calls) {
      expect(host).toBe('buildbox')
    }
  })

  it.each([
    ['CPU', <CpuPage key="c" />],
    ['Memory', <MemoryPage key="m" />],
    ['Disk', <DiskPage key="d" />],
    ['Network', <NetworkPage key="n" />],
    ['Processes', <ProcessPage key="p" />],
  ] as const)('%s scopes its series', async (_name, page) => {
    renderWithHost(page, { hostName: 'buildbox' })

    await waitFor(() => expect(getSnapshotSeries).toHaveBeenCalled())
    for (const [params] of vi.mocked(getSnapshotSeries).mock.calls) {
      expect(params.host).toBe('buildbox')
    }
  })

  it('History scopes its query', async () => {
    renderWithHost(<HistoryPage />, { hostName: 'buildbox' })

    await waitFor(() => expect(listSnapshots).toHaveBeenCalled())
    expect(vi.mocked(listSnapshots).mock.calls[0][0]).toMatchObject({ host: 'buildbox' })
  })

  it('asks for no host in particular when none has reported', async () => {
    // A fresh install. host=null would be a filter matching nothing.
    renderWithHost(<CpuPage />, { hosts: [], hostName: null })

    await waitFor(() => expect(getLatestSnapshot).toHaveBeenCalled())
    expect(vi.mocked(getLatestSnapshot).mock.calls[0][0]).toBeUndefined()
  })
})

describe('switching host', () => {
  /** AppShell and one page, under a selection a test can change. */
  function Switchable() {
    const [hostName, setHostName] = useState('devbox')
    const value: SelectedHostValue = {
      hosts: [testHost('devbox'), testHost('buildbox')],
      hostName,
      loading: false,
      select: setHostName,
    }

    return (
      <SelectedHostContext.Provider value={value}>
        <MemoryRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route index element={<CpuPage />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </SelectedHostContext.Provider>
    )
  }

  it('does not leave the previous machine on screen', async () => {
    // The done-when: no page silently shows a mixture. useApi keeps its last
    // value through a refetch by design - right for a poll, wrong here - so
    // without the remount devbox's 43% would sit under buildbox's name until
    // the new request landed.
    vi.mocked(getLatestSnapshot).mockImplementation((host) =>
      Promise.resolve(snapshot(host ?? 'devbox', host === 'buildbox' ? 91.5 : 42.5)),
    )

    render(
      <AuthContext.Provider
        value={{
          status: 'authenticated',
          user: TEST_ADMIN,
          isAdmin: true,
          signIn: vi.fn(),
          signOut: vi.fn(),
        }}
      >
        <Switchable />
      </AuthContext.Provider>,
    )

    await waitFor(() => expect(screen.getByText('43%')).toBeInTheDocument())

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /host/i }), 'buildbox')

    // devbox's number is gone the moment the switch happens, not once
    // buildbox's request lands.
    expect(screen.queryByText('43%')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('92%')).toBeInTheDocument())
  })

  it('asks the backend for the newly chosen host', async () => {
    render(
      <AuthContext.Provider
        value={{
          status: 'authenticated',
          user: TEST_ADMIN,
          isAdmin: true,
          signIn: vi.fn(),
          signOut: vi.fn(),
        }}
      >
        <Switchable />
      </AuthContext.Provider>,
    )

    await waitFor(() => expect(getLatestSnapshot).toHaveBeenCalled())

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /host/i }), 'buildbox')

    await waitFor(() =>
      expect(vi.mocked(getLatestSnapshot).mock.calls.some(([host]) => host === 'buildbox')).toBe(
        true,
      ),
    )
  })
})
